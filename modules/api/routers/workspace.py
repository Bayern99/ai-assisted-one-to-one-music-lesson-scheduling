from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from modules.api.dependencies import get_scheduler_context
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.workspace import WorkspaceData
from modules.api.security import require_session
from modules.api.services.workspace import read_workspace_snapshot
from modules.scheduler.context import SchedulerContext
from modules.shared.health_check import run_health_check

router = APIRouter(tags=["workspace"], dependencies=[Depends(require_session)])


@router.get("/workspace", response_model=ApiEnvelope[WorkspaceData])
def get_workspace(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[WorkspaceData]:
    base_dir = request.app.state.config.base_dir
    editable_data, workspace_version = read_workspace_snapshot(
        base_dir,
        context,
        lambda: (
            context.loader.load_workflow_state(),
            context.session_manager.load_activity(),
        ),
    )
    workflow_state, activity = editable_data
    data = WorkspaceData(
        workflow_state=workflow_state,
        activity=activity,
        health=run_health_check(base_dir=str(base_dir)),
    )
    return ApiEnvelope(
        data=data,
        workspace_version=workspace_version,
    )
