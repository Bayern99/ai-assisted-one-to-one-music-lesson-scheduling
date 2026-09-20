"""Request-level reconciliation for source workbooks and Step 4 state."""

from modules.shared.field_schema import DAY_MAP_EN, parse_studio_date
from modules.scheduler.logic.validation_authority import build_occupancy_assignments
from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.source_requests import (
    is_missing,
    stable_row_index,
    studio_source_request_id,
    studio_time_tokens,
    weekly_source_request_id,
)


MATCH = "MATCH"
PHANTOM = "PHANTOM"
MISSING = "MISSING"


def normalize_time(t_str):
    normalized = TimeParser.normalize_course_range(t_str)
    if not normalized:
        return None
    return TimeParser.to_minutes(normalized[0], default=None) // 60


def _rows(value):
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return value.to_dict(orient="records")
    return [row for row in value if isinstance(row, dict)]


def _source_request(source_request_id, row, *, source, day=None, date=None, time_value="", slot=None):
    normalized = TimeParser.normalize_course_range(time_value)
    interval = None
    if normalized:
        interval = (
            TimeParser.to_minutes(normalized[0], default=None),
            TimeParser.to_minutes(normalized[1], default=None),
        )
    return {
        "source_request_id": source_request_id,
        "source": source,
        "Instructor": str(row.get("Instructor", "")).strip(),
        "Student No": str(row.get("Student No", "")).strip(),
        "Student Name": row.get("Student Name", ""),
        "Day": day,
        "Date": date,
        "Time": normalized and f"{normalized[0]}-{normalized[1]}" or str(time_value or ""),
        "start": interval[0] if interval else None,
        "end": interval[1] if interval else None,
        "valid_time": interval is not None,
        "slot": slot,
    }


def build_source_requests(weekly_df=None, studio_df=None):
    requests = []
    for fallback_index, row in enumerate(_rows(weekly_df)):
        row_index = stable_row_index(row, fallback_index)
        day = row.get("Day of Week")
        if isinstance(day, str):
            day = DAY_MAP_EN.get(day.strip(), day)
        requests.append(
            _source_request(
                weekly_source_request_id(row, fallback_index),
                row,
                source="weekly",
                day=day,
                time_value=row.get("Class Time", ""),
            )
        )

    for fallback_index, row in enumerate(_rows(studio_df)):
        for slot_index in range(1, 4):
            date_value = row.get(f"Studio {slot_index} Date")
            time_value = row.get(f"Studio {slot_index} Time")
            if is_missing(date_value) and is_missing(time_value):
                continue
            date = TimeParser.extract_iso_date(date_value)
            if not date:
                parsed, _day, _name = parse_studio_date(str(date_value or ""))
                date = parsed.strftime("%Y-%m-%d") if parsed else None
            tokens = studio_time_tokens(time_value)
            for time_index, token in enumerate(tokens):
                request_id = studio_source_request_id(
                    row,
                    fallback_index,
                    slot_index,
                    time_index,
                )
                requests.append(
                    _source_request(
                        request_id,
                        row,
                        source="studio",
                        day=TimeParser.to_js_weekday(date, default=None),
                        date=date,
                        time_value=token,
                        slot=f"{slot_index}:{time_index}",
                    )
                )
    return requests


def _assignment_source_id(assignment):
    props = assignment.get("extendedProps") or {}
    if not isinstance(props, dict):
        props = {}
    return assignment.get("source_request_id") or props.get("source_request_id")


def _assignment_signature(assignment):
    props = assignment.get("extendedProps") or {}
    if not isinstance(props, dict):
        props = {}
    start, end = TimeParser.event_to_minute_range(assignment, default=None)
    day = (
        (assignment.get("daysOfWeek") or [None])[0]
        if assignment.get("daysOfWeek")
        else props.get("Day of Week")
    )
    if isinstance(day, str):
        day = DAY_MAP_EN.get(day.strip(), day)
    return {
        "Instructor": str(props.get("Instructor", props.get("instructor", ""))).strip(),
        "Student No": str(props.get("Student No", props.get("student_id", ""))).strip(),
        "Day": day,
        "start": start,
        "end": end,
    }


