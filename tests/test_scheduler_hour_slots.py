import pandas as pd

from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.optimizer_studio import prepare_studio_requests
from modules.shared.time_parser import TimeParser


def test_hour_slot_expands_both_bounds_outward():
    assert TimeParser.normalize_course_range("09:30-10:30") == ("09:00", "11:00")
    assert TimeParser.normalize_course_range("09:00-10:00") == ("09:00", "10:00")


def test_course_request_rejects_non_hourly_or_non_half_hour_requests():
    for value in (
        "09:30-09:45",
        "09:00-09:30",
        "09:00-10:30",
        "09:15-10:15",
    ):
        assert TimeParser.normalize_course_range(value) is None


def test_weekly_optimizer_emits_canonical_occupancy_range_and_source_id():
    allocator = RoomAllocator(
        [],
        [{"id": "R1", "types": ["Piano"]}],
        [],
        {
            "room_types": {"R1": ["Piano"]},
            "priorities": {"Piano": {"Piano": 10}},
            "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
            "instructor_priority": {},
        },
    )
    assignments, _, _ = allocator.optimize(
        pd.DataFrame(
            [
                {
                    "Student Name": "Student 0001",
                    "Student No": "S1",
                    "Instructor": "Instructor 0008",
                    "Course Code": "Piano",
                    "Day of Week": "Monday",
                    "Class Time": "09:30-10:30",
                }
            ]
        )
    )

    assert assignments[0]["startTime"] == "09:00:00"
    assert assignments[0]["endTime"] == "11:00:00"
    assert assignments[0]["source_request_id"] == "weekly:0"
    assert assignments[0]["extendedProps"]["Class Time"] == "09:00-11:00"


def test_invalid_weekly_request_is_unresolved_instead_of_being_scheduled():
    allocator = RoomAllocator(
        [],
        [{"id": "R1", "types": ["Piano"]}],
        [],
        {
            "room_types": {"R1": ["Piano"]},
            "priorities": {"Piano": {"Piano": 10}},
            "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
            "instructor_priority": {},
        },
    )

    assignments, unresolved, _ = allocator.optimize(
        pd.DataFrame(
            [
                {
                    "Student Name": "Student 0001",
                    "Student No": "S1",
                    "Instructor": "Instructor 0008",
                    "Course Code": "Piano",
                    "Day of Week": "Monday",
                    "Class Time": "09:30-09:45",
                }
            ]
        )
    )

    assert assignments == []
    assert allocator.unassigned[0]["reason_code"] == "invalid_course_time"


def test_invalid_studio_request_is_rejected_before_room_allocation():
    requests, rejections = prepare_studio_requests(
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Instruments": "Piano",
                    "Studio 1 Date": "2026年3月30日 星期一",
                    "Studio 1 Time": "09:30-09:45",
                }
            ]
        ),
        room_types={"R1": ["Piano"]},
        normalize_instrument_type=lambda value: "Piano",
    )

    assert requests == []
    assert rejections[0]["reason_code"] == "invalid_course_time"


def test_studio_missing_time_is_rejected_instead_of_defaulting_to_nineteen():
    requests, rejections = prepare_studio_requests(
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Instruments": "Piano",
                    "Studio 1 Date": "2026年3月30日 星期一",
                }
            ]
        ),
        room_types={"R1": ["Piano"]},
        normalize_instrument_type=lambda value: "Piano",
    )

    assert requests == []
    assert rejections[0]["reason_code"] == "missing_studio_time"
    assert "source_request_id" not in rejections[0]["payload"]


def test_trailing_studio_delimiter_does_not_create_an_extra_request():
    requests, rejections = prepare_studio_requests(
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Instruments": "Piano",
                    "Studio 1 Date": "2026年3月30日 星期一",
                    "Studio 1 Time": "09:00-10:00,",
                }
            ]
        ),
        room_types={"R1": ["Piano"]},
        normalize_instrument_type=lambda value: "Piano",
    )

    assert rejections == []
    assert len(requests) == 1
    assert requests[0]["source_request_id"] == "studio:0:1:0"
