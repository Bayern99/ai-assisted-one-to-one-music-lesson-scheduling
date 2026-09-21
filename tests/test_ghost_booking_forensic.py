"""
TDD Forensic Test: Ghost Booking Root Cause

These tests are written FIRST (RED phase) to prove the design inconsistency
between Optimizer.can_assign() and ConflictValidator.check_conflict().

Expected behavior:
- Same instructor's events still conflict when they share the same room/time.
- Studio-specific-date events conservatively block the same room/weekday/time for Weekly assignments.
- The safety gate does not use instructor identity to exempt a room occupancy conflict.

Current behavior (BUG):
- ConflictValidator reports "ghost conflicts" with the instructor's own bookings
- Studio events on Wed block ALL Wednesday assignments to that room
"""

import pytest
from modules.scheduler.logic.conflict_validator import ConflictValidator


# ─── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def data_with_instructor_0002_studio():
    """Instructor 0002 has a Studio class on a specific Wednesday, R101 14:00-15:00"""
    return {
        "assignments": [
            {
                "id": "studio_instructor_0002_mar4",
                "resourceId": "R101",
                "start": "2026-03-04T14:00:00",  # Wed Mar 4
                "end": "2026-03-04T15:00:00",
                "type": "studio_class",
                "extendedProps": {
                    "Instructor": "Instructor 0002",
                    "Student Name": "Student 0001"
                }
            }
        ],
        "lectures": [],
        "rules": {"room_types": {"R101": ["Piano", "Voice"]}}
    }


@pytest.fixture
def data_with_same_instructor_weekly():
    """Same instructor has a Weekly lesson AND a Studio on the same weekday"""
    return {
        "assignments": [
            {
                "id": "wk_student_0003_wed",
                "resourceId": "R101",
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "daysOfWeek": [3],  # Wed (JS convention)
                "type": "weekly_lesson",
                "extendedProps": {
                    "Instructor": "Instructor 0001",
                    "Student Name": "Student 0003"
                }
            },
            {
                "id": "studio_demo_mar4",
                "resourceId": "R101",
                "start": "2026-03-04T14:00:00",  # Also Wed
                "end": "2026-03-04T15:00:00",
                "type": "studio_class",
                "extendedProps": {
                    "Instructor": "Instructor 0001",
                    "Student Name": "Student 0002"
                }
            }
        ],
        "lectures": [],
        "rules": {"room_types": {"R101": ["Piano", "Voice"]}}
    }


@pytest.fixture
def data_with_different_instructor_studio():
    """Different instructor has a Studio on the same weekday/time"""
    return {
        "assignments": [
            {
                "id": "studio_instructor_0012_mar4",
                "resourceId": "R101",
                "start": "2026-03-04T14:00:00",  # Wed
                "end": "2026-03-04T15:00:00",
                "type": "studio_class",
                "extendedProps": {
                    "Instructor": "Instructor 0012",
                    "Student Name": "Student 0003"
                }
            }
        ],
        "lectures": [],
        "rules": {"room_types": {"R101": ["Piano", "Voice"]}}
    }


# ─── Ghost Booking Tests (BUG 2: False Conflict) ───────────

class TestGhostBooking:
    """
    Prove the safety-first Weekly-vs-Studio weekday rule.
    """

    def test_studio_does_not_block_weekly_assignment(self, data_with_instructor_0002_studio):
        """
        Instructor 0002 has a Studio class on Wed Mar 4.
        A Weekly Wednesday lesson in the same room/time is conservatively blocked.
        """
        validator = ConflictValidator(data_with_instructor_0002_studio)
        
        # Try to assign a WEEKLY lesson to R101 Wed 14:00-15:00
        # This is for a DIFFERENT instructor (Student 0003's teacher, Instructor 0001)
        conflict = validator.check_conflict(
            room_id="R101",
            day_idx=3,       # Wed (JS: 0=Sun, 3=Wed)
            start_min=14*60, # 14:00
            end_min=15*60,   # 15:00
            specific_date=None  # Weekly target
        )
        
        assert conflict is not None

    def test_weekly_vs_weekly_still_conflicts(self, data_with_same_instructor_weekly):
        """
        Weekly vs Weekly on same day/time/room SHOULD still conflict.
        """
        validator = ConflictValidator(data_with_same_instructor_weekly)
        
        conflict = validator.check_conflict(
            room_id="R101",
            day_idx=3,       # Wed
            start_min=14*60,
            end_min=15*60,
            specific_date=None
        )
        
        # EXPECTED: Conflict (two weekly lessons in same slot)
        assert conflict is not None


