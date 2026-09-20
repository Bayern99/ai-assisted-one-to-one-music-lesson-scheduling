"""
Legacy experimental CSP scheduler for room scheduling.
This module remains for compatibility and diagnostics, not the mainline flow.
"""
from typing import Dict, List, Set, Tuple

from modules.shared.time_parser import TimeParser


class CSPScheduler:
    """
    Constraint Satisfaction Problem based scheduler.
    Uses backtracking with forward checking to find valid room assignments.
    """

    def __init__(self, students: List[dict], rooms: List[dict], existing_bookings: List[dict]):
        self.students = students
        self.rooms = rooms
        self.bookings = existing_bookings
        self.assignments: Dict[str, Tuple[str, int, int]] = {}

        self.blocked_slots: Dict[str, Set[Tuple[int, int]]] = {}
        self._index_blocked_slots()

    def _index_blocked_slots(self):
        for room in self.rooms:
            self.blocked_slots[room["id"]] = set()

        for booking in self.bookings:
            rid = booking.get("resourceId")
            if not rid or rid not in self.blocked_slots:
                continue

            if booking.get("daysOfWeek"):
                days = booking.get("daysOfWeek", [])
                start_time = booking.get("startTime", "00:00:00")
                end_time = booking.get("endTime", "00:00:00")

                start_hour = TimeParser.extract_start_hour(start_time, default=None)
                end_hour = TimeParser.extract_start_hour(end_time, default=None)
                if start_hour is None or end_hour is None:
                    continue

                for day in days:
                    for hour in range(start_hour, end_hour):
                        self.blocked_slots[rid].add((day, hour))

            else:
                fc_dow = TimeParser.event_primary_js_day(booking, default=None)
                start_hour = TimeParser.event_clock_pair(booking, default=(None, None))[0]
                end_hour = TimeParser.event_clock_pair(booking, default=(None, None))[1]
                start_hour = TimeParser.extract_start_hour(start_hour, default=None)
                end_hour = TimeParser.extract_start_hour(end_hour, default=None)
                if fc_dow is None or start_hour is None or end_hour is None:
                    continue
                for hour in range(start_hour, end_hour):
                    self.blocked_slots[rid].add((fc_dow, hour))

    def is_available(self, room_id: str, day: int, hour: int) -> bool:
        if room_id not in self.blocked_slots:
            return False
        return (day, hour) not in self.blocked_slots[room_id]

    def get_room_type(self, room_id: str) -> str:
        for room in self.rooms:
            if room["id"] == room_id:
                return room.get("type", "General")
        return "General"

    def is_compatible(self, student: dict, room: dict) -> bool:
        student_type = student.get("type", "Instrumental")
        room_type = room.get("type", "General")

        compatibility = {
            "Piano": ["Piano", "General"],
            "Percussion": ["Percussion", "General"],
            "Voice": ["Voice", "Non-Piano", "General"],
            "Instrumental": ["Instrumental", "Non-Piano", "General"],
        }

        allowed_rooms = compatibility.get(student_type, ["General"])
        return room_type in allowed_rooms

    def get_domain(self, student: dict) -> List[Tuple[str, int, int]]:
        domain = []

        for room in self.rooms:
            if not self.is_compatible(student, room):
                continue

            rid = room["id"]
            for day in range(1, 7):
                for hour in range(8, 22):
                    if self.is_available(rid, day, hour):
                        domain.append((rid, day, hour))

        return domain

    def solve(self) -> bool:
        unassigned = [s for s in self.students if s["student_id"] not in self.assignments]
        if not unassigned:
            return True

        student = min(unassigned, key=lambda s: len(self.get_domain(s)))
        domain = self.get_domain(student)
        if not domain:
            return False

        for room_id, day, hour in domain:
            self.assignments[student["student_id"]] = (room_id, day, hour)
            self.blocked_slots[room_id].add((day, hour))

            if self.solve():
                return True

            del self.assignments[student["student_id"]]
            self.blocked_slots[room_id].discard((day, hour))

        return False

    def get_assignments(self) -> Dict[str, Tuple[str, int, int]]:
        return self.assignments.copy()

    def generate_events(self, semester_start: str = "2026-02-24", semester_end: str = "2026-06-30") -> List[dict]:
        events = []
        student_map = {s["student_id"]: s for s in self.students}

        for sid, (room_id, day, hour) in self.assignments.items():
            student = student_map.get(sid, {})

            event = {
                "id": f"csp_{sid}",
                "title": f"👤 {student.get('name_en', sid)} ({student.get('instructor', 'Unknown')})",
                "resourceId": room_id,
                "startTime": f"{hour:02d}:00:00",
                "endTime": f"{hour + 1:02d}:00:00",
                "daysOfWeek": [day],
                "startRecur": semester_start,
                "endRecur": semester_end,
                "type": "weekly_lesson",
                "editable": True,
                "backgroundColor": "#27ae60",
                "extendedProps": {
                    "auto_generated": True,
                    "generator": "CSPScheduler",
                    "instructor": student.get("instructor"),
                    "student_id": sid,
                },
            }
            events.append(event)

        return events
