"""Server-issued candidate actions for Step 4 intervention planning."""

from __future__ import annotations

import copy
import hashlib
import json


class InterventionActionError(ValueError):
    """Raised when a plan references an invalid candidate action."""


def _action_id(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"action-{digest}"


def _assign_action(issue_id, option, *, source, option_index):
    identity = {
        "type": "assign_issue",
        "issue_id": issue_id,
        "source": source,
        "option_index": option_index,
        "target": option,
    }
    return {
        "action_id": _action_id(identity),
        "type": "assign_issue",
        "issue_id": issue_id,
        "source": source,
        "option_index": option_index,
        "target": copy.deepcopy(option),
        "requires_teacher_confirmation": bool(
            option.get("requires_teacher_confirmation")
        ),
    }


def _block_action(proposal):
    proposal_id = str(proposal.get("id") or "").strip()
    if not proposal_id:
        raise InterventionActionError("Block move proposals require an id.")
    identity = {"type": "move_block", "proposal_id": proposal_id}
    block_proposal = copy.deepcopy(proposal)
    # The existing Piano leverage proposal includes optional fills. Fills are
    # exposed as later assign_issue actions so a plan can order them after the
    # block move and the simulator can report each child action separately.
    block_proposal["fills"] = []
    return {
        "action_id": _action_id(identity),
        "type": "move_block",
        "proposal_id": proposal_id,
        "proposal": block_proposal,
        "requires_teacher_confirmation": True,
    }


def _blocked_by_constraints(action, constraints):
    for constraint in constraints or []:
        if not isinstance(constraint, dict):
            continue
        kind = constraint.get("type")
        if kind == "avoid_day":
            day = constraint.get("day")
            target = action.get("target") or {}
            proposal = action.get("proposal") or {}
            if target.get("day") == day or proposal.get("target_day") == day:
                return True
        elif kind == "protect_teacher_day":
            if (
                action.get("instructor") == constraint.get("instructor")
                and (
                    action.get("original_day") == constraint.get("day")
                    or (action.get("proposal") or {}).get("from_day") == constraint.get("day")
                )
            ):
                return True
        elif kind == "prefer_room_only" and action.get("requires_teacher_confirmation"):
            return True
        elif (
            kind == "max_teacher_confirmations"
            and int(constraint.get("value") or 0) == 0
            and action.get("requires_teacher_confirmation")
        ):
            return True
    return False


def build_intervention_action_catalog(cases, *, piano_leverage=None, constraints=None):
    """Return stable, server-owned actions from deterministic advice.

    The returned mapping is an internal catalog. Pi should receive the action
    ids and safe display fields, never arbitrary schedule mutation payloads.
    """
    catalog = {}
    for case in cases or []:
        for issue in case.get("issues") or []:
            issue_id = str(issue.get("issue_id") or "").strip()
            if not issue_id:
                continue
            package_id = str(case.get("id") or "").strip()
            package_issue_ids = [
                str(item.get("issue_id") or "").strip()
                for item in case.get("issues") or []
                if str(item.get("issue_id") or "").strip()
            ]
            for source, options_key in (
                ("same_day", "options"),
                ("cross_day", "cross_day_options"),
            ):
                for index, option in enumerate(issue.get(options_key) or []):
                    if not isinstance(option, dict):
                        continue
                    action = _assign_action(
                        issue_id,
                        option,
                        source=source,
                        option_index=index,
                    )
                    action["instructor"] = case.get("instructor")
                    action["original_day"] = case.get("day")
                    action["teacher_day_package_id"] = package_id
                    action["package_issue_ids"] = package_issue_ids
                    if not _blocked_by_constraints(action, constraints):
                        catalog[action["action_id"]] = action

    for proposal in piano_leverage or []:
        if isinstance(proposal, dict):
            action = _block_action(proposal)
            action["instructor"] = proposal.get("instructor")
            action["original_day"] = (
                (proposal.get("moves") or [{}])[0].get("from_day")
            )
            if not _blocked_by_constraints(action, constraints):
                catalog[action["action_id"]] = action
    return catalog


def resolve_intervention_actions(catalog, action_ids):
    """Resolve a unique ordered list of server-issued action ids."""
    if not isinstance(catalog, dict) or not isinstance(action_ids, list):
        raise InterventionActionError("An intervention plan requires action ids.")
    if len(action_ids) != len(set(action_ids)):
        raise InterventionActionError("An intervention plan cannot repeat an action.")
    actions = []
    for action_id in action_ids:
        action = catalog.get(str(action_id))
        if not isinstance(action, dict):
            raise InterventionActionError(
                f"Intervention action {action_id!r} is stale or unknown."
            )
        actions.append(copy.deepcopy(action))
    return actions
