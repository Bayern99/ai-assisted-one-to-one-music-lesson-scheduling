"""Pure identity, validation, and history operations for unresolved assignments."""

import copy
import hashlib
import json
import math

from modules.shared.field_schema import DAY_MAP_EN, extract_instrument_from_course_code
from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.unresolved_assignment_policy import validate_unresolved_policy


def _is_missing(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in {
        "",
        "<na>",
        "nan",
        "none",
        "null",
        "nat",
    }


def _first_value(sources, keys, default=None):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if not _is_missing(value):
                return value
    return default


def _stable_json_value(value):
    if isinstance(value, dict):
        return {
            str(key): _stable_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _source_identity_payload(unresolved):
    raw_row = unresolved.get("raw_row")
    if isinstance(raw_row, dict) and raw_row:
        return {
            "raw_row": raw_row,
            "type": unresolved.get("type"),
            "date": unresolved.get("date"),
            "day": unresolved.get("day"),
            "start": unresolved.get("start"),
            "end": unresolved.get("end"),
            "source_row_index": unresolved.get("source_row_index"),
        }
    ignored = {
        "reason",
        "reason_code",
        "placement_group_id",
        "placement_group_size",
        "backgroundColor",
        "borderColor",
        "textColor",
        "color",
        "className",
        "classNames",
        "display",
    }
    return {key: value for key, value in unresolved.items() if key not in ignored}


def _stable_digest(value):
    serialized = json.dumps(
        _stable_json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def source_request_id(unresolved):
    """Return a source identity that never depends on queue position."""
    explicit = _first_value(
        [unresolved],
        ("source_request_id", "request_id", "source_id"),
    )
    if explicit is not None:
        return str(explicit).strip()
    legacy_id = _first_value([unresolved], ("id",))
    if legacy_id is not None and not _is_studio_request(unresolved):
        return str(legacy_id).strip()
    return f"source-{_stable_digest(_source_identity_payload(unresolved))}"


def issue_id(unresolved):
    explicit = _first_value([unresolved], ("issue_id",))
    if explicit is not None:
        return str(explicit).strip()
    legacy_id = _first_value([unresolved], ("id",))
    if legacy_id is not None and not _is_studio_request(unresolved):
        return str(legacy_id).strip()
    return f"issue-{_stable_digest(_source_identity_payload(unresolved))}"


def _is_studio_request(unresolved):
    event_type = str(unresolved.get("type") or "").strip().lower()
    legacy_id = str(unresolved.get("id") or "").strip().lower()
    return (
        event_type == "studio_class"
        or bool(TimeParser.extract_iso_date(unresolved.get("date")))
        or legacy_id.startswith("stu_")
        or legacy_id.startswith("stu-")
    )


def find_unresolved(unassigned, stable_issue_id):
    stable_issue_id = str(stable_issue_id or "").strip()
    return next(
        (
            item
            for item in unassigned
            if issue_id(item) == stable_issue_id
            or str(item.get("id") or "").strip() == stable_issue_id
        ),
        None,
    )


def _clock_value(value, *, prefer_end=False):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not _is_missing(value):
        hour = int(value)
        if value == hour and 0 <= hour <= 23:
            return f"{hour:02d}:00"
    return TimeParser.normalize_clock(
        value,
        prefer_end=prefer_end,
        allow_midnight=prefer_end,
    )


def _string_list(value):
    if value is None:
        return []
    values = (
        value
        if isinstance(value, (list, tuple, set))
        else str(value).replace("，", ",").split(",")
    )
    result = []
    for item in values:
        text = str(item).strip()
        if text and text.lower() not in {"<na>", "nan", "none", "null"} and text not in result:
            result.append(text)
    return result


def enrich_student_instruments(unresolved_items, students):
    by_id, by_name = {}, {}
    for student in students or []:
        if not isinstance(student, dict):
            continue
        meta = student.get("meta") if isinstance(student.get("meta"), dict) else {}
        instrument = str(student.get("instrument") or meta.get("Instrument") or "").strip()
        if not instrument:
            continue
        student_id = str(student.get("student_id") or meta.get("Student No") or "").strip()
        student_name = str(student.get("name_en") or student.get("display_name") or "").strip()
        if student_id:
            by_id[student_id.removesuffix(".0")] = instrument
        if student_name:
            by_name[student_name.casefold()] = instrument
    generic = {"", "instrumental", "unknown", "general", "n/a", "studio/unknown"}
    for item in unresolved_items or []:
        if not isinstance(item, dict):
            continue
        context = build_context(item)
        if str(context.get("instrument") or "").strip().casefold() not in generic:
            continue
        student_id = str(context.get("student_id") or "").strip().removesuffix(".0")
        student_name = str(context.get("student_name") or "").strip().casefold()
        instrument = by_id.get(student_id) or by_name.get(student_name)
        if instrument:
            item["instrument"] = instrument

def build_context(unresolved):
    raw_row = (
        unresolved.get("raw_row")
        if isinstance(unresolved.get("raw_row"), dict)
        else {}
    )
    props = (
        unresolved.get("extendedProps")
        if isinstance(unresolved.get("extendedProps"), dict)
        else {}
    )
    sources = [unresolved, raw_row, props]
    course_code = str(
        _first_value(sources, ("course_code", "Course Code"), "") or ""
    ).strip()
    instrument = str(
        _first_value(
            sources,
            ("instrument", "Instrument", "Instruments", "normalized_instrument"),
            "",
        )
        or ""
    ).strip()
    if not instrument and course_code:
        instrument = extract_instrument_from_course_code(course_code)

    original_date = TimeParser.extract_iso_date(
        _first_value(
            sources,
            ("original_date", "date", "Date", "Studio Date"),
        )
    )
    if original_date:
        original_day = TimeParser.to_js_weekday(original_date, default=None)
    else:
        original_day = _first_value(
            sources,
            ("original_day", "day", "dayOfWeek", "Day of Week"),
        )
        if isinstance(original_day, str) and not original_day.strip().isdigit():
            original_day = DAY_MAP_EN.get(original_day.strip())
        try:
            original_day = int(original_day)
        except (TypeError, ValueError):
            original_day = None
    if isinstance(original_day, bool) or original_day not in range(7):
        original_day = None

    original_start = _clock_value(
        _first_value(
            sources,
            ("original_start", "start", "startTime", "Class Time"),
        )
    )
    original_end = _clock_value(
        _first_value(
            sources,
            ("original_end", "end", "endTime", "Class Time"),
        ),
        prefer_end=True,
    )
    start_min = TimeParser.to_minutes(original_start, default=None)
    end_min = TimeParser.to_minutes(original_end, default=None)
    duration = _first_value(
        sources,
        ("duration_minutes", "duration", "Duration"),
    )
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        interval = TimeParser.date_clock_interval(
            original_date,
            original_start,
            original_end,
        )
        if interval:
            start_dt, end_dt = interval
            duration = TimeParser.event_duration_minutes(
                {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                default=60,
            )
        else:
            duration = (
                end_min - start_min
                if start_min is not None and end_min is not None
                else 60
            )
    if duration <= 0:
        duration = 60

    preferred_raw = _first_value(
        sources,
        ("preferred_venues", "prefs", "Preferred Venue", "preferred_venue"),
    )
    room_types = _string_list(
        _first_value(sources, ("room_types", "room_type", "Room Type"))
    )
    if not room_types and instrument:
        room_types = [instrument]
    event_type = str(
        _first_value(sources, ("type", "event_type", "Event Type"), "") or ""
    ).strip()
    if not event_type:
        event_type = "studio_class" if original_date else "weekly_lesson"

    reason = str(
        unresolved.get("reason") or unresolved.get("reason_code") or "unknown"
    ).strip()
    placement_group_id = str(
        _first_value(sources, ("placement_group_id",), "") or ""
    ).strip() or None
    placement_group_size = _first_value(sources, ("placement_group_size",))
    try:
        placement_group_size = int(placement_group_size)
    except (TypeError, ValueError):
        placement_group_size = None
    if placement_group_size is not None and placement_group_size < 1:
        placement_group_size = None
    return {
        "source_request_id": source_request_id(unresolved),
        "instructor": str(
            _first_value(sources, ("inst", "instructor", "Instructor"), "") or ""
        ).strip()
        or None,
        "course_code": course_code or None,
        "student_name": str(
            _first_value(
                sources,
                ("student", "student_name", "Student Name", "title"),
                "",
            )
            or ""
        ).strip()
        or None,
        "student_id": str(
            _first_value(
                sources,
                ("sid", "student_id", "Student No", "Student ID"),
                "",
            )
            or ""
        ).strip()
        or None,
        "type": event_type,
        "instrument": instrument or None,
        "duration_minutes": duration,
        "original_day": original_day,
        "original_start": original_start,
        "original_end": original_end,
        "original_time": (
            f"{original_start}-{original_end}"
            if original_start and original_end
            else original_start or original_end
        ),
        "original_date": original_date,
        "preferred_venues": _string_list(preferred_raw),
        "room_types": room_types,
        "reason": reason,
        "placement_group_id": placement_group_id,
        "placement_group_size": placement_group_size,
    }


def build_assignment(unresolved, *, room, day, start, end):
    context = build_context(unresolved)
    start_min = TimeParser.to_minutes(start, default=None)
    end_min = TimeParser.to_minutes(end, default=None)
    normalized_range = TimeParser.canonical_course_occupancy(start_min, end_min)
    if normalized_range is None:
        raise ValueError("invalid_course_time")
    start_norm, end_norm = TimeParser.minute_range_to_clocks(*normalized_range)
    raw_row = copy.deepcopy(
        unresolved.get("raw_row")
        if isinstance(unresolved.get("raw_row"), dict)
        else {}
    )
    existing_props = unresolved.get("extendedProps")
    props = copy.deepcopy(existing_props if isinstance(existing_props, dict) else {})
    canonical_values = {
        "Instructor": context["instructor"],
        "Student Name": context["student_name"],
        "Student No": context["student_id"],
        "Instrument": context["instrument"],
        "Course Code": context["course_code"],
        "Preferred Venue": raw_row.get("Preferred Venue")
        or ", ".join(context["preferred_venues"]),
        "source_request_id": context["source_request_id"],
        "original_day": context["original_day"],
        "original_start": start_norm,
        "original_end": end_norm,
        "original_time": f"{start_norm}-{end_norm}",
        "original_date": context["original_date"],
    }
    props.update(
        {
            key: value
            for key, value in canonical_values.items()
            if value not in (None, "")
        }
    )
    title = str(unresolved.get("title") or "").strip()
    if not title:
        identity = (
            context["student_name"]
            or context["instructor"]
            or context["source_request_id"]
        )
        instrument_label = (
            f" ({context['instrument']})" if context["instrument"] else ""
        )
        title = f"👤 {identity}{instrument_label}"
    assignment = {
        "id": context["source_request_id"],
        "source_request_id": context["source_request_id"],
        "unresolved_issue_id": issue_id(unresolved),
        "resourceId": str(room).strip(),
        "room_id": str(room).strip(),
        "title": title,
        "type": context["type"],
        "pinned": True,
        "raw_row": raw_row,
        "source_payload": copy.deepcopy(unresolved),
        "extendedProps": props,
    }
    if context["type"] == "studio_class" and context["original_date"]:
        interval = TimeParser.date_clock_interval(
            context["original_date"],
            start_norm,
            end_norm,
        )
        if interval:
            start_dt, end_dt = interval
            start_value = start_dt.isoformat(timespec="seconds")
            end_value = end_dt.isoformat(timespec="seconds")
        else:
            start_value = f"{context['original_date']}T{start_norm}:00"
            end_value = f"{context['original_date']}T{end_norm}:00"
        assignment.update(
            {
                "start": start_value,
                "end": end_value,
            }
        )
    else:
        assignment.update(
            {
                "startTime": f"{start_norm}:00" if start_norm else str(start),
                "endTime": f"{end_norm}:00" if end_norm else str(end),
                "daysOfWeek": [day],
            }
        )
    return assignment


def validate(
    validator,
    unresolved,
    room,
    day,
    start,
    end,
    *,
    teacher_confirmed=None,
):
    room = str(room or "").strip()
    if not room:
        return {"success": False, "message": "Room must not be blank."}
    if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
        return {"success": False, "message": "Day must be between 0 and 6."}

    canonical_rooms = getattr(validator, "rooms", None)
    if canonical_rooms is not None:
        room_ids = {
            str(item.get("id") or "").strip()
            for item in canonical_rooms
            if isinstance(item, dict) and item.get("id")
        }
        if room not in room_ids:
            return {"success": False, "message": f"Unknown room: {room}"}

    context = build_context(unresolved)
    if context["type"] == "studio_class" and context["original_date"]:
        required_day = context["original_day"]
        if day != required_day:
            date_value = TimeParser.parse_date(context["original_date"])
            day_label = date_value.strftime("%A") if date_value else f"day {required_day}"
            return {
                "success": False,
                "message": (
                    f"Studio date {context['original_date']} is {day_label}; "
                    f"day must remain {required_day}."
                ),
            }

    raw_start = TimeParser.normalize_clock(start)
    raw_end = TimeParser.normalize_clock(end, prefer_end=True)
    if raw_start and raw_end and TimeParser.to_minutes(raw_end) <= TimeParser.to_minutes(raw_start):
        return {"success": False, "message": "End time must be after start time."}
    normalized_range = TimeParser.normalize_course_range(f"{start}-{end}")
    if not normalized_range:
        return {
            "success": False,
            "message": "Invalid course time: use a one-hour :00 or :30 proposal.",
        }
    start_norm, end_norm = normalized_range
    proposal_start = raw_start
    proposal_end = raw_end
    start_min = TimeParser.to_minutes(start_norm, default=None)
    end_min = TimeParser.to_minutes(end_norm, default=None)
    if context["type"] == "studio_class" and context["original_date"]:
        interval = TimeParser.date_clock_interval(
            context["original_date"],
            start_norm,
            end_norm,
        )
        if interval:
            start_dt, end_dt = interval
            duration = TimeParser.event_duration_minutes(
                {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                default=0,
            )
            end_min = start_min + duration if start_min is not None else None
    if start_min is None or end_min is None or end_min <= start_min:
        return {"success": False, "message": "End time must be after start time."}
    if hasattr(validator, "within_time_range") and not validator.within_time_range(
        start_min,
        end_min,
    ):
        return {
            "success": False,
            "message": "Time is outside the configured scheduling window.",
        }

    assignment = build_assignment(
        unresolved,
        room=room,
        day=day,
        start=start_norm,
        end=end_norm,
    )
    conflict = validator.check_conflict(
        room_id=room,
        day_idx=day,
        start_min=start_min,
        end_min=end_min,
        specific_date=(
            context["original_date"]
            if context["type"] == "studio_class"
            else None
        ),
    )
    if conflict:
        conflict_props = conflict.get("extendedProps") or {}
        conflict_name = (
            conflict_props.get("Instructor")
            or conflict.get("title")
            or "Unknown Event"
        )
        if conflict.get("is_locked_lecture"):
            message = f"Conflict with Locked Lecture: {conflict_name}"
        else:
            message = f"Conflict with {conflict_name}"
        return {"success": False, "message": message}

    policy = validate_unresolved_policy(
        validator,
        context=context,
        room=room,
        day=day,
        start_norm=start_norm,
        end_norm=end_norm,
        start_min=start_min,
        end_min=end_min,
        teacher_confirmed=teacher_confirmed,
    )
    if not policy["success"]:
        return policy

    return {
        "success": True,
        "message": None,
        "proposal_start": proposal_start,
        "proposal_end": proposal_end,
        "start_norm": start_norm,
        "end_norm": end_norm,
        "specific_date": (
            context["original_date"]
            if context["type"] == "studio_class"
            else None
        ),
        "warnings": [],
        "requires_teacher_confirmation": policy["requires_teacher_confirmation"],
        "teacher_confirmation_message": policy["teacher_confirmation_message"],
        "assignment": assignment,
    }


def apply(assignments, unassigned, unresolved, assignment):
    index = unassigned.index(unresolved)
    previous = copy.deepcopy(unresolved)
    new_state = copy.deepcopy(assignment)
    unassigned.pop(index)
    assignments.append(copy.deepcopy(assignment))
    return {
        "action": "assign",
        "slot_id": assignment["id"],
        "issue_id": issue_id(unresolved),
        "source_request_id": source_request_id(unresolved),
        "unassigned_index": index,
        "prev_state": previous,
        "new_state": new_state,
    }


def _find_assignment(assignments, slot_id):
    return next((item for item in assignments if item.get("id") == slot_id), None)


def revert_record(assignments, unassigned, record):
    slot_id = record["slot_id"]
    previous = record["prev_state"]
    target = _find_assignment(assignments, slot_id)
    if target:
        assignments.remove(target)
    stable_issue_id = record.get("issue_id") or issue_id(previous)
    if not find_unresolved(unassigned, stable_issue_id):
        index = record.get("unassigned_index", len(unassigned))
        index = max(0, min(int(index), len(unassigned)))
        unassigned.insert(index, copy.deepcopy(previous))
    return True


def replay_record(assignments, unassigned, record):
    stable_issue_id = record.get("issue_id") or issue_id(
        record.get("prev_state", {})
    )
    target = find_unresolved(unassigned, stable_issue_id)
    if target:
        unassigned.remove(target)
    new_state = copy.deepcopy(record.get("new_state", {}))
    existing = _find_assignment(assignments, record["slot_id"])
    if existing:
        existing.update(new_state)
    else:
        assignments.append(new_state)
    return True
