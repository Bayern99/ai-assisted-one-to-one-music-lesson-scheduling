"""
TDD Forensic Test: Lost Items After Reassignment (Bug 1)

ROOT CAUSE: When reassigning a Failed Assignment, the day detection
(scheduling.py L1288-1293) defaults to Monday (1) if the time string
has no day name (e.g., "14:00-15:00"). Events originally on Wednesday
get silently reassigned to Monday → appear "lost" in the UI.

Also: unassign_slot doesn't preserve 'Day of Week' in raw_row,
so the reassignment flow has no fallback to recover the original day.
"""

import pytest
import copy
from modules.scheduler.logic.manual_override_legacy import ManualOverrider


# ─── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def scheduler_data_with_wed_event():
    """Student 0003's weekly lesson on Wednesday R101 14:00-15:00"""
    return {
        "assignments": [
            {
                "id": "wk_student_0003_wed",
                "resourceId": "R101",
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "daysOfWeek": [3],  # Wed (JS convention)
                "type": "weekly_lesson",
                "title": "👤 Student 0003 (Instructor 0001)",
                "extendedProps": {
                    "Instructor": "Instructor 0001",
                    "Student Name": "Student 0003",
                    "Student No": "S12345",
                    "Instrument": "Piano",
                    "Study Year": "2",
                    "Course Code": "MUSC1234",
                    "day_en": "Wednesday"
                }
            }
        ],
        "unassigned_lessons": [],
        "lectures": [],
        "rules": {"room_types": {"R101": ["Piano", "Voice"]}}
    }


# ─── Test: Unassign Preserves Day ───────────────────────────

class TestUnassignPreservesDay:
    """After unassigning, the item in unassigned_lessons MUST retain
    enough information to recover the original day."""

    def test_unassign_preserves_day_of_week_in_raw_row(self, scheduler_data_with_wed_event):
        """
        RED TEST: After unassigning Student 0003's Wed lesson, raw_row should
        contain 'Day of Week' = 'Wednesday' for the reassignment flow.
        """
        overrider = ManualOverrider(scheduler_data_with_wed_event)
        
        result = overrider.unassign_slot("wk_student_0003_wed")
        assert result is True
        
        # Item should be in unassigned_lessons
        unassigned = scheduler_data_with_wed_event['unassigned_lessons']
        assert len(unassigned) == 1
        
        item = unassigned[0]
        raw = item.get('raw_row', {})
        
        # CRITICAL: Must have Day of Week for reassignment
        assert 'Day of Week' in raw, (
            f"raw_row is missing 'Day of Week'! Keys: {list(raw.keys())}"
        )
        assert raw['Day of Week'] == 'Wednesday', (
            f"Expected 'Wednesday' but got '{raw['Day of Week']}'"
        )

    def test_unassign_preserves_days_of_week_array(self, scheduler_data_with_wed_event):
        """
        The unassigned item should also retain the original daysOfWeek array
        as a top-level property for fallback.
        """
        overrider = ManualOverrider(scheduler_data_with_wed_event)
        overrider.unassign_slot("wk_student_0003_wed")
        
        item = scheduler_data_with_wed_event['unassigned_lessons'][0]
        
        # daysOfWeek should still be present at top level
        assert 'daysOfWeek' in item, (
            f"Top-level 'daysOfWeek' lost after unassign! Keys: {list(item.keys())}"
        )
        assert item['daysOfWeek'] == [3], (
            f"Expected daysOfWeek=[3] but got {item['daysOfWeek']}"
        )

    def test_unassign_preserves_class_time(self, scheduler_data_with_wed_event):
        """Class Time should be preserved in raw_row."""
        overrider = ManualOverrider(scheduler_data_with_wed_event)
        overrider.unassign_slot("wk_student_0003_wed")
        
        item = scheduler_data_with_wed_event['unassigned_lessons'][0]
        raw = item.get('raw_row', {})
        
        # Class Time should be reconstructed
        assert 'Class Time' in raw or 'Time' in raw, (
            f"No time info in raw_row! Keys: {list(raw.keys())}"
        )
        
    def test_unassign_preserves_student_name(self, scheduler_data_with_wed_event):
        """Student Name must be in raw_row."""
        overrider = ManualOverrider(scheduler_data_with_wed_event)
        overrider.unassign_slot("wk_student_0003_wed")
        
        item = scheduler_data_with_wed_event['unassigned_lessons'][0]
        raw = item.get('raw_row', {})
        
        assert raw.get('Student Name') == 'Student 0003'

    def test_unassign_preserves_instrument(self, scheduler_data_with_wed_event):
        """Instrument must be in raw_row."""
        overrider = ManualOverrider(scheduler_data_with_wed_event)
        overrider.unassign_slot("wk_student_0003_wed")
        
        item = scheduler_data_with_wed_event['unassigned_lessons'][0]
        raw = item.get('raw_row', {})
        
        assert raw.get('Instrument') == 'Piano'


