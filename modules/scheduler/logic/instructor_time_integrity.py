"""Hard instructor timeline integrity checks for scheduler inputs and drafts."""

from __future__ import annotations

import math
from collections import defaultdict

from modules.shared.field_schema import (
    DAY_MAP_CN,
    DAY_MAP_EN,
    DAY_MAP_EN_SHORT,
    parse_studio_date,
)
from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.source_requests import stable_row_index, studio_time_tokens


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null"} else text


def instructor_key(value) -> str:
    """Return a stable comparison key without changing the displayed name."""
    return " ".join(_text(value).casefold().split())


def _rows(value):
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return value.to_dict(orient="records")
    return [row for row in value if isinstance(row, dict)]


def _day(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in range(7):
        return value
    text = _text(value)
    if text.isdigit() and int(text) in range(7):
        return int(text)
    return DAY_MAP_EN.get(text, DAY_MAP_EN_SHORT.get(text, DAY_MAP_CN.get(text)))


def _interval(value):
    normalized = TimeParser.normalize_course_range(value)
    if not normalized:
        return None
    return tuple(TimeParser.to_minutes(item, default=None) for item in normalized)


def _studio_date(value):
    iso_date = TimeParser.extract_iso_date(value)
    if iso_date:
        return iso_date
    parsed, _day_idx, _day_name = parse_studio_date(_text(value))
    return parsed.strftime("%Y-%m-%d") if parsed else None


def _occurrence(*, occurrence_id, source, state, instructor, day, date, interval, label):
    if not instructor or day not in range(7) or interval is None:
        return None
    start, end = interval
    return {
        "id": str(occurrence_id),
        "source": source,
        "state": state,
        "instructor": instructor,
        "day": day,
        "date": date,
        "start": start,
        "end": end,
        "label": label,
    }


def _source_occurrences(weekly, studio):
    result = []
    for row_index, row in enumerate(_rows(weekly)):
        source_row_index = stable_row_index(row, row_index)
        item = _occurrence(
            occurrence_id=f"weekly:{source_row_index}",
            source="weekly",
            state="source",
            instructor=_text(row.get("Instructor")),
            day=_day(row.get("Day of Week")),
            date=None,
            interval=_interval(row.get("Class Time")),
            label=_text(row.get("Student Name")) or f"Weekly row {row_index + 1}",
        )
        if item:
            result.append(item)

    for row_index, row in enumerate(_rows(studio)):
        source_row_index = stable_row_index(row, row_index)
        instructor = _text(row.get("Instructor"))
        for slot_index in range(1, 4):
            date = _studio_date(row.get(f"Studio {slot_index} Date"))
            day = TimeParser.to_js_weekday(date, default=None)
            raw_times = _text(row.get(f"Studio {slot_index} Time"))
            for time_index, raw_time in enumerate(studio_time_tokens(raw_times)):
                item = _occurrence(
                    occurrence_id=f"studio:{source_row_index}:{slot_index}:{time_index}",
                    source="studio",
                    state="source",
                    instructor=instructor,
                    day=day,
                    date=date,
                    interval=_interval(raw_time),
                    label=f"Studio row {row_index + 1}, slot {slot_index}",
                )
                if item:
                    result.append(item)
    return result


def _assignment_occurrences(assignments):
    result = []
    for event in assignments or []:
        props = event.get("extendedProps") or {}
        instructor = _text(props.get("Instructor") or event.get("instructor"))
        interval = TimeParser.board_event_occupancy(event)
        date = TimeParser.event_specific_date(event)
        days = [TimeParser.to_js_weekday(date, default=None)] if date else event.get("daysOfWeek", [])
        for day in days if isinstance(days, list) else []:
            item = _occurrence(
                occurrence_id=event.get("id", "assignment"),
                source=str(event.get("type") or "assignment"),
                state="assigned",
                instructor=instructor,
                day=day,
                date=date,
                interval=interval,
                label=_text(event.get("title")) or str(event.get("id") or "Assignment"),
            )
            if item:
                result.append(item)
    return result


def _unresolved_occurrences(unresolved):
    from modules.scheduler.logic import unresolved_assignment_primitives

    result = []
    for raw in unresolved or []:
        context = unresolved_assignment_primitives.build_context(raw)
        date = context.get("original_date")
        start_min = TimeParser.to_minutes(context.get("original_start"), default=None)
        end_min = TimeParser.to_minutes(
            context.get("original_end"),
            default=None,
            prefer_end=True,
        )
        item = _occurrence(
            occurrence_id=unresolved_assignment_primitives.issue_id(raw),
            source=context.get("type") or "unresolved",
            state="unresolved",
            instructor=context.get("instructor") or "",
            day=context.get("original_day"),
            date=date,
            interval=TimeParser.canonical_course_occupancy(start_min, end_min),
            label=context.get("student_name") or context.get("course_code") or "Unresolved",
        )
        if item:
            result.append(item)
    return result


def _same_occurrence(left, right):
    if left["date"] and right["date"]:
        return left["date"] == right["date"]
    return left["day"] == right["day"]


def _format_minutes(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def _find_conflicts(occurrences):
    by_instructor = defaultdict(list)
    for item in occurrences:
        by_instructor[instructor_key(item["instructor"])].append(item)

    conflicts = []
    # ponytail: O(n²) per instructor; bucket intervals if import sizes grow materially.
    for key in sorted(by_instructor):
        items = sorted(
            by_instructor[key],
            key=lambda item: (item["date"] or "", item["day"], item["start"], item["id"]),
        )
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                if left["id"] == right["id"] or not _same_occurrence(left, right):
                    continue
                overlap_start = max(left["start"], right["start"])
                overlap_end = min(left["end"], right["end"])
                if overlap_start >= overlap_end:
                    continue
                conflicts.append(
                    {
                        "code": "instructor_time_overlap",
                        "instructor": left["instructor"],
                        "date": left["date"] or right["date"],
                        "day": left["day"],
                        "start": _format_minutes(overlap_start),
                        "end": _format_minutes(overlap_end),
                        "left": dict(left),
                        "right": dict(right),
                    }
                )
    return conflicts


def audit_source_schedule(weekly, studio):
    """Return blocking instructor overlaps from source schedule frames."""
    return _find_conflicts(_source_occurrences(weekly, studio))


def audit_canonical_schedule(assignments, unresolved=None):
    """Return blocking instructor overlaps from canonical Step 4 state."""
    occurrences = _assignment_occurrences(assignments)
    occurrences.extend(_unresolved_occurrences(unresolved))
    return _find_conflicts(occurrences)


def instructor_is_available(
    assignments,
    *,
    instructor,
    day,
    start_min,
    end_min,
    specific_date=None,
    exclude_ids=None,
):
    """Check one proposed interval against the instructor's canonical timeline."""
    if not instructor:
        return True
    excluded = {str(value) for value in (exclude_ids or [])}
    candidate = {
        "id": "__candidate__",
        "instructor": str(instructor).strip(),
        "day": day,
        "date": specific_date,
        "start": start_min,
        "end": end_min,
    }
    for existing in _assignment_occurrences(assignments):
        if existing["id"] in excluded:
            continue
        if instructor_key(existing["instructor"]) != instructor_key(candidate["instructor"]):
            continue
        if not _same_occurrence(existing, candidate):
            continue
        if max(existing["start"], start_min) < min(existing["end"], end_min):
            return False
    return True


def format_instructor_conflict(conflict):
    date_or_day = conflict.get("date") or f"weekday {conflict.get('day')}"
    return (
        f"Instructor time conflict: {conflict.get('instructor')} on {date_or_day} "
        f"at {conflict.get('start')}-{conflict.get('end')} "
        f"({conflict['left'].get('label')} vs {conflict['right'].get('label')})."
    )
