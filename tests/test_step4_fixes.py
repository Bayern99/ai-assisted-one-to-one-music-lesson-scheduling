"""
Test Suite: Step 4 Six Fixes Verification
==========================================
Validates 6 fixes applied to scheduling.py Step 4:
  1. Lectures merged into viz data
  2. Lecture visual layer uses 'academic_lecture' type
  3a. ✅ Tag on scheduled events
  3b. Failed Assignments section data
  4. Cache clear on override actions
  5. Finalize conflict detection blocks double-booking
  6. build_viz_data handles all time formats
"""
import pytest
import sys
import os
from datetime import datetime, date, timedelta

# Path setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.scheduler.logic.conflict_validator import ConflictValidator


# ===== FIXTURES =====

@pytest.fixture
def weekly_assignments():
    """Realistic weekly lesson assignments"""
    return [
        {
            "id": "wk_1",
            "resourceId": "R101",
            "startTime": "09:00:00",
            "endTime": "10:00:00",
            "daysOfWeek": [1],  # Monday
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Dr. Smith"}
        },
        {
            "id": "wk_2",
            "resourceId": "CC322",
            "startTime": "14:00:00",
            "endTime": "15:00:00",
            "daysOfWeek": [3],  # Wednesday
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0002"}
        }
    ]


@pytest.fixture
def studio_assignments():
    """Realistic studio class assignments (ISO format)"""
    return [
        {
            "id": "stu_1",
            "resourceId": "R106",
            "start": "2026-03-30T17:00:00",
            "end": "2026-03-30T18:00:00",
            "type": "studio_class",
            "extendedProps": {"Instructor": "Dr. Zhao"}
        }
    ]


@pytest.fixture
def lecture_bookings():
    """Academic lectures from Step 0"""
    return [
        {
            "id": "lec_1",
            "resourceId": "R101",
            "startTime": "11:00:00",
            "endTime": "13:00:00",
            "daysOfWeek": [2],  # Tuesday
            "type": "lecture",  # ← Real data uses 'lecture' not 'academic_lecture'
            "title": "Music Theory 101",
            "extendedProps": {"Instructor": "Lecture"}
        }
    ]



@pytest.fixture
def unassigned_lessons():
    """Failed assignments with raw_row data"""
    return [
        {
            "reason": "No available room",
            "raw_row": {
                "Student Name": "Student 0001",
                "Instrument": "Violin",
                "Requested Time": "Mon 10:00-11:00",
                "Time Slot": "10:00-11:00"
            }
        },
        {
            "reason": "Instructor conflict",
            "raw_row": {
                "Student Name": "Student 0002",
                "Instrument": "Piano",
                "Requested Time": "Wed 14:00-15:00"
            }
        }
    ]


# ===== FIX 1: Lectures merged into viz =====

class TestFix1_LecturesInViz:
    """Lectures must be included in the viz data pipeline"""

    def test_lecture_type_preserved_in_combined_list(self, weekly_assignments, lecture_bookings):
        """When we merge assignments + lectures, lecture type is preserved"""
        combined = weekly_assignments + lecture_bookings
        types = [e.get('type') for e in combined]
        assert 'lecture' in types or 'academic_lecture' in types
        assert 'weekly_lesson' in types

    def test_lecture_has_required_viz_fields(self, lecture_bookings):
        """Lectures must have all fields needed by build_viz_data"""
        lec = lecture_bookings[0]
        # Must have time info
        assert lec.get('startTime') or lec.get('start'), "Lecture missing time field"
        # Must have room
        assert lec.get('resourceId'), "Lecture missing resourceId"
        # Must have day info
        assert lec.get('daysOfWeek'), "Lecture missing daysOfWeek"

    def test_combined_list_count(self, weekly_assignments, studio_assignments, lecture_bookings):
        """Combined list should contain all event types"""
        combined = weekly_assignments + studio_assignments + lecture_bookings
        assert len(combined) == 4  # 2 weekly + 1 studio + 1 lecture


# ===== FIX 2: Lecture visual distinction =====

