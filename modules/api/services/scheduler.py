from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Literal, Optional

import pandas as pd

from modules.api.schemas.scheduler import (
    DraftState,
    Issue,
    IssueGroup,
    ReservationClassification,
    SchedulerMetrics,
    SchedulerSessionView,
)
from modules.scheduler.logic.session_state import (
    can_start_round_two,
    clear_round_two_state,
    collect_scheduler_warning_messages,
    ensure_step4_edit_session,
    infer_default_scheduler_tab,
    migrate_legacy_step4_state,
    resolve_draft_save_status,
    SCHEDULER_SESSION_REVISION_KEY,
)
from modules.scheduler.logic.optimizer_service import run_optimizer
from modules.scheduler.logic.optimizer_learning_record import (
    finalize_optimizer_run,
    repair_optimizer_learning_record,
    record_optimizer_intervention,
    record_optimizer_run,
)
from modules.scheduler.logic.instructor_profiles import collect_instructor_profiles
from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.reservation_classifier import classify_unresolved_reservations
from modules.scheduler.logic.step4_service import build_step4_runtime
from modules.scheduler.logic.validation_authority import (
    authority_assignments,
    authority_stale,
    resolve_validation_tri_state,
    seed_validation_authority,
)
from modules.scheduler.logic.workflow_service import reset_scheduling_workspace
from modules.scheduler.logic.source_requests import is_missing, studio_time_tokens
from modules.shared.time_parser import TimeParser


STAGE_BY_LABEL = {
    "Step 0: Lock Lectures": "lectures",
    "Step 1: Upload Data": "import",
    "Step 2: Configuration": "rules",
    "Step 3: Run Optimizer": "optimize",
    "Step 4: Interactive Editor": "resolve",
    "Step 5: Master Export": "export",
}

PRESENTATION_ONLY_KEYS = frozenset(
    {
        "backgroundColor",
        "borderColor",
        "textColor",
        "color",
        "className",
        "classNames",
        "display",
    }
)


@dataclass(frozen=True)
class DraftCommand:
    kind: Literal["assign", "move", "unassign", "unassign_block", "unlock", "undo", "redo"]
    event_id: Optional[str] = None
    event_ids: tuple[str, ...] = ()
    issue_id: Optional[str] = None
    room: Optional[str] = None
    day: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    label: Optional[str] = None
    teacher_confirmed: bool = False
    teacher_confirmation_note: str = ""
    decision_note: str = ""


class SchedulerCommandRejected(Exception):
    def __init__(self, message: str, warnings=None) -> None:
        super().__init__(message)
        self.message = message
        self.warnings = list(warnings or [])


class SchedulerPersistenceConflict(Exception):
    def __init__(self, warning: str = "") -> None:
        super().__init__(warning or "Scheduler draft persistence conflict")
        self.warning = warning


def sanitize_legacy_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_legacy_payload(item)
            for key, item in value.items()
            if key not in PRESENTATION_ONLY_KEYS
        }
    if isinstance(value, list):
        return [sanitize_legacy_payload(item) for item in value]
    return value


def assignment_with_editable_proposal(value: dict[str, Any]) -> dict[str, Any]:
    """Expose Python's canonical editable request bounds to the UI."""
    assignment = sanitize_legacy_payload(value)
    start, end = TimeParser.event_clock_pair(assignment, default=(None, None))
    proposal = TimeParser.course_proposal_from_occupancy(
        TimeParser.to_minutes(start, default=None),
        TimeParser.to_minutes(end, default=None, prefer_end=True),
    )
    if proposal is not None:
        assignment["proposal_start"], assignment["proposal_end"] = proposal
    return assignment