def _legacy_match(source, assignment_signature):
    if source["Instructor"] != assignment_signature["Instructor"]:
        return False
    source_student = source["Student No"]
    if source_student and assignment_signature["Student No"] and source_student != assignment_signature["Student No"]:
        return False
    if source["Day"] != assignment_signature["Day"]:
        return False
    if source["start"] is None or assignment_signature["start"] is None:
        return False
    return source["start"] == assignment_signature["start"]


def reconcile_assignments(
    raw_df,
    assignments,
    *,
    studio_df=None,
    unresolved=None,
    strict_identity=True,
):
    source_requests = build_source_requests(raw_df, studio_df)
    by_source_id = {
        item["source_request_id"]: item for item in source_requests
    }
    unresolved_items = list(unresolved or [])
    unresolved_by_source = {}
    unresolved_missing_id = []
    unresolved_source_ids = {}
    for index, item in enumerate(unresolved_items):
        props = item.get("extendedProps") or {}
        source_id = item.get("source_request_id") or (
            props.get("source_request_id") if isinstance(props, dict) else None
        )
        if source_id:
            source_id = str(source_id)
            unresolved_source_ids.setdefault(source_id, []).append(index)
            unresolved_by_source.setdefault(source_id, item)
        else:
            unresolved_missing_id.append(
                {
                    "collection": "unresolved",
                    "index": index,
                    "item_id": item.get("id"),
                }
            )

    report = {
        "matches": [],
        "missing": [],
        "phantom": [],
        "duplicates": [],
        "source_request_count": len(source_requests),
        "assigned_count": len(assignments or []),
        "unresolved_count": len(unresolved_items),
        "accounted_request_count": 0,
        "is_valid": True,
        "missing_source_request_ids": [],
        "phantom_source_request_ids": [],
        "duplicate_assigned_source_request_ids": [],
        "duplicate_unresolved_source_request_ids": [],
        "dual_state_source_request_ids": [],
        "missing_source_id_locations": list(unresolved_missing_id),
        "blocking_reason_codes": [],
    }
    matched_source_ids = set()
    assignment_source_ids = {}
    assignment_missing_id = []
    assignment_ids_by_source = {}

    for index, assignment in enumerate(assignments or []):
        source_id = _assignment_source_id(assignment)
        if not source_id:
            assignment_missing_id.append(
                {
                    "collection": "assigned",
                    "index": index,
                    "item_id": assignment.get("id"),
                }
            )
            if not strict_identity:
                source = _legacy_match_source(source_requests, assignment, matched_source_ids)
            else:
                source = None
        else:
            source_id = str(source_id)
            assignment_ids_by_source.setdefault(source_id, []).append(index)
            source = by_source_id.get(source_id)
        if source is None and source_id:
            report["phantom"].append(
                {
                    "assignment_id": assignment.get("id"),
                    "source_request_id": source_id,
                    "state": "assigned",
                    "details": "Assignment source_request_id is absent from the current source workbook.",
                }
            )
            continue
        if source is None and not source_id and not strict_identity:
            signature = _assignment_signature(assignment)
            source = next(
                (
                    item
                    for item in source_requests
                    if item["source_request_id"] not in matched_source_ids
                    and _legacy_match(item, signature)
                ),
                None,
            )
        if source is None:
            if not source_id and strict_identity:
                continue
            report["phantom"].append(
                {
                    "assignment_id": assignment.get("id"),
                    "details": "No source request matches this assignment.",
                }
            )
            continue

        source_id = source["source_request_id"]
        if source_id in assignment_source_ids:
            report["duplicates"].append(
                {
                    "source_request_id": source_id,
                    "assignment_ids": [
                        assignment_source_ids[source_id],
                        assignment.get("id"),
                    ],
                }
            )
            continue
        assignment_source_ids[source_id] = assignment.get("id")
        matched_source_ids.add(source_id)

    for source_id, indexes in unresolved_source_ids.items():
        if len(indexes) > 1:
            report["duplicate_unresolved_source_request_ids"].append(source_id)

    report["missing_source_id_locations"].extend(assignment_missing_id)

    for source in source_requests:
        source_id = source["source_request_id"]
        assigned = source_id in assignment_source_ids
        unresolved_item = unresolved_by_source.get(source_id)
        if assigned:
            report["matches"].append(
                {
                    "assignment_id": assignment_source_ids[source_id],
                    "source_request_id": source_id,
                    "state": "assigned",
                    "details": next(
                        (
                            item.get("details")
                            for item in report["matches"]
                            if item.get("source_request_id") == source_id
                            and item.get("state") == "assigned"
                        ),
                        "Assigned",
                    ),
                }
            )
        if unresolved_item is not None:
            report["matches"].append(
                {
                    "assignment_id": None,
                    "source_request_id": source_id,
                    "state": "unresolved",
                    "details": unresolved_item.get("reason", "Unresolved"),
                }
            )
        if not assigned and unresolved_item is None:
            report["missing"].append(
                {
                    "source_request_id": source_id,
                    "Instructor": source["Instructor"],
                    "Day": source["Day"],
                    "Time": source["Time"],
                    "Student": source["Student Name"],
                }
            )

    unresolved_unknown_ids = sorted(
        source_id for source_id in unresolved_source_ids if source_id not in by_source_id
    )
    for source_id in unresolved_unknown_ids:
        report["phantom"].append(
            {
                "assignment_id": unresolved_by_source[source_id].get("id"),
                "source_request_id": source_id,
                "state": "unresolved",
                "details": "Unresolved source_request_id is absent from the current source workbook.",
            }
        )

    assigned_ids = set(assignment_source_ids)
    unresolved_ids = set(unresolved_source_ids)
    report["dual_state_source_request_ids"] = sorted(
        assigned_ids & unresolved_ids & set(by_source_id)
    )
    report["missing_source_request_ids"] = sorted(
        set(by_source_id) - assigned_ids - unresolved_ids
    )
    report["phantom_source_request_ids"] = sorted(
        {
            str(item["source_request_id"])
            for item in report["phantom"]
            if item.get("source_request_id")
        }
    )
    report["duplicate_assigned_source_request_ids"] = sorted(
        source_id
        for source_id, indexes in assignment_ids_by_source.items()
        if len(indexes) > 1
    )
    duplicate_compatibility = sorted(
        report["duplicates"],
        key=lambda item: str(item.get("source_request_id") or ""),
    )
    duplicate_compatibility.extend(
        {
            "source_request_id": source_id,
            "state": "unresolved",
            "item_indexes": unresolved_source_ids[source_id],
        }
        for source_id in report["duplicate_unresolved_source_request_ids"]
    )
    report["duplicates"] = sorted(
        duplicate_compatibility,
        key=lambda item: (
            str(item.get("source_request_id") or ""),
            str(item.get("state") or "assigned"),
        ),
    )
    present_valid_ids = (assigned_ids | unresolved_ids) & set(by_source_id)
    report["accounted_request_count"] = len(present_valid_ids)
    reason_pairs = (
        ("missing_source", bool(report["missing_source_request_ids"])),
        ("phantom_result", bool(report["phantom"])),
        ("duplicate_assigned", bool(report["duplicate_assigned_source_request_ids"])),
        ("duplicate_unresolved", bool(report["duplicate_unresolved_source_request_ids"])),
        ("assigned_and_unresolved", bool(report["dual_state_source_request_ids"])),
        ("missing_source_request_id", bool(report["missing_source_id_locations"])),
    )
    report["blocking_reason_codes"] = [code for code, present in reason_pairs if present]
    report["is_valid"] = not report["blocking_reason_codes"]
    report["missing_count"] = len(report["missing_source_request_ids"])
    report["phantom_count"] = len(report["phantom_source_request_ids"])
    report["duplicate_assigned_count"] = len(
        report["duplicate_assigned_source_request_ids"]
    )
    report["duplicate_unresolved_count"] = len(
        report["duplicate_unresolved_source_request_ids"]
    )
    report["dual_state_count"] = len(report["dual_state_source_request_ids"])
    report["missing_source_id_count"] = len(report["missing_source_id_locations"])
    return report


