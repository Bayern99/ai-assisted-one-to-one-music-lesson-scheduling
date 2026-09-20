"""Shared in-memory execution for Step 4 intervention plans."""

import copy

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.resolution_package import PackageRejected, apply_piano_leverage_package
from modules.scheduler.logic.teacher_day_package import (
    build_teacher_day_package,
    validate_teacher_day_placement,
)
from modules.shared.time_parser import TimeParser


def _failed_after_prior_action(action, message):
    return {
        "action_id": str(action.get("action_id") or ""),
        "type": str(action.get("type") or "unknown"),
        "success": False,
        "message": message,
        "failure_code": "blocked_by_prior_action",
        "requires_teacher_confirmation": bool(
            action.get("requires_teacher_confirmation")
        ),
        "execution_state": "blocked",
        "warnings": [],
    }


def _execute_intervention_action(
    controller,
    action,
    *,
    teacher_confirmed=None,
    confirmation_note="",
):
    """Execute one server-issued action against the controller's memory only."""
    action_id = str(action.get("action_id") or "")
    action_type = str(action.get("type") or "")
    requires_confirmation = bool(action.get("requires_teacher_confirmation"))

    if action_type == "assign_issue":
        target = action.get("target") or {}
        issue_id = str(action.get("issue_id") or "").strip()
        validation = controller.validate_assignment(
            issue_id,
            target.get("room"),
            target.get("day"),
            target.get("start"),
            target.get("end"),
            teacher_confirmed=teacher_confirmed,
        )
        requires_confirmation = bool(
            validation.get("requires_teacher_confirmation")
            or requires_confirmation
        )
        result = {
            "action_id": action_id,
            "type": action_type,
            "issue_id": issue_id,
            "target": copy.deepcopy(target),
            "success": bool(validation.get("success")),
            "message": validation.get("message"),
            "failure_code": None
            if validation.get("success")
            else "assignment_rejected",
            "requires_teacher_confirmation": requires_confirmation,
            "execution_state": "blocked",
            "warnings": list(validation.get("warnings", []) or []),
        }
        if not result["success"]:
            return result, None

        unresolved = controller._find_unresolved(issue_id)
        if not unresolved:
            result.update(
                success=False,
                failure_code="issue_not_found",
                message=f"Issue {issue_id} not found.",
            )
            return result, None

        context = unresolved_assignment_primitives.build_context(unresolved)
        if validation.get("requires_teacher_confirmation") and teacher_confirmed:
            from modules.scheduler.logic.schedule_change_policy import attach_teacher_confirmation

            attach_teacher_confirmation(
                validation["assignment"],
                instructor=context.get("instructor"),
                note=confirmation_note,
            )
        record = unresolved_assignment_primitives.apply(
            controller._assignments,
            controller._unassigned_lessons,
            unresolved,
            validation["assignment"],
        )
        record["pi_plan_action_id"] = action_id
        controller._sync_validator_state()
        return result, record

    if action_type == "move_block":
        try:
            child_records = apply_piano_leverage_package(
                controller,
                action.get("proposal") or {},
                confirmation_note=confirmation_note,
            )
            proposal = action.get("proposal") or {}
            result = {
                "action_id": action_id,
                "type": action_type,
                "success": True,
                "message": None,
                "failure_code": None,
                "requires_teacher_confirmation": requires_confirmation,
                "execution_state": "blocked",
                "warnings": [],
                "moves": copy.deepcopy(proposal.get("moves") or []),
            }
            return result, {
                "action": "compound",
                "label": "pi_plan_move_block",
                "pi_plan_action_id": action_id,
                "records": copy.deepcopy(child_records or []),
            }
        except PackageRejected as exc:
            return {
                "action_id": action_id,
                "type": action_type,
                "success": False,
                "message": str(exc),
                "failure_code": "block_move_rejected",
                "requires_teacher_confirmation": requires_confirmation,
                "warnings": [],
            }, None

    return {
        "action_id": action_id,
        "type": action_type or "unknown",
        "success": False,
        "message": "Unsupported intervention action type.",
        "failure_code": "unsupported_action_type",
        "requires_teacher_confirmation": False,
        "execution_state": "blocked",
        "warnings": [],
    }, None