def restore_scheduler_state(context) -> dict:
    loaded, revision = context.session_manager.load_session_with_revision()
    restored = loaded if isinstance(loaded, dict) else {}
    for key in ("wk_df", "stu_df"):
        if isinstance(restored.get(key), list):
            records = restored[key]
            restored[key] = pd.DataFrame(records) if records else None
    migrate_legacy_step4_state(restored)
    restored[SCHEDULER_SESSION_REVISION_KEY] = revision
    restored["scheduler_session_mtime"] = revision.mtime
    return restored


def run_optimizer_operation(
    *,
    context,
    base_dir,
    expected_version: str,
    registry,
    operation_id: str,
    rerun_mode: str = "fresh",
) -> None:
    from modules.api.services.workspace import require_current_version

    def guard_version() -> None:
        require_current_version(
            base_dir,
            expected_version,
            context=context,
        )

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started_clock = monotonic()
    try:
        # A queued operation whose token has gone stale never enters a running
        # phase and never reads optimizer inputs into mutable scheduler state.
        guard_version()
        state = restore_scheduler_state(context)
        result = run_optimizer(
            context,
            state,
            run_id=operation_id,
            on_phase=lambda phase: registry.start(operation_id, phase=phase),
            version_guard=guard_version,
            commit_lock=context.mutation_lock,
            learning_metadata={
                "input_workspace_version": expected_version,
                "started_at": started_at,
                "started_clock": started_clock,
            },
            rerun_mode=rerun_mode,
        )
        learning_record_warning = None
        try:
            with context.mutation_lock:
                record_optimizer_run(
                    context.loader,
                    run_id=operation_id,
                    input_workspace_version=expected_version,
                    state=state,
                    rules=result.rules_snapshot,
                    duplicate_count=result.duplicate_count,
                    preserved_pin_count=result.preserved_pin_count,
                    downgraded_pin_count=result.downgraded_pin_count,
                    downgraded_pins=result.downgraded_pins,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    duration_ms=round((monotonic() - started_clock) * 1000),
                )
        except Exception as exc:
            learning_record_warning = (
                "Optimizer completed, but its learning record needs repair: "
                f"{exc}"
            )
            result.logs.append(learning_record_warning)
        operation_result = {
            "assignment_count": result.assignment_count,
            "unassigned_count": result.unassigned_count,
            "duplicate_count": result.duplicate_count,
            "duplicates": result.duplicates,
            "logs": result.logs,
            "rerun_mode": result.rerun_mode,
            "preserved_pin_count": result.preserved_pin_count,
            "downgraded_pin_count": result.downgraded_pin_count,
            "downgraded_pins": result.downgraded_pins,
        }
        if learning_record_warning:
            operation_result["learning_record_warning"] = learning_record_warning
        registry.complete(operation_id, result=operation_result)
    except Exception as exc:
        registry.fail(operation_id, error=str(exc))


def stage_key_for_label(label: str) -> str:
    return STAGE_BY_LABEL[label]


def group_unassigned_by_reason(
    unassigned_items: list[dict[str, Any]],
) -> tuple[dict, dict]:
    counts = {}
    groups = {}
    for item in unassigned_items:
        reason_code = item.get("reason_code") or "unknown"
        counts[reason_code] = counts.get(reason_code, 0) + 1
        groups.setdefault(reason_code, []).append(item)
    return counts, groups


def issue_context_with_proposal(item: dict[str, Any]) -> dict[str, Any]:
    context = unresolved_assignment_primitives.build_context(item)
    proposal = TimeParser.course_proposal_from_occupancy(
        TimeParser.to_minutes(context.get("original_start"), default=None),
        TimeParser.to_minutes(
            context.get("original_end"), default=None, prefer_end=True
        ),
    )
    context["proposal_start"], context["proposal_end"] = proposal or (None, None)
    return context


