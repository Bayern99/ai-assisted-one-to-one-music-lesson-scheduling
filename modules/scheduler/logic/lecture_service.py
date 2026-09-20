from __future__ import annotations

from typing import Any, Iterable

from modules.shared.time_parser import TimeParser


def detect_lecture_time_overlap(
    new_start: Any,
    new_end: Any,
    existing_start: Any,
    existing_end: Any,
) -> bool:
    """Return whether two valid clock ranges overlap at minute precision."""
    if not all([new_start, new_end, existing_start, existing_end]):
        return False
    new_start_minute = TimeParser.to_minutes(str(new_start), default=None)
    new_end_minute = TimeParser.to_minutes(str(new_end), default=None)
    existing_start_minute = TimeParser.to_minutes(
        str(existing_start),
        default=None,
    )
    existing_end_minute = TimeParser.to_minutes(str(existing_end), default=None)
    if None in (
        new_start_minute,
        new_end_minute,
        existing_start_minute,
        existing_end_minute,
    ):
        return False
    return (
        new_start_minute < existing_end_minute
        and new_end_minute > existing_start_minute
    )


def normalize_lecture_candidates(events: Iterable[dict]) -> list[dict]:
    normalized = []
    for event in events:
        candidate = dict(event)
        candidate["type"] = "lecture"
        candidate["locked"] = True
        normalized.append(candidate)
    return normalized


def find_lecture_conflicts(
    lectures: Iterable[dict],
    existing_bookings: Iterable[dict],
) -> list[dict]:
    """Apply Step 0 room/day/time conflict semantics to lecture candidates."""
    weekly_by_room: dict[str, list[dict]] = {}
    for booking in existing_bookings:
        if booking.get("type") != "weekly_lesson":
            continue
        room_id = booking.get("resourceId")
        if room_id:
            weekly_by_room.setdefault(str(room_id), []).append(booking)

    conflicts = []
    for lecture in lectures:
        room_id = lecture.get("resourceId")
        if not room_id:
            continue
        lecture_days = list(lecture.get("daysOfWeek") or [])
        for booking in weekly_by_room.get(str(room_id), []):
            booking_days = list(booking.get("daysOfWeek") or [])
            shared_days = [day for day in lecture_days if day in booking_days]
            if not shared_days:
                continue
            if not detect_lecture_time_overlap(
                lecture.get("startTime"),
                lecture.get("endTime"),
                booking.get("startTime"),
                booking.get("endTime"),
            ):
                continue
            lecture_title = str(lecture.get("title") or "?")
            booking_title = str(booking.get("title") or "?")
            conflicts.append(
                {
                    "room_id": str(room_id),
                    "lecture_id": str(lecture.get("id") or ""),
                    "lecture_title": lecture_title,
                    "existing_booking_id": str(booking.get("id") or ""),
                    "existing_booking_title": booking_title,
                    "days_of_week": shared_days,
                    "start_time": str(lecture.get("startTime") or ""),
                    "end_time": str(lecture.get("endTime") or ""),
                    "existing_start_time": str(booking.get("startTime") or ""),
                    "existing_end_time": str(booking.get("endTime") or ""),
                    "message": (
                        "⚠️ Conflict: {0} - {1} overlaps {2}".format(
                            room_id,
                            lecture_title,
                            booking_title,
                        )
                    ),
                }
            )
    return conflicts


def validate_lecture_candidates(
    events: Iterable[dict],
    existing_bookings: Iterable[dict],
) -> dict:
    lectures = normalize_lecture_candidates(events)
    return {
        "lectures": lectures,
        "conflicts": find_lecture_conflicts(lectures, existing_bookings),
    }


def load_lectures(loader: Any) -> list[dict]:
    return [
        event
        for event in (loader.load_bookings() or [])
        if event.get("type") == "lecture"
    ]


def replace_lectures(loader: Any, events: Iterable[dict]) -> dict:
    lectures = normalize_lecture_candidates(events)
    existing = loader.load_bookings() or []
    preserved = [event for event in existing if event.get("type") != "lecture"]
    outcome = loader.save_bookings(preserved + lectures)
    return {
        "lectures": lectures,
        "warning": getattr(outcome, "warning", "") if outcome else "",
    }


def save_lectures(loader: Any, events: Iterable[dict]) -> tuple[bool, str]:
    """Retain the Step 0 UI-compatible save result while sharing persistence."""
    try:
        result = replace_lectures(loader, events)
        message = "✅ Scaled {0} Lectures into Schedule.".format(
            len(result["lectures"])
        )
        if result["warning"]:
            message = "{0} Warning: {1}".format(message, result["warning"])
        return True, message
    except Exception as exc:
        return False, "❌ Save Failed: {0}".format(exc)