def _package_error(controller, actions):
    """Return one package-level rejection before any action mutates memory."""
    grouped = {}
    unresolved_by_id = {}
    for item in controller._unassigned_lessons or []:
        context = unresolved_assignment_primitives.build_context(item)
        issue_id = unresolved_assignment_primitives.issue_id(item)
        unresolved_by_id[issue_id] = (item, context)

    for action in actions or []:
        package_id = str(action.get("teacher_day_package_id") or "").strip()
        if not package_id or action.get("type") != "assign_issue":
            continue
        grouped.setdefault(package_id, []).append(action)

    for package_id, package_actions in grouped.items():
        changed = False
        for action in package_actions:
            issue_id = str(action.get("issue_id") or "").strip()
            item_context = unresolved_by_id.get(issue_id)
            if item_context is None:
                continue
            _item, context = item_context
            target = action.get("target") or {}
            target_start = TimeParser.normalize_clock(target.get("start"))
            target_end = TimeParser.normalize_clock(
                target.get("end"), prefer_end=True, allow_midnight=True
            )
            if (
                target.get("day") != context.get("original_day")
                or target_start != context.get("original_start")
                or target_end != context.get("original_end")
            ):
                changed = True
                break
        if not changed:
            continue

        expected_ids = {
            str(item).strip() for item in package_actions[0].get("package_issue_ids") or []
        }
        selected_ids = {
            str(action.get("issue_id") or "").strip()
            for action in package_actions
        }
        if (
            expected_ids != selected_ids
            or len(package_actions) != len(selected_ids)
        ):
            return (
                "Teacher-Day Package changes must include one placement for every "
                "issue in the package."
            )

        source_events = []
        placement_items = []
        for issue_id in sorted(expected_ids):
            item_context = unresolved_by_id.get(issue_id)
            if item_context is None:
                return f"Teacher-Day Package issue {issue_id} is stale."
            _item, context = item_context
            source_events.append(
                {
                    "id": issue_id,
                    "daysOfWeek": [context.get("original_day")],
                    "startTime": context.get("original_start"),
                    "endTime": context.get("original_end"),
                    "extendedProps": {"Instructor": context.get("instructor")},
                }
            )
            action = next(
                item
                for item in package_actions
                if str(item.get("issue_id") or "").strip() == issue_id
            )
            target = action.get("target") or {}
            placement_items.append(
                {
                    "event_id": issue_id,
                    "day": target.get("day"),
                    "start": target.get("start"),
                    "end": target.get("end"),
                    "room": target.get("room"),
                }
            )
        try:
            package = build_teacher_day_package(source_events)
        except ValueError as exc:
            return str(exc)
        placements = [
            next(
                item
                for item in placement_items
                if str(item.get("event_id") or "").strip() == issue_id
            )
            for issue_id in package.get("event_ids") or []
        ]
        validation = validate_teacher_day_placement(package, placements)
        if not validation.get("valid"):
            return "Teacher-Day Package is invalid: " + ", ".join(
                validation.get("errors") or []
            )
    return None


