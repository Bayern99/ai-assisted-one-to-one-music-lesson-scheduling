from __future__ import annotations

import copy

from modules.api.services.scheduler import (
    SchedulerCommandRejected,
    SchedulerPersistenceConflict,
    build_scheduler_view,
    restore_scheduler_state,
)
from modules.scheduler.logic.finalize_validation import collect_finalize_conflicts
from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.causal_diagnosis import build_local_causal_diagnosis
from modules.scheduler.logic.resolution_advice import (
    build_resolution_advice,
    resolution_case_ids,
)
from modules.scheduler.logic.piano_leverage import build_piano_leverage_proposals
from modules.api.services.pi_optimizer_intervention import public_pi_runtime
from modules.scheduler.logic.optimizer_learning_record import (
    OptimizerLearningRecordError,
    _find_run,
    _load_ledger,
    record_optimizer_intervention,
    repair_optimizer_learning_record,
)
from modules.scheduler.logic.session_state import persist_scheduler_session
from modules.scheduler.logic.step4_service import build_step4_runtime
from modules.shared.time_parser import TimeParser
from modules.api.services.pi_reconciliation import get_reconciliation_public_record


def _day_instructor_names(runtime):
    """Real instructor names per weekday, for the operator's protect list."""
    names = {}
    for assignment in runtime.edit_session.get("assignments", []) or []:
        props = assignment.get("extendedProps") if isinstance(assignment.get("extendedProps"), dict) else {}
        instructor = str(props.get("Instructor") or assignment.get("instructor") or "").strip()
        if not instructor:
            continue
        day = TimeParser.event_primary_js_day(assignment, default=None)
        if day not in range(7):
            continue
        names.setdefault(day, set()).add(instructor)
    for issue in runtime.edit_session.get("unassigned_lessons", []) or []:
        context = unresolved_assignment_primitives.build_context(issue)
        instructor = str(context.get("instructor") or "").strip()
        day = context.get("original_day")
        if instructor and day in range(7):
            names.setdefault(day, set()).add(instructor)
    return {str(day): sorted(values, key=str.casefold) for day, values in names.items()}


def build_resolution_view(context):
    state = restore_scheduler_state(context)
    learning_ready = True
    try:
        repair_optimizer_learning_record(context.loader, state=state)
    except Exception:
        learning_ready = False
    runtime = build_step4_runtime(context, state)
    advice = build_resolution_advice(runtime)
    advice["causal_diagnosis"] = build_local_causal_diagnosis(
        advice.get("cases") or [],
        piano_proposals=advice.get("piano_leverage") or [],
    )
    run_id = str(runtime.edit_session.get("optimizer_run_id") or "").strip()
    advice["pi_available"] = False
    advice["pi_runtime"] = public_pi_runtime()
    advice["pi_reconciliation"] = get_reconciliation_public_record(context, runtime)
    advice["intervention_constraints"] = copy.deepcopy(
        runtime.edit_session.get("intervention_constraints", []) or []
    )
    advice["day_instructors"] = _day_instructor_names(runtime)
    if run_id and learning_ready:
        try:
            _find_run(_load_ledger(context.loader), run_id)
            advice["pi_available"] = True
        except OptimizerLearningRecordError:
            advice["pi_available"] = False
    return advice


def review_draft(context):
    """Deterministic pre-finalize review of the current Step 4 draft."""
    state = restore_scheduler_state(context)
    runtime = build_step4_runtime(context, state)
    controller = runtime.draft_controller
    conflicts, warnings = collect_finalize_conflicts(
        controller,
        controller._assignments,
    )
    integrity = controller._candidate_integrity()
    conflict_items = []
    for left, right in conflicts:
        conflict_items.append(
            {
                "left": str(left.get("id") or "?") if isinstance(left, dict) else "?",
                "right": str(right.get("id") or "?") if isinstance(right, dict) else "?",
                "message": str(right.get("message") or "conflict") if isinstance(right, dict) else "conflict",
            }
        )
    if not integrity.get("is_valid"):
        status = "integrity_blocked"
    elif conflict_items:
        status = "blocked"
    else:
        status = "ready"
    return {
        "status": status,
        "summary": {
            "assignments": len(controller._assignments),
            "unassigned": len(controller._unassigned_lessons),
            "draft_dirty": bool(controller.edit_session.get("dirty")),
            "history": len(controller._history),
        },
        "conflicts": conflict_items,
        "warnings": list(warnings or []),
        "integrity": {
            "blocking_reason_codes": integrity.get("blocking_reason_codes", []),
            "validation_errors": integrity.get("validation_errors", []),
        },
    }


def update_resolution_waiting(context, *, case_id, waiting, note):
    state = restore_scheduler_state(context)
    runtime = build_step4_runtime(context, state)
    if case_id not in resolution_case_ids(runtime):
        raise SchedulerCommandRejected(f"Resolution case {case_id} not found.")

    entries = runtime.edit_session.setdefault("resolution_waiting", {})
    if waiting:
        waiting_note = str(note or "").strip()
        if not waiting_note:
            raise SchedulerCommandRejected(
                "Add a Waiting note so the next operator knows what response is needed."
            )
        entries[case_id] = {"status": "waiting", "note": waiting_note}
    else:
        entries.pop(case_id, None)
    outcome = persist_scheduler_session(
        context.session_manager,
        state,
        expected_mtime=state.get("scheduler_session_revision")
        or state.get("scheduler_session_mtime"),
    )
    if getattr(outcome, "status", "") == "conflict":
        raise SchedulerPersistenceConflict(getattr(outcome, "warning", ""))
    return build_resolution_advice(runtime)


def apply_piano_leverage(
    context,
    *,
    proposal_id,
    teacher_confirmed,
    confirmation_note,
):
    state = restore_scheduler_state(context)
    runtime = build_step4_runtime(context, state)
    proposal = next(
        (
            item
            for item in build_piano_leverage_proposals(runtime)
            if item["id"] == proposal_id
        ),
        None,
    )
    if proposal is None:
        raise SchedulerCommandRejected(
            "Piano leverage proposal is stale; refresh advice and try again."
        )
    result = runtime.draft_controller.apply_piano_leverage(
        state,
        proposal,
        teacher_confirmed=teacher_confirmed,
        confirmation_note=confirmation_note,
    )
    outcome = getattr(result, "persistence_outcome", None)
    if getattr(outcome, "status", "") == "conflict":
        raise SchedulerPersistenceConflict(getattr(outcome, "warning", ""))
    if not result.success:
        raise SchedulerCommandRejected(result.message, result.warnings)
    warnings = list(result.warnings)
    history = runtime.edit_session.get("history") or []
    if history:
        try:
            record_optimizer_intervention(
                context.loader,
                state=state,
                history_record=history[-1],
                active=True,
            )
        except Exception as exc:
            warnings.append(
                "Draft saved, but its optimizer intervention record was not "
                f"updated: {exc}"
            )
    return build_scheduler_view(context), warnings
