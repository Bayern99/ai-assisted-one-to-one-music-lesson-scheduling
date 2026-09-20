"""Shared policy for teacher-approved schedule time changes."""

from __future__ import annotations

from datetime import datetime, timezone

from modules.shared.time_parser import TimeParser


def _clock(value):
    return TimeParser.normalize_clock(value)


def event_time_changed(event, *, day, start, end):
    original_day = TimeParser.event_primary_js_day(event, default=None)
    original_start, original_end = TimeParser.event_clock_pair(
        event,
        default=(None, None),
    )
    if original_day not in range(7) or not original_start or not original_end:
        return False
    return (
        day != original_day
        or _clock(start) != _clock(original_start)
        or _clock(end) != _clock(original_end)
    )


def context_time_changed(context, *, day, start, end):
    original_day = context.get("original_day")
    original_start = context.get("original_start")
    original_end = context.get("original_end")
    if original_day not in range(7) or not original_start or not original_end:
        return False
    return (
        day != original_day
        or _clock(start) != _clock(original_start)
        or _clock(end) != _clock(original_end)
    )


def confirmation_message(instructor):
    teacher = str(instructor or "the teacher").strip() or "the teacher"
    return (
        f"Teacher confirmation is required before changing {teacher}'s "
        "scheduled day or time."
    )


def instructor_time_change_status(rules, instructor):
    """Return the explicit time-change status without exposing teacher names."""
    eligibility = rules.get("instructor_time_change_eligibility", {}) if isinstance(rules, dict) else {}
    if not isinstance(eligibility, dict):
        return "unknown"
    teacher = str(instructor or "").strip().casefold()
    for name, value in eligibility.items():
        if str(name).strip().casefold() != teacher:
            continue
        if isinstance(value, bool):
            return "ask_allowed" if value else "original_time_only"
        value = str(value or "").strip().casefold()
        if value in {"ask_allowed", "original_time_only", "unknown"}:
            return value
        return "unknown"
    return "unknown"


def instructor_allows_time_change(rules, instructor):
    """Return whether Step 4 may propose or apply a day/time change."""
    status = instructor_time_change_status(rules, instructor)
    return status in {"ask_allowed", "unknown"}


def time_change_pool_message(instructor):
    teacher = str(instructor or "This instructor").strip() or "This instructor"
    return (
        f"{teacher} is set to original-time options only. Update the time-change "
        "proposal pool in Rules before changing the scheduled day or time."
    )


def attach_teacher_confirmation(event, *, instructor, note=""):
    props = event.setdefault("extendedProps", {})
    props["teacher_time_change_confirmation"] = {
        "confirmed": True,
        "instructor": str(instructor or "").strip(),
        "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": str(note or "").strip(),
    }
    return event