def execute_intervention_actions(
    controller,
    actions,
    *,
    confirmed_action_ids=None,
    apply=False,
):
    """Run one ordered action plan in memory for both simulation and Apply."""
    results = []
    records = []
    conditional_count = 0
    confirmations_required = 0
    resolved_now_count = 0
    constraints = controller.edit_session.get("intervention_constraints") or []
    max_confirmations = next(
        (
            int(item.get("value"))
            for item in constraints
            if isinstance(item, dict)
            and item.get("type") == "max_teacher_confirmations"
            and str(item.get("value", "")).isdigit()
        ),
        None,
    )
    confirmed_action_ids = {
        str(item).strip() for item in confirmed_action_ids or []
    }
    package_error = _package_error(controller, actions)
    if package_error:
        failed = {
            "action_id": str((actions or [{}])[0].get("action_id") or ""),
            "type": str((actions or [{}])[0].get("type") or "unknown"),
            "success": False,
            "message": package_error,
            "failure_code": "teacher_day_package_invalid",
            "requires_teacher_confirmation": False,
            "execution_state": "blocked",
            "warnings": [],
        }
        blocked_actions = [failed]
        blocked_actions.extend(
            _failed_after_prior_action(
                action,
                "Not attempted because the Teacher-Day Package is invalid.",
            )
            for action in (actions or [])[1:]
        )
        return {
            "feasible": False,
            "status": "invalid",
            "resolved_now": 0,
            "conditionally_resolvable": 0,
            "confirmations_required": 0,
            "resolved_count": 0,
            "remaining_unresolved": len(controller._unassigned_lessons),
            "actions": blocked_actions,
            "integrity": {"blocking_reason_codes": [], "validation_errors": []},
            "history_records": [],
        }
    confirmation_pending = False
    for index, action in enumerate(actions or []):
        action_id = str(action.get("action_id") or "").strip()
        requires_confirmation = bool(action.get("requires_teacher_confirmation"))
        if apply and requires_confirmation and action_id not in confirmed_action_ids:
            result = {
                "action_id": action_id,
                "type": str(action.get("type") or "unknown"),
                "success": False,
                "message": (
                    f"Action {action_id} requires explicit teacher confirmation "
                    "before the plan can be applied."
                ),
                "failure_code": "teacher_confirmation_required",
                "requires_teacher_confirmation": True,
                "execution_state": "blocked",
                "warnings": [],
            }
            result_record = None
        else:
            result, result_record = _execute_intervention_action(
                controller,
                action,
                teacher_confirmed=(
                    True if apply and requires_confirmation else False if apply else None
                ),
                confirmation_note="Plan-level teacher confirmation" if apply else "",
            )

        if result["success"]:
            requires_confirmation = bool(
                result.get("requires_teacher_confirmation")
            )
            if requires_confirmation:
                confirmations_required += 1
                confirmation_pending = True
            result["execution_state"] = (
                "conditional" if confirmation_pending else "executable"
            )
            if result["execution_state"] == "conditional" and result.get("type") == "assign_issue":
                conditional_count += 1
            if result["execution_state"] == "executable" and result.get("type") == "assign_issue":
                resolved_now_count += 1
            if result_record is not None:
                records.append(result_record)

            if (
                requires_confirmation
                and max_confirmations is not None
                and confirmations_required > max_confirmations
            ):
                result.update(
                    success=False,
                    execution_state="blocked",
                    failure_code="max_teacher_confirmations",
                    message=(
                        f"Plan exceeds the session limit of {max_confirmations} "
                        "teacher confirmations."
                    ),
                )
                if records and records[-1] is result_record:
                    records.pop()

        results.append(result)
        if not result["success"]:
            results.extend(
                _failed_after_prior_action(
                    later,
                    "Not attempted because an earlier plan action failed.",
                )
                for later in (actions or [])[index + 1 :]
            )
            break

    resolved = sum(
        result.get("success") and result.get("type") == "assign_issue"
        for result in results
    )
    integrity = controller._candidate_integrity()
    feasible = bool(results) and all(
        result.get("success") for result in results
    ) and integrity["is_valid"]
    return {
        "feasible": feasible,
        "status": (
            "verified_conditional"
            if feasible and confirmation_pending
            else "verified_executable"
            if feasible
            else "invalid"
        ),
        "resolved_now": resolved_now_count if feasible else 0,
        "conditionally_resolvable": conditional_count if feasible else 0,
        "confirmations_required": confirmations_required if feasible else 0,
        "resolved_count": resolved if feasible else 0,
        "remaining_unresolved": len(controller._unassigned_lessons),
        "actions": results,
        "integrity": {
            "blocking_reason_codes": integrity.get("blocking_reason_codes", []),
            "validation_errors": integrity.get("validation_errors", []),
        },
        "history_records": records,
    }


def simulate_intervention_plan(controller, actions):
    """Sandbox an ordered heterogeneous plan without persistence."""
    state = {"step4_edit_session": controller.edit_session}
    snapshot = controller._snapshot_mutation_state(state)
    try:
        return execute_intervention_actions(controller, actions)
    finally:
        controller._restore_mutation_state(state, snapshot)


def simulate_assignment_plan(controller, actions):
    state = {"step4_edit_session": controller.edit_session}
    snapshot = controller._snapshot_mutation_state(state)
    results = []
    try:
        for action in actions:
            issue_id = str(action.get("issue_id") or "").strip()
            validation = controller.validate_assignment(
                issue_id,
                action.get("room"),
                action.get("day"),
                action.get("start"),
                action.get("end"),
                teacher_confirmed=None,
            )
            result = {
                "issue_id": issue_id,
                "success": bool(validation.get("success")),
                "message": validation.get("message"),
                "requires_teacher_confirmation": bool(
                    validation.get("requires_teacher_confirmation")
                ),
                "warnings": list(validation.get("warnings", []) or []),
            }
            results.append(result)
            if not result["success"]:
                continue
            unresolved = controller._find_unresolved(issue_id)
            unresolved_assignment_primitives.apply(
                controller._assignments,
                controller._unassigned_lessons,
                unresolved,
                validation["assignment"],
            )
            controller._sync_validator_state()
        resolved = sum(result["success"] for result in results)
        integrity = controller._candidate_integrity()
        return {
            "feasible": bool(results) and resolved == len(results) and integrity["is_valid"],
            "resolved_count": resolved,
            "remaining_unresolved": len(controller._unassigned_lessons),
            "actions": results,
            "integrity": {
                "blocking_reason_codes": integrity.get("blocking_reason_codes", []),
                "validation_errors": integrity.get("validation_errors", []),
            },
        }
    finally:
        controller._restore_mutation_state(state, snapshot)