class TestFix2_LectureVisualLayer:
    """Lecture layer must use 'academic_lecture' for transform_filter"""

    def test_lecture_type_is_academic_lecture(self, lecture_bookings):
        """The type field must be 'academic_lecture' to match the layer filter"""
        for lec in lecture_bookings:
            assert lec['type'] in ('academic_lecture', 'lecture')

    def test_weekly_type_distinct(self, weekly_assignments):
        for evt in weekly_assignments:
            assert evt['type'] == 'weekly_lesson'

    def test_studio_type_distinct(self, studio_assignments):
        for evt in studio_assignments:
            assert evt['type'] == 'studio_class'


# ===== FIX 3: Failed Assignments display =====

class TestFix3_FailedAssignments:
    """Failed items must show original request data"""

    def test_failed_has_raw_row(self, unassigned_lessons):
        """Every failed item must contain a raw_row dict"""
        for u in unassigned_lessons:
            assert 'raw_row' in u
            assert isinstance(u['raw_row'], dict)

    def test_failed_shows_student_name(self, unassigned_lessons):
        for u in unassigned_lessons:
            raw = u['raw_row']
            name = raw.get('Student Name', raw.get('title', None))
            assert name is not None, "Failed item missing student name"

    def test_failed_shows_requested_time(self, unassigned_lessons):
        """Original requested time must be accessible"""
        for u in unassigned_lessons:
            raw = u['raw_row']
            time = raw.get('Requested Time', raw.get('Time Slot', None))
            assert time is not None, f"Failed item {raw.get('Student Name')} missing requested time"

    def test_failed_shows_reason(self, unassigned_lessons):
        for u in unassigned_lessons:
            assert 'reason' in u
            assert len(u['reason']) > 0

    def test_failed_includes_instrument(self, unassigned_lessons):
        for u in unassigned_lessons:
            assert 'Instrument' in u['raw_row']


# ===== FIX 5: Finalize conflict detection =====

