import copy
from types import SimpleNamespace

import pytest

from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY
from modules.scheduler.logic import step4_service as _editor_service
from modules.shared.save_outcome import SaveOutcome


class DummySessionManager:
    def __init__(self):
        self.saved = None
        self.calls = 0

    def save_session(self, payload, **kwargs):
        self.calls += 1
        self.saved = payload
        return None


class OutcomeSessionManager(DummySessionManager):
    def __init__(self, outcome):
        super().__init__()
        self.outcome = outcome

    def save_session(self, payload, **kwargs):
        super().save_session(payload, **kwargs)
        return self.outcome


class OverriderStub:
    def __init__(self, *, undo_result=True, unlock_result=True, unassign_result=True, move_result=None):
        self.undo_result = undo_result
        self.unlock_result = unlock_result
        self.unassign_result = unassign_result
        self.move_result = move_result or {"success": True, "message": ""}
        self.calls = []

    def undo(self):
        self.calls.append(("undo",))
        return self.undo_result

    def unlock_slot(self, event_id):
        self.calls.append(("unlock", event_id))
        return self.unlock_result

    def unassign_slot(self, event_id):
        self.calls.append(("unassign", event_id))
        return self.unassign_result

    def move_slot(self, event_id, new_room, day, new_start, new_end):
        self.calls.append(("move", event_id, new_room, day, new_start, new_end))
        return self.move_result

    def find_slot(self, assignments, event_id):
        self.calls.append(("find_slot", event_id))
        return next((item for item in assignments if item["id"] == event_id), None)

    def validate_move(
        self,
        slot,
        new_room,
        day,
        new_start,
        new_end,
        *,
        teacher_confirmed=None,
    ):
        del teacher_confirmed
        self.calls.append(("validate_move", slot["id"], new_room, day, new_start, new_end))
        if not self.move_result["success"]:
            return {"success": False, "message": self.move_result["message"]}
        return {
            "success": True,
            "start_norm": "14:00",
            "end_norm": "15:00",
            "specific_date": None,
            "warnings": self.move_result.get("warnings", []),
        }

    def apply_move(self, slot, new_room, day, start_norm, end_norm, specific_date=None):
        self.calls.append(("apply_move", slot["id"], new_room, day, start_norm, end_norm, specific_date))
        slot["resourceId"] = new_room
        slot["room_id"] = new_room
        slot["daysOfWeek"] = [day]
        slot["startTime"] = f"{start_norm}:00"
        slot["endTime"] = f"{end_norm}:00"
        slot["pinned"] = True
        return {"id": slot["id"], "resourceId": new_room}

    def enrich_unassigned_slot(self, slot):
        self.calls.append(("enrich_unassigned", slot["id"]))
        slot.setdefault("raw_row", {})
        return slot

    def apply_unassign(self, assignments, unassigned, slot):
        self.calls.append(("apply_unassign", slot["id"]))
        assignments.remove(slot)
        self.enrich_unassigned_slot(slot)
        unassigned.append(slot)
        return {"id": slot["id"]}

    def revert_record(self, assignments, unassigned, record):
        self.calls.append(("revert_record", record["action"], record["slot_id"]))
        if record["action"] == "move":
            target = next(item for item in assignments if item["id"] == record["slot_id"])
            target.update(record["prev_state"])
        elif record["action"] == "unassign":
            target = next(item for item in unassigned if item["id"] == record["slot_id"])
            unassigned.remove(target)
            target.update(record["prev_state"])
            assignments.append(target)

    def replay_record(self, assignments, unassigned, record):
        self.calls.append(("replay_record", record["action"], record["slot_id"]))
        if record["action"] == "move":
            target = next(item for item in assignments if item["id"] == record["slot_id"])
            target.update(record["new_state"])
        elif record["action"] == "unassign":
            target = next(item for item in assignments if item["id"] == record["slot_id"])
            assignments.remove(target)
            target.update(record["new_state"])
            unassigned.append(target)


