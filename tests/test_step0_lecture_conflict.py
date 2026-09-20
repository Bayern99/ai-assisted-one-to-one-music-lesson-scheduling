"""TDD: Step 0 lecture conflict detection must use minute-based overlap."""
from modules.scheduler.logic.lecture_service import detect_lecture_time_overlap


def test_detects_overlap_with_single_digit_hour_times():
    """9:00:00 vs 10:00:00 must overlap when ranges cross (string compare would miss)."""
    assert detect_lecture_time_overlap("9:00:00", "10:30:00", "09:30:00", "11:00:00") is True


def test_no_overlap_adjacent_slots():
    assert detect_lecture_time_overlap("09:00:00", "10:00:00", "10:00:00", "11:00:00") is False


def test_overlap_same_format():
    assert detect_lecture_time_overlap("09:00:00", "11:00:00", "10:00:00", "12:00:00") is True
