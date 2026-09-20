import copy

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic._data_normalization import enrich_unassigned_slot
from modules.scheduler.logic._time_strategy import apply_time_to_slot
from modules.scheduler.logic.instructor_time_integrity import instructor_is_available
from modules.scheduler.logic.schedule_change_policy import (
    confirmation_message,
    event_time_changed,
    instructor_allows_time_change,
    time_change_pool_message,
)
from modules.shared.field_schema import extract_instrument_from_course_code
from modules.shared.time_parser import TimeParser


def find_slot(assignments, slot_id):
    return next((a for a in assignments if a["id"] == slot_id), None)


def resolve_specific_date(slot):
    if slot.get("type") == "studio_class":
        return TimeParser.event_specific_date(slot)
    return None


def resolve_slot_instrument(slot):
    """Resolve instrument metadata across optimizer, studio, and manual event shapes."""
    props = slot.get("extendedProps") or {}
    raw_row = slot.get("raw_row") or {}
    ignored = {"", "?", "unknown", "n/a", "na", "studio/unknown"}

    for source in (props, raw_row, slot):
        for key in ("normalized_instrument", "Instrument", "instrument", "Instruments"):
            value = str(source.get(key, "")).strip()
            if value.lower() not in ignored:
                return value

    course_code = (
        props.get("Course Code")
        or raw_row.get("Course Code")
        or slot.get("Course Code")
    )
    if course_code:
        return extract_instrument_from_course_code(course_code)
    return ""