class ValidatorStub:
    def __init__(self, conflict=None, rooms=None):
        self.conflict = conflict
        self.calls = []
        if rooms is not None:
            self.rooms = rooms

    def check_conflict(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.conflict


def _state():
    return {
        "generated_assignments": [],
        "unassigned_lessons": [{"id": "u1", "type": "weekly_lesson"}],
        "override_history": [],
        "redo_stack": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [],
            "unassigned_lessons": [{"id": "u1", "type": "weekly_lesson"}],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
    }


class PrimitiveOnlyOverriderStub(OverriderStub):
    def undo(self):
        raise AssertionError("controller should not call overrider.undo")

    def redo(self):
        raise AssertionError("controller should not call overrider.redo")

    def move_slot(self, event_id, new_room, day, new_start, new_end):
        raise AssertionError("controller should not call overrider.move_slot")

    def unassign_slot(self, event_id):
        raise AssertionError("controller should not call overrider.unassign_slot")


def test_apply_undo_action_persists_draft_on_success():
    session_mgr = DummySessionManager()
    state = _state()
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(undo_result=True),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    runtime = SimpleNamespace(session_mgr=session_mgr, draft_controller=controller)
    controller._assignments = [{"id": "wk_1"}]
    controller._history.append({
        "action": "move",
        "slot_id": "wk_1",
        "prev_state": {"id": "wk_1", "resourceId": "R101"},
        "new_state": {"id": "wk_1", "resourceId": "R105"},
    })

    result = runtime.draft_controller.undo(state)

    assert result.status == "success"
    assert result.message == "Undone!"
    assert result.draft_dirty is True
    assert session_mgr.calls == 1
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True


def test_step4_draft_controller_exposes_undo_state_without_ui_touching_overrider():
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["history"] = [{"action": "move"}]
    state[STEP4_EDIT_SESSION_KEY]["redo_stack"] = [{"action": "undo"}]
    controller = _editor_service.Step4DraftController(
        session_mgr=DummySessionManager(),
        validator=ValidatorStub(),
        overrider=OverriderStub(),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    assert controller.can_undo is True
    assert controller.history_count == 1
    assert controller.can_redo is True
    assert controller.redo_count == 1


def test_step4_draft_controller_redo_persists_draft_on_success():
    state = _state()
    session_mgr = DummySessionManager()

    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    controller._assignments = [{"id": "wk_1", "resourceId": "R101"}]
    controller._redo_stack = [{
        "action": "move",
        "slot_id": "wk_1",
        "prev_state": {"id": "wk_1", "resourceId": "R101"},
        "new_state": {"id": "wk_1", "resourceId": "R105"},
    }]

    result = controller.redo(state)

    assert result.status == "success"
    assert result.message == "Redone!"
    assert result.draft_dirty is True
    assert session_mgr.calls == 1
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True


def test_apply_move_action_returns_failure_without_persisting():
    session_mgr = DummySessionManager()
    state = _state()
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": False, "message": "Conflict"}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    runtime = SimpleNamespace(session_mgr=session_mgr, draft_controller=controller)
    controller._assignments = [{"id": "wk_1", "resourceId": "R101"}]

    result = runtime.draft_controller.move(
        state,
        "wk_1",
        "R105",
        1,
        "14:00:00",
        "15:00:00",
    )

    assert result.status == "failed"
    assert result.message == "Conflict"
    assert result.draft_dirty is False
    assert session_mgr.calls == 0
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is False


def test_apply_move_action_returns_room_type_warnings():
    session_mgr = DummySessionManager()
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [{"id": "wk_1", "resourceId": "R101"}]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(
            move_result={"success": True, "warnings": ["Room Type Mismatch"]}
        ),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    result = controller.move(state, "wk_1", "R105", 3, "14:00:00", "15:00:00")

    assert result.success is True
    assert result.warnings == ["Room Type Mismatch"]
    assert session_mgr.calls == 1


def test_move_exposes_single_persistence_outcome_to_command_adapter():
    outcome = SaveOutcome(
        status="shadow",
        path="/tmp/session-shadow.json",
        warning="Saved to shadow",
    )
    session_mgr = OutcomeSessionManager(outcome)
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [
        {"id": "wk_1", "resourceId": "R101"}
    ]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": True}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    result = controller.move(
        state,
        "wk_1",
        "R105",
        3,
        "14:00:00",
        "15:00:00",
    )

    assert result.persistence_outcome is outcome
    assert result.warnings == ["Saved to shadow"]
    assert session_mgr.calls == 1


def test_persistence_conflict_is_not_controller_success():
    outcome = SaveOutcome(
        status="conflict",
        path="/tmp/session.json",
        warning="Session changed before save",
    )
    session_mgr = OutcomeSessionManager(outcome)
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [
        {"id": "wk_1", "resourceId": "R101"}
    ]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": True}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    result = controller.move(
        state,
        "wk_1",
        "R105",
        3,
        "14:00:00",
        "15:00:00",
    )

    assert result.success is False
    assert result.status == "conflict"
    assert result.message == "Session changed before save"
    assert result.persistence_outcome is outcome
    assert session_mgr.calls == 1


