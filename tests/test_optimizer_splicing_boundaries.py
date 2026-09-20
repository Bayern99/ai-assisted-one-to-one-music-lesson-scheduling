import pandas as pd

from modules.scheduler.logic.optimizer import RoomAllocator


def _make_allocator(rules=None):
    return RoomAllocator([], [], [], rules or {})


def test_splice_into_blocks_respects_disabled_instructor_blocks():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Prof A",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student Name": "S1",
                "Student No": "1",
                "Course Code": "MUS100",
                "Preferred Venue": "",
            },
            {
                "Instructor": "Prof A",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
                "Student Name": "S2",
                "Student No": "2",
                "Course Code": "MUS100",
                "Preferred Venue": "",
            },
        ]
    )
    allocator = _make_allocator(
        {
            "constraints": {
                "enforce_instructor_blocks": False,
                "min_break_between_lessons": 60,
            }
        }
    )

    blocks = allocator._splice_into_blocks(df)

    assert len(blocks) == 2
    assert all(block["size"] == 1 for block in blocks)


def test_splice_into_blocks_accepts_partial_normalized_rows(monkeypatch):
    from modules.shared import field_schema

    df = pd.DataFrame([{"raw": "ignored"}])
    allocator = _make_allocator()

    def fake_normalize(_source_type, _raw_data, extra=None):
        return {
            "Student No": "123",
            "Instructor": "Prof Partial",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Course Code": "MUS200",
        }

    monkeypatch.setattr(field_schema, "normalize_to_weekly_format", fake_normalize)

    blocks = allocator._splice_into_blocks(df)

    assert len(blocks) == 1
    lesson = blocks[0]["lessons"][0]
    assert lesson["student"] == ""
    assert lesson["prefs"] == []
    assert lesson["raw_row"]["Course Code"] == "MUS200"


def test_splice_into_blocks_routes_normalization_failure_to_unassigned(monkeypatch):
    from modules.shared import field_schema

    df = pd.DataFrame(
        [
            {"Student Name": "Broken", "Student No": "1"},
            {
                "Instructor": "Prof A",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student Name": "Valid",
                "Student No": "2",
                "Course Code": "MUS100",
                "Preferred Venue": "",
            },
        ]
    )
    allocator = _make_allocator()

    original_normalize = field_schema.normalize_to_weekly_format

    def fake_normalize(source_type, raw_data, extra=None):
        if raw_data.get("Student Name") == "Broken":
            raise ValueError("bad row")
        return original_normalize(source_type, raw_data, extra)

    monkeypatch.setattr(field_schema, "normalize_to_weekly_format", fake_normalize)

    blocks = allocator._splice_into_blocks(df)

    assert len(blocks) == 1
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["reason_code"] == "normalization_failed"
    assert allocator.unassigned[0]["raw_row"]["Student Name"] == "Broken"
