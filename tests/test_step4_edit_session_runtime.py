import copy
from pathlib import Path

from modules.scheduler.logic.step4_service import build_step4_runtime
from modules.scheduler.logic.workflow_service import commit_current_round, promote_failed_assignment
from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY


class DummyLoader:
    def __init__(self):
        self.saved_bookings = None
        self.load_rooms_calls = 0

    def load_bookings(self):
        return []

    def load_rooms(self):
        self.load_rooms_calls += 1
        return [{"id": "R101"}, {"id": ""}, {"id": "R105"}]

    def save_bookings(self, payload):
        self.saved_bookings = payload


class DummySessionManager:
    def __init__(self):
        self.saved = None

    def save_session(self, payload):
        self.saved = payload


class DummyContext:
    def __init__(self):
        self.loader = DummyLoader()
        self.session_manager = DummySessionManager()

    def load_rules(self):
        return {}


def test_build_step4_runtime_bootstraps_working_copy_without_sharing_root_lists():
    context = DummyContext()
    original_assignments = [
        {
            "id": "wk_1",
            "resourceId": "R101",
            "daysOfWeek": [1],
            "startTime": "14:00:00",
            "endTime": "15:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001"},
        }
    ]
    state = {
        "generated_assignments": copy.deepcopy(original_assignments),
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
    }

    runtime = build_step4_runtime(context, state)

    assert STEP4_EDIT_SESSION_KEY in state
    assert runtime.draft_controller.edit_session["assignments"] is state[STEP4_EDIT_SESSION_KEY]["assignments"]
    assert runtime.draft_controller.edit_session["assignments"] is not state["generated_assignments"]
    assert runtime.draft_controller.edit_session["assignments"] == original_assignments


