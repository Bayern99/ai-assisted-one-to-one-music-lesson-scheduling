"""Value-of-information analysis for Step 4 intervention plans.

The dashboard simulates the YES and NO branch for each teacher-confirmation
decision point. Pi may phrase the question; the branch evidence is
deterministic and does not depend on a model.
"""

from __future__ import annotations

import copy
import hashlib

from modules.scheduler.logic.intervention_actions import (
    InterventionActionError,
    resolve_intervention_actions,
)

MAX_BASE_ACTIONS = 6
MAX_ATTEMPTS = 12


def _decision_label(action) -> str:
    if action.get("type") == "move_block":
        proposal = action.get("proposal") or {}
        instructor = str(proposal.get("instructor") or "teacher").strip()
        return (
            f"Move {instructor}'s block to "
            f"{proposal.get('target_room')} {proposal.get('target_day')} "
            f"{proposal.get('target_start')}–{proposal.get('target_end')}"
        )
    issue_id = str(action.get("issue_id") or "unknown")
    target = action.get("target") or {}
    return (
        f"Move {issue_id} to {target.get('room')} {target.get('day')} "
        f"{target.get('start')}–{target.get('end')}"
    )


def _question_text(action) -> str:
    if action.get("type") == "move_block":
        proposal = action.get("proposal") or {}
        instructor = str(proposal.get("instructor") or "the teacher").strip()
        return (
            f"Can {instructor} move the whole block to "
            f"{proposal.get('target_room')} {proposal.get('target_day')} "
            f"{proposal.get('target_start')}–{proposal.get('target_end')}?"
        )
    target = action.get("target") or {}
    issue_id = str(action.get("issue_id") or "this lesson").strip()
    return (
        f"Can {issue_id} move to {target.get('room')} {target.get('day')} "
        f"{target.get('start')}–{target.get('end')}?"
    )


def _greedy_plan(controller, catalog, ordered_actions, *, exclude_ids):
    """Greedily keep as many ordered actions as stay feasible together."""
    exclude = set(str(item) for item in exclude_ids or [])
    kept = []
    for action in ordered_actions:
        action_id = str(action.get("action_id") or "")
        if not action_id or action_id in exclude:
            continue
        candidate = [copy.deepcopy(item) for item in kept] + [
            copy.deepcopy(action)
        ]
        try:
            resolved = resolve_intervention_actions(catalog, [item["action_id"] for item in candidate])
        except InterventionActionError:
            continue
        simulation = controller.simulate_intervention_plan(resolved)
        if simulation.get("feasible"):
            kept.append(copy.deepcopy(action))
    return kept


def _simulate(controller, catalog, actions):
    if not actions:
        return {
            "feasible": False,
            "status": "invalid",
            "resolved_now": 0,
            "conditionally_resolvable": 0,
            "resolved_count": 0,
            "remaining_unresolved": 0,
            "actions": [],
        }
    resolved = resolve_intervention_actions(
        catalog,
        [item["action_id"] for item in actions],
    )
    return controller.simulate_intervention_plan(resolved)


def build_counterfactual_advice(controller, catalog, *, _depth=0):
    """Compare YES/NO branches for each confirmation decision point.

    At depth zero, attach one deterministic next-question layer so the UI can
    follow a bounded decision tree without asking Pi to invent branch logic.
    """
    if not isinstance(catalog, dict) or not catalog:
        return []
    base_actions = [
        action
        for action in catalog.values()
        if not action.get("requires_teacher_confirmation")
    ]
    base_actions.sort(
        key=lambda action: (
            action.get("source") == "cross_day",
            not bool((action.get("target") or {}).get("preferred")),
            str(action.get("action_id") or ""),
        )
    )
    base_actions = base_actions[:MAX_BASE_ACTIONS]
    base_plan = _greedy_plan(
        controller,
        catalog,
        base_actions,
        exclude_ids=None,
    )
    base_simulation = _simulate(controller, catalog, base_plan)

    decision_points = []
    for action in catalog.values():
        if not action.get("requires_teacher_confirmation"):
            continue
        yes_plan = _greedy_plan(
            controller,
            catalog,
            [action] + base_actions,
            exclude_ids=None,
        )
        no_plan = [
            item for item in base_plan
            if item.get("action_id") != action.get("action_id")
        ]
        yes_simulation = _simulate(controller, catalog, yes_plan)
        no_simulation = (
            base_simulation
            if [item["action_id"] for item in no_plan]
            == [item["action_id"] for item in base_plan]
            else _simulate(controller, catalog, no_plan)
        )
        if not yes_simulation.get("feasible"):
            continue
        yes_now = int(yes_simulation.get("resolved_now") or 0)
        no_now = int(no_simulation.get("resolved_now") or 0)
        yes_count = int(yes_simulation.get("resolved_count") or 0)
        no_count = int(no_simulation.get("resolved_count") or 0)
        if yes_count <= no_count:
            continue
        point_id = "ask-" + hashlib.sha256(
            str(action.get("action_id") or "").encode("utf-8")
        ).hexdigest()[:12]
        decision_points.append(
            {
                "point_id": point_id,
                "action_ids": [str(action.get("action_id") or "")],
                "label": _decision_label(action),
                "question": _question_text(action),
                "impact": {
                    "delta": yes_count - no_count,
                    "yes_resolved": yes_now,
                    "no_resolved": no_now,
                    "yes_total": yes_count,
                    "no_total": no_count,
                    "remaining_after_yes": int(
                        yes_simulation.get("remaining_unresolved") or 0
                    ),
                    "remaining_after_no": int(
                        no_simulation.get("remaining_unresolved") or 0
                    ),
                },
                "yes": {
                    "action_ids": [item["action_id"] for item in yes_plan],
                    "simulation": copy.deepcopy(yes_simulation),
                },
                "no": {
                    "action_ids": [item["action_id"] for item in no_plan],
                    "simulation": copy.deepcopy(no_simulation),
                },
            }
        )
        if _depth == 0:
            remaining_catalog = {
                key: value
                for key, value in catalog.items()
                if str(key) != str(action.get("action_id") or "")
            }
            next_points = build_counterfactual_advice(
                controller,
                remaining_catalog,
                _depth=1,
            )
            next_questions = [
                {
                    "point_id": item["point_id"],
                    "label": item["label"],
                    "question": item["question"],
                    "impact": copy.deepcopy(item["impact"]),
                }
                for item in next_points[:2]
            ]
            decision_points[-1]["next_questions"] = {
                "yes": next_questions,
                "no": next_questions,
            }

    decision_points.sort(
        key=lambda point: (
            -int(point["impact"]["delta"]),
            -int(point["impact"]["yes_total"]),
            point["point_id"],
        )
    )
    return decision_points[:3]