def issue_groups(
    counts: dict,
    groups: dict,
    reservation_labels: Optional[dict[str, dict]] = None,
) -> list[IssueGroup]:
    reservation_labels = reservation_labels or {}
    result = []
    ordered_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    for reason_code, count in ordered_counts:
        items = groups[reason_code]
        label = next(
            (str(item.get("reason")) for item in items if item.get("reason")),
            str(reason_code).replace("_", " ").title(),
        )
        issue_items = []
        for item in items:
            issue_id = unresolved_assignment_primitives.issue_id(item)
            classification = reservation_labels.get(issue_id, {})
            issue_items.append(
                Issue(
                    id=issue_id,
                    reason_code=str(reason_code),
                    message=str(item.get("reason") or label),
                    assignment_id=item.get("assignment_id"),
                    **issue_context_with_proposal(item),
                    payload=item,
                    reservation_label=classification.get("label"),
                    magnet_room=classification.get("magnet_room"),
                    reservation_note=classification.get("reservation_note"),
                )
            )
        result.append(
            IssueGroup(
                reason_code=str(reason_code),
                label=label,
                count=count,
                items=issue_items,
            )
        )
    return result


def _source_room_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(room).strip() for room in value if str(room).strip()]
    try:
        if bool(pd.isna(value)):
            return []
    except (TypeError, ValueError):
        pass
    return [
        room.strip()
        for room in str(value).replace("，", ",").split(",")
        if room.strip()
    ]


def build_source_preference_summary(
    state: dict,
    room_ids: list[str],
) -> list[dict[str, Any]]:
    rooms = set(room_ids)
    by_instructor: dict[str, dict[str, Any]] = {}
    for state_key in ("wk_df", "stu_df"):
        frame = state.get(state_key)
        if frame is None:
            continue
        records = (
            frame.to_dict(orient="records")
            if hasattr(frame, "to_dict")
            else list(frame)
        )
        for row in records:
            if not isinstance(row, dict):
                continue
            instructor_value = row.get("Instructor")
            try:
                instructor_missing = bool(pd.isna(instructor_value))
            except (TypeError, ValueError):
                instructor_missing = False
            instructor = (
                ""
                if instructor_missing
                else str(instructor_value or "").strip()
            )
            if not instructor:
                continue
            item = by_instructor.setdefault(
                instructor,
                {
                    "instructor": instructor,
                    "request_count": 0,
                    "room_variants": [],
                    "unknown_rooms": [],
                },
            )
            request_count = 1
            if state_key == "stu_df":
                request_count = 0
                for slot_index in range(1, 4):
                    date_value = row.get(f"Studio {slot_index} Date")
                    time_value = row.get(f"Studio {slot_index} Time")
                    if is_missing(date_value) and is_missing(time_value):
                        continue
                    tokens = studio_time_tokens(time_value)
                    request_count += len(tokens)
            item["request_count"] += request_count
            variant = _source_room_list(row.get("Preferred Venue"))
            if variant and variant not in item["room_variants"]:
                item["room_variants"].append(variant)
            for room in variant:
                if room not in rooms and room not in item["unknown_rooms"]:
                    item["unknown_rooms"].append(room)
    return [by_instructor[name] for name in sorted(by_instructor)]


def build_metrics(edit_session: dict) -> SchedulerMetrics:
    assignments = list(edit_session.get("assignments", []) or [])
    unresolved = list(edit_session.get("unassigned_lessons", []) or [])
    source_gaps = sum(
        1
        for item in unresolved
        if item.get("reason_code") == "missing_source_data"
    )
    return SchedulerMetrics(
        assigned=len(assignments),
        unresolved=len(unresolved),
        source_gaps=source_gaps,
    )


