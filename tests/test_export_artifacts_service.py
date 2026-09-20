from io import BytesIO
import json
import zipfile

import numpy as np
import pandas as pd

from modules.scheduler.logic.export_artifacts import (
    ExportArtifacts,
    build_download_artifacts,
    build_instructor_bundle_zip,
)


def _bookings():
    return [
        {
            "id": "wk-1",
            "resourceId": "R101",
            "startTime": "09:00:00",
            "endTime": "10:00:00",
            "daysOfWeek": [1],
            "type": "weekly_lesson",
            "extendedProps": {
                "Instructor": "Instructor 0001",
                "Student Name": "Student 0001",
                "Student No": "S1",
                "Study Year": "1",
                "Course Code": "MUS101 (Piano)",
                "day_en": "Monday",
            },
        },
        {
            "id": "stu-1",
            "resourceId": "R102",
            "start": "2026-03-30T19:00:00",
            "end": "2026-03-30T20:00:00",
            "type": "studio_class",
            "extendedProps": {
                "Instructor": "Instructor 0004",
                "Instrument": "Voice",
                "day_en": "Monday",
                "class_time": "19:00-20:00",
            },
        },
    ]


def _unassigned():
    return [
        {
            "id": "wk-reject",
            "student": "Student 0002",
            "reason": "Duplicate Student Entry: S2",
            "raw_row": {
                "Instructor": "Instructor 0001",
                "Student Name": "Student 0002",
                "Student No": "S2",
                "Study Year": "1",
                "Course Code": "MUS101 (Piano)",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
            },
        }
    ]


def _student_map():
    return {
        "S1": {"student_id": "S1", "name_en": "Student 0001", "instrument": "Piano"},
        "S2": {"student_id": "S2", "name_en": "Student 0002", "instrument": "Piano"},
    }


def _studio_df():
    return pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0004",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "19:00-20:00",
            }
        ]
    )


def _build(bookings=None):
    return build_download_artifacts(
        _bookings() if bookings is None else bookings,
        _unassigned(),
        _student_map(),
        ["Instructor 0001", "Instructor 0004"],
        uploaded_studio_df=_studio_df(),
    )


def test_build_download_artifacts_preserves_workbooks_and_preview_records():
    artifacts = _build()

    assert isinstance(artifacts, ExportArtifacts)
    assert sorted(artifacts.files) == [
        "Master_Schedule.xlsx",
        "Studio_Schedule.xlsx",
        "Weekly_Schedule.xlsx",
    ]
    assert all(payload.startswith(b"PK") for payload in artifacts.files.values())

    master = pd.read_excel(BytesIO(artifacts.files["Master_Schedule.xlsx"]))
    weekly = pd.read_excel(BytesIO(artifacts.files["Weekly_Schedule.xlsx"]))
    studio = pd.read_excel(BytesIO(artifacts.files["Studio_Schedule.xlsx"]))

    assert len(master) == len(artifacts.preview_records) == 3
    assert sorted(master["Room"].tolist()) == ["R101", "R102", "Unassigned"]
    assert master["Event Type"].value_counts().to_dict() == {
        "Weekly Lesson": 2,
        "Studio Class": 1,
    }
    assert set(weekly["Event Type"]) == {"Weekly Lesson"}
    assert set(weekly["Room"]) == {"R101"}
    assert set(studio["Event Type"]) == {"Studio Class"}
    assert set(studio["Room"]) == {"R102"}


def test_master_is_always_present_and_type_workbooks_are_conditional():
    no_canonical_types = _build(
        [{"id": "lecture-1", "type": "lecture", "resourceId": "CC100"}]
    )
    weekly_only = _build([_bookings()[0]])
    studio_only = _build([_bookings()[1]])

    assert list(no_canonical_types.files) == ["Master_Schedule.xlsx"]
    assert sorted(weekly_only.files) == [
        "Master_Schedule.xlsx",
        "Weekly_Schedule.xlsx",
    ]
    assert sorted(studio_only.files) == [
        "Master_Schedule.xlsx",
        "Studio_Schedule.xlsx",
    ]


def test_instructor_bundle_preserves_one_workbook_per_named_instructor():
    artifacts = _build()
    bundle = build_instructor_bundle_zip(pd.DataFrame(artifacts.preview_records))

    assert bundle.startswith(b"PK")
    with zipfile.ZipFile(BytesIO(bundle), "r") as archive:
        assert sorted(archive.namelist()) == [
            "Dr_Studio_Schedule.xlsx",
            "Dr_X_Schedule.xlsx",
        ]
        dr_x = pd.read_excel(BytesIO(archive.read("Dr_X_Schedule.xlsx")))
        studio = pd.read_excel(BytesIO(archive.read("Dr_Studio_Schedule.xlsx")))

    assert set(dr_x["Instructor"]) == {"Instructor 0001"}
    assert set(dr_x["Student Name (EN)"]) == {"Student 0001", "Student 0002"}
    assert set(studio["Instructor"]) == {"Instructor 0004"}


def test_preview_records_are_strict_json_safe_with_pandas_and_numpy_values():
    unassigned = [
        {
            "id": "wk-json-safe",
            "raw_row": {
                "Instructor": "Instructor 0001",
                "Student Name": np.nan,
                "Student No": "S-json",
                "Instrument": pd.NaT,
                "Study Year": np.int64(3),
                "Course Code": pd.Timestamp("2026-07-11 12:34:56"),
                "Day of Week": "Monday",
                "Class Time": "11:00-12:00",
            },
        }
    ]

    artifacts = build_download_artifacts([], unassigned, {}, ["Instructor 0001"])

    assert json.loads(
        json.dumps(artifacts.preview_records, allow_nan=False)
    ) == artifacts.preview_records
    assert artifacts.preview_records == [
        {
            "Instructor": "Instructor 0001",
            "Student Name (EN)": None,
            "Student Name (CN)": "",
            "Student ID": "S-json",
            "Instrument": None,
            "Year": 3,
            "Course Code": "2026-07-11T12:34:56.000",
            "Event Type": "Weekly Lesson",
            "Day": "Monday",
            "Date": "",
            "Time": "11:00-12:00",
            "Room": "Unassigned",
            "Duration": "1h",
        }
    ]


def test_instructor_bundle_for_non_export_bookings_is_an_empty_zip():
    artifacts = build_download_artifacts(
        [{"id": "lecture-1", "type": "lecture", "resourceId": "CC100"}],
        [],
        {},
        [],
    )

    bundle = build_instructor_bundle_zip(pd.DataFrame(artifacts.preview_records))

    assert bundle.startswith(b"PK")
    with zipfile.ZipFile(BytesIO(bundle), "r") as archive:
        assert archive.namelist() == []
