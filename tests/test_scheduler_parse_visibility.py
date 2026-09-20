import io
import tempfile

import pandas as pd

from modules.scheduler.logic.optimizer import RoomAllocator
from modules.shared.data_loader import DataLoader
from modules.shared.scheduler_data_service import (
    parse_lectures_from_csv,
    import_schedule_from_excel,
    export_schedule_to_excel,
    detect_scheduler_conflicts,
)


def _make_schedule_workbook(weekly_df=None, studio_df=None):
    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        (weekly_df if weekly_df is not None else pd.DataFrame()).to_excel(
            writer, sheet_name="Weekly Schedule", index=False
        )
        (studio_df if studio_df is not None else pd.DataFrame()).to_excel(
            writer, sheet_name="Studio Schedule", index=False, startrow=1
        )
    payload.name = "schedule.xlsx"
    payload.seek(0)
    return payload


def test_optimizer_routes_invalid_studio_date_into_unassigned():
    rooms = [{"id": "R103", "type": ["Piano"], "types": ["Piano"]}]
    rules = {
        "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
        "priorities": {"Piano": {"Piano": 10}},
        "room_types": {},
        "instructor_priority": {},
        "instructor_preferred_rooms": {},
    }
    studio_df = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher",
                "Instruments": "Piano",
                "Studio 1 Date": "2026/03/30",
                "Studio 1 Time": "18:00-19:00",
                "Preferred Venue": "R103",
            }
        ]
    )

    allocator = RoomAllocator([], rooms, [], rules)
    assignments, duplicates, logs = allocator.optimize(pd.DataFrame(), studio_df=studio_df)

    assert assignments == []
    assert duplicates == []
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["reason_code"] == "invalid_studio_date"
    assert "Malformed Studio Date" in allocator.unassigned[0]["reason"]
    assert any("invalid studio date" in line.lower() for line in logs)


def test_parse_lectures_from_csv_surfaces_partial_warning_for_invalid_time_rows():
    csv_text = """Course Code,Course Title & Session,Teachers,Class Schedule,Hours,Classroom
MUS101,Theory A,Instructor 0008,Mon 10:00-11:00,1,CC-105
MUS102,Theory B,Instructor 0009,Wed TBD,1,CC-106
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        lecture_file = io.StringIO(csv_text)
        lecture_file.name = "lectures.csv"

        events, err = parse_lectures_from_csv(loader, lecture_file)

        assert len(events) == 1
        assert err is not None
        assert "Skipped 1 invalid lecture row" in err


def test_import_schedule_from_excel_reports_skipped_invalid_rows():
    weekly_df = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student No": "S1",
                "Student Name": "Student 0001",
                "Course Code": "MUS101 - Demo Course I (Piano)",
                "Preferred Venue": "R103",
            },
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "TBD",
                "Student No": "S2",
                "Student Name": "Student 0002",
                "Course Code": "MUS101 - Demo Course I (Piano)",
                "Preferred Venue": "R103",
            },
        ]
    )
    studio_df = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher",
                "Studio 1 Date": "2026/03/30",
                "Studio 1 Time": "18:00-19:00",
                "Preferred Venue": "R103",
            }
        ]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        workbook = _make_schedule_workbook(weekly_df=weekly_df, studio_df=studio_df)

        message = import_schedule_from_excel(loader, workbook)

        assert "Imported 1 events" in message
        assert "skipped 1 invalid weekly row" in message.lower()
        assert "skipped 1 invalid studio slot" in message.lower()


def test_export_schedule_to_excel_leaves_blank_time_for_malformed_event():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        loader.save_bookings(
            [
                {
                    "id": "broken_evt",
                    "resourceId": "R103",
                    "daysOfWeek": [1],
                    "startTime": "bad",
                    "endTime": "15:00:00",
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "Student Name": "Student 0001",
                        "Student No": "S1",
                        "Instructor": "Instructor 0001",
                        "Course Code": "MUS101",
                    },
                }
            ]
        )

        output = export_schedule_to_excel(loader)
        df = pd.read_excel(io.BytesIO(output), sheet_name="Master Schedule")

        assert pd.isna(df.loc[0, "Class Time"])


def test_detect_scheduler_conflicts_reports_malformed_event_time():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        loader.save_bookings(
            [
                {
                    "id": "broken_evt",
                    "resourceId": "R103",
                    "daysOfWeek": [1],
                    "startTime": "bad",
                    "endTime": "15:00:00",
                    "type": "weekly_lesson",
                    "title": "Broken Event",
                }
            ]
        )

        conflicts = detect_scheduler_conflicts(loader)

        assert any("MALFORMED TIME" in item for item in conflicts)


def test_detect_scheduler_conflicts_uses_real_multi_hour_lecture_window():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        loader.save_bookings(
            [
                {
                    "id": "lec_four_h",
                    "resourceId": "R101",
                    "daysOfWeek": [3],
                    "startTime": "10:00:00",
                    "endTime": "14:00:00",
                    "type": "lecture",
                    "title": "Choral Studies",
                    "locked": True,
                },
                {
                    "id": "pi_inside",
                    "resourceId": "R101",
                    "daysOfWeek": [3],
                    "startTime": "12:00:00",
                    "endTime": "13:00:00",
                    "type": "weekly_lesson",
                    "title": "Piano (Instructor 0001)",
                    "extendedProps": {"Instructor": "Instructor 0001"},
                },
                {
                    "id": "pi_outside",
                    "resourceId": "R101",
                    "daysOfWeek": [3],
                    "startTime": "16:00:00",
                    "endTime": "17:00:00",
                    "type": "weekly_lesson",
                    "title": "Violin (Dr. B)",
                    "extendedProps": {"Instructor": "Dr. B"},
                },
            ]
        )

        conflicts = detect_scheduler_conflicts(loader)

        assert not any("MALFORMED TIME" in item and "lec_four_h" in item for item in conflicts)
        assert any("ROOM R101" in item and "pi_inside" in item for item in conflicts)
        assert not any("pi_outside" in item for item in conflicts)
