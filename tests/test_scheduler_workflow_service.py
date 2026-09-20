"""TDD for extracted scheduler workflow helpers."""

import copy

from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY
from modules.scheduler.logic.workflow_service import (
    build_locked_context,
    build_manual_assignment_from_failed,
    promote_failed_assignment,
    repair_unassigned_metadata,
)


def test_build_locked_context_includes_committed_and_non_scheduler_items():
    bookings = [
        {"id": "legacy_weekly", "type": "weekly_lesson", "committed": True},
        {"id": "open_weekly", "type": "weekly_lesson"},
        {"id": "legacy_studio", "type": "studio_class", "committed": True},
        {"id": "lecture_1", "type": "lecture"},
        {"id": "other_1", "type": "jury_hold"},
    ]

    locked = build_locked_context(bookings)
    locked_ids = {evt["id"] for evt in locked}

    assert locked_ids == {"legacy_weekly", "legacy_studio", "lecture_1", "other_1"}


def test_build_manual_assignment_from_failed_preserves_current_shape():
    raw = {
        "source_request_id": "weekly:0",
        "Student Name": "Student 0001",
        "Instrument": "Violin",
        "Instructor": "Dr. V",
        "Student No": "S100",
        "Study Year": "1",
        "Course Code": "MUS101 (Violin)",
    }

    evt = build_manual_assignment_from_failed(
        raw=raw,
        requested_time="Mon 10:00-11:00",
        room="R101",
        detected_day=1,
    )

    assert evt["resourceId"] == "R101"
    assert evt["daysOfWeek"] == [1]
    assert evt["type"] == "weekly_lesson"
    assert evt["startTime"] == "10:00:00"
    assert evt["endTime"] == "11:00:00"
    assert evt["extendedProps"]["Student Name"] == "Student 0001"
    assert evt["extendedProps"]["Instructor"] == "Dr. V"


def test_build_manual_assignment_from_failed_detects_studio_rows():
    raw = {
        "source_request_id": "studio:0:1:0",
        "Student Name": "Studio Class",
        "Instrument": "Voice",
        "Instructor": "Instructor 0004",
        "Course Code": "STU_CLASS",
    }

    evt = build_manual_assignment_from_failed(
        raw=raw,
        requested_time="Wed 19:00-20:00",
        room="R102",
        detected_day=3,
    )

    assert evt["type"] == "studio_class"


class DummySessionManager:
    def __init__(self):
        self.saved = None
        self.calls = 0

    def save_session(self, payload):
        self.calls += 1
        self.saved = payload


def test_promote_failed_assignment_updates_edit_session_and_persists_copy():
    session_mgr = DummySessionManager()
    original_generated = [{"id": "wk_existing", "resourceId": "R1", "extendedProps": {}}]
    original_unassigned = [
        {"id": "u1", "student": "Student 0001"},
        {"id": "u2", "student": "Student 0002"},
    ]
    state = {
        "generated_assignments": copy.deepcopy(original_generated),
        "unassigned_lessons": copy.deepcopy(original_unassigned),
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }
    new_evt = {
        "id": "manual_1",
        "resourceId": "R101",
        "type": "weekly_lesson",
        "extendedProps": {"Student Name": "Student 0002"},
    }

    result = promote_failed_assignment(
        session_mgr=session_mgr,
        state=state,
        failed_index=1,
        new_event=new_evt,
    )

    assert result["generated_assignments"][-1]["id"] == "manual_1"
    assert [row["id"] for row in result["unassigned_lessons"]] == ["u1"]
    # Root keys should remain unchanged; edit_session is the sole mutation target
    assert state["generated_assignments"] == original_generated
    assert state["unassigned_lessons"] == original_unassigned
    edit_session = state["step4_edit_session"]
    assert edit_session["assignments"] is result["generated_assignments"]
    assert edit_session["unassigned_lessons"] is result["unassigned_lessons"]
    assert "generated_assignments" not in session_mgr.saved
    assert "unassigned_lessons" not in session_mgr.saved
    assert session_mgr.saved["step4_edit_session"]["assignments"][-1]["id"] == "manual_1"