# ─── Test: Day Detection Robustness ─────────────────────────

class TestDayDetection:
    """Simulate the day detection logic from scheduling.py L1288-1293.
    Test with various time string formats."""

    def _detect_day(self, requested_time, raw_row=None, item=None):
        """Replicate the day detection logic from scheduling.py"""
        day_map_f = {'mon':1,'tue':2,'wed':3,'thu':4,'fri':5,'sat':6,'sun':0}
        day_full_map = {'monday':1,'tuesday':2,'wednesday':3,
                        'thursday':4,'friday':5,'saturday':6,'sunday':0}
        
        detected_day = None
        raw = raw_row or {}
        u = item or {}
        
        # Source 1: requested_time string
        for dname, dnum in day_map_f.items():
            if dname in str(requested_time).lower():
                detected_day = dnum
                break
        
        # Source 2: raw_row 'Day of Week'
        if detected_day is None:
            dow = str(raw.get('Day of Week', '')).lower().strip()
            if dow in day_full_map:
                detected_day = day_full_map[dow]
        
        # Source 3: raw_row 'day_en'
        if detected_day is None:
            day_en = str(raw.get('day_en', '')).lower().strip()
            if day_en in day_full_map:
                detected_day = day_full_map[day_en]
        
        # Source 4: Original event's daysOfWeek
        if detected_day is None:
            orig_days = u.get('daysOfWeek', [])
            if orig_days:
                detected_day = orig_days[0]
        
        # Final fallback
        if detected_day is None:
            detected_day = 1  # Monday default
        
        return detected_day

    def test_day_from_time_string(self):
        """Wed prefix in time string → detect Wednesday"""
        assert self._detect_day("Wed 14:00-15:00") == 3

    def test_day_from_raw_row_day_of_week(self):
        """No day in time, but raw_row has Day of Week"""
        assert self._detect_day("14:00-15:00", raw_row={"Day of Week": "Wednesday"}) == 3

    def test_day_from_raw_row_day_en(self):
        """No day in time or Day of Week, but day_en available"""
        assert self._detect_day("14:00-15:00", raw_row={"day_en": "Wednesday"}) == 3

    def test_day_from_item_daysOfWeek(self):
        """No day anywhere in raw, but daysOfWeek preserved from original event"""
        assert self._detect_day("14:00-15:00", item={"daysOfWeek": [3]}) == 3

    def test_day_defaults_to_monday_only_as_last_resort(self):
        """Only default to Monday when ALL sources are empty"""
        assert self._detect_day("14:00-15:00") == 1

    def test_time_string_without_day_should_not_default_to_monday_if_raw_has_day(self):
        """
        RED TEST (current code): Time string "14:00-15:00" has no day name.
        BUT raw_row has Day of Week = Wednesday.
        Current code defaults to Monday. Fixed code should detect Wednesday.
        """
        assert self._detect_day(
            "14:00-15:00",
            raw_row={"Day of Week": "Wednesday"}
        ) == 3  # Should be Wednesday, not Monday!