@pytest.mark.parametrize("action", ["move", "unassign", "unlock", "undo", "redo", "assign_failed"])
def test_persistence_conflict_rolls_back_mutating_action_runtime_state(action):
    outcome = SaveOutcome(
        status="conflict",
        path="/tmp/session.json",
        warning="Session changed before save",
    )
    session_mgr = OutcomeSessionManager(outcome)
    state = _state()
    move_record = {
        "action": "move",
        "slot_id": "wk_1",
        "prev_state": {"id": "wk_1", "resourceId": "R103", "pinned": True},
        "new_state": {"id": "wk_1", "resourceId": "R101", "pinned": True},
    }
    redo_record = {
        "action": "move",
        "slot_id": "wk_1",
        "prev_state": {"id": "wk_1", "resourceId": "R101", "pinned": True},
        "new_state": {"id": "wk_1", "resourceId": "R105", "pinned": True},
    }
    state[STEP4_EDIT_SESSION_KEY].update({
        "assignments": [{"id": "wk_1", "resourceId": "R101", "pinned": True}],
        "history": [move_record],
        "redo_stack": [redo_record],
        "dirty": False,
        "last_save_outcome": {"status": "shadow", "path": "/tmp/shadow.json"},
        "issues": ["existing issue"],
    })
    state["scheduler_save_warning"] = "Existing warning"
    state["scheduler_session_mtime"] = 123.0
    state["_scheduler_snapshot_df_cache"] = {"wk_df": [{"existing": True}]}
    validator = ValidatorStub()
    validator.assignments = []
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=validator,
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": True}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[{"id": "locked_1"}],
        booked_lectures=[],
        normalized_rules={},
    )
    before_state = copy.deepcopy(state)
    before_controller = {
        "assignments": copy.deepcopy(controller._assignments),
        "unassigned_lessons": copy.deepcopy(controller._unassigned_lessons),
        "history": copy.deepcopy(controller._history),
        "redo_stack": copy.deepcopy(controller._redo_stack),
        "validator_assignments": copy.deepcopy(validator.assignments),
    }

    if action == "move":
        result = controller.move(state, "wk_1", "R105", 3, "14:00:00", "15:00:00")
    elif action == "unassign":
        result = controller.unassign(state, "wk_1", "Student 0001")
    elif action == "unlock":
        result = controller.unlock(state, "wk_1")
    elif action == "assign_failed":
        result = controller.assign_failed(
            state,
            failed_item={"type": "weekly_lesson"},
            index=0,
            view_model={
                "raw": {"Instructor": "Instructor 0001"},
                "requested_time": "Mon 10:00-11:00",
                "detected_day": 1,
                "name": "Student 0001",
            },
            new_room="R105",
        )
    else:
        result = getattr(controller, action)(state)

    assert result.success is False
    assert result.status == "conflict"
    assert result.message == "Session changed before save"
    assert result.draft_dirty is False
    assert state == before_state
    assert controller._assignments == before_controller["assignments"]
    assert controller._unassigned_lessons == before_controller["unassigned_lessons"]
    assert controller._history == before_controller["history"]
    assert controller._redo_stack == before_controller["redo_stack"]
    assert validator.assignments == before_controller["validator_assignments"]
    assert controller.history_count == 1
    assert controller.redo_count == 1
    assert session_mgr.calls == 1


def test_validate_move_action_is_read_only_and_returns_warnings():
    session_mgr = DummySessionManager()
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [{"id": "wk_1", "resourceId": "R101"}]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(
            move_result={"success": True, "warnings": ["Room Type Mismatch"]}
        ),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    result = controller.validate_move("wk_1", "R105", 3, "14:00:00", "15:00:00")

    assert result["success"] is True
    assert result["warnings"] == ["Room Type Mismatch"]
    assert controller._assignments[0]["resourceId"] == "R101"
    assert session_mgr.calls == 0


