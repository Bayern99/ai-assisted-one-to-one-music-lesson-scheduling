import pandas as pd

from modules.scheduler.logic.optimizer_normalization import (
    group_lessons_into_blocks,
    prepare_weekly_lessons,
)


def test_prepare_weekly_lessons_accepts_partial_normalized_rows(monkeypatch):
    from modules.shared import field_schema

    df = pd.DataFrame([{"raw": "ignored"}])
    duplicates = []
    rejections = []

    def fake_normalize(_source_type, _raw_data, extra=None):
        return {
            "Student No": "123",
            "Instructor": "Prof Partial",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Course Code": "MUS200",
        }

    monkeypatch.setattr(field_schema, "normalize_to_weekly_format", fake_normalize)

    lessons = prepare_weekly_lessons(
        df,
        duplicate_sink=duplicates,
        reject_weekly=lambda raw_row, reason, normalized=None, row_idx=None, reason_code=None: rejections.append(
            {
                "raw_row": raw_row,
                "reason": reason,
                "normalized": normalized,
                "row_idx": row_idx,
                "reason_code": reason_code,
            }
        ),
    )

    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson["student"] == ""
    assert lesson["prefs"] == []
    assert lesson["raw_row"]["Course Code"] == "MUS200"
    assert duplicates == []
    assert rejections == []


def test_prepare_weekly_lessons_reports_duplicate_students_and_rejections():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Prof A",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student Name": "Student 0001",
                "Student No": "S1",
                "Course Code": "MUS100 Piano",
                "Preferred Venue": "CC105",
            },
            {
                "Instructor": "Prof A",
                "Day of Week": "Tuesday",
                "Class Time": "11:00-12:00",
                "Student Name": "Student 0001 Duplicate",
                "Student No": "S1",
                "Course Code": "MUS200 Voice",
                "Preferred Venue": "CC105, R101",
            },
        ]
    )
    duplicates = []
    rejections = []

    lessons = prepare_weekly_lessons(
        df,
        duplicate_sink=duplicates,
        reject_weekly=lambda raw_row, reason, normalized=None, row_idx=None, reason_code=None: rejections.append(
            {
                "reason_code": reason_code,
                "normalized": normalized,
                "reason": reason,
            }
        ),
    )

    assert len(lessons) == 1
    assert duplicates == [
        {
            "name": "Student 0001 Duplicate",
            "id": "S1",
            "course": "MUS200 Voice",
            "day": "Tuesday",
            "time": "11:00-12:00",
        }
    ]
    assert rejections[0]["reason_code"] == "duplicate_student"
    assert rejections[0]["normalized"]["Student No"] == "S1"


def test_group_lessons_into_blocks_respects_disabled_instructor_blocks():
    lessons = [
        {
            "id": "wk_1",
            "student": "S1",
            "sid": "1",
            "inst": "Prof A",
            "day": 1,
            "start": 9,
            "end": 10,
            "instrument": "Instrumental",
            "prefs": [],
            "raw_row": {},
        },
        {
            "id": "wk_2",
            "student": "S2",
            "sid": "2",
            "inst": "Prof A",
            "day": 1,
            "start": 10,
            "end": 11,
            "instrument": "Instrumental",
            "prefs": [],
            "raw_row": {},
        },
    ]

    blocks = group_lessons_into_blocks(
        lessons,
        {
            "constraints": {
                "enforce_instructor_blocks": False,
                "min_break_between_lessons": 60,
            }
        },
    )

    assert len(blocks) == 2
    assert all(block["size"] == 1 for block in blocks)


def _group_lesson(lesson_id, start, end, inst="Prof A", day=1):
    return {
        "id": lesson_id,
        "student": lesson_id,
        "sid": lesson_id,
        "inst": inst,
        "day": day,
        "start": start,
        "end": end,
        "instrument": "Instrumental",
        "prefs": [],
        "raw_row": {},
    }


def test_group_lessons_into_blocks_bridges_zero_and_sixty_minute_gaps():
    lessons = [
        _group_lesson("wk_1", 9, 10),
        _group_lesson("wk_2", 10, 11),
        _group_lesson("wk_3", 12, 13),
        _group_lesson("wk_4", 15, 16),
    ]

    blocks = group_lessons_into_blocks(lessons, {"constraints": {"enforce_instructor_blocks": True}})
    blocks.sort(key=lambda block: block["start"])

    assert [block["start"] for block in blocks] == [9, 15]
    assert blocks[0]["end"] == 13
    assert blocks[0]["size"] == 3
    assert [lesson["id"] for lesson in blocks[0]["lessons"]] == ["wk_1", "wk_2", "wk_3"]
    assert blocks[1]["size"] == 1
    assert blocks[1]["lessons"][0]["id"] == "wk_4"


def test_group_lessons_into_blocks_does_not_merge_overlapping_lessons():
    lessons = [
        _group_lesson("wk_1", 9, 11),
        _group_lesson("wk_2", 10, 12),
    ]

    blocks = group_lessons_into_blocks(lessons, {"constraints": {"enforce_instructor_blocks": True}})

    assert len(blocks) == 2
    assert all(block["size"] == 1 for block in blocks)
