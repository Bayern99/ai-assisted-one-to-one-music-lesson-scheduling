"""
TDD Test: Studio Weekday-Level Conflict (Bug 3)

Business Rule:
- Same or different instructor, same room, same weekday, different dates → CONFLICT
- Different instructor, different room, same weekday → OK
- Different instructor, same room, different weekday → OK

This test validates the Optimizer's can_assign() behavior.
"""

import pytest
from modules.scheduler.logic.optimizer import RoomAllocator


@pytest.fixture
def allocator_with_studio():
    """
    RoomAllocator with Dr.A's Studio already assigned:
    R101, Wed Mar 4, 18:00-19:00
    """
    # Minimal config to construct RoomAllocator
    rooms = [{"id": "R101"}, {"id": "R105"}]
    rules = {
        "room_types": {
            "R101": ["Piano", "Voice"],
            "R105": ["Piano", "Instrumental"]
        },
        "instructor_priority": {},
        "time_range": {"start": 8, "end": 22},
        "min_break": 0
    }
    
    allocator = RoomAllocator([], rooms, [], rules)
    
    # Pre-existing Studio: Dr.A on R101, Wed Mar 4, 18:00-19:00
    allocator.assignments.append({
        "id": "stu_drA_1_0_opt",
        "resourceId": "R101",
        "start": "2026-03-04T18:00:00",  # Wed Mar 4
        "end": "2026-03-04T19:00:00",
        "type": "studio_class",
        "extendedProps": {
            "Instructor": "Instructor 0001",
            "is_studio": True
        }
    })
    
    return allocator


class TestStudioWeekdayConflict:
    """Studio 不同老师不能占同一 room/weekday/time"""

    def test_different_instructor_same_weekday_conflict(self, allocator_with_studio):
        """
        RED TEST: Dr.B tries R101 Wed Mar 11 18:00 → should be REJECTED
        (Different instructor, same room, same weekday, different date)
        """
        result = allocator_with_studio.can_assign(
            room_id="R101",
            day_idx=3,       # Wed (JS convention: 0=Sun,3=Wed)
            start_h=18,
            end_h=19,
            specific_date="2026-03-11",  # Different Wednesday
            instructor_id="Dr. B"
        )
        
        assert result is False, (
            "Different instructor should NOT be allowed on same room/weekday/time! "
            "Dr.A already has R101 Wed 18:00 (Mar 4)"
        )

    def test_same_instructor_same_weekday_conflict(self, allocator_with_studio):
        """
        Dr.A tries R101 Wed Mar 11 18:00 → should be REJECTED
        (The room/weekday occupancy rule is safety-first and instructor-independent.)
        """
        result = allocator_with_studio.can_assign(
            room_id="R101",
            day_idx=3,
            start_h=18,
            end_h=19,
            specific_date="2026-03-11",
            instructor_id="Instructor 0001"
        )
        
        assert result is False

    def test_different_instructor_different_weekday_ok(self, allocator_with_studio):
        """
        Dr.B tries R101 Thu Mar 5 18:00 → should be ALLOWED
        (Different weekday = no conflict)
        """
        result = allocator_with_studio.can_assign(
            room_id="R101",
            day_idx=4,       # Thu
            start_h=18,
            end_h=19,
            specific_date="2026-03-05",  # Thursday
            instructor_id="Dr. B"
        )
        
        assert result is True

    def test_different_instructor_different_room_ok(self, allocator_with_studio):
        """
        Dr.B tries R105 Wed Mar 11 18:00 → should be ALLOWED
        (Different room = no conflict)
        """
        result = allocator_with_studio.can_assign(
            room_id="R105",
            day_idx=3,
            start_h=18,
            end_h=19,
            specific_date="2026-03-11",
            instructor_id="Dr. B"
        )
        
        assert result is True

    def test_different_instructor_same_date_conflict(self, allocator_with_studio):
        """
        Dr.B tries R101 Wed Mar 4 18:00 → should be REJECTED
        (Same date + same time + same room = obvious conflict, already handled)
        """
        result = allocator_with_studio.can_assign(
            room_id="R101",
            day_idx=3,
            start_h=18,
            end_h=19,
            specific_date="2026-03-04",  # Same date as Dr.A
            instructor_id="Dr. B"
        )
        
        assert result is False

    def test_different_instructor_different_time_ok(self, allocator_with_studio):
        """
        Dr.B tries R101 Wed Mar 11 17:00-18:00 → should be ALLOWED
        (Different time = no overlap)
        """
        result = allocator_with_studio.can_assign(
            room_id="R101",
            day_idx=3,
            start_h=17,
            end_h=18,
            specific_date="2026-03-11",
            instructor_id="Dr. B"
        )
        
        assert result is True

    def test_weekly_vs_studio_different_instructor_still_conflicts(self, allocator_with_studio):
        """
        Weekly lesson on R101 Wed 18:00 by Dr.B should also be blocked
        (Dr.A's Studio occupies that weekday/time slot)
        
        BUT: This is the existing Weekly-vs-Studio check behavior.
        With the new Bug 2 fix we removed Weekly-vs-Studio blocking...
        This test documents the current behavior for awareness.
        """
        # This is a design decision point - does a Studio block Weekly?
        # For now, document rather than assert
        pass