def test_promote_failed_assignment_out_of_range_leaves_state_and_session_untouched():
    session_mgr = DummySessionManager()
    original_generated = [{"id": "wk_existing", "resourceId": "R1", "extendedProps": {}}]
    original_unassigned = [{"id": "u1", "student": "Student 0001"}]
    state = {
        "generated_assignments": copy.deepcopy(original_generated),
        "unassigned_lessons": copy.deepcopy(original_unassigned),
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    try:
        promote_failed_assignment(
            session_mgr=session_mgr,
            state=state,
            failed_index=3,
            new_event={"id": "manual_bad"},
        )
        raise AssertionError("expected IndexError")
    except IndexError:
        pass

    assert state["generated_assignments"] == original_generated
    assert state["unassigned_lessons"] == original_unassigned
    assert session_mgr.calls == 0
    assert session_mgr.saved is None


def test_repair_unassigned_metadata_uses_extended_props_and_persists_copy():
    session_mgr = DummySessionManager()
    original_unassigned = [
        {
            "id": "u1",
            "raw_row": {"Instrument": "Studio/Unknown", "Course Code": "MUS101 (Violin)"},
            "extendedProps": {"normalized_instrument": "Violin"},
        }
    ]
    state = {
        "generated_assignments": [],
        "unassigned_lessons": copy.deepcopy(original_unassigned),
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    result = repair_unassigned_metadata(session_mgr=session_mgr, state=state)

    assert result["repaired"] is True
    assert result["unassigned_lessons"][0]["raw_row"]["Instrument"] == "Violin"
    # Root keys unchanged; edit_session holds the repaired data
    assert state["unassigned_lessons"] == original_unassigned
    edit_session = state["step4_edit_session"]
    assert edit_session["unassigned_lessons"] is result["unassigned_lessons"]
    assert edit_session["unassigned_lessons"] is not original_unassigned
    assert session_mgr.calls == 1
    assert "unassigned_lessons" not in session_mgr.saved
    assert session_mgr.saved["step4_edit_session"]["unassigned_lessons"][0]["raw_row"]["Instrument"] == "Violin"


def test_repair_unassigned_metadata_falls_back_to_course_code():
    session_mgr = DummySessionManager()
    state = {
        "generated_assignments": [],
        "unassigned_lessons": [
            {
                "id": "u1",
                "raw_row": {"Instrument": "?", "Course Code": "MUS4153 - Demo Instruction VIII (Piano)"},
                "extendedProps": {},
            }
        ],
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    result = repair_unassigned_metadata(session_mgr=session_mgr, state=state)

    assert result["repaired"] is True
    assert result["unassigned_lessons"][0]["raw_row"]["Instrument"] == "Piano"
    # Root key unchanged; repair lives in edit_session
    assert state["unassigned_lessons"][0]["raw_row"]["Instrument"] == "?"
    assert session_mgr.calls == 1


def test_repair_unassigned_metadata_skips_persist_when_nothing_changes():
    session_mgr = DummySessionManager()
    original_unassigned = [{"id": "u1", "raw_row": {"Instrument": "Piano"}, "extendedProps": {}}]
    state = {
        "generated_assignments": [],
        "unassigned_lessons": copy.deepcopy(original_unassigned),
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    result = repair_unassigned_metadata(session_mgr=session_mgr, state=state)

    assert result["repaired"] is False
    assert result["unassigned_lessons"] == original_unassigned
    assert session_mgr.calls == 0


def test_repair_unassigned_metadata_persists_when_creating_missing_raw_row():
    session_mgr = DummySessionManager()
    state = {
        "generated_assignments": [],
        "unassigned_lessons": [{"id": "u1", "extendedProps": {}}],
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    result = repair_unassigned_metadata(session_mgr=session_mgr, state=state)

    assert result["unassigned_lessons"][0]["raw_row"] == {}
    assert session_mgr.calls == 1
    assert "unassigned_lessons" not in session_mgr.saved
    assert session_mgr.saved[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"][0]["raw_row"] == {}
