from modules.scheduler.logic.synthetic_blockage_audit import inspect_rules_health
from modules.scheduler.logic.instructor_time_integrity import (
    audit_source_schedule,
    format_instructor_conflict,
)
from modules.scheduler.logic.room_location import build_room_profiles
from modules.scheduler.logic.rules_schema import DEFAULT_RULES
from modules.scheduler.logic.optimizer_normalization import prepare_weekly_lessons
from modules.scheduler.logic.optimizer_studio import prepare_studio_requests
from modules.scheduler.logic.source_requests import is_missing


def _source_records(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict(orient="records")
    return [item for item in frame if isinstance(item, dict)]


def _source_health(weekly_df, studio_df, rooms):
    health = {
        "status": "not_checked",
        "weekly_row_count": len(_source_records(weekly_df)),
        "studio_row_count": len(_source_records(studio_df)),
        "weekly_request_count": 0,
        "studio_request_count": 0,
        "expected_request_count": 0,
        "rejection_count": 0,
        "blocking_errors": [],
        "rejections": [],
    }
    weekly_columns = {str(column).strip() for column in getattr(weekly_df, "columns", [])}
    studio_columns = {str(column).strip() for column in getattr(studio_df, "columns", [])}
    weekly_applicable = {
        "Instructor",
        "Day of Week",
        "Class Time",
    }.issubset(weekly_columns)
    studio_applicable = "Instructor" in studio_columns and bool(
        studio_columns
        & {
            "Studio 1 Date",
            "Studio 1 Time",
            "Studio 2 Date",
            "Studio 2 Time",
            "Studio 3 Date",
            "Studio 3 Time",
        }
    )
    if not weekly_applicable and not studio_applicable:
        return health

    if weekly_applicable and weekly_df is not None:
        weekly_rejections = []
        weekly_requests = prepare_weekly_lessons(
            weekly_df.copy(),
            duplicate_sink=[],
            reject_weekly=lambda raw, reason, normalized=None, row_idx=None, reason_code=None: weekly_rejections.append(
                {
                    "source_request_id": (
                        (normalized or {}).get("source_request_id")
                        or raw.get("_source_request_id")
                        or f"weekly:{row_idx}"
                    ),
                    "reason_code": reason_code or "invalid_source",
                    "reason": reason,
                }
            ),
        )
        health["weekly_request_count"] = len(weekly_requests)
        health["rejections"].extend(weekly_rejections)

    if studio_applicable and studio_df is not None:
        studio_rejections = []
        room_types = {}
        for room in rooms or []:
            if not isinstance(room, dict) or not room.get("id"):
                continue
            raw_types = room.get("types", room.get("type", []))
            room_types[str(room["id"])] = raw_types if isinstance(raw_types, list) else [raw_types]

        def normalize_instrument(raw):
            value = str(raw or "").lower()
            if "piano" in value:
                return "Piano"
            if "voice" in value or "vocal" in value:
                return "Voice"
            if "percussion" in value:
                return "Percussion"
            return "Instrumental"

        studio_requests, studio_rejection_items = prepare_studio_requests(
            studio_df.copy(),
            room_types=room_types,
            normalize_instrument_type=normalize_instrument,
        )
        health["studio_request_count"] = len(studio_requests)
        health["rejections"].extend(
            {
                "source_request_id": item.get("payload", {}).get("source_request_id"),
                "reason_code": item.get("reason_code", "invalid_source"),
                "reason": item.get("reason", "Invalid Studio source"),
            }
            for item in studio_rejection_items
        )

    health["rejection_count"] = len(health["rejections"])
    health["expected_request_count"] = (
        health["weekly_request_count"]
        + health["studio_request_count"]
        + health["rejection_count"]
    )
    health["status"] = "blocked" if health["rejection_count"] else "healthy"
    if health["rejection_count"]:
        health["blocking_errors"].append(
            f"{health['rejection_count']} source request(s) are malformed or incomplete."
        )
    return health


def _draft_health(draft):
    assignments = list((draft or {}).get("assignments", []) or [])
    unresolved = list((draft or {}).get("unassigned_lessons", []) or [])
    source_ids = []
    for item in assignments:
        props = item.get("extendedProps") if isinstance(item, dict) else {}
        props = props if isinstance(props, dict) else {}
        source_id = item.get("source_request_id") or props.get("source_request_id")
        if source_id:
            source_ids.append(str(source_id))
    duplicates = sorted({item for item in source_ids if source_ids.count(item) > 1})
    return {
        "dirty": bool((draft or {}).get("dirty")),
        "assignment_count": len(assignments),
        "unresolved_count": len(unresolved),
        "pinned_count": sum(1 for item in assignments if item.get("pinned") is True),
        "duplicate_source_request_ids": duplicates,
    }


SPECIALIZED_ROOM_TYPES = {"Piano", "Percussion", "Voice", "Instrumental"}


def inspect_room_inventory_health(rooms, rules=None):
    profiles = build_room_profiles(rooms, rules or {})
    total_rooms = len(profiles)
    specialized_room_count = 0
    for profile in profiles:
        effective_types = set(profile.get("effective_types", []))
        if effective_types & SPECIALIZED_ROOM_TYPES:
            specialized_room_count += 1

    all_rooms_general = total_rooms > 0 and specialized_room_count == 0
    degenerated = total_rooms == 0 or all_rooms_general
    status = "degenerated" if degenerated else "healthy"

    return {
        "status": status,
        "rooms_corrupted_or_degenerated": degenerated,
        "total_rooms": total_rooms,
        "specialized_room_count": specialized_room_count,
        "all_rooms_general": all_rooms_general,
    }


def collect_optimizer_preflight(
    loader,
    default_rules=None,
    *,
    weekly_df=None,
    studio_df=None,
    draft=None,
):
    rules_path = loader.preferred_data_path("scheduling_rules.json")
    raw_rules = loader.load_json_data("scheduling_rules.json", default_value={})
    rules_health = inspect_rules_health(
        raw_rules,
        default_rules=default_rules or DEFAULT_RULES,
        source_path=rules_path,
    )

    rooms = loader.get_data("rooms.json") or []
    source_health = _source_health(weekly_df, studio_df, rooms)
    draft_health = _draft_health(draft)
    room_health = inspect_room_inventory_health(rooms, raw_rules)
    instructor_conflicts = audit_source_schedule(weekly_df, studio_df)

    issues = []
    if rules_health["rules_corrupted_or_degenerated"]:
        issues.append(
            "Scheduling rules are degenerated. Restore or rebuild `scheduling_rules.json` before running the optimizer."
        )
    if rules_health.get("validation_errors"):
        issues.append(
            "Scheduling rules contain invalid values: "
            + "; ".join(rules_health["validation_errors"])
        )
    if room_health["rooms_corrupted_or_degenerated"]:
        issues.append(
            "Room inventory has no specialized room types. Re-import room data or restore room type mappings before running the optimizer."
        )
    if instructor_conflicts:
        issues.append(
            f"{len(instructor_conflicts)} instructor time conflicts must be corrected before optimization."
        )
        issues.extend(
            format_instructor_conflict(conflict)
            for conflict in instructor_conflicts[:5]
        )
        if len(instructor_conflicts) > 5:
            issues.append(
                f"{len(instructor_conflicts) - 5} additional instructor conflicts are available in the structured preflight response."
            )
    issues.extend(source_health["blocking_errors"])
    if draft_health["duplicate_source_request_ids"]:
        issues.append("Step 4 draft contains duplicate source_request_id assignments.")

    return {
        "rules_health": rules_health,
        "room_health": room_health,
        "instructor_conflicts": instructor_conflicts,
        "source_health": source_health,
        "draft_health": draft_health,
        "issues": issues,
        "is_blocked": bool(issues),
    }
