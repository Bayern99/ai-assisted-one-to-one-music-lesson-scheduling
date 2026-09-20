import io
import json
import os
import tempfile
import time

import pandas as pd
import pytest

from modules.scheduler.logic.provenance import SCHEDULER_PROVENANCE_KEY
from modules.scheduler.logic.session_state import SCHEDULER_SAVE_WARNING_KEY
from modules.scheduler.logic.upload_workbook_service import process_scheduler_upload
from modules.shared.data_loader import DataLoader
from modules.shared.save_outcome import SaveOutcome
from modules.shared.session_manager import SessionManager


def _make_workbook_bytes(
    *,
    weekly_df=None,
    studio_df=None,
    room_df=None,
    student_df=None,
):
    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        (weekly_df if weekly_df is not None else pd.DataFrame()).to_excel(
            writer, sheet_name="Weekly Schedule", index=False
        )
        (studio_df if studio_df is not None else pd.DataFrame()).to_excel(
            writer, sheet_name="Studio Schedule", index=False
        )
        if room_df is not None:
            room_df.to_excel(writer, sheet_name="Room", index=False)
        if student_df is not None:
            student_df.to_excel(writer, sheet_name="Student Info", index=False)
    return payload.getvalue()


def _weekly_df():
    return pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student No": "S1",
                "Student Name": "Student 0001",
                "Course Code": "MUS101 - Demo Course I (Piano)",
                "Preferred Venue": "R103",
            }
        ]
    )


def _room_df():
    return pd.DataFrame(
        [
            {
                "Room Number": "R103",
                "Piano Specifications": "Yamaha upright piano",
            }
        ]
    )


def _student_df():
    return pd.DataFrame(
        [
            {
                "Student No": "S1",
                "English Name": "Student 0001",
                "Chinese Name": "学生三",
                "Study Year": 1,
                "Programme": "Music",
                "Instructor": "Instructor 0001",
                "Instrument": "Piano",
                "Course Code": "MUS101 - Demo Course I (Piano)",
            }
        ]
    )


def test_process_scheduler_upload_syncs_rooms_and_marks_missing_students_not_present():
    workbook_bytes = _make_workbook_bytes(weekly_df=_weekly_df(), room_df=_room_df())

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        session_mgr = SessionManager(base_dir=tmpdir)
        state = {}

        result = process_scheduler_upload(
            loader,
            session_mgr,
            state,
            upload_slot="weekly",
            file_name="rooms-only.xlsx",
            file_bytes=workbook_bytes,
        )

        assert result["sheet_name"] == "Weekly Schedule"
        assert len(state["wk_df"]) == 1
        assert loader.get_data("rooms.json")[0]["id"] == "R103"
        assert state[SCHEDULER_PROVENANCE_KEY]["master_data_sync"]["rooms"]["status"] == "synced"
        assert state[SCHEDULER_PROVENANCE_KEY]["master_data_sync"]["students"]["status"] == "not_present"
        saved_session = session_mgr.load_session()
        assert SCHEDULER_PROVENANCE_KEY in saved_session


def test_atomic_upload_rejects_newer_divergent_shadow_readback():
    workbook_bytes = _make_workbook_bytes(weekly_df=_weekly_df(), room_df=_room_df())

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        session_mgr = SessionManager(base_dir=tmpdir)
        shadow_path = os.path.join(loader.shadow_dirs[0], "rooms.json")
        with open(shadow_path, "w", encoding="utf-8") as handle:
            json.dump([{"id": "SHADOW-NEWER"}], handle)
        future = time.time() + 60
        os.utime(shadow_path, (future, future))

        with pytest.raises(RuntimeError, match="Master-data sync failed for: rooms"):
            process_scheduler_upload(
                loader,
                session_mgr,
                {},
                upload_slot="weekly",
                file_name="shadow.xlsx",
                file_bytes=workbook_bytes,
                require_atomic_success=True,
            )

        assert loader.get_last_io_metadata("rooms.json")["selected_path"] == shadow_path


