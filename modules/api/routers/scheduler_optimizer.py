from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    OptimizerLearningView,
    SchedulerOptimizeAccepted,
    SchedulerOptimizerPreflight,
    SchedulerOptimizeRequest,
)
from modules.api.security import require_session
from modules.api.services.scheduler import run_optimizer_operation
from modules.api.services.scheduler import restore_scheduler_state
from modules.api.services.workspace import (
    compute_workspace_version,
    read_workspace_snapshot,
    require_current_version,
)
from modules.scheduler.logic.preflight import collect_optimizer_preflight
from modules.scheduler.logic.optimizer_learning_record import (
    get_optimizer_learning_view,
    repair_optimizer_learning_record,
)
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


@router.get(
    "/optimize/records",
    response_model=ApiEnvelope[OptimizerLearningView],
)
def get_optimizer_learning_records(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[OptimizerLearningView]:
    with context.mutation_lock:
        repair_optimizer_learning_record(
            context.loader,
            state=restore_scheduler_state(context),
        )
        view = OptimizerLearningView(
            **get_optimizer_learning_view(context.loader)
        )
        workspace_version = compute_workspace_version(
            request.app.state.config.base_dir,
            context=context,
        )
    return ApiEnvelope(data=view, workspace_version=workspace_version)


@router.get(
    "/optimize/preflight",
    response_model=ApiEnvelope[SchedulerOptimizerPreflight],
)
def get_optimizer_preflight(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerOptimizerPreflight]:
    def collect_current_preflight():
        state = restore_scheduler_state(context)
        return collect_optimizer_preflight(
            context.loader,
            default_rules=context.default_rules,
            weekly_df=state.get("wk_df"),
            studio_df=state.get("stu_df"),
            draft=state.get("step4_edit_session"),
        )

    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        collect_current_preflight,
    )
    return ApiEnvelope(
        data=SchedulerOptimizerPreflight(**result),
        workspace_version=workspace_version,
    )


@router.post(
    "/optimize",
    response_model=ApiEnvelope[SchedulerOptimizeAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
def optimize_scheduler(
    request: Request,
    command: SchedulerOptimizeRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerOptimizeAccepted]:
    base_dir = request.app.state.config.base_dir
    workspace_version = require_current_version(
        base_dir,
        command.expected_version,
        context=context,
    )
    state = restore_scheduler_state(context)
    edit_session = state.get("step4_edit_session") or {}
    if bool(edit_session.get("dirty")) and command.rerun_mode is None:
        raise ApiProblem(
            status_code=409,
            code="OPTIMIZER_RERUN_MODE_REQUIRED",
            message="The Step 4 draft has unsaved edits. Choose preserve pinned edits or start fresh before rerunning.",
        )
    rerun_mode = command.rerun_mode or "fresh"
    operation = request.app.state.operation_registry.create("optimizer")
    request.app.state.operation_executor.submit(
        run_optimizer_operation,
        context=context,
        base_dir=base_dir,
        expected_version=command.expected_version,
        registry=request.app.state.operation_registry,
        operation_id=operation.id,
        rerun_mode=rerun_mode,
    )
    return ApiEnvelope(
        data=SchedulerOptimizeAccepted(
            operation_id=operation.id,
            status="queued",
        ),
        workspace_version=workspace_version,
    )