def test_build_step4_runtime_controller_owns_history_and_redo_lists():
    context = DummyContext()
    state = {
        "generated_assignments": [],
        "unassigned_lessons": [],
        "override_history": [{"action": "seed"}],
        "redo_stack": [{"action": "seed_redo"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [],
            "unassigned_lessons": [],
            "history": [{"action": "seed"}],
            "redo_stack": [{"action": "seed_redo"}],
            "dirty": False,
            "last_save_outcome": None,
        },
    }

    runtime = build_step4_runtime(context, state)
    state[STEP4_EDIT_SESSION_KEY]["history"].append({"action": "external_mutation"})
    state[STEP4_EDIT_SESSION_KEY]["redo_stack"].append({"action": "external_redo_mutation"})

    assert runtime.draft_controller.history_count == 1
    assert runtime.draft_controller.redo_count == 1


def test_build_step4_runtime_loads_rooms_once_and_reuses_filtered_cache():
    context = DummyContext()
    state = {
        "generated_assignments": [],
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
    }

    runtime = build_step4_runtime(context, state)

    assert context.loader.load_rooms_calls == 1
    assert runtime.rooms_cache == [{"id": "R101"}, {"id": "R105"}]


def test_build_step4_runtime_prefers_manual_override_primitives_over_legacy_adapter():
    source = Path("modules/scheduler/logic/step4_service.py").read_text(encoding="utf-8")

    assert "manual_override_primitives" in source
    assert "ManualOverrider(" not in source


def test_build_step4_runtime_controller_reclaims_assignments_and_unassigned_from_external_mutation():
    context = DummyContext()
    state = {
        "generated_assignments": [
            {
                "id": "wk_1",
                "resourceId": "R101",
                "daysOfWeek": [1],
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "type": "weekly_lesson",
                "extendedProps": {"Instructor": "Instructor 0001"},
            }
        ],
        "unassigned_lessons": [{"id": "u1", "type": "weekly_lesson"}],
        "override_history": [],
        "redo_stack": [],
    }

    runtime = build_step4_runtime(context, state)
    state[STEP4_EDIT_SESSION_KEY]["assignments"].append({"id": "rogue_evt", "resourceId": "CC999"})
    state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"].append({"id": "rogue_unassigned"})

    runtime.draft_controller.move(state, "wk_1", "R105", 1, "14:00:00", "15:00:00")

    assignment_ids = [item["id"] for item in state[STEP4_EDIT_SESSION_KEY]["assignments"]]
    unassigned_ids = [item["id"] for item in state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"]]
    assert assignment_ids == ["wk_1"]
    assert unassigned_ids == ["u1"]


def test_controller_move_updates_working_copy_but_not_root_scheduler_assignments():
    context = DummyContext()
    state = {
        "generated_assignments": [
            {
                "id": "wk_1",
                "resourceId": "R101",
                "daysOfWeek": [1],
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "type": "weekly_lesson",
                "extendedProps": {"Instructor": "Instructor 0001"},
            }
        ],
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
    }
    runtime = build_step4_runtime(context, state)

    result = runtime.draft_controller.move(
        state,
        "wk_1",
        "R105",
        3,
        "14:00:00",
        "15:00:00",
        teacher_confirmed=True,
        confirmation_note="Teacher approved Wednesday block",
    )

    assert result.success is True
    assert state["generated_assignments"][0]["resourceId"] == "R101"
    assert state["generated_assignments"][0]["daysOfWeek"] == [1]
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R105"
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["daysOfWeek"] == [3]
    confirmation = state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["extendedProps"][
        "teacher_time_change_confirmation"
    ]
    assert confirmation["instructor"] == "Instructor 0001"
    assert confirmation["note"] == "Teacher approved Wednesday block"
    assert runtime.draft_controller.history_count == 1
    assert runtime.draft_controller.redo_count == 0
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True


def test_controller_undo_updates_history_and_redo_without_touching_committed_root():
    context = DummyContext()
    state = {
        "generated_assignments": [
            {
                "id": "wk_1",
                "resourceId": "R101",
                "daysOfWeek": [1],
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "type": "weekly_lesson",
                "extendedProps": {"Instructor": "Instructor 0001"},
            }
        ],
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
    }
    runtime = build_step4_runtime(context, state)

    move_result = runtime.draft_controller.move(state, "wk_1", "R105", 1, "14:00:00", "15:00:00")
    undo_result = runtime.draft_controller.undo(state)

    assert move_result.success is True
    assert undo_result.success is True
    assert state["generated_assignments"][0]["resourceId"] == "R101"
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R101"
    assert runtime.draft_controller.history_count == 0
    assert runtime.draft_controller.redo_count == 1
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True


def test_controller_redo_restores_moved_state_and_clears_redo_on_new_action():
    context = DummyContext()
    state = {
        "generated_assignments": [
            {
                "id": "wk_1",
                "resourceId": "R101",
                "daysOfWeek": [1],
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "type": "weekly_lesson",
                "extendedProps": {"Instructor": "Instructor 0001"},
            }
        ],
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
    }
    runtime = build_step4_runtime(context, state)

    runtime.draft_controller.move(state, "wk_1", "R105", 1, "14:00:00", "15:00:00")
    runtime.draft_controller.undo(state)
    redo_result = runtime.draft_controller.redo(state)

    assert redo_result.success is True
    assert state["generated_assignments"][0]["resourceId"] == "R101"
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R105"
    assert runtime.draft_controller.history_count == 1
    assert runtime.draft_controller.redo_count == 0

    runtime.draft_controller.undo(state)
    runtime.draft_controller.move(state, "wk_1", "R105", 1, "14:00:00", "15:00:00")
    assert runtime.draft_controller.redo_count == 0


def test_promote_failed_assignment_only_mutates_working_copy_until_commit():
    session_mgr = DummySessionManager()
    state = {
        "generated_assignments": [],
        "unassigned_lessons": [{"id": "u1", "student": "Student 0001"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [],
            "unassigned_lessons": [{"id": "u1", "student": "Student 0001"}],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    promote_failed_assignment(
        session_mgr=session_mgr,
        state=state,
        failed_index=0,
        new_event={"id": "manual_1", "extendedProps": {}},
    )

    assert state["generated_assignments"] == []
    assert state["unassigned_lessons"] == [{"id": "u1", "student": "Student 0001"}]
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["id"] == "manual_1"
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []


def test_commit_current_round_promotes_working_copy_into_edit_session_and_bookings():
    loader = DummyLoader()
    session_mgr = DummySessionManager()
    state = {
        "generated_assignments": [{"id": "old_evt", "type": "weekly_lesson", "resourceId": "R1", "extendedProps": {}}],
        "unassigned_lessons": [{"id": "old_failed"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt", "type": "weekly_lesson", "resourceId": "R2", "extendedProps": {}}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    final = commit_current_round(loader, session_mgr, state)

    assert [evt["id"] for evt in final] == ["draft_evt"]
    # Root keys should remain unchanged after commit; edit_session is the committed state
    assert [evt["id"] for evt in state["generated_assignments"]] == ["old_evt"]
    assert [evt["id"] for evt in state["unassigned_lessons"]] == ["old_failed"]
    # edit_session should reflect the committed state with dirty cleared
    edit_session = state[STEP4_EDIT_SESSION_KEY]
    assert [evt["id"] for evt in edit_session["assignments"]] == ["draft_evt"]
    assert [evt["id"] for evt in edit_session["unassigned_lessons"]] == ["draft_failed"]
    assert edit_session["dirty"] is False
    assert state["round_committed"] is True


def test_commit_current_round_failure_leaves_all_state_unchanged():
    class FailingLoader(DummyLoader):
        def save_bookings(self, payload):
            raise OSError("disk full")

    loader = FailingLoader()
    session_mgr = DummySessionManager()
    state = {
        "generated_assignments": [{"id": "old_evt", "type": "weekly_lesson", "resourceId": "R1", "extendedProps": {}}],
        "unassigned_lessons": [{"id": "old_failed"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt", "type": "weekly_lesson", "resourceId": "R2", "extendedProps": {}}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
    }

    try:
        commit_current_round(loader, session_mgr, state)
        raise AssertionError("expected OSError")
    except OSError:
        pass

    # Root keys never touched by commit
    assert [evt["id"] for evt in state["generated_assignments"]] == ["old_evt"]
    assert [evt["id"] for evt in state["unassigned_lessons"]] == ["old_failed"]
    # Draft remains intact after failed commit
    assert [evt["id"] for evt in state[STEP4_EDIT_SESSION_KEY]["assignments"]] == ["draft_evt"]
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True
    assert state["round_committed"] is False
