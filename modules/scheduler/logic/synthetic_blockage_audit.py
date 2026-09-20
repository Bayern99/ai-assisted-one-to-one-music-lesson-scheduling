from collections import Counter
import copy

import pandas as pd

from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.rules_schema import (
    CANONICAL_TOP_LEVEL_KEYS,
    DEFAULT_RULES,
    canonicalize_rules_for_save,
    get_rules_trace,
    normalize_rules,
    validate_rules_payload,
)
from modules.scheduler.logic.workflow_service import build_locked_context


def _safe_len(value):
    if isinstance(value, list):
        return len(value)
    return 0


def _load_raw_json(loader, name, default):
    path = loader.preferred_data_path(name)
    try:
        data = loader.load_json_data(name, default_value=default)
    except Exception:
        return copy.deepcopy(default), path
    if not isinstance(data, type(default)):
        return copy.deepcopy(default), path
    return data, path


def inspect_rules_health(raw_rules, default_rules=None, source_path=None):
    raw = raw_rules if isinstance(raw_rules, dict) else {}
    validation_errors = validate_rules_payload(raw)
    normalized = normalize_rules(raw, default_rules=default_rules or DEFAULT_RULES, source_path=source_path)
    canonical = canonicalize_rules_for_save(raw, default_rules=default_rules or DEFAULT_RULES, source_path=source_path)
    trace = get_rules_trace(normalized)

    recognized = [key for key in CANONICAL_TOP_LEVEL_KEYS if key in raw]
    unknown = list(trace.get("ignored_top_level_keys", []))
    missing = [key for key in CANONICAL_TOP_LEVEL_KEYS if key not in raw]
    degenerated = not recognized or len(recognized) == 0
    status = (
        "degenerated"
        if degenerated
        else ("invalid" if validation_errors else ("compat_dirty" if unknown else "healthy"))
    )

    return {
        "status": status,
        "rules_corrupted_or_degenerated": degenerated,
        "recognized_top_level_keys": recognized,
        "unknown_top_level_keys": unknown,
        "missing_canonical_top_level_keys": missing,
        "ignored_nested_keys": list(trace.get("ignored_nested_keys", [])),
        "validation_errors": validation_errors,
        "canonical_rules_snapshot": canonical,
        "source_path": source_path or "",
    }


def build_booking_migration_plan(raw_bookings, include_entries=False):
    entries = []
    action_counts = Counter()
    type_counts = Counter()
    legacy_type_counts = Counter()

    for idx, booking in enumerate(raw_bookings or []):
        if not isinstance(booking, dict):
            continue

        booking_type = str(booking.get("type", ""))
        type_counts[booking_type] += 1
        if booking_type in {"committed_weekly", "committed_studio"}:
            legacy_type_counts[booking_type] += 1

        action = "keep_locked"
        canonical_type = booking_type

        if booking_type == "committed_weekly":
            action = "canonicalize_locked"
            canonical_type = "weekly_lesson"
        elif booking_type == "committed_studio":
            action = "canonicalize_locked"
            canonical_type = "studio_class"
        elif booking.get("committed") and booking_type == "studio":
            action = "canonicalize_locked"
            canonical_type = "studio_class"
        elif booking_type in {"weekly_lesson", "studio_class", "studio"} and not booking.get("committed"):
            action = "exclude_from_active_lock_set"
        elif booking_type in {"lecture", "academic_lecture"}:
            action = "keep_locked"
        elif booking.get("committed"):
            action = "keep_locked"

        action_counts[action] += 1
        if include_entries:
            entries.append(
                {
                    "id": booking.get("id") or f"booking_{idx}",
                    "type": booking_type,
                    "action": action,
                    "canonical_type": canonical_type,
                    "committed": bool(booking.get("committed")),
                }
            )

    result = {
        "summary": {
            "total_bookings": sum(type_counts.values()),
            "type_counts": dict(type_counts),
            "legacy_type_counts": dict(legacy_type_counts),
            "action_counts": dict(action_counts),
        }
    }
    if include_entries:
        result["entries"] = entries
    return result


def _top_room_counts(bookings, limit=5):
    counts = Counter()
    for booking in bookings or []:
        room_id = booking.get("resourceId")
        if room_id:
            counts[str(room_id)] += 1
    return [{"room_id": room_id, "count": count} for room_id, count in counts.most_common(limit)]


