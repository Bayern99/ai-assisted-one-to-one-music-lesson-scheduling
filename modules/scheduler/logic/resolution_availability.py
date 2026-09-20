"""Request-scoped availability indexes for Step 4 advice."""

from __future__ import annotations

from collections import defaultdict

from modules.scheduler.logic.instructor_time_integrity import (
    _assignment_occurrences,
    _same_occurrence,
    instructor_key,
)
from modules.scheduler.logic.validation_authority import build_occupancy_assignments
from modules.shared.time_parser import TimeParser


class ResolutionAvailability:
    def __init__(self, runtime):
        assignments = build_occupancy_assignments(
            runtime.locked_context_assignments,
            runtime.edit_session.get("assignments", []),
        )
        self._teacher = defaultdict(list)
        for item in _assignment_occurrences(assignments):
            self._teacher[instructor_key(item["instructor"])].append(item)

        self._rooms = defaultdict(list)
        validator = runtime.validator
        for event in list(validator.lectures) + list(validator.assignments):
            room = str(event.get("resourceId") or "").strip()
            days = event.get("daysOfWeek")
            if not room or not isinstance(days, list):
                continue
            start_min, end_min = TimeParser.event_to_minute_range(event, default=None)
            # Occupancy of what is already on the board, not course-request
            # canonicalization: 3–4h lectures must not vanish or block 00–24.
            if start_min is None or end_min is None or not 0 <= start_min < end_min <= 24 * 60:
                continue
            for day in days:
                if day in range(7):
                    self._rooms[(room, day)].append((start_min, end_min))

        self._validator = validator
        self._rules = {}

    def teacher_free(self, *, instructor, day, start, end, date=None):
        candidate = {"day": day, "date": date}
        for existing in self._teacher.get(instructor_key(instructor), []):
            if _same_occurrence(existing, candidate) and (
                max(existing["start"], start) < min(existing["end"], end)
            ):
                return False
        return True

    def room_free(self, *, room, day, start, end, date=None):
        if date:
            return not self._validator.check_conflict(
                room, day, start, end, specific_date=date
            )
        return all(
            interval is not None
            and max(interval[0], start) >= min(interval[1], end)
            for interval in self._rooms.get((room, day), [])
        )

    def room_allowed(self, room, instrument):
        key = (room, str(instrument or ""))
        if key not in self._rules:
            self._rules[key] = self._validator.validate_rules(room, instrument)
        return self._rules[key]