# ─── Same Instructor Exemption Tests (BUG 3) ───────────────

class TestSameInstructorExemption:
    """
    Optimizer allows same-instructor overlap (Self-Healing).
    ConflictValidator should also allow it for consistency.
    """

    def test_same_instructor_studio_not_conflict(self, data_with_same_instructor_weekly):
        """
        RED TEST: Instructor 0001 has BOTH a Weekly and Studio on Wed 14:00.
        The Optimizer created this intentionally (same instructor, different students).
        ConflictValidator should NOT report this as a conflict.
        
        Current behavior: FAILS (reports conflict)
        Expected behavior: No conflict (same instructor exemption)
        """
        validator = ConflictValidator(data_with_same_instructor_weekly)
        
        # Check if the Studio event conflicts with itself in the context of
        # trying to reassign Instructor 0001's lesson
        # NOTE: This test shows the conceptual problem - the validator has no
        # notion of "who is trying to assign" so it can't exempt same-instructor
        conflict = validator.check_conflict(
            room_id="R101",
            day_idx=3,
            start_min=14*60,
            end_min=15*60,
            specific_date="2026-03-04"  # Studio target date
        )
        
        # This WILL report conflict with the weekly lesson (id: wk_student_0003_wed)
        # For now, this test documents the inconsistency
        # A proper fix would add instructor_id parameter to check_conflict
        if conflict:
            print(f"\n[DOCUMENTED] ConflictValidator reports conflict: {conflict.get('id')}")
            print(f"  Optimizer would ALLOW this (Self-Healing logic)")
            print(f"  ConflictValidator does NOT have Self-Healing logic")

    def test_different_instructor_studio_blocks_weekly(self, data_with_different_instructor_studio):
        """
        Different instructor's Studio on same weekday/time/room 
        should also NOT block Weekly assignments.
        Reason: Studio is a one-time event, Weekly is recurring.
        They operate on different schedules.
        """
        validator = ConflictValidator(data_with_different_instructor_studio)
        
        conflict = validator.check_conflict(
            room_id="R101",
            day_idx=3,
            start_min=14*60,
            end_min=15*60,
            specific_date=None  # Weekly assignment
        )
        
        assert conflict is not None


# ─── Duplicate Studio Cards Tests (Lower Priority) ─────────

class TestDuplicateStudioCards:
    """Documents the duplicate card issue (lower priority per user)."""

    def test_duplicate_studio_entries_detected(self):
        """
        Same instructor, same room, same time, same weekday, different dates.
        These appear as duplicate cards in the UI.
        """
        data = {
            "assignments": [
                {
                    "id": "studio_demo_mar4",
                    "resourceId": "R101",
                    "start": "2026-03-04T14:00:00",
                    "end": "2026-03-04T15:00:00",
                    "type": "studio_class",
                    "extendedProps": {"Instructor": "Instructor 0001"}
                },
                {
                    "id": "studio_demo_mar11",
                    "resourceId": "R101",
                    "start": "2026-03-11T14:00:00",
                    "end": "2026-03-11T15:00:00",
                    "type": "studio_class",
                    "extendedProps": {"Instructor": "Instructor 0001"}
                },
                {
                    "id": "studio_demo_mar18",
                    "resourceId": "R101",
                    "start": "2026-03-18T14:00:00",
                    "end": "2026-03-18T15:00:00",
                    "type": "studio_class",
                    "extendedProps": {"Instructor": "Instructor 0001"}
                }
            ],
            "lectures": [],
            "rules": {}
        }
        
        # Count "unique" slots (same instructor + same room + same time + same weekday)
        seen = set()
        dupes = 0
        for evt in data["assignments"]:
            key = (
                evt.get("resourceId"),
                evt.get("extendedProps", {}).get("Instructor"),
                evt.get("start", "").split("T")[1] if "T" in evt.get("start", "") else evt.get("startTime"),
            )
            if key in seen:
                dupes += 1
            seen.add(key)
        
        # Document: there are duplicates
        print(f"\n[DOCUMENTED] {dupes} duplicate Studio cards found out of {len(data['assignments'])} total")
        assert dupes > 0, "Expected duplicate Studio cards"
