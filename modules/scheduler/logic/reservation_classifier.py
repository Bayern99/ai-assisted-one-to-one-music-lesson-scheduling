"""Read-only instructor-reservation labels for unresolved Studio occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from modules.shared.time_parser import TimeParser

RESERVATION_INTERNAL = "reservation_internal"
CONTENTION = "contention"

RESERVATION_NOTE_TEMPLATE = (
    "Optimizer did not place this studio date; it belongs to the instructor's "
    "existing {weekday} {clock} reservation."
)


@dataclass(frozen=True)
class ReservationKey:
    instructor: str
    weekday: int
    clock: str


@dataclass
class ReservationBucket:
    weekly_room: Optional[str] = None
    studio_rooms: list[str] = None
    studio_dates: set[str] = None

    def __post_init__(self):
        if self.studio_rooms is None:
            self.studio_rooms = []
        if self.studio_dates is None:
            self.studio_dates = set()


def _normalize_instructor(value: Any) -> str:
    return str(value or "").strip()


def _event_instructor(event: dict) -> str:
    props = event.get("extendedProps") or {}
    props = props if isinstance(props, dict) else {}
    return _normalize_instructor(
        props.get("Instructor")
        or event.get("instructor")
        or props.get("instructor")
    )


def _event_source_request_id(event: dict) -> str:
    props = event.get("extendedProps") or {}
    props = props if isinstance(props, dict) else {}
    return str(
        event.get("source_request_id")
        or props.get("source_request_id")
        or ""
    ).strip()


def _is_studio_event(event: dict) -> bool:
    event_type = str(event.get("type") or "").strip().lower()
    if event_type == "studio_class":
        return True
    props = event.get("extendedProps") or {}
    if isinstance(props, dict) and props.get("is_studio") is True:
        return True
    return bool(TimeParser.event_specific_date(event))


def _is_studio_unresolved(item: dict) -> bool:
    event_type = str(item.get("type") or "").strip().lower()
    if event_type == "studio_class":
        return True
    raw_row = item.get("raw_row") or {}
    if not isinstance(raw_row, dict):
        raw_row = {}
    for token in (
        str(raw_row.get("Event Type", "")).lower(),
        str(raw_row.get("Course Code", "")).lower(),
        str(item.get("type", "")).lower(),
    ):
        if "studio" in token or token.startswith("stu"):
            return True
    return bool(item.get("date") or item.get("original_date"))


def _weekday_clock_for_event(event: dict) -> tuple[Optional[int], Optional[str]]:
    specific_date = TimeParser.event_specific_date(event)
    if specific_date:
        weekday = TimeParser.to_js_weekday(specific_date, default=None)
    else:
        days = event.get("daysOfWeek") or []
        weekday = days[0] if days else None
    start_clock, _end_clock = TimeParser.event_clock_pair(event, default=(None, None))
    return weekday, start_clock


def _clock_from_unresolved_value(value: Any, *, prefer_end: bool = False) -> Optional[str]:
    """Accept HH:MM clocks and the integer hour payloads Optimizer still emits."""
    clock = TimeParser.normalize_clock(value, prefer_end=prefer_end)
    if clock:
        return clock
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        hour = int(value)
        if float(value) == hour and 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return None
    text = str(value).strip()
    if text.isdigit():
        hour = int(text)
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    return None


def _weekday_clock_for_unresolved(item: dict) -> tuple[Optional[int], Optional[str], Optional[str]]:
    specific_date = (
        item.get("date")
        or item.get("original_date")
        or (item.get("raw_row") or {}).get("date")
    )
    if specific_date:
        weekday = TimeParser.to_js_weekday(specific_date, default=None)
        if weekday is None and item.get("day") is not None:
            weekday = int(item["day"])
    else:
        weekday = item.get("day")
        if weekday is not None:
            weekday = int(weekday)
    start_clock = _clock_from_unresolved_value(
        item.get("start")
        or item.get("original_start")
        or (item.get("raw_row") or {}).get("Class Time")
        or (item.get("raw_row") or {}).get("start")
    )
    return weekday, start_clock, TimeParser.extract_iso_date(specific_date)


def _weekday_name(weekday: int) -> str:
    names = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]
    if 0 <= weekday < len(names):
        return names[weekday]
    return f"day-{weekday}"


def _reservation_note(weekday: int, clock: str) -> str:
    return RESERVATION_NOTE_TEMPLATE.format(
        weekday=_weekday_name(weekday),
        clock=clock,
    )


def _event_room(event: dict) -> str:
    return str(event.get("resourceId") or event.get("room_id") or "").strip()


def build_reservation_index(assignments: list[dict]) -> dict[ReservationKey, ReservationBucket]:
    index: dict[ReservationKey, ReservationBucket] = {}
    for event in assignments or []:
        if not isinstance(event, dict):
            continue
        instructor = _event_instructor(event)
        weekday, clock = _weekday_clock_for_event(event)
        if not instructor or weekday is None or not clock:
            continue
        key = ReservationKey(instructor=instructor, weekday=weekday, clock=clock)
        bucket = index.setdefault(key, ReservationBucket())
        room = _event_room(event)
        if _is_studio_event(event):
            specific_date = TimeParser.event_specific_date(event)
            if room and room not in bucket.studio_rooms:
                bucket.studio_rooms.append(room)
            if specific_date:
                bucket.studio_dates.add(specific_date)
        else:
            if room:
                bucket.weekly_room = room
    return index


def _instructor_weekday_clocks(
    index: dict[ReservationKey, ReservationBucket],
) -> dict[tuple[str, int], set[str]]:
    grouped: dict[tuple[str, int], set[str]] = {}
    for key in index:
        grouped.setdefault((key.instructor, key.weekday), set()).add(key.clock)
    return grouped


def reservation_magnet_room(bucket: ReservationBucket) -> Optional[str]:
    if bucket.weekly_room:
        return bucket.weekly_room
    if bucket.studio_rooms:
        return bucket.studio_rooms[0]
    return None


def _same_day_overlap(
    instructor: str,
    specific_date: str,
    start_clock: str,
    *,
    end_clock: Optional[str] = None,
    assignments: list[dict],
    unassigned: list[dict],
    exclude_source_request_id: str = "",
) -> bool:
    if not specific_date or not start_clock:
        return False

    def interval(start_value: Any, end_value: Any = None) -> tuple[Optional[int], Optional[int]]:
        start_min = TimeParser.to_minutes(start_value, default=None)
        if start_min is None:
            return None, None
        end_min = TimeParser.to_minutes(
            end_value,
            default=None,
            prefer_end=True,
        )
        if end_min is None or end_min <= start_min:
            end_min = start_min + 60
        return start_min, end_min

    target_start, target_end = interval(start_clock, end_clock)
    if target_start is None or target_end is None:
        return False

    def overlaps(other_start: Any, other_end: Any = None) -> bool:
        other_start_min, other_end_min = interval(other_start, other_end)
        if other_start_min is None or other_end_min is None:
            return False
        return target_start < other_end_min and other_start_min < target_end

    for event in assignments or []:
        if not isinstance(event, dict) or not _is_studio_event(event):
            continue
        if _event_instructor(event) != instructor:
            continue
        event_date = TimeParser.event_specific_date(event)
        if event_date != specific_date:
            continue
        sid = _event_source_request_id(event)
        if exclude_source_request_id and sid == exclude_source_request_id:
            continue
        event_start, event_end = TimeParser.event_clock_pair(event, default=(None, None))
        if overlaps(event_start, event_end):
            return True

    for item in unassigned or []:
        if not isinstance(item, dict) or not _is_studio_unresolved(item):
            continue
        instructor_value = _normalize_instructor(
            item.get("instructor")
            or (item.get("raw_row") or {}).get("Instructor")
        )
        if instructor_value != instructor:
            continue
        _weekday, clock, date_value = _weekday_clock_for_unresolved(item)
        if date_value != specific_date:
            continue
        sid = str(
            item.get("source_request_id")
            or (item.get("raw_row") or {}).get("source_request_id")
            or ""
        ).strip()
        if exclude_source_request_id and sid == exclude_source_request_id:
            continue
        other_end = item.get("end") or (item.get("raw_row") or {}).get("Class Time")
        if overlaps(clock, other_end):
            return True
    return False


def classify_unresolved_reservations(
    assignments: list[dict],
    unassigned_lessons: list[dict],
) -> dict[str, dict[str, Any]]:
    """Return read-only reservation labels keyed by unresolved issue id."""
    index = build_reservation_index(assignments)
    weekday_clocks = _instructor_weekday_clocks(index)
    labels: dict[str, dict[str, Any]] = {}

    for item in unassigned_lessons or []:
        if not isinstance(item, dict) or not _is_studio_unresolved(item):
            continue
        issue_id = str(
            item.get("id")
            or item.get("assignment_id")
            or unresolved_issue_id(item)
        ).strip()
        if not issue_id:
            continue
        instructor = _normalize_instructor(
            item.get("instructor")
            or (item.get("raw_row") or {}).get("Instructor")
        )
        weekday, clock, specific_date = _weekday_clock_for_unresolved(item)
        if not instructor or weekday is None or not clock:
            continue
        source_request_id = str(
            item.get("source_request_id")
            or (item.get("raw_row") or {}).get("source_request_id")
            or ""
        ).strip()
        end_clock = _clock_from_unresolved_value(
            item.get("end")
            or item.get("original_end")
            or (item.get("raw_row") or {}).get("Class Time"),
            prefer_end=True,
        )

        if _same_day_overlap(
            instructor,
            specific_date or "",
            clock,
            end_clock=end_clock,
            assignments=assignments,
            unassigned=unassigned_lessons,
            exclude_source_request_id=source_request_id,
        ):
            labels[issue_id] = {
                "label": CONTENTION,
                "magnet_room": None,
                "reservation_note": None,
            }
            continue

        key = ReservationKey(instructor=instructor, weekday=weekday, clock=clock)
        bucket = index.get(key)
        if bucket is not None:
            labels[issue_id] = {
                "label": RESERVATION_INTERNAL,
                "magnet_room": reservation_magnet_room(bucket),
                "reservation_note": _reservation_note(weekday, clock),
            }
            continue

        sibling_clocks = weekday_clocks.get((instructor, weekday), set())
        if sibling_clocks and clock not in sibling_clocks:
            labels[issue_id] = {
                "label": CONTENTION,
                "magnet_room": None,
                "reservation_note": None,
            }

    return labels


def unresolved_issue_id(item: dict) -> str:
    from modules.scheduler.logic import unresolved_assignment_primitives

    return unresolved_assignment_primitives.issue_id(item)


def classify_reservation_state(
    assignments: list[dict],
    unassigned_lessons: list[dict],
) -> dict[str, Any]:
    """Aggregate classifier output without mutating ledger counts."""
    labels = classify_unresolved_reservations(assignments, unassigned_lessons)
    return {
        "labels": labels,
        "assigned_count": len(assignments or []),
        "unresolved_count": len(unassigned_lessons or []),
    }
