from fastapi import APIRouter, Depends, Request

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler_resolution import (
    PianoLeverageApplyRequest,
    ResolutionAdvice,
    ResolutionWaitingRequest,
)
from modules.api.schemas.scheduler import SchedulerSessionView
from modules.api.security import require_session
from modules.api.services.scheduler import SchedulerCommandRejected, SchedulerPersistenceConflict
from modules.api.services.scheduler_resolution import (
    apply_piano_leverage,
    build_resolution_view,
    update_resolution_waiting,
)
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    read_workspace_snapshot,
    require_current_version,
)
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler/resolution",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


@router.get("/advice", response_model=ApiEnvelope[ResolutionAdvice])
def get_resolution_advice(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[ResolutionAdvice]:
    advice, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: build_resolution_view(context),
    )
    return ApiEnvelope(data=ResolutionAdvice(**advice), workspace_version=workspace_version)


@router.post(
    "/piano-leverage/{proposal_id}/apply",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def apply_piano_leverage_proposal(
    proposal_id: str,
    command: PianoLeverageApplyRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            session, warnings = apply_piano_leverage(
                context,
                proposal_id=proposal_id,
                teacher_confirmed=command.teacher_confirmed,
                confirmation_note=command.confirmation_note,
            )
            workspace_version = compute_workspace_version(base_dir, context=context)
    except SchedulerPersistenceConflict as exc:
        current = compute_workspace_version(base_dir, context=context)
        raise WorkspaceChanged(expected=command.expected_version, current=current) from exc
    except SchedulerCommandRejected as exc:
        raise ApiProblem(
            status_code=400,
            code="SCHEDULER_PIANO_LEVERAGE_REJECTED",
            message=exc.message,
            details={"warnings": exc.warnings},
        ) from exc
    return ApiEnvelope(
        data=session,
        workspace_version=workspace_version,
        warnings=warnings,
    )


@router.post(
    "/cases/{case_id}/waiting",
    response_model=ApiEnvelope[ResolutionAdvice],
)
def set_resolution_waiting(
    case_id: str,
    command: ResolutionWaitingRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[ResolutionAdvice]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            advice = update_resolution_waiting(
                context,
                case_id=case_id,
                waiting=command.waiting,
                note=command.note,
            )
            workspace_version = compute_workspace_version(base_dir, context=context)
    except SchedulerPersistenceConflict as exc:
        current = compute_workspace_version(base_dir, context=context)
        raise WorkspaceChanged(expected=command.expected_version, current=current) from exc
    except SchedulerCommandRejected as exc:
        raise ApiProblem(
            status_code=400,
            code="SCHEDULER_RESOLUTION_WAITING_REJECTED",
            message=exc.message,
        ) from exc
    return ApiEnvelope(data=ResolutionAdvice(**advice), workspace_version=workspace_version)