def build_scheduler_view(context) -> SchedulerSessionView:
    state = restore_scheduler_state(context)
    warnings = collect_scheduler_warning_messages(state)
    try:
        repair_optimizer_learning_record(
            context.loader,
            state=state,
            warnings=warnings,
        )
    except Exception as exc:
        warnings.append(
            "Optimizer learning evidence needs repair before research export: "
            f"{exc}"
        )
    runtime = build_step4_runtime(context, state)
    edit_session = ensure_step4_edit_session(state)
    assignments = [
        assignment_with_editable_proposal(item)
        for item in list(edit_session.get("assignments", []) or [])
    ]
    unresolved = [
        sanitize_legacy_payload(item)
        for item in list(edit_session.get("unassigned_lessons", []) or [])
    ]
    reservation_labels = classify_unresolved_reservations(assignments, unresolved)
    counts, groups = group_unassigned_by_reason(unresolved)
    validation_state = resolve_validation_tri_state(state, edit_session)
    return SchedulerSessionView(
        active_stage=stage_key_for_label(infer_default_scheduler_tab(state)),
        assignments=assignments,
        issues=issue_groups(counts, groups, reservation_labels),
        rooms=[sanitize_legacy_payload(room) for room in runtime.rooms_cache],
        instructors=[
            profile["name"]
            for profile in collect_instructor_profiles(context.loader, state)
        ],
        draft=DraftState(
            dirty=bool(edit_session.get("dirty")),
            can_undo=runtime.draft_controller.can_undo,
            can_redo=runtime.draft_controller.can_redo,
            validation_state=validation_state,
            unsealed=bool(edit_session.get("unsealed")),
            authority_stale=authority_stale(edit_session),
            save_status=resolve_draft_save_status(edit_session),
        ),
        metrics=build_metrics(edit_session),
        reservation_classifications={
            issue_id: ReservationClassification(**payload)
            for issue_id, payload in reservation_labels.items()
        },
        validation_authority=[
            assignment_with_editable_proposal(item)
            for item in authority_assignments(edit_session)
        ],
        source_preferences=build_source_preference_summary(
            state,
            [str(room.get("id")) for room in runtime.rooms_cache if room.get("id")],
        ),
        warnings=warnings,
        operating_window={
            **context.load_rules().get("constraints", {}).get(
                "time_range",
                {"start": "08:00", "end": "23:00"},
            ),
            "slot_minutes": 60,
        },
    )


def execute_draft_command(
    context,
    command: DraftCommand,
) -> tuple[SchedulerSessionView, list[str]]:
    """Map API draft commands onto the canonical Step 4 controller."""
    state = restore_scheduler_state(context)
    controller = build_step4_runtime(context, state).draft_controller
    edit_session = state.get("step4_edit_session")
    edit_session = edit_session if isinstance(edit_session, dict) else {}

    if command.kind == "move":
        result = controller.move(
            state,
            command.event_id,
            command.room,
            command.day,
            command.start,
            command.end,
            teacher_confirmed=command.teacher_confirmed,
            confirmation_note=command.teacher_confirmation_note,
            decision_note=command.decision_note,
        )
    elif command.kind == "assign":
        result = controller.assign(
            state,
            command.issue_id,
            command.room,
            command.day,
            command.start,
            command.end,
            teacher_confirmed=command.teacher_confirmed,
            confirmation_note=command.teacher_confirmation_note,
            decision_note=command.decision_note,
        )
    elif command.kind == "unassign":
        result = controller.unassign(
            state,
            command.event_id,
            command.label or command.event_id,
            decision_note=command.decision_note,
        )
    elif command.kind == "unassign_block":
        result = controller.unassign_block(
            state,
            command.event_ids,
            decision_note=command.decision_note,
        )
    elif command.kind == "unlock":
        result = controller.unlock(state, command.event_id)
    elif command.kind == "undo":
        result = controller.undo(state)
    elif command.kind == "redo":
        result = controller.redo(state)
    else:
        raise ValueError("Unsupported draft command: {0}".format(command.kind))

    persistence_outcome = getattr(result, "persistence_outcome", None)
    persistence_status = getattr(persistence_outcome, "status", "")
    persistence_warning = getattr(persistence_outcome, "warning", "")
    if persistence_status == "conflict":
        raise SchedulerPersistenceConflict(persistence_warning)
    warnings = list(getattr(result, "warnings", []) or [])
    if not result.success:
        raise SchedulerCommandRejected(result.message, warnings)
    if persistence_warning and persistence_warning not in warnings:
        warnings.append(persistence_warning)
    history_record = None
    active = True
    if command.kind in {"move", "assign", "unassign", "unassign_block", "redo"}:
        history = edit_session.get("history") or []
        history_record = history[-1] if history else None
    elif command.kind == "undo":
        redo_stack = edit_session.get("redo_stack") or []
        history_record = redo_stack[-1] if redo_stack else None
        active = False
    if isinstance(history_record, dict):
        try:
            record_optimizer_intervention(
                context.loader,
                state=state,
                history_record=history_record,
                active=active,
            )
        except Exception as exc:
            warnings.append(
                "Draft saved, but its optimizer intervention record was not "
                f"updated: {exc}"
            )
    return build_scheduler_view(context), warnings


