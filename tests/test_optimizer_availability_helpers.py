from modules.scheduler.logic.optimizer_availability import (
    can_assign_against_bookings,
    is_time_overlap,
)


def test_is_time_overlap_matches_scheduler_contract():
    assert is_time_overlap(10 * 60, 11 * 60, 10 * 60 + 30, 11 * 60 + 30) is True
    assert is_time_overlap(10 * 60, 11 * 60, 11 * 60, 12 * 60) is False


def test_can_assign_against_bookings_blocks_self_overlap_for_same_instructor():
    bookings = [
        {
            "resourceId": "R101",
            "daysOfWeek": [1],
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "title": "👤 Student 0001 (Instructor 0001)",
            "extendedProps": {"Instructor": "Instructor 0001"},
        }
    ]

    result = can_assign_against_bookings(
        bookings,
        room_id="R101",
        day_idx=1,
        start_h=10,
        end_h=11,
        specific_date=None,
        instructor_id="Instructor 0001",
        parse_event_times=lambda evt: (10 * 60, 11 * 60),
    )

    assert result is False


def test_can_assign_against_bookings_blocks_malformed_events_fail_closed():
    bookings = [
        {
            "resourceId": "R101",
            "daysOfWeek": [1],
            "startTime": "bad",
            "endTime": "11:00:00",
            "extendedProps": {"Instructor": "Dr. B"},
        }
    ]

    result = can_assign_against_bookings(
        bookings,
        room_id="R101",
        day_idx=1,
        start_h=10,
        end_h=11,
        specific_date=None,
        instructor_id="Instructor 0001",
        parse_event_times=lambda evt: (0, 24 * 60),
    )

    assert result is False


def test_can_assign_against_bookings_enforces_studio_weekday_conflict():
    bookings = [
        {
            "resourceId": "R101",
            "start": "2026-03-04T18:00:00",
            "end": "2026-03-04T19:00:00",
            "type": "studio_class",
            "extendedProps": {"Instructor": "Instructor 0001", "is_studio": True},
        }
    ]

    result = can_assign_against_bookings(
        bookings,
        room_id="R101",
        day_idx=3,
        start_h=18,
        end_h=19,
        specific_date="2026-03-11",
        instructor_id="Dr. B",
        parse_event_times=lambda evt: (18 * 60, 19 * 60),
    )

    assert result is False
