import pandas as pd

from modules.scheduler.logic.optimizer import RoomAllocator


def _make_allocator():
    return RoomAllocator([], [], [], {})


def test_splice_into_blocks_reports_duplicate_student_through_duplicates_and_unassigned():
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
    allocator = _make_allocator()

    blocks = allocator._splice_into_blocks(df)

    assert len(blocks) == 1
    assert len(allocator.duplicates) == 1
    assert allocator.duplicates[0] == {
        "name": "Student 0001 Duplicate",
        "id": "S1",
        "course": "MUS200 Voice",
        "day": "Tuesday",
        "time": "11:00-12:00",
    }
    assert len(allocator.unassigned) == 1
    rejection = allocator.unassigned[0]
    assert rejection["reason_code"] == "duplicate_student"
    assert rejection["sid"] == "S1"
    assert rejection["day"] == 2
    assert rejection["start"] == 11
    assert rejection["end"] == 12
    assert rejection["instrument"] == "Voice"
    assert rejection["prefs"] == ["CC105", "R101"]


def test_splice_into_blocks_reports_missing_day_or_time_with_safe_defaults():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Prof A",
                "Day of Week": "",
                "Class Time": "",
                "Student Name": "Missing Fields",
                "Student No": "S2",
                "Course Code": "MUS101 Piano",
                "Preferred Venue": "CC105",
            }
        ]
    )
    allocator = _make_allocator()

    blocks = allocator._splice_into_blocks(df)

    assert blocks == []
    assert len(allocator.unassigned) == 1
    rejection = allocator.unassigned[0]
    assert rejection["reason_code"] == "missing_day_or_time"
    assert rejection["day"] == -1
    assert rejection["start"] == 0
    assert rejection["end"] == 0
    assert rejection["instrument"] == "Piano"
    assert rejection["prefs"] == ["CC105"]


def test_splice_into_blocks_reports_unsupported_weekday_and_preserves_raw_row():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Prof A",
                "Day of Week": "Funday",
                "Class Time": "09:00-10:00",
                "Student Name": "Odd Day",
                "Student No": "S3",
                "Course Code": "MUS101 Voice",
                "Preferred Venue": "CC105",
            }
        ]
    )
    allocator = _make_allocator()

    allocator._splice_into_blocks(df)

    assert len(allocator.unassigned) == 1
    rejection = allocator.unassigned[0]
    assert rejection["reason_code"] == "unsupported_weekday"
    assert rejection["day"] == -1
    assert rejection["start"] == 9
    assert rejection["end"] == 10
    assert rejection["raw_row"]["Day of Week"] == "Funday"


def test_process_studio_reports_malformed_class_time_via_unified_rejection():
    """Both detection paths (missing dash and TimeParser failure)
    must route through the same rejection helper so structure stays consistent."""
    from modules.shared.field_schema import normalize_to_weekly_format, parse_studio_date

    class ProbeAllocator(RoomAllocator):
        def __init__(self):
            super().__init__([], [], [], {})
            self.room_types = {"CC105": {"Piano"}, "R101": {"Piano", "Voice"}}
            self.room_instruments = {}

        def _init_grouped_assignments(self, *args, **kwargs):
            return

        def _build_block_map(self):
            return

        def can_assign(self, *args, **kwargs):
            return False

    studio_rows = [
        {
            "Instructor": "Instructor 0004",
            "Instruments": "Piano",
            "Preferred Venue": "CC105",
            "Studio 1 Date": "2026年3月30日 星期一",
            "Studio 1 Time": "badtime",
        }
    ]
    df = pd.DataFrame(studio_rows)

    allocator = ProbeAllocator()
    allocator._process_studio(df)

    assert len(allocator.unassigned) >= 1
    rejection = allocator.unassigned[0]
    assert rejection["reason_code"] == "invalid_course_time"
    assert rejection["inst"] == "Instructor 0004"
    assert "raw_row" in rejection


def test_splice_into_blocks_reports_malformed_class_time_with_zeroed_range():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Prof A",
                "Day of Week": "Monday",
                "Class Time": "25:99-26:99",
                "Student Name": "Bad Time",
                "Student No": "S4",
                "Course Code": "MUS101 Instrumental",
                "Preferred Venue": "CC105，R101",
            }
        ]
    )
    allocator = _make_allocator()

    allocator._splice_into_blocks(df)

    assert len(allocator.unassigned) == 1
    rejection = allocator.unassigned[0]
    assert rejection["reason_code"] == "invalid_course_time"
    assert rejection["day"] == 1
    assert rejection["start"] == 0
    assert rejection["end"] == 0
    assert rejection["instrument"] == "Instrumental"
    assert rejection["prefs"] == ["CC105", "R101"]