def validate_draft_move(
    context,
    *,
    event_id: str,
    room: str,
    day: int,
    start: str,
    end: str,
) -> dict:
    state = restore_scheduler_state(context)
    controller = build_step4_runtime(context, state).draft_controller
    result = controller.validate_move(event_id, room, day, start, end)
    return {
        "success": bool(result.get("success")),
        "message": result.get("message"),
        "proposal_start": result.get("proposal_start"),
        "proposal_end": result.get("proposal_end"),
        "start_norm": result.get("start_norm"),
        "end_norm": result.get("end_norm"),
        "specific_date": result.get("specific_date"),
        "warnings": list(result.get("warnings", []) or []),
        "requires_teacher_confirmation": bool(
            result.get("requires_teacher_confirmation")
        ),
        "teacher_confirmation_message": result.get(
            "teacher_confirmation_message"
        ),
    }


def validate_draft_assignment(
    context,
    *,
    issue_id: str,
    room: str,
    day: int,
    start: str,
    end: str,
) -> dict:
    state = restore_scheduler_state(context)
    controller = build_step4_runtime(context, state).draft_controller
    result = controller.validate_assignment(issue_id, room, day, start, end)
    return {
        "success": bool(result.get("success")),
        "message": result.get("message"),
        "proposal_start": result.get("proposal_start"),
        "proposal_end": result.get("proposal_end"),
        "start_norm": result.get("start_norm"),
        "end_norm": result.get("end_norm"),
        "specific_date": result.get("specific_date"),
        "warnings": list(result.get("warnings", []) or []),
        "requires_teacher_confirmation": bool(
            result.get("requires_teacher_confirmation")
        ),
        "teacher_confirmation_message": result.get(
            "teacher_confirmation_message"
        ),
    }


def finalize_scheduler(context):
    """Finalize through the canonical Step 4 controller."""
    state = restore_scheduler_state(context)
    controller = build_step4_runtime(context, state).draft_controller
    edit_session = ensure_step4_edit_session(state)
    finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    edit_session["optimizer_finalized_at"] = finalized_at
    result = controller.finalize(state, loader=context.loader)
    if result.status == "committed":
        seed_validation_authority(edit_session)
        try:
            finalize_optimizer_run(
                context.loader,
                state=state,
                warnings=result.warnings,
                finalized_at=finalized_at,
            )
        except Exception as exc:
            result.save_warnings.append(
                "Schedule committed, but its optimizer learning record was not "
                f"updated: {exc}"
            )
    else:
        edit_session.pop("optimizer_finalized_at", None)
        edit_session.pop("optimizer_finalize_warnings", None)
    return result


def start_round_two(context) -> list[dict[str, Any]]:
    state = restore_scheduler_state(context)
    if not can_start_round_two(state):
        raise SchedulerCommandRejected(
            "Round two cannot start until the current round is committed "
            "with no pending draft changes."
        )
    committed = [
        sanitize_legacy_payload(booking)
        for booking in context.loader.load_bookings()
        if booking.get("committed") is True
    ]
    clear_round_two_state(state, context.session_manager)
    return committed
