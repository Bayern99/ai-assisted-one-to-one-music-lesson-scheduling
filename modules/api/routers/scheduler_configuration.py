from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile

from modules.api.dependencies import get_scheduler_context
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    SchedulerLectureValidationRequest,
    SchedulerLectureValidationResult,
    SchedulerLectureCsvPreview,
    SchedulerLecturesSaveRequest,
    SchedulerLecturesView,
    SchedulerRulesSaveRequest,
    SchedulerReconciliationReport,
    SchedulerRulesView,
)
from modules.api.security import require_session
from modules.api.services import scheduler_configuration
from modules.api.services.workspace import (
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


@router.get("/rules", response_model=ApiEnvelope[SchedulerRulesView])
def get_scheduler_rules(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerRulesView]:
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: scheduler_configuration.load_rules(context),
    )
    return ApiEnvelope(
        data=SchedulerRulesView(**result),
        workspace_version=workspace_version,
    )


@router.get(
    "/rules/reconciliation",
    response_model=ApiEnvelope[SchedulerReconciliationReport],
)
def get_scheduler_reconciliation(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerReconciliationReport]:
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: scheduler_configuration.reconcile_scheduler_data(context),
    )
    return ApiEnvelope(
        data=SchedulerReconciliationReport(**result),
        workspace_version=workspace_version,
    )


@router.put("/rules", response_model=ApiEnvelope[SchedulerRulesView])
def put_scheduler_rules(
    request: Request,
    command: SchedulerRulesSaveRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerRulesView]:
    base_dir = request.app.state.config.base_dir
    with context.mutation_lock:
        require_current_version(
            base_dir,
            command.expected_version,
            context=context,
        )
        try:
            result = scheduler_configuration.save_rules(context, command.rules)
        except ValueError as exc:
            from modules.api.errors import ApiProblem

            raise ApiProblem(
                status_code=422,
                code="INVALID_SCHEDULING_RULES",
                message="Scheduling rules contain invalid values",
                details={"reason": str(exc)},
            ) from exc
        workspace_version = compute_workspace_version(
            base_dir,
            context=context,
        )
    return ApiEnvelope(
        data=SchedulerRulesView(**result),
        workspace_version=workspace_version,
    )


@router.get("/lectures", response_model=ApiEnvelope[SchedulerLecturesView])
def get_scheduler_lectures(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerLecturesView]:
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: scheduler_configuration.load_lectures(context),
    )
    return ApiEnvelope(
        data=SchedulerLecturesView(**result),
        workspace_version=workspace_version,
    )


@router.post(
    "/lectures/preview",
    response_model=ApiEnvelope[SchedulerLectureCsvPreview],
)
async def preview_scheduler_lectures(
    request: Request,
    file: UploadFile = File(...),
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerLectureCsvPreview]:
    file_name = file.filename or "lectures.csv"
    file_bytes = await file.read()
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: scheduler_configuration.preview_lecture_csv(
            context,
            file_name,
            file_bytes,
        ),
    )
    response_data = SchedulerLectureCsvPreview(**result)
    return ApiEnvelope(
        data=response_data,
        workspace_version=workspace_version,
        warnings=response_data.warnings,
    )


@router.post(
    "/lectures/validate",
    response_model=ApiEnvelope[SchedulerLectureValidationResult],
)
def validate_scheduler_lectures(
    request: Request,
    command: SchedulerLectureValidationRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerLectureValidationResult]:
    lectures = [lecture.model_dump() for lecture in command.lectures]
    result, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: scheduler_configuration.validate_lectures(context, lectures),
    )
    return ApiEnvelope(
        data=SchedulerLectureValidationResult(**result),
        workspace_version=workspace_version,
    )


@router.put(
    "/lectures",
    response_model=ApiEnvelope[SchedulerLecturesView],
)
def put_scheduler_lectures(
    request: Request,
    command: SchedulerLecturesSaveRequest,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerLecturesView]:
    base_dir = request.app.state.config.base_dir
    with context.mutation_lock:
        require_current_version(
            base_dir,
            command.expected_version,
            context=context,
        )
        lectures = [lecture.model_dump() for lecture in command.lectures]
        result = scheduler_configuration.save_lectures(context, lectures)
        workspace_version = compute_workspace_version(
            base_dir,
            context=context,
        )
    return ApiEnvelope(
        data=SchedulerLecturesView(lectures=result["lectures"]),
        workspace_version=workspace_version,
        warnings=result["warnings"],
    )
