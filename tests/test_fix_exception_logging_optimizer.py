"""
TDD tests for P1-1: optimizer.py silent failure → logging.

Strategy: verify fallback behavior unchanged + logging is emitted.
"""
import logging
import pytest
from unittest.mock import patch, MagicMock

from modules.shared.time_parser import TimeParser


# ---------------------------------------------------------------------------
# _check_global_constraints (line 73)
# ---------------------------------------------------------------------------
class TestCheckGlobalConstraints:
    """Verify _check_global_constraints exception fallback behavior."""

    def test_returns_true_when_timeparser_throws(self, allocator_with_rules):
        """When TimeParser fails, return True (constraint check passes)."""
        opt = allocator_with_rules
        with patch.object(TimeParser, 'extract_start_hour',
                          side_effect=ValueError("bad time format")):
            result = opt._check_global_constraints(8, 23)
        assert result is True

    def test_logs_warning_when_timeparser_throws(self, allocator_with_rules, caplog):
        """When TimeParser fails, a WARNING log should be emitted."""
        opt = allocator_with_rules
        with caplog.at_level(logging.WARNING):
            with patch.object(TimeParser, 'extract_start_hour',
                              side_effect=ValueError("bad time format")):
                opt._check_global_constraints(8, 23)
        assert len(caplog.records) >= 1
        assert any("constraint" in r.message.lower() or
                   "time" in r.message.lower()
                   for r in caplog.records)


# ---------------------------------------------------------------------------
# _parse_event_times (line 183)
# ---------------------------------------------------------------------------
class TestParseEventTimes:
    """Verify _parse_event_times exception fallback."""

    def test_returns_fail_closed_full_day_range_on_exception(self, allocator_with_rules):
        """When event_to_minute_range throws, return a full-day blocking range."""
        opt = allocator_with_rules
        bad_evt = {"startTime": None, "endTime": None}
        with patch.object(TimeParser, 'event_to_minute_range',
                          side_effect=ValueError("bad event")):
            s, e = opt._parse_event_times(bad_evt)
        assert s == 0
        assert e == 24 * 60

    def test_logs_warning_on_exception(self, allocator_with_rules, caplog):
        """When event_to_minute_range throws, a log is emitted."""
        opt = allocator_with_rules
        bad_evt = {"startTime": None, "endTime": None}
        with caplog.at_level(logging.WARNING):
            with patch.object(TimeParser, 'event_to_minute_range',
                              side_effect=ValueError("bad event")):
                opt._parse_event_times(bad_evt)
        assert len(caplog.records) >= 1


# ---------------------------------------------------------------------------
# Multi-hour locked context uses its real occupancy (regression)
# ---------------------------------------------------------------------------
class TestLectureRealOccupancy:
    """A 3-4h lecture must block only its real window, not the whole day."""

    LECTURE = {
        "id": "lec_reg",
        "resourceId": "R101",
        "daysOfWeek": [3],
        "startTime": "10:00:00",
        "endTime": "14:00:00",
        "title": "Choral Studies",
        "type": "lecture",
        "locked": True,
    }

    @pytest.fixture
    def allocator_with_lecture(self):
        from modules.scheduler.logic.optimizer import RoomAllocator
        from modules.scheduler.logic.rules_schema import DEFAULT_RULES
        return RoomAllocator(
            students=[],
            rooms=[],
            existing_bookings=[dict(self.LECTURE)],
            rules=DEFAULT_RULES,
        )

    def test_parse_returns_real_lecture_range(self, allocator_with_lecture):
        assert allocator_with_lecture._parse_event_times(dict(self.LECTURE)) == (600, 840)

    def test_lecture_blocks_its_own_window(self, allocator_with_lecture):
        assert allocator_with_lecture.can_assign("R101", 3, 12, 13) is False

    def test_room_is_free_outside_lecture_window(self, allocator_with_lecture):
        assert allocator_with_lecture.can_assign("R101", 3, 16, 17) is True

    def test_other_weekday_is_unaffected(self, allocator_with_lecture):
        assert allocator_with_lecture.can_assign("R101", 2, 12, 13) is True


# ---------------------------------------------------------------------------
# Shared allocator fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def allocator_with_rules():
    """Minimal RoomAllocator with default rules for exception-logging tests."""
    from modules.scheduler.logic.optimizer import RoomAllocator
    from modules.scheduler.logic.rules_schema import DEFAULT_RULES
    return RoomAllocator(
        students=[],
        rooms=[],
        existing_bookings=[],
        rules=DEFAULT_RULES,
    )
