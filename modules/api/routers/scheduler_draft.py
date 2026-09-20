from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    SchedulerExpectedVersionRequest,
    SchedulerInterventionRequest,
    SchedulerUnassignBlockRequest,
    SchedulerIssueAssignmentRequest,
    SchedulerIssueAssignmentValidationRequest,
    SchedulerMoveRequest,
    SchedulerMoveValidationRequest,
    SchedulerMoveValidationResult,
    SchedulerRoundStartResult,
    SchedulerSessionView,
)
from modules.api.security import require_session
from modules.api.services.scheduler import (
    DraftCommand,
    SchedulerCommandRejected,
    SchedulerPersistenceConflict,
    build_scheduler_view,
    execute_draft_command,
    restore_scheduler_state,
    reset_scheduling_workspace,
    start_round_two,
    validate_draft_assignment,
    validate_draft_move,
)
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    read_workspace_snapshot,
    require_current_version,
)
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


def _execute_versioned_draft_command(
    *,
    request: Request,
    context: SchedulerContext,
    expected_version: str,
    draft_command: DraftCommand,
) -> ApiEnvelope[SchedulerSessionView]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(
                base_dir,
                expected_version,
                context=context,
            )
            try:
                session, warnings = execute_draft_command(
                    context,
                    draft_command,
                )
            except SchedulerPersistenceConflict as exc:
                current_version = compute_workspace_version(
                    base_dir,
                    context=context,
                )
                raise WorkspaceChanged(
                    expected=expected_version,
                    current=current_version,
                ) from exc
            workspace_version = compute_workspace_version(
                base_dir,
                context=context,
            )
    except SchedulerCommandRejected as exc:
        raise ApiProblem(
            status_code=400,
            code="SCHEDULER_COMMAND_REJECTED",
            message=exc.message,
            details={"warnings": exc.warnings},
        ) from exc

    return ApiEnvelope(
        data=session,
        workspace_version=workspace_version,
        warnings=warnings
        + [item for item in session.warnings if item not in warnings],
    )


@router.post(
    "/assignments/{assignment_id}/validate-move",
    response_model=ApiEnvelope[SchedulerMoveValidationResult],
)
def validate_scheduler_assignment_move(
    assignment_id: str,
    request: Request,
    command: SchedulerMoveValidationRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerMoveValidationResult]:
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: validate_draft_move(
            context,
            event_id=assignment_id,
            room=command.room,
            day=command.day,
            start=command.start,
            end=command.end,
        ),
    )
    validation = SchedulerMoveValidationResult(**result)
    return ApiEnvelope(
        data=validation,
        workspace_version=workspace_version,
        warnings=validation.warnings,
    )


@router.post(
    "/issues/{issue_id}/validate-assignment",
    response_model=ApiEnvelope[SchedulerMoveValidationResult],
)
def validate_scheduler_issue_assignment(
    issue_id: str,
    request: Request,
    command: SchedulerIssueAssignmentValidationRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerMoveValidationResult]:
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: validate_draft_assignment(
            context,
            issue_id=issue_id,
            room=command.room,
            day=command.day,
            start=command.start,
            end=command.end,
        ),
    )
    validation = SchedulerMoveValidationResult(**result)
    return ApiEnvelope(
        data=validation,
        workspace_version=workspace_version,
        warnings=validation.warnings,
    )


@router.post(
    "/issues/{issue_id}/assign",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def assign_scheduler_issue(
    issue_id: str,
    request: Request,
    command: SchedulerIssueAssignmentRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(
            kind="assign",
            issue_id=issue_id,
            room=command.room,
            day=command.day,
            start=command.start,
            end=command.end,
            teacher_confirmed=command.teacher_confirmed,
            teacher_confirmation_note=command.teacher_confirmation_note,
            decision_note=command.decision_note,
        ),
    )


@router.post(
    "/assignments/{assignment_id}/move",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def move_scheduler_assignment(
    assignment_id: str,
    request: Request,
    command: SchedulerMoveRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(
            kind="move",
            event_id=assignment_id,
            room=command.room,
            day=command.day,
            start=command.start,
            end=command.end,
            teacher_confirmed=command.teacher_confirmed,
            teacher_confirmation_note=command.teacher_confirmation_note,
            decision_note=command.decision_note,
        ),
    )


@router.post(
    "/assignments/unassign-block",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def unassign_scheduler_block(
    request: Request,
    command: SchedulerUnassignBlockRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(
            kind="unassign_block",
            event_ids=tuple(command.assignment_ids),
            decision_note=command.decision_note,
        ),
    )


@router.post(
    "/assignments/{assignment_id}/unassign",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def unassign_scheduler_assignment(
    assignment_id: str,
    request: Request,
    command: SchedulerInterventionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(
            kind="unassign",
            event_id=assignment_id,
            decision_note=command.decision_note,
        ),
    )


@router.post(
    "/assignments/{assignment_id}/unlock",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def unlock_scheduler_assignment(
    assignment_id: str,
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(kind="unlock", event_id=assignment_id),
    )


@router.post(
    "/draft/undo",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def undo_scheduler_draft(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(kind="undo"),
    )


@router.post(
    "/draft/redo",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def redo_scheduler_draft(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    return _execute_versioned_draft_command(
        request=request,
        context=context,
        expected_version=command.expected_version,
        draft_command=DraftCommand(kind="redo"),
    )


@router.post(
    "/reset",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def reset_scheduler(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    base_dir = request.app.state.config.base_dir
    with context.mutation_lock:
        require_current_version(
            base_dir,
            command.expected_version,
            context=context,
        )
        state = restore_scheduler_state(context)
        reset_scheduling_workspace(
            context.loader,
            context.session_manager,
            state,
        )
        session = build_scheduler_view(context)
        workspace_version = compute_workspace_version(
            base_dir,
            context=context,
        )
    return ApiEnvelope(
        data=session,
        workspace_version=workspace_version,
        warnings=session.warnings,
    )


@router.post(
    "/rounds/start",
    response_model=ApiEnvelope[SchedulerRoundStartResult],
)
def start_scheduler_round(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerRoundStartResult]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(
                base_dir,
                command.expected_version,
                context=context,
            )
            locked_assignments = start_round_two(context)
            workspace_version = compute_workspace_version(
                base_dir,
                context=context,
            )
    except SchedulerCommandRejected as exc:
        raise ApiProblem(
            status_code=400,
            code="SCHEDULER_COMMAND_REJECTED",
            message=exc.message,
            details={"warnings": exc.warnings},
        ) from exc

    return ApiEnvelope(
        data=SchedulerRoundStartResult(
            locked_assignments=locked_assignments,
        ),
        workspace_version=workspace_version,
    )
