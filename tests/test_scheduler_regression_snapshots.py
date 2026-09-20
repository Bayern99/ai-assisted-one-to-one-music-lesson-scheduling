import tempfile
from pathlib import Path

from modules.scheduler.logic.workflow_service import (
    build_manual_assignment_from_failed,
    promote_failed_assignment,
)
from tests.scheduling_non_rule_harness import (
    commit_current_round,
    export_current_state,
    restore_scheduler_state,
    run_step3_optimize,
    summarize_export_dataframe,
    summarize_optimizer_state,
)
from tests.test_scheduling_non_rule_harness import (
    _fixture_json,
    _rooms_fixture,
    _students_fixture,
    _studio_df,
    _test_loader_and_session,
    _weekly_df,
)


def test_optimizer_harness_snapshot_stays_stable_for_duplicate_plus_studio_fixture():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)

        state = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")),
            _studio_df(_fixture_json("studio_upload.json")),
            students=_students_fixture(),
            rooms=_rooms_fixture(),
            rules=_fixture_json("rules_shadow.json"),
        )

        assert summarize_optimizer_state(state) == {
            "assignments": 1,
            "duplicates": 1,
            "rooms": {"R101": 1},
            "types": {"weekly_lesson": 1},
            "reasons": {
                "duplicate_student": 1,
                "no_room_type_match": 1,
            },
            "studio_summary": "✅ Scheduled 0/1 Studio Classes.",
        }


def test_step4_promote_then_commit_keeps_export_summary_stable():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)

        state = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")),
            _studio_df(_fixture_json("studio_upload.json")),
            students=_students_fixture(),
            rooms=_rooms_fixture(),
            rules=_fixture_json("rules_shadow.json"),
        )

        promoted_event = build_manual_assignment_from_failed(
            raw=state["unassigned_lessons"][0]["raw_row"],
            requested_time="Monday 10:00-11:00",
            room="R101",
            detected_day=1,
        )
        promote_failed_assignment(
            session_mgr=session_mgr,
            state=state,
            failed_index=0,
            new_event=promoted_event,
        )
        commit_current_round(loader, session_mgr, state)
        restored = restore_scheduler_state(session_mgr)

        export_df = export_current_state(
            loader,
            restored,
            students=_students_fixture(),
            valid_instructors=["Instructor 0004", "Instructor 0001"],
        )

        assert summarize_export_dataframe(export_df) == {
            "rows": 3,
            "rooms": ["R101", "Unassigned"],
            "event_types": {
                "Studio Class": 1,
                "Weekly Lesson": 2,
            },
            "students": ["Student 0001", "Student 0001 Duplicate", "Studio Class"],
            "unassigned_students": ["Studio Class"],
        }

        promoted_row = export_df[export_df["Student Name (EN)"] == "Student 0001 Duplicate"].iloc[0]
        assert promoted_row["Room"] == "R101"
        assert promoted_row["Time"] == "10:00 - 11:00"


def test_scheduler_application_services_do_not_write_bookings_directly():
    service_sources = (
        Path("modules/api/services/scheduler.py"),
        Path("modules/api/services/scheduler_resolution.py"),
        Path("modules/api/services/scheduler_configuration.py"),
    )

    for path in service_sources:
        source = path.read_text(encoding="utf-8")
        assert "save_bookings(" not in source
        assert 'save_data("bookings.json"' not in source
        assert "save_data('bookings.json'" not in source
