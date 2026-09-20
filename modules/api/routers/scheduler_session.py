from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from modules.api.dependencies import get_scheduler_context
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import SchedulerSessionView
from modules.api.security import require_session
from modules.api.services.scheduler import build_scheduler_view
from modules.api.services.workspace import read_workspace_snapshot
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


@router.get("/session", response_model=ApiEnvelope[SchedulerSessionView])
def get_scheduler_session(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerSessionView]:
    view, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: build_scheduler_view(context),
    )
    return ApiEnvelope(
        data=view,
        workspace_version=workspace_version,
        warnings=view.warnings,
    )