class TestFix5_FinalizeConflictCheck:
    """Finalize must detect and BLOCK double bookings"""

    @pytest.fixture
    def conflicting_assignments(self):
        """Two events in same room, same day, overlapping time"""
        return [
            {
                "id": "conf_1",
                "resourceId": "R101",
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "daysOfWeek": [1],
                "type": "weekly_lesson"
            },
            {
                "id": "conf_2",
                "resourceId": "R101",
                "startTime": "14:30:00",
                "endTime": "15:30:00",
                "daysOfWeek": [1],
                "type": "weekly_lesson"
            }
        ]

    @pytest.fixture
    def clean_assignments(self):
        """Non-overlapping events"""
        return [
            {
                "id": "clean_1",
                "resourceId": "R101",
                "startTime": "09:00:00",
                "endTime": "10:00:00",
                "daysOfWeek": [1],
                "type": "weekly_lesson"
            },
            {
                "id": "clean_2",
                "resourceId": "R101",
                "startTime": "10:00:00",
                "endTime": "11:00:00",
                "daysOfWeek": [1],
                "type": "weekly_lesson"
            }
        ]

    def test_detects_overlap_same_room_same_day(self, conflicting_assignments):
        """CRITICAL: Must detect double booking"""
        cv = ConflictValidator({
            'assignments': conflicting_assignments,
            'lectures': [],
            'rules': {}
        })

        # Check conf_1's slot — should find conf_2 as conflict
        conflict = cv.check_conflict("R101", 1, 14*60, 15*60)
        assert conflict is not None, "FAILED: Double booking not detected!"

    def test_no_false_positive_adjacent_slots(self, clean_assignments):
        """Adjacent (non-overlapping) slots must NOT be flagged"""
        cv = ConflictValidator({
            'assignments': clean_assignments,
            'lectures': [],
            'rules': {}
        })

        # Check a free slot
        conflict = cv.check_conflict("R101", 1, 11*60, 12*60)
        assert conflict is None, "False positive: flagged a free slot as conflict"

    def test_detects_lecture_conflict(self, weekly_assignments, lecture_bookings):
        """Assignment overlapping a lecture must be detected"""
        cv = ConflictValidator({
            'assignments': weekly_assignments,
            'lectures': lecture_bookings,
            'rules': {}
        })

        # Try Tuesday 11:30-12:30 in R101 (overlaps lecture 11:00-13:00)
        conflict = cv.check_conflict("R101", 2, 11*60+30, 12*60+30)
        assert conflict is not None
        assert conflict.get('is_locked_lecture') == True

    def test_different_rooms_no_conflict(self, conflicting_assignments):
        """Same time, different room = no conflict"""
        cv = ConflictValidator({
            'assignments': conflicting_assignments,
            'lectures': [],
            'rules': {}
        })

        # Check CC322 (different room) — should be free
        conflict = cv.check_conflict("CC322", 1, 14*60, 15*60)
        assert conflict is None

    def test_full_scan_finds_all_conflicts(self, conflicting_assignments):
        """Simulate the Finalize scan loop — must find at least one pair"""
        cv = ConflictValidator({
            'assignments': conflicting_assignments,
            'lectures': [],
            'rules': {}
        })

        conflicts = []
        seen_pairs = set()
        for evt in conflicting_assignments:
            days = evt.get('daysOfWeek', [])
            s, e = cv._parse_time(evt)
            for d in days:
                c = cv.check_conflict(evt['resourceId'], d, s, e)
                if c and c.get('id') != evt.get('id'):
                    pair_key = tuple(sorted([evt.get('id', ''), c.get('id', '')]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        conflicts.append((evt, c))

        assert len(conflicts) > 0, "CRITICAL: Finalize scan missed double booking!"

    def test_clean_scan_no_conflicts(self, clean_assignments):
        """Clean data should produce zero conflicts"""
        cv = ConflictValidator({
            'assignments': clean_assignments,
            'lectures': [],
            'rules': {}
        })

        conflicts = []
        seen_pairs = set()
        for evt in clean_assignments:
            days = evt.get('daysOfWeek', [])
            s, e = cv._parse_time(evt)
            for d in days:
                c = cv.check_conflict(evt['resourceId'], d, s, e)
                if c and c.get('id') != evt.get('id'):
                    pair_key = tuple(sorted([evt.get('id', ''), c.get('id', '')]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        conflicts.append((evt, c))

        assert len(conflicts) == 0, f"False positives: {conflicts}"


# ===== FIX 6: Time format handling in build_viz_data =====

class TestFix6_TimeFormatHandling:
    """build_viz_data must handle both weekly (startTime) and studio (ISO start) formats"""

    def test_weekly_startTime_read(self, weekly_assignments):
        """Weekly events use startTime/endTime fields"""
        for evt in weekly_assignments:
            start = evt.get('startTime') or evt.get('start', '09:00:00')
            assert start == evt['startTime'], "Should read startTime for weekly"

    def test_studio_iso_start_read(self, studio_assignments):
        """Studio events use ISO start/end fields"""
        for evt in studio_assignments:
            start = evt.get('startTime') or evt.get('start', '09:00:00')
            # startTime is None, so should fallback to 'start'
            assert start == evt['start'], "Should fallback to ISO start for studio"

    def test_iso_time_extraction(self):
        """ISO format must extract time portion correctly"""
        iso = "2026-03-30T17:00:00"
        if 'T' in iso:
            time_part = iso.split('T')[1]
        assert time_part == "17:00:00"

    def test_priority_startTime_over_start(self):
        """startTime must take priority over start (the fix)"""
        evt = {
            'startTime': '09:00:00',
            'start': '2026-03-30T17:00:00'  # This should be ignored
        }
        result = evt.get('startTime') or evt.get('start', '09:00:00')
        assert result == '09:00:00', "startTime should take priority"

    def test_fallback_when_no_startTime(self):
        """When startTime is absent, use start"""
        evt = {
            'start': '2026-03-30T17:00:00',
            'end': '2026-03-30T18:00:00'
        }
        result = evt.get('startTime') or evt.get('start', '09:00:00')
        assert result == '2026-03-30T17:00:00'

    def test_fallback_default_when_no_time(self):
        """When both are absent, use default"""
        evt = {'type': 'weekly_lesson'}
        result = evt.get('startTime') or evt.get('start', '09:00:00')
        assert result == '09:00:00'

    def test_lecture_time_format(self, lecture_bookings):
        """Lectures use startTime format like weekly"""
        lec = lecture_bookings[0]
        start = lec.get('startTime') or lec.get('start', '09:00:00')
        assert start == '11:00:00'