def test_validate_and_move_share_canonical_room_rejection():
    session_mgr = DummySessionManager()
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [
        {"id": "wk_1", "resourceId": "R101"}
    ]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(rooms=[{"id": "R101"}, {"id": "R105"}]),
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": True}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    validation = controller.validate_move(
        "wk_1",
        "CC999",
        3,
        "14:00:00",
        "15:00:00",
    )
    result = controller.move(
        state,
        "wk_1",
        "CC999",
        3,
        "14:00:00",
        "15:00:00",
    )

    assert validation == {"success": False, "message": "Unknown room: CC999"}
    assert result.status == "failed"
    assert result.message == validation["message"]
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R101"
    assert state[STEP4_EDIT_SESSION_KEY]["history"] == []
    assert session_mgr.calls == 0


def test_controller_rejects_blank_room_and_invalid_day_before_persistence():
    session_mgr = DummySessionManager()
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [
        {"id": "wk_1", "resourceId": "R101"}
    ]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(rooms=[{"id": "R101"}]),
        overrider=PrimitiveOnlyOverriderStub(move_result={"success": True}),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )

    blank_room = controller.move(
        state,
        "wk_1",
        "   ",
        3,
        "14:00:00",
        "15:00:00",
    )
    invalid_day = controller.move(
        state,
        "wk_1",
        "R101",
        7,
        "14:00:00",
        "15:00:00",
    )

    assert blank_room.status == "failed"
    assert blank_room.message == "Room must not be blank."
    assert invalid_day.status == "failed"
    assert invalid_day.message == "Day must be between 0 and 6."
    assert state[STEP4_EDIT_SESSION_KEY]["history"] == []
    assert session_mgr.calls == 0


def test_apply_unassign_action_persists_draft_and_returns_message():
    session_mgr = DummySessionManager()
    state = _state()
    state[STEP4_EDIT_SESSION_KEY]["assignments"] = [{"id": "wk_1", "resourceId": "R101", "extendedProps": {}}]
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(),
        overrider=PrimitiveOnlyOverriderStub(unassign_result=True),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    runtime = SimpleNamespace(session_mgr=session_mgr, draft_controller=controller)

    result = runtime.draft_controller.unassign(state, event_id="wk_1", label="Student 0001")

    assert result.status == "success"
    assert result.message == "Unassigned Student 0001"
    assert result.draft_dirty is True
    assert session_mgr.calls == 1
    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True


def test_assign_failed_lesson_blocks_promotion_when_conflict_exists():
    session_mgr = DummySessionManager()
    state = _state()
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(conflict={"title": "Dr. B"}),
        overrider=PrimitiveOnlyOverriderStub(),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    runtime = SimpleNamespace(session_mgr=session_mgr, draft_controller=controller)

    result = runtime.draft_controller.assign_failed(
        state,
        failed_item={"type": "weekly_lesson"},
        index=0,
        view_model={
            "raw": {"Instructor": "Instructor 0001"},
            "requested_time": "Mon 10:00-11:00",
            "detected_day": 1,
            "name": "Student 0001",
        },
        new_room="R105",
    )

    assert result.status == "failed"
    assert result.message == "Conflict with Dr. B"
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"] == []
    assert len(state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"]) == 1
    assert session_mgr.calls == 0


def test_assign_failed_lesson_promotes_when_no_conflict():
    session_mgr = DummySessionManager()
    state = _state()
    controller = _editor_service.Step4DraftController(
        session_mgr=session_mgr,
        validator=ValidatorStub(conflict=None),
        overrider=PrimitiveOnlyOverriderStub(),
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    runtime = SimpleNamespace(session_mgr=session_mgr, draft_controller=controller)

    result = runtime.draft_controller.assign_failed(
        state,
        failed_item={"type": "weekly_lesson"},
        index=0,
        view_model={
            "raw": {"Instructor": "Instructor 0001"},
            "requested_time": "Mon 10:00-11:00",
            "detected_day": 1,
            "name": "Student 0001",
        },
        new_room="R105",
    )

    assert result.status == "success"
    assert result.message == "Assigned u1 to R105"
    assert result.draft_dirty is True
    assert session_mgr.calls == 1
    assert len(state[STEP4_EDIT_SESSION_KEY]["assignments"]) == 1
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R105"
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []
