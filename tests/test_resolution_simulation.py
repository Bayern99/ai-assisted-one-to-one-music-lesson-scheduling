from copy import deepcopy
from types import SimpleNamespace

from modules.scheduler.logic.resolution_simulation import (
    simulate_intervention_plan,
)
from modules.scheduler.logic.step4_service import ActionResult, Step4DraftController
from modules.scheduler.logic import manual_override_primitives


class _FakeController:
    def __init__(self):
        self._assignments = []
        self._unassigned_lessons = [
            {"id": "issue-1"},
            {"id": "issue-2"},
        ]
        self.edit_session = {
            "assignments": self._assignments,
            "unassigned_lessons": self._unassigned_lessons,
        }

    def _snapshot_mutation_state(self, _state):
        return {
            "assignments": deepcopy(self._assignments),
            "unresolved": deepcopy(self._unassigned_lessons),
        }

    def _restore_mutation_state(self, _state, snapshot):
        self._assignments[:] = snapshot["assignments"]
        self._unassigned_lessons[:] = snapshot["unresolved"]

    def validate_assignment(
        self,
        issue_id,
        room,
        day,
        start,
        end,
        *,
        teacher_confirmed=None,
    ):
        if issue_id == "missing":
            return {"success": False, "message": "missing issue"}
        return {
            "success": True,
            "assignment": {
                "id": issue_id,
                "resourceId": room,
                "daysOfWeek": [day],
                "startTime": start,
                "endTime": end,
            },
            "requires_teacher_confirmation": issue_id == "issue-2",
            "warnings": [],
        }

    def _find_unresolved(self, issue_id):
        return next(
            (item for item in self._unassigned_lessons if item.get("id") == issue_id),
            None,
        )

    def _sync_validator_state(self):
        return None

    def _candidate_integrity(self):
        return {"is_valid": True, "blocking_reason_codes": [], "validation_errors": []}


def _assign(action_id, issue_id):
    return {
        "action_id": action_id,
        "type": "assign_issue",
        "issue_id": issue_id,
        "target": {"room": "R1", "day": 4, "start": "09:00", "end": "10:00"},
        "requires_teacher_confirmation": issue_id == "issue-2",
    }


def test_simulate_intervention_plan_restores_state_and_marks_conditional_result():
    controller = _FakeController()

    result = simulate_intervention_plan(
        controller,
        [_assign("action-1", "issue-1"), _assign("action-2", "issue-2")],
    )

    assert result["feasible"] is True
    assert result["status"] == "verified_conditional"
    assert result["resolved_now"] == 1
    assert result["conditionally_resolvable"] == 1
    assert result["confirmations_required"] == 1
    assert result["resolved_count"] == 2
    assert len(controller._unassigned_lessons) == 2
    assert controller._assignments == []


def test_simulate_intervention_plan_stops_after_failed_action():
    controller = _FakeController()

    result = simulate_intervention_plan(
        controller,
        [_assign("action-1", "missing"), _assign("action-2", "issue-1")],
    )

    assert result["feasible"] is False
    assert result["status"] == "invalid"
    assert result["actions"][0]["failure_code"] == "assignment_rejected"
    assert result["actions"][0]["execution_state"] == "blocked"
    assert result["actions"][1]["failure_code"] == "blocked_by_prior_action"
    assert controller._assignments == []
    assert len(controller._unassigned_lessons) == 2


def test_simulate_intervention_plan_can_order_block_move_before_assignment(monkeypatch):
    controller = _FakeController()

    def fake_block_move(current, _proposal, *, confirmation_note):
        current._assignments.append({"id": "moved-block"})
        return []

    monkeypatch.setattr(
        "modules.scheduler.logic.resolution_simulation.apply_piano_leverage_package",
        fake_block_move,
    )
    result = simulate_intervention_plan(
        controller,
        [
            {
                "action_id": "block-1",
                "type": "move_block",
                "proposal": {"id": "piano-1", "moves": [], "fills": []},
                "requires_teacher_confirmation": True,
            },
            _assign("action-1", "issue-1"),
        ],
    )

    assert result["feasible"] is True
    assert result["status"] == "verified_conditional"
    assert result["resolved_now"] == 0
    assert result["conditionally_resolvable"] == 1
    assert result["confirmations_required"] == 1
    assert result["actions"][1]["execution_state"] == "conditional"
    assert result["actions"][0]["type"] == "move_block"
    assert result["actions"][1]["success"] is True
    assert controller._assignments == []


class _PackageController(_FakeController):
    def __init__(self):
        self._assignments = []
        self._unassigned_lessons = [
            {
                "id": "issue-1",
                "instructor": "Instructor 0008",
                "day": 1,
                "start": "09:00",
                "end": "10:00",
            },
            {
                "id": "issue-2",
                "instructor": "Instructor 0008",
                "day": 1,
                "start": "10:30",
                "end": "11:30",
            },
        ]
        self.edit_session = {
            "assignments": self._assignments,
            "unassigned_lessons": self._unassigned_lessons,
        }


def _package_assign(action_id, issue_id, *, day, start, end, room="R1"):
    return {
        "action_id": action_id,
        "type": "assign_issue",
        "issue_id": issue_id,
        "teacher_day_package_id": "case-teacher-day",
        "package_issue_ids": ["issue-1", "issue-2"],
        "target": {"room": room, "day": day, "start": start, "end": end},
        "requires_teacher_confirmation": False,
    }


