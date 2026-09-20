from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    SchedulerExpectedVersionRequest,
    SchedulerSessionView,
)
from modules.api.security import require_session
from modules.api.services.scheduler import (
    SchedulerPersistenceConflict,
    build_scheduler_view,
    restore_scheduler_state,
)
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    require_current_version,
)
from modules.scheduler.context import SchedulerContext
from modules.scheduler.logic.stage_service import StageResult, stage_schedule


router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


@router.post(
    "/stage",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def stage_scheduler_schedule(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    base_dir = request.app.state.config.base_dir
    with context.mutation_lock:
        require_current_version(base_dir, command.expected_version, context=context)
        state = restore_scheduler_state(context)
        result: StageResult = stage_schedule(
            context,
            state,
            expected_mtime=state.get("scheduler_session_mtime"),
        )
        if result.status == "conflict":
            current_version = compute_workspace_version(base_dir, context=context)
            raise WorkspaceChanged(
                expected=command.expected_version,
                current=current_version,
            )
        if not result.success:
            raise ApiProblem(
                status_code=400,
                code="SCHEDULER_STAGE_REJECTED",
                message=result.message or "Schedule could not be staged.",
                details={"warnings": result.warnings},
            )
        session = build_scheduler_view(context)
        workspace_version = compute_workspace_version(base_dir, context=context)

    warnings = list(result.warnings)
    for warning in session.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return ApiEnvelope(
        data=session,
        workspace_version=workspace_version,
        warnings=warnings,
    )