def _legacy_match_source(source_requests, assignment, matched_source_ids):
    signature = _assignment_signature(assignment)
    return next(
        (
            item
            for item in source_requests
            if item["source_request_id"] not in matched_source_ids
            and _legacy_match(item, signature)
        ),
        None,
    )


def verify_candidate_state(
    raw_df,
    assignments,
    *,
    studio_df=None,
    unresolved=None,
    rooms=None,
    rules=None,
    locked_context_assignments=None,
    lectures=None,
    validator=None,
):
    """Verify one complete candidate before any scheduler state is persisted."""
    report = reconcile_assignments(
        raw_df,
        assignments,
        studio_df=studio_df,
        unresolved=unresolved,
        strict_identity=True,
    )
    validation_errors = []
    candidate_assignments = build_occupancy_assignments(
        locked_context_assignments,
        assignments,
    )

    if validator is None:
        from modules.scheduler.logic.conflict_validator import ConflictValidator

        validator = ConflictValidator(
            {
                "assignments": candidate_assignments,
                "lectures": list(lectures or []),
                "rooms": list(rooms or []),
                "rules": rules or {},
            }
        )
    elif hasattr(validator, "assignments"):
        validator.assignments = candidate_assignments

    room_ids = {
        str(room.get("id"))
        for room in rooms or []
        if isinstance(room, dict) and room.get("id")
    }
    for index, event in enumerate(assignments or []):
        start_min, end_min = TimeParser.event_to_minute_range(event, default=None)
        interval = TimeParser.canonical_course_occupancy(start_min, end_min)
        if interval is None:
            validation_errors.append(
                {
                    "code": "noncanonical_occupancy",
                    "collection": "assigned",
                    "index": index,
                    "item_id": event.get("id"),
                }
            )
            continue

        room_id = str(event.get("resourceId") or event.get("room_id") or "").strip()
        if room_ids and room_id not in room_ids:
            validation_errors.append(
                {
                    "code": "room_missing",
                    "collection": "assigned",
                    "index": index,
                    "item_id": event.get("id"),
                    "room_id": room_id,
                }
            )
        if hasattr(validator, "within_time_range") and not validator.within_time_range(*interval):
            validation_errors.append(
                {
                    "code": "outside_scheduling_window",
                    "collection": "assigned",
                    "index": index,
                    "item_id": event.get("id"),
                }
            )

        props = event.get("extendedProps") if isinstance(event.get("extendedProps"), dict) else {}
        if hasattr(validator, "validate_rules") and room_id:
            rules_check = validator.validate_rules(
                room_id,
                props.get("normalized_instrument") or props.get("Instrument", ""),
            )
            if not rules_check.get("allowed", True):
                validation_errors.append(
                    {
                        "code": "room_type_mismatch",
                        "collection": "assigned",
                        "index": index,
                        "item_id": event.get("id"),
                    }
                )

        days = event.get("daysOfWeek") or []
        specific_date = TimeParser.event_specific_date(event)
        if specific_date and not days:
            days = [TimeParser.to_js_weekday(specific_date, default=None)]
        for day in days if isinstance(days, list) else []:
            if day not in range(7) or not room_id:
                continue
            conflict = validator.check_conflict(
                room_id,
                day,
                interval[0],
                interval[1],
                specific_date=specific_date,
                exclude_id=event.get("id"),
            )
            if conflict and conflict.get("id") != event.get("id"):
                validation_errors.append(
                    {
                        "code": "schedule_conflict",
                        "collection": "assigned",
                        "index": index,
                        "item_id": event.get("id"),
                        "conflict_id": conflict.get("id"),
                    }
                )

    from modules.scheduler.logic.instructor_time_integrity import audit_canonical_schedule

    candidate_ids = {str(item.get("id")) for item in assignments or []}
    for conflict in audit_canonical_schedule(candidate_assignments):
        if not candidate_ids.intersection(
            {
                str(conflict["left"].get("id")),
                str(conflict["right"].get("id")),
            }
        ):
            continue
        validation_errors.append(
            {
                "code": "teacher_conflict",
                "left_id": conflict["left"].get("id"),
                "right_id": conflict["right"].get("id"),
            }
        )

    codes = set(report.get("blocking_reason_codes", []))
    codes.update(item["code"] for item in validation_errors)
    return {
        "is_valid": bool(report.get("is_valid")) and not validation_errors,
        "reconciliation": report,
        "validation_errors": sorted(
            validation_errors,
            key=lambda item: tuple(str(item.get(key, "")) for key in ("code", "collection", "index", "item_id", "left_id", "right_id")),
        ),
        "blocking_reason_codes": sorted(codes),
    }