def test_process_scheduler_upload_syncs_students_and_replaces_digest_when_workbook_changes():
    workbook_v1 = _make_workbook_bytes(weekly_df=_weekly_df(), student_df=_student_df())
    weekly_v2 = _weekly_df().copy()
    weekly_v2.loc[0, "Student Name"] = "Student 0001 Updated"
    workbook_v2 = _make_workbook_bytes(weekly_df=weekly_v2, student_df=_student_df())

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        session_mgr = SessionManager(base_dir=tmpdir)
        state = {}

        process_scheduler_upload(
            loader,
            session_mgr,
            state,
            upload_slot="weekly",
            file_name="students.xlsx",
            file_bytes=workbook_v1,
        )
        digest_v1 = state[SCHEDULER_PROVENANCE_KEY]["uploads"]["weekly"]["digest"]

        process_scheduler_upload(
            loader,
            session_mgr,
            state,
            upload_slot="weekly",
            file_name="students.xlsx",
            file_bytes=workbook_v2,
        )
        digest_v2 = state[SCHEDULER_PROVENANCE_KEY]["uploads"]["weekly"]["digest"]

        assert digest_v2 != digest_v1
        assert state["wk_df"].iloc[0]["Student Name"] == "Student 0001 Updated"
        assert state[SCHEDULER_PROVENANCE_KEY]["master_data_sync"]["students"]["status"] == "synced"


def test_process_scheduler_upload_records_shadow_save_and_verifies_readback(monkeypatch):
    workbook_bytes = _make_workbook_bytes(weekly_df=_weekly_df(), room_df=_room_df())

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        session_mgr = SessionManager(base_dir=tmpdir)
        state = {}
        original_atomic_save = loader._atomic_save
        primary_rooms_path = f"{loader.base_dir}/rooms.json"

        def flaky_atomic_save(path, data):
            if path == primary_rooms_path:
                raise PermissionError("primary locked")
            return original_atomic_save(path, data)

        monkeypatch.setattr(loader, "_atomic_save", flaky_atomic_save)

        process_scheduler_upload(
            loader,
            session_mgr,
            state,
            upload_slot="weekly",
            file_name="shadow.xlsx",
            file_bytes=workbook_bytes,
        )

        rooms_sync = state[SCHEDULER_PROVENANCE_KEY]["master_data_sync"]["rooms"]
        assert rooms_sync["status"] == "synced"
        assert rooms_sync["save_source"] == "shadow"
        assert rooms_sync["verified"] is True
        assert rooms_sync["save_target_path"].endswith("rooms.json")
        assert any("Primary save failed" in item for item in rooms_sync["warnings"])


def test_process_scheduler_upload_records_session_cache_shadow_warning(monkeypatch):
    workbook_bytes = _make_workbook_bytes(weekly_df=_weekly_df(), room_df=_room_df())

    with tempfile.TemporaryDirectory() as tmpdir:
        loader = DataLoader(base_dir=tmpdir)
        session_mgr = SessionManager(base_dir=tmpdir)
        state = {}

        original_save_session = session_mgr.save_session

        def shadowed_save_session(payload, expected_mtime=None):
            original_save_session(payload, expected_mtime=expected_mtime)
            return SaveOutcome(
                status="shadow",
                path="/tmp/shadow/session_cache.json",
                warning="Primary session cache save failed; wrote fallback shadow copy.",
            )

        monkeypatch.setattr(session_mgr, "save_session", shadowed_save_session)

        process_scheduler_upload(
            loader,
            session_mgr,
            state,
            upload_slot="weekly",
            file_name="shadow-session.xlsx",
            file_bytes=workbook_bytes,
        )

        assert state[SCHEDULER_SAVE_WARNING_KEY] == "Primary session cache save failed; wrote fallback shadow copy."


def test_collector_picks_up_all_step1_warnings():
    """collect_scheduler_warning_messages() aggregates warnings written to state keys
    by both provenance sync and SCHEDULER_SAVE_WARNING_KEY."""
    from modules.scheduler.logic.session_state import collect_scheduler_warning_messages

    state = {
        SCHEDULER_PROVENANCE_KEY: {
            "master_data_sync": {
                "rooms": {
                    "warnings": [
                        "Primary save failed for rooms.json; wrote fallback shadow copy.",
                    ]
                }
            }
        },
        SCHEDULER_SAVE_WARNING_KEY: "Primary session cache save failed; wrote fallback shadow copy.",
    }
    messages = collect_scheduler_warning_messages(state)
    assert "Primary save failed for rooms.json; wrote fallback shadow copy." in messages
    assert "Primary session cache save failed; wrote fallback shadow copy." in messages
