from modules.scheduler.logic.optimizer_rejections import (
    append_unassigned_entry,
    build_studio_failed_unassigned,
    build_weekly_rejection_entry,
)


def test_append_unassigned_entry_preserves_payload_and_adds_reason_fields():
    sink = []

    entry = append_unassigned_entry(
        sink,
        {"id": "wk_1", "student": "Student 0001"},
        "No feasible room-time placement",
        "no_time_feasible_room",
    )

    assert entry == {
        "id": "wk_1",
        "student": "Student 0001",
        "reason": "No feasible room-time placement",
        "reason_code": "no_time_feasible_room",
    }
    assert sink == [entry]


def test_build_weekly_rejection_entry_uses_safe_defaults_and_normalized_fields():
    entry = build_weekly_rejection_entry(
        {
            "Student Name": "Student 0001",
            "Student No": "S1",
            "Instructor": "Instructor 0004",
            "Course Code": "MUS101 Voice",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Preferred Venue": "CC105，R101",
        },
        reason="Duplicate Student Entry: S1",
        normalized=None,
        row_idx=4,
        reason_code="duplicate_student",
        existing_unassigned_count=0,
    )

    assert entry["id"] == "wk_reject_S1_4"
    assert entry["student"] == "Student 0001"
    assert entry["sid"] == "S1"
    assert entry["inst"] == "Instructor 0004"
    assert entry["day"] == 1
    assert entry["start"] == 9
    assert entry["end"] == 10
    assert entry["instrument"] == "Voice"
    assert entry["prefs"] == ["CC105", "R101"]
    assert entry["reason"] == "Duplicate Student Entry: S1"
    assert entry["reason_code"] == "duplicate_student"


def test_build_weekly_rejection_entry_zeroes_range_on_malformed_time():
    entry = build_weekly_rejection_entry(
        {
            "Student Name": "Student 0002",
            "Student No": "S2",
            "Instructor": "Prof A",
            "Course Code": "MUS101 Instrumental",
            "Day of Week": "Monday",
            "Class Time": "25:99-26:99",
            "Preferred Venue": "CC105",
        },
        reason="Malformed Class Time: 25:99-26:99",
        normalized=None,
        row_idx=None,
        reason_code="malformed_class_time",
        existing_unassigned_count=3,
    )

    assert entry["id"] == "wk_reject_S2_3"
    assert entry["day"] == 1
    assert entry["start"] == 0
    assert entry["end"] == 0
    assert entry["instrument"] == "Instrumental"
    assert entry["reason_code"] == "malformed_class_time"


def test_build_studio_failed_unassigned_preserves_req_shape():
    req = {
        "inst": "Instructor 0004",
        "start": 18,
        "end": 19,
        "day": 1,
        "date": "2026-03-30",
        "id_suffix": "1_0",
        "raw_row": {"Instructor": "Instructor 0004", "Class Time": "18:00-19:00"},
    }

    entry = build_studio_failed_unassigned(
        req,
        reason="Blocked by locked context",
        reason_code="blocked_by_locked_context",
    )

    assert entry == {
        "id": "stu_Instructor 0004_1_0_failed",
        "student": "Studio",
        "inst": "Instructor 0004",
        "start": 18,
        "end": 19,
        "day": 1,
        "date": "2026-03-30",
        "raw_row": {"Instructor": "Instructor 0004", "Class Time": "18:00-19:00"},
        "reason": "Blocked by locked context",
        "reason_code": "blocked_by_locked_context",
    }