def test_teacher_day_package_requires_the_complete_same_day_placement():
    controller = _PackageController()
    result = simulate_intervention_plan(
        controller,
        [
            _package_assign("action-1", "issue-1", day=2, start="13:00", end="14:00"),
            _package_assign("action-2", "issue-2", day=2, start="14:30", end="15:30", room="R2"),
        ],
    )

    assert result["feasible"] is True
    assert result["remaining_unresolved"] == 0


def test_teacher_day_package_rejects_partial_split_and_gap_changes():
    cases = [
        [
            _package_assign("action-1", "issue-1", day=2, start="13:00", end="14:00"),
        ],
        [
            _package_assign("action-1", "issue-1", day=2, start="13:00", end="14:00"),
            _package_assign("action-2", "issue-2", day=3, start="14:30", end="15:30"),
        ],
        [
            _package_assign("action-1", "issue-1", day=2, start="13:00", end="14:00"),
            _package_assign("action-2", "issue-2", day=2, start="15:00", end="16:15"),
        ],
    ]

    for actions in cases:
        result = simulate_intervention_plan(_PackageController(), actions)
        assert result["feasible"] is False
        assert result["status"] == "invalid"
        assert all(item["execution_state"] == "blocked" for item in result["actions"])


class _CompoundController(Step4DraftController):
    def __init__(self):
        self._assignments = []
        self._unassigned_lessons = [{"id": "issue-1"}, {"id": "issue-2"}]
        self._history = []
        self._redo_stack = []
        self.edit_session = {
            "assignments": self._assignments,
            "unassigned_lessons": self._unassigned_lessons,
            "history": self._history,
            "redo_stack": self._redo_stack,
        }
        self.validator = SimpleNamespace(assignments=[])
        self.locked_context_assignments = []
        self.primitive_ops = manual_override_primitives

    def validate_assignment(self, issue_id, room, day, start, end, *, teacher_confirmed=None):
        return {
            "success": True,
            "assignment": {
                "id": issue_id,
                "resourceId": room,
                "daysOfWeek": [day],
                "startTime": start,
                "endTime": end,
            },
            "requires_teacher_confirmation": False,
            "warnings": [],
        }

    def _find_unresolved(self, issue_id):
        return next((item for item in self._unassigned_lessons if item["id"] == issue_id), None)

    def _candidate_integrity(self):
        return {"is_valid": True, "blocking_reason_codes": [], "validation_errors": []}

    def _persist_mutation(self, state, snapshot, message, warnings=None, *, keep_sealed=False):
        self._sync_edit_session_state()
        return ActionResult(status="success", message=message, draft_dirty=True)


def test_plan_apply_is_one_compound_undoable_mutation():
    controller = _CompoundController()
    state = {"step4_edit_session": controller.edit_session}
    actions = [_assign("action-1", "issue-1"), _assign("action-2", "issue-2")]

    applied = controller.apply_intervention_plan(
        state,
        actions,
        confirmed_action_ids=["action-2"],
        plan_package_id="package-1",
        profile="minimal_disturbance",
    )

    assert applied.success is True
    assert len(controller._history) == 1
    assert controller._history[0]["action"] == "compound"
    assert controller._history[0]["pi_plan_action_ids"] == ["action-1", "action-2"]
    assert len(controller._history[0]["records"]) == 2
    assert len(controller._assignments) == 2

    undone = controller.undo(state)
    assert undone.success is True
    assert controller._assignments == []
    assert len(controller._unassigned_lessons) == 2
    assert controller.redo_count == 1

    redone = controller.redo(state)
    assert redone.success is True
    assert len(controller._assignments) == 2
    assert controller.history_count == 1
    assert controller.redo_count == 0


def test_plan_apply_restores_memory_when_persistence_fails():
    class FailingController(_CompoundController):
        def _persist_mutation(self, state, snapshot, message, warnings=None, *, keep_sealed=False):
            raise OSError("session write failed")

    controller = FailingController()
    state = {"step4_edit_session": controller.edit_session}
    before = deepcopy(controller._unassigned_lessons)

    try:
        controller.apply_intervention_plan(
            state,
            [_assign("action-1", "issue-1")],
            plan_package_id="package-1",
            profile="minimal_disturbance",
        )
    except OSError:
        pass
    else:
        raise AssertionError("persistence failure should propagate")

    assert controller._assignments == []
    assert controller._unassigned_lessons == before
    assert controller._history == []
    assert controller._redo_stack == []


def test_plan_apply_restores_memory_when_integrity_check_fails():
    class IntegrityFailController(_CompoundController):
        def _persist_mutation(self, state, snapshot, message, warnings=None, *, keep_sealed=False):
            self._sync_edit_session_state()
            return ActionResult(status="failed", message="integrity failed")

    controller = IntegrityFailController()
    state = {"step4_edit_session": controller.edit_session}
    before = deepcopy(controller._unassigned_lessons)

    result = controller.apply_intervention_plan(
        state,
        [_assign("action-1", "issue-1")],
        plan_package_id="package-1",
        profile="minimal_disturbance",
    )

    assert result.success is False
    assert controller._assignments == []
    assert controller._unassigned_lessons == before
    assert controller._history == []
    assert controller._redo_stack == []