def _top_instructor_day_counts(items, limit=5):
    counts = Counter()
    for item in items or []:
        inst = str(item.get("inst", "")).strip() or "Unknown"
        day = item.get("day", -1)
        counts[(inst, day)] += 1
    return [
        {"instructor": inst, "day": day, "count": count}
        for (inst, day), count in counts.most_common(limit)
    ]


def _invalid_preferred_venues(weekly_df, room_ids):
    counts = Counter()
    if weekly_df is None or getattr(weekly_df, "empty", True):
        return []

    for _, row in weekly_df.iterrows():
        raw_value = str(row.get("Preferred Venue", "")).strip()
        if not raw_value or raw_value.lower() in {"nan", "none"}:
            continue
        for venue in [v.strip() for v in raw_value.replace("，", ",").split(",") if v.strip()]:
            if venue not in room_ids:
                counts[venue] += 1
    return [{"venue": venue, "count": count} for venue, count in counts.most_common()]


def _compare_with_previous(previous_snapshot, assignments, unassigned):
    previous_generated = _safe_len((previous_snapshot or {}).get("generated_assignments"))
    previous_unassigned = _safe_len((previous_snapshot or {}).get("unassigned_lessons"))
    return {
        "previous_generated_assignments": previous_generated,
        "previous_unassigned_lessons": previous_unassigned,
        "current_generated_assignments": len(assignments),
        "current_unassigned_lessons": len(unassigned),
        "generated_delta": len(assignments) - previous_generated,
        "unassigned_delta": len(unassigned) - previous_unassigned,
    }


def audit_scheduler_state(loader, weekly_df, studio_df, previous_snapshot=None, default_rules=None):
    raw_rules, rules_path = _load_raw_json(loader, "scheduling_rules.json", {})
    raw_bookings, _ = _load_raw_json(loader, "bookings.json", [])
    rules_health = inspect_rules_health(raw_rules, default_rules=default_rules, source_path=rules_path)
    booking_plan = build_booking_migration_plan(raw_bookings, include_entries=False)

    current_rules = normalize_rules(raw_rules, default_rules=default_rules or DEFAULT_RULES, source_path=rules_path)
    bookings = loader.load_bookings()
    locked = build_locked_context(bookings)
    students = loader.get_data("students.json") or []
    rooms = loader.load_rooms() or []

    optimizer = RoomAllocator(
        students,
        rooms,
        locked,
        current_rules,
        rules_source_path=rules_path,
    )
    weekly_input = weekly_df.copy() if isinstance(weekly_df, pd.DataFrame) else pd.DataFrame(weekly_df or [])
    studio_input = studio_df.copy() if isinstance(studio_df, pd.DataFrame) else pd.DataFrame(studio_df or [])
    assignments, duplicates, logs = optimizer.optimize(weekly_input, studio_input)

    reason_counts = Counter()
    for item in optimizer.unassigned:
        reason_code = item.get("reason_code") or "unknown"
        reason_counts[reason_code] += 1

    room_ids = {room.get("id") for room in rooms if isinstance(room, dict) and room.get("id")}
    optimizer_summary = {
        "weekly_rows": 0 if weekly_input is None else len(weekly_input),
        "studio_rows": 0 if studio_input is None else len(studio_input),
        "locked_context_count": len(locked),
        "generated_assignments": len(assignments),
        "duplicates": len(duplicates),
        "unassigned_lessons": len(optimizer.unassigned),
        "reason_code_counts": dict(reason_counts),
        "sample_unassigned": optimizer.unassigned[:10],
        "log_tail": logs[-20:],
    }

    booking_health = {
        "raw_booking_count": len(raw_bookings),
        "normalized_booking_count": len(bookings),
        "active_locked_count": len(locked),
        "legacy_type_counts": booking_plan["summary"]["legacy_type_counts"],
        "type_counts": booking_plan["summary"]["type_counts"],
        "migration_action_counts": booking_plan["summary"]["action_counts"],
        "top_locked_rooms": _top_room_counts(locked),
    }

    return {
        "rules_health": rules_health,
        "booking_health": booking_health,
        "booking_migration_plan": booking_plan,
        "optimizer_blockage_summary": optimizer_summary,
        "blocking_hotspots": {
            "top_locked_rooms": _top_room_counts(locked),
            "blocked_instructor_day_blocks": _top_instructor_day_counts(optimizer.unassigned),
            "invalid_preferred_venues": _invalid_preferred_venues(weekly_input, room_ids),
        },
        "comparative_regression": _compare_with_previous(previous_snapshot, assignments, optimizer.unassigned),
    }
