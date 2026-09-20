import pandas as pd

from modules.scheduler.logic.instructor_time_integrity import (
    audit_canonical_schedule,
    audit_source_schedule,
    instructor_is_available,
)


def _weekly(*rows):
    return pd.DataFrame(rows)


def _studio(*rows):
    return pd.DataFrame(rows)


def test_source_audit_detects_weekly_overlap_for_same_instructor():
    conflicts = audit_source_schedule(
        _weekly(
            {
                "Instructor": "Instructor 0001",
                "Student Name": "One",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
            },
            {
                "Instructor": "Instructor 0001",
                "Student Name": "Two",
                "Day of Week": "Monday",
                "Class Time": "10:30-11:30",
            },
        ),
        None,
    )

    assert len(conflicts) == 1
    assert conflicts[0]["instructor"] == "Instructor 0001"
    assert conflicts[0]["left"]["source"] == "weekly"
    assert conflicts[0]["right"]["source"] == "weekly"


def test_source_audit_matches_case_and_repeated_whitespace():
    conflicts = audit_source_schedule(
        _weekly(
            {
                "Instructor": "Dr.   A",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
            },
            {
                "Instructor": "dr. a",
                "Day of Week": "Monday",
                "Class Time": "10:30-11:30",
            },
        ),
        None,
    )

    assert len(conflicts) == 1


def test_source_audit_detects_weekly_studio_overlap_on_actual_date():
    conflicts = audit_source_schedule(
        _weekly(
            {
                "Instructor": "Instructor 0001",
                "Student Name": "Weekly",
                "Day of Week": "Tuesday",
                "Class Time": "17:00-18:00",
            },
        ),
        _studio(
            {
                "Instructor": "Instructor 0001",
                "Studio 1 Date": "2026-02-24",
                "Studio 1 Time": "17:00-18:00",
            },
        ),
    )

    assert len(conflicts) == 1
    assert conflicts[0]["date"] == "2026-02-24"


def test_source_audit_allows_adjacent_lessons_and_different_studio_dates():
    conflicts = audit_source_schedule(
        _weekly(
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
            },
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "11:00-12:00",
            },
        ),
        _studio(
            {
                "Instructor": "Dr. B",
                "Studio 1 Date": "2026-03-02",
                "Studio 1 Time": "18:00-19:00",
                "Studio 2 Date": "2026-03-09",
                "Studio 2 Time": "18:00-19:00",
            },
        ),
    )

    assert conflicts == []


def test_canonical_audit_detects_cross_room_teacher_overlap():
    assignments = [
        {
            "id": "a",
            "resourceId": "R1",
            "daysOfWeek": [1],
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001"},
        },
        {
            "id": "b",
            "resourceId": "R2",
            "daysOfWeek": [1],
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001"},
        },
    ]

    conflicts = audit_canonical_schedule(assignments)

    assert len(conflicts) == 1
    assert {conflicts[0]["left"]["id"], conflicts[0]["right"]["id"]} == {"a", "b"}


def test_instructor_is_available_honours_locked_lecture_window():
    assignments = [
        {
            "id": "lec-locked",
            "resourceId": "R101",
            "daysOfWeek": [3],
            "startTime": "10:00:00",
            "endTime": "14:00:00",
            "type": "locked_lecture",
            "title": "Choral Studies",
            "extendedProps": {"Instructor": "Dr. Choir"},
        }
    ]

    assert instructor_is_available(
        assignments,
        instructor="Dr. Choir",
        day=3,
        start_min=12 * 60,
        end_min=13 * 60,
    ) is False
    assert instructor_is_available(
        assignments,
        instructor="Dr. Choir",
        day=3,
        start_min=16 * 60,
        end_min=17 * 60,
    ) is True


def test_canonical_audit_detects_overlap_with_locked_lecture():
    assignments = [
        {
            "id": "lec-locked",
            "resourceId": "R101",
            "daysOfWeek": [3],
            "startTime": "10:00:00",
            "endTime": "14:00:00",
            "type": "locked_lecture",
            "title": "Choral Studies",
            "extendedProps": {"Instructor": "Dr. Choir"},
        },
        {
            "id": "weekly-overlap",
            "resourceId": "R106",
            "daysOfWeek": [3],
            "startTime": "12:00:00",
            "endTime": "13:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Dr. Choir"},
        },
    ]

    conflicts = audit_canonical_schedule(assignments)

    assert len(conflicts) == 1
    assert conflicts[0]["left"]["id"] == "lec-locked"
    assert conflicts[0]["right"]["id"] == "weekly-overlap"
