"""Deterministic rules for moving one teacher's day package."""

from __future__ import annotations

from modules.shared.time_parser import TimeParser


def _event_interval(event):
    start, end = TimeParser.event_clock_pair(event, default=(None, None))
    start_min = TimeParser.to_minutes(start, default=None)
    end_min = TimeParser.to_minutes(end, default=None, prefer_end=True)
    if (
        start_min is None
        or end_min is None
        or start_min < 0
        or end_min > 24 * 60
        or end_min <= start_min
    ):
        raise ValueError("Teacher-day package contains an invalid event interval.")
    return start_min, end_min


def _event_day(event):
    day = TimeParser.event_primary_js_day(event, default=None)
    if day not in range(7):
        raise ValueError("Teacher-day package contains an invalid source day.")
    return day


def _event_id(event):
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise ValueError("Teacher-day package events require an id.")
    return event_id


def build_teacher_day_package(events):
    """Build a stable package descriptor without mutating the input events.

    A package preserves the source ordering, durations, and gaps between a
    teacher's events. Placement validation later permits translating that
    complete structure to one target day, but not splitting it across days.
    """
    if not isinstance(events, list) or not events:
        raise ValueError("Teacher-day package requires at least one event.")

    items = []
    instructors = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Teacher-day package events must be objects.")
        event_id = _event_id(event)
        day = _event_day(event)
        start, end = _event_interval(event)
        props = event.get("extendedProps") or {}
        instructor = str(
            props.get("Instructor")
            or event.get("instructor")
            or ""
        ).strip()
        if instructor:
            instructors.add(instructor)
        items.append(
            {
                "event_id": event_id,
                "day": day,
                "start": start,
                "end": end,
                "duration_minutes": end - start,
                "room": str(event.get("resourceId") or event.get("room") or ""),
                "instructor": instructor,
            }
        )

    event_ids = [item["event_id"] for item in items]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("Teacher-day package event ids must be unique.")
    if len({item["day"] for item in items}) != 1:
        raise ValueError("Teacher-day package events must share one source day.")
    if len(instructors) > 1:
        raise ValueError("Teacher-day package events must share one instructor.")

    items.sort(key=lambda item: (item["start"], item["end"], item["event_id"]))
    gaps = [
        current["start"] - previous["end"]
        for previous, current in zip(items, items[1:])
    ]
    return {
        "event_ids": [item["event_id"] for item in items],
        "source_day": items[0]["day"],
        "instructor": next(iter(instructors), ""),
        "source_intervals": [
            {
                "event_id": item["event_id"],
                "start": item["start"],
                "end": item["end"],
                "duration_minutes": item["duration_minutes"],
            }
            for item in items
        ],
        "source_gaps_minutes": gaps,
    }


def _placement_interval(placement):
    start = TimeParser.to_minutes(placement.get("start"), default=None)
    end = TimeParser.to_minutes(
        placement.get("end"),
        default=None,
        prefer_end=True,
    )
    if (
        start is None
        or end is None
        or start < 0
        or end > 24 * 60
        or end <= start
    ):
        return None
    return start, end


def validate_teacher_day_placement(package, placements):
    """Validate a translated package while preserving its source structure.

    This is deliberately independent of room/instructor availability. The
    canonical scheduler remains responsible for those checks. This helper
    only enforces package-level invariants: one target day, unchanged lesson
    durations and source gaps, preserved order, and at most one room
    transition during the day.
    """
    errors = []
    if not isinstance(package, dict) or not isinstance(placements, list):
        return {"valid": False, "errors": ["invalid_package_or_placements"]}

    expected_ids = list(package.get("event_ids") or [])
    actual_ids = [
        str(item.get("event_id") or "").strip()
        for item in placements
        if isinstance(item, dict)
    ]
    if (
        len(actual_ids) != len(expected_ids)
        or len(set(actual_ids)) != len(actual_ids)
        or set(actual_ids) != set(expected_ids)
    ):
        errors.append("placement_event_ids_must_match_package")

    if len(placements) != len(expected_ids):
        return {"valid": False, "errors": errors or ["invalid_placement_count"]}

    by_id = {
        str(item.get("event_id") or "").strip(): item
        for item in placements
        if isinstance(item, dict)
    }
    ordered = [by_id[event_id] for event_id in expected_ids if event_id in by_id]
    if len(ordered) != len(expected_ids):
        return {
            "valid": False,
            "errors": errors or ["placement_event_ids_must_match_package"],
        }

    target_days = {item.get("day") for item in ordered}
    if len(target_days) != 1 or next(iter(target_days), None) not in range(7):
        errors.append("package_must_remain_on_one_day")

    source_intervals = list(package.get("source_intervals") or [])
    target_intervals = [_placement_interval(item) for item in ordered]
    if any(interval is None for interval in target_intervals):
        errors.append("placement_intervals_must_be_valid")
        return {"valid": False, "errors": errors}

    if len(source_intervals) == len(target_intervals):
        source_durations = [
            int(item["end"]) - int(item["start"])
            for item in source_intervals
        ]
        target_durations = [end - start for start, end in target_intervals]
        if source_durations != target_durations:
            errors.append("package_lesson_durations_must_be_preserved")

        target_gaps = [
            target_intervals[index][0] - target_intervals[index - 1][1]
            for index in range(1, len(target_intervals))
        ]
        if target_gaps != list(package.get("source_gaps_minutes") or []):
            errors.append("original_time_gaps_must_be_preserved")

        if any(
            target_intervals[index][0] < target_intervals[index - 1][0]
            for index in range(1, len(target_intervals))
        ):
            errors.append("package_event_order_must_be_preserved")

    rooms = [str(item.get("room") or "").strip() for item in ordered]
    if any(not room for room in rooms):
        errors.append("package_placements_require_rooms")
    transitions = sum(
        current != previous
        for previous, current in zip(rooms, rooms[1:])
    )
    if transitions > 1:
        errors.append("at_most_one_room_transition")

    return {"valid": not errors, "errors": errors}
