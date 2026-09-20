from copy import deepcopy

from modules.scheduler.logic.counterfactual import build_counterfactual_advice


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

    def simulate_intervention_plan(self, actions):
        from modules.scheduler.logic.resolution_simulation import (
            simulate_intervention_plan,
        )

        return simulate_intervention_plan(self, actions)


def _assign(action_id, issue_id, *, confirmation=False, day=4):
    return {
        "action_id": action_id,
        "type": "assign_issue",
        "issue_id": issue_id,
        "source": "same_day",
        "target": {"room": "R1", "day": day, "start": "09:00", "end": "10:00"},
        "requires_teacher_confirmation": confirmation,
    }


def test_counterfactual_reports_delta_for_conditional_decision_point():
    controller = _FakeController()
    catalog = {
        "action-1": _assign("action-1", "issue-1"),
        "action-2": _assign("action-2", "issue-2", confirmation=True),
    }

    points = build_counterfactual_advice(controller, catalog)

    assert len(points) == 1
    point = points[0]
    assert point["action_ids"] == ["action-2"]
    assert point["impact"]["yes_total"] == 2
    assert point["impact"]["no_total"] == 1
    assert point["impact"]["delta"] == 1
    assert point["impact"]["yes_resolved"] == 0
    assert point["yes"]["simulation"]["feasible"] is True
    assert point["no"]["simulation"]["feasible"] is True


def test_counterfactual_skips_decision_points_without_gain():
    controller = _FakeController()
    catalog = {
        "action-1": _assign("action-1", "issue-1"),
        "action-2": _assign(
            "action-2",
            "issue-2",
            confirmation=True,
            day=4,
        ),
    }

    # issue-2 cannot be placed when the conditional action is excluded, so NO
    # keeps only issue-1 and YES resolves both: delta stays positive.
    points = build_counterfactual_advice(controller, catalog)
    assert len(points) == 1

    # A catalog with only conditional actions still asks: YES resolves one
    # lesson while the current base resolves none.
    only_conditional = {
        "action-2": _assign("action-2", "issue-2", confirmation=True),
    }
    assert len(build_counterfactual_advice(controller, only_conditional)) == 1


def test_counterfactual_empty_without_catalog():
    assert build_counterfactual_advice(_FakeController(), {}) == []
    assert build_counterfactual_advice(_FakeController(), None) == []
