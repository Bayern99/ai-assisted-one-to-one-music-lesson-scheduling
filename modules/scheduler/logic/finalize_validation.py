"""Final safety checks run immediately before a Step 4 commit."""

from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.instructor_time_integrity import audit_canonical_schedule
from modules.scheduler.logic.validation_authority import (
    authority_assignments,
    build_occupancy_assignments,
)
from modules.shared.time_parser import TimeParser


def collect_finalize_conflicts(runtime, generated_assignments):
    edit_session = getattr(runtime, "edit_session", None)
    if isinstance(edit_session, dict):
        l1_assignments = authority_assignments(edit_session)
    else:
        l1_assignments = list(getattr(runtime, "locked_context_assignments", []) or [])
    assignments = build_occupancy_assignments(l1_assignments, generated_assignments)
    validator = ConflictValidator(
        {
            "assignments": assignments,
            "lectures": runtime.booked_lectures,
            "rooms": getattr(runtime, "rooms_cache", []) or [],
            "rules": runtime.normalized_rules,
        }
    )
    conflicts = []
    seen_pairs = set()
    warnings = []

    room_ids = {
        str(room.get("id"))
        for room in getattr(runtime, "rooms_cache", []) or []
        if isinstance(room, dict) and room.get("id")
    }
    source_ids = set()
    validation_errors = []
    for event in generated_assignments:
        props = event.get("extendedProps") or {}
        props = props if isinstance(props, dict) else {}
        source_id = event.get("source_request_id") or props.get("source_request_id")
        if source_id and source_id in source_ids:
            validation_errors.append(
                (event, {"id": event.get("id"), "message": f"Duplicate source_request_id: {source_id}"})
            )
        if not source_id:
            validation_errors.append(
                (event, {"id": event.get("id"), "message": "Missing source_request_id."})
            )
        else:
            source_ids.add(source_id)
        room_id = str(event.get("resourceId") or event.get("room_id") or "").strip()
        if room_id not in room_ids:
            validation_errors.append(
                (event, {"id": event.get("id"), "message": f"Unknown room: {room_id}"})
            )
        raw_start, raw_end = TimeParser.event_to_minute_range(event, default=None)
        normalized = TimeParser.canonical_course_occupancy(raw_start, raw_end)
        if normalized is None:
            validation_errors.append(
                (event, {"id": event.get("id"), "message": "Event time is not a canonical whole-hour interval."})
            )
        if normalized and hasattr(validator, "within_time_range") and not validator.within_time_range(*normalized):
            validation_errors.append(
                (event, {"id": event.get("id"), "message": "Event time is outside the configured scheduling window."})
            )
        specific_date = TimeParser.event_specific_date(event)
        days = event.get("daysOfWeek")
        if specific_date and isinstance(days, list) and days:
            expected_day = TimeParser.to_js_weekday(specific_date, default=None)
            if expected_day is None or expected_day not in days:
                validation_errors.append(
                    (event, {"id": event.get("id"), "message": "Studio date and day do not match."})
                )
        if hasattr(validator, "validate_rules"):
            rules_check = validator.validate_rules(
                room_id,
                props.get("normalized_instrument") or props.get("Instrument", ""),
            )
            if not rules_check.get("allowed", True):
                validation_errors.append(
                    (event, {"id": event.get("id"), "message": rules_check.get("reason", "Room type mismatch")})
                )

    def append_pair(event, conflict):
        pair_key = tuple(sorted([event.get("id", ""), conflict.get("id", "")]))
        if pair_key in seen_pairs:
            return
        seen_pairs.add(pair_key)
        conflicts.append((event, conflict))

    for event in generated_assignments:
        start_min, end_min = validator._parse_time(event)
        if start_min is None or end_min is None:
            continue
        props = event.get("extendedProps")
        props = props if isinstance(props, dict) else {}
        room_id = str(event.get("resourceId") or event.get("room_id") or "").strip()
        if not room_id:
            continue
        for day in event.get("daysOfWeek", []):
            conflict = validator.check_conflict(
                room_id,
                day,
                start_min,
                end_min,
                exclude_id=event.get("id"),
            )
            if conflict and conflict.get("id") != event.get("id"):
                append_pair(event, conflict)

        specific_date = TimeParser.event_specific_date(event)
        if event.get("daysOfWeek") or not specific_date:
            continue
        try:
            day_js = TimeParser.to_js_weekday(specific_date, default=None)
            if day_js is None:
                raise ValueError("invalid specific_date")
            conflict = validator.check_conflict(
                event["resourceId"],
                day_js,
                start_min,
                end_min,
                specific_date=specific_date,
                exclude_id=event.get("id"),
            )
            if conflict and conflict.get("id") != event.get("id"):
                append_pair(event, conflict)
        except Exception:
            validation_errors.append(
                (
                    event,
                    {
                        "id": event.get("id"),
                        "message": "Studio date cannot be validated.",
                    },
                )
            )

    events_by_id = {
        str(event.get("id")): event
        for event in assignments
        if event.get("id") is not None
    }
    for conflict in audit_canonical_schedule(assignments):
        left = events_by_id.get(str(conflict["left"]["id"]))
        right = events_by_id.get(str(conflict["right"]["id"]))
        if left is not None and right is not None:
            append_pair(left, right)

    return conflicts + validation_errors, warnings
