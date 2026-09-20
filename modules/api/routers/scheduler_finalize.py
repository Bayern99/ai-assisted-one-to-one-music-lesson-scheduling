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
    build_scheduler_view,
    finalize_scheduler,
    sanitize_legacy_payload,
)
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    require_current_version,
)
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


@router.post(
    "/finalize",
    response_model=ApiEnvelope[SchedulerSessionView],
)
def finalize_schedule(
    request: Request,
    command: SchedulerExpectedVersionRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    base_dir = request.app.state.config.base_dir
    with context.mutation_lock:
        require_current_version(base_dir, command.expected_version, context=context)
        result = finalize_scheduler(context)
        if result.status == "blocked":
            if result.error == "Stage before finalizing.":
                raise ApiProblem(
                    status_code=400,
                    code="SCHEDULER_FINALIZE_REQUIRES_STAGE",
                    message=result.error,
                    details={"warnings": result.warnings},
                )
            raise ApiProblem(
                status_code=400,
                code="SCHEDULER_FINALIZE_CONFLICT",
                message="Schedule has conflicts that must be resolved before finalizing",
                details={
                    "conflicts": [
                        {
                            "event": sanitize_legacy_payload(event),
                            "conflict": sanitize_legacy_payload(conflict),
                        }
                        for event, conflict in result.conflicts
                    ],
                    "warnings": result.warnings,
                },
            )
        if result.status == "conflict":
            current_version = compute_workspace_version(base_dir, context=context)
            raise WorkspaceChanged(
                expected=command.expected_version,
                current=current_version,
            )
        if result.status != "committed":
            raise ApiProblem(
                status_code=500,
                code="SCHEDULER_FINALIZE_FAILED",
                message=result.error or "Schedule could not be finalized",
                details={"warnings": result.warnings},
            )
        session = build_scheduler_view(context)
        workspace_version = compute_workspace_version(base_dir, context=context)

    warnings = list(result.warnings)
    for warning in result.save_warnings + session.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return ApiEnvelope(
        data=session,
        workspace_version=workspace_version,
        warnings=warnings,
    )