def compute_slot_duration_minutes(slot):
    """Return the slot's original duration in minutes, defaulting to 60."""
    start_clock, end_clock = TimeParser.event_clock_pair(slot, default=(None, None))
    interval = TimeParser.canonical_course_occupancy(
        TimeParser.to_minutes(start_clock, default=None),
        TimeParser.to_minutes(end_clock, default=None),
    )
    if interval is None:
        specific_date = resolve_specific_date(slot)
        dated_interval = TimeParser.date_clock_interval(
            specific_date,
            start_clock,
            end_clock,
        )
        if dated_interval:
            return max(
                1,
                int((dated_interval[1] - dated_interval[0]).total_seconds() // 60),
            )
        return 60
    return interval[1] - interval[0]


def validate_move(
    validator,
    slot,
    new_room_id,
    new_day_idx,
    new_start_str,
    new_end_str,
    *,
    teacher_confirmed=None,
):
    raw_start = TimeParser.normalize_clock(new_start_str)
    raw_end = TimeParser.normalize_clock(new_end_str, prefer_end=True)
    if raw_start and raw_end and TimeParser.to_minutes(raw_end) <= TimeParser.to_minutes(raw_start):
        return {"success": False, "message": "End time must be after start time."}
    normalized_range = TimeParser.normalize_course_range(
        f"{new_start_str}-{new_end_str}"
    )
    if not normalized_range:
        return {"success": False, "message": "Invalid time format."}
    start_norm, end_norm = normalized_range

    spec_date = resolve_specific_date(slot)
    if spec_date:
        expected_day = TimeParser.to_js_weekday(spec_date, default=None)
        if new_day_idx != expected_day:
            return {
                "success": False,
                "message": f"Studio date {spec_date} requires day {expected_day}.",
            }
        interval = TimeParser.date_clock_interval(spec_date, start_norm, end_norm)
        if interval is None:
            return {"success": False, "message": "Invalid time range."}
        start_dt, end_dt = interval
        s_min = start_dt.hour * 60 + start_dt.minute
        e_min = s_min + int((end_dt - start_dt).total_seconds() // 60)
    else:
        sh, sm = map(int, start_norm.split(":"))
        eh, em = map(int, end_norm.split(":"))
        s_min = sh * 60 + sm
        e_min = eh * 60 + em
        if e_min <= s_min:
            return {"success": False, "message": "End time must be after start time."}

    if hasattr(validator, "within_time_range") and not validator.within_time_range(
        s_min,
        e_min,
    ):
        return {
            "success": False,
            "message": "Time is outside the configured scheduling window.",
        }

    conflict = validator.check_conflict(
        room_id=new_room_id,
        day_idx=new_day_idx,
        start_min=s_min,
        end_min=e_min,
        specific_date=spec_date,
        exclude_id=slot.get("id"),
    )
    if conflict:
        conflict_name = conflict.get("title", "Unknown Event")
        if conflict.get("is_locked_lecture"):
            return {
                "success": False,
                "message": f"Conflict with Locked Lecture: {conflict_name}",
            }
        return {"success": False, "message": f"Conflict with {conflict_name}"}

    props = slot.get("extendedProps") or {}
    instructor = str(props.get("Instructor") or slot.get("instructor") or "").strip()
    if not instructor_is_available(
        getattr(validator, "assignments", []),
        instructor=instructor,
        day=new_day_idx,
        start_min=s_min,
        end_min=e_min,
        specific_date=spec_date,
        exclude_ids=[slot.get("id")],
    ):
        return {
            "success": False,
            "message": f"Instructor time conflict: {instructor} is already teaching at this time.",
        }

    instrument = resolve_slot_instrument(slot)
    if instrument and hasattr(validator, "validate_rules"):
        rules_check = validator.validate_rules(new_room_id, instrument)
        if not rules_check.get("allowed", True):
            return {
                "success": False,
                "message": rules_check.get("reason", "Room type mismatch"),
            }

    requires_confirmation = event_time_changed(
        slot,
        day=new_day_idx,
        start=start_norm,
        end=end_norm,
    )
    if requires_confirmation and not instructor_allows_time_change(
        getattr(validator, "rules", {}),
        instructor,
    ):
        return {
            "success": False,
            "message": time_change_pool_message(instructor),
        }
    teacher_message = confirmation_message(instructor) if requires_confirmation else None
    if requires_confirmation and teacher_confirmed is False:
        return {
            "success": False,
            "message": teacher_message,
            "requires_teacher_confirmation": True,
            "teacher_confirmation_message": teacher_message,
        }

    return {
        "success": True,
        "proposal_start": raw_start,
        "proposal_end": raw_end,
        "start_norm": start_norm,
        "end_norm": end_norm,
        "specific_date": spec_date,
        "warnings": [],
        "requires_teacher_confirmation": requires_confirmation,
        "teacher_confirmation_message": teacher_message,
    }


def apply_move(slot, new_room_id, new_day_idx, start_norm, end_norm, specific_date=None):
    slot["resourceId"] = new_room_id
    slot["room_id"] = new_room_id
    apply_time_to_slot(slot, new_day_idx, start_norm, end_norm, specific_date)
    slot["pinned"] = True
    return copy.deepcopy(slot)


def apply_unassign(assignments, unassigned, slot):
    assignments.remove(slot)
    enrich_unassigned_slot(slot)
    unassigned.append(slot)
    return copy.deepcopy(slot)


def revert_record(assignments, unassigned, record):
    action = record.get("action", "move")
    if action == "compound":
        for child in reversed(record.get("records", [])):
            revert_record(assignments, unassigned, child)
        return True
    slot_id = record["slot_id"]
    prev = record["prev_state"]

    if action == "move":
        target = find_slot(assignments, slot_id)
        if target:
            target.update(prev)
    elif action == "unassign":
        target = find_slot(unassigned, slot_id)
        if target:
            unassigned.remove(target)
            target.update(prev)
            assignments.append(target)
        else:
            assignments.append(copy.deepcopy(prev))
    elif action == "assign":
        return unresolved_assignment_primitives.revert_record(
            assignments,
            unassigned,
            record,
        )
    return True


def replay_record(assignments, unassigned, record):
    action = record.get("action", "move")
    if action == "compound":
        for child in record.get("records", []):
            replay_record(assignments, unassigned, child)
        return True
    slot_id = record["slot_id"]
    new_state = copy.deepcopy(record.get("new_state", {}))

    if action == "move":
        target = find_slot(assignments, slot_id)
        if target:
            target.update(new_state)
        else:
            assignments.append(new_state)
    elif action == "unassign":
        target = find_slot(assignments, slot_id)
        if target:
            assignments.remove(target)
            target.update(new_state)
            unassigned.append(target)
        else:
            unassigned.append(new_state)
    elif action == "assign":
        return unresolved_assignment_primitives.replay_record(
            assignments,
            unassigned,
            record,
        )
    return True
