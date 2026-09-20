import io
import tempfile

import pandas as pd

from modules.scheduler.context import build_scheduler_context
from modules.scheduler.logic.preflight import collect_optimizer_preflight
from modules.scheduler.logic.provenance import SCHEDULER_PROVENANCE_KEY, build_step3_provenance_status
from modules.scheduler.logic.upload_workbook_service import process_scheduler_upload


def _make_regression_workbook():
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
            }
        ]
    )
    studio_df = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "13:00-14:00",
                "Preferred Venue": "R103",
            }
        ]
    )
    room_df = pd.DataFrame(
        [
            {
                "Room Number": "R103",
                "Piano Specifications": "Yamaha upright piano",
            }
        ]
    )
    student_df = pd.DataFrame(
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

    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        weekly_df.to_excel(writer, sheet_name="Weekly Schedule", index=False)
        studio_df.to_excel(writer, sheet_name="Studio Schedule", index=False)
        room_df.to_excel(writer, sheet_name="Room", index=False)
        student_df.to_excel(writer, sheet_name="Student Info", index=False)
    return payload.getvalue()


def test_generated_workbook_auto_sync_and_optimize_path_produces_assignments():
    workbook_bytes = _make_regression_workbook()

    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=tmpdir)
        state = {}

        process_scheduler_upload(
            context.loader,
            context.session_manager,
            state,
            upload_slot="weekly",
            file_name="regression.xlsx",
            file_bytes=workbook_bytes,
        )
        process_scheduler_upload(
            context.loader,
            context.session_manager,
            state,
            upload_slot="studio",
            file_name="regression.xlsx",
            file_bytes=workbook_bytes,
        )
        context.save_rules(context.default_rules)

        preflight = collect_optimizer_preflight(context.loader, default_rules=context.default_rules)
        assert preflight["is_blocked"] is False
        assert state[SCHEDULER_PROVENANCE_KEY]["master_data_sync"]["rooms"]["verified"] is True

        students = context.loader.get_data("students.json")
        rooms = context.loader.get_data("rooms.json")
        optimizer = context.make_optimizer(students, rooms, [], rules=context.load_rules())
        assignments, duplicates, _logs = optimizer.optimize(state["wk_df"], state["stu_df"])

        assert duplicates == []
        assert len(assignments) > 0


def test_provenance_status_warns_when_active_upload_drift_is_introduced():
    workbook_bytes = _make_regression_workbook()

    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=tmpdir)
        state = {}

        process_scheduler_upload(
            context.loader,
            context.session_manager,
            state,
            upload_slot="weekly",
            file_name="regression.xlsx",
            file_bytes=workbook_bytes,
        )

        provenance = state[SCHEDULER_PROVENANCE_KEY]
        provenance["uploads"]["weekly"]["digest"] = "changed-digest"
        status = build_step3_provenance_status(provenance, context.load_rules())

        assert any("does not match the active upload digest" in item for item in status["warnings"])
