from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import ValidationError

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.pi_intervention import (
    PiReviewDraftRequest,
    PiReviewDraftView,
    ReconciliationApplyRequest,
    ReconciliationDecisionRequest,
    ReconciliationInvestigateRequest,
    ReconciliationSimulateParams,
    ReconciliationSubmitParams,
    ReconciliationToolRequest,
)
from modules.api.schemas.scheduler import SchedulerOptimizeAccepted
from modules.api.schemas.scheduler_resolution import ResolutionAdvice
from modules.api.security import require_session
from modules.api.services.pi_reconciliation import (
    PiReconciliationError,
    build_reconciliation_investigation,
    apply_reconciliation,
    decide_reconciliation,
    run_pi_reconciliation_operation,
)
from modules.api.services.scheduler import (
    SchedulerCommandRejected,
    SchedulerPersistenceConflict,
)
from modules.api.services.scheduler_resolution import (
    review_draft,
    build_resolution_view,
)
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    require_current_version,
)
from modules.scheduler.logic.resolution_package import PackageRejected
from modules.scheduler.context import SchedulerContext


router = APIRouter(
    prefix="/scheduler/resolution",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)
internal_router = APIRouter(prefix="/internal/pi-intervention", tags=["internal"])


@router.post(
    "/review-draft",
    response_model=ApiEnvelope[PiReviewDraftView],
)
def review_current_draft(
    command: PiReviewDraftRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[PiReviewDraftView]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(
                base_dir,
                command.expected_version,
                context=context,
            )
            review = review_draft(context)
            workspace_version = compute_workspace_version(base_dir, context=context)
    except SchedulerCommandRejected as exc:
        raise ApiProblem(
            400,
            "PI_DRAFT_REVIEW_REJECTED",
            exc.message,
        ) from exc
    return ApiEnvelope(
        data=review,
        workspace_version=workspace_version,
    )


@router.post(
    "/reconciliation/investigate",
    response_model=ApiEnvelope[SchedulerOptimizeAccepted],
    status_code=status.HTTP_202_ACCEPTED,
)
def investigate_reconciliation(
    command: ReconciliationInvestigateRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerOptimizeAccepted]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            investigation = build_reconciliation_investigation(
                context,
                expected_version=command.expected_version,
                day=command.day,
                goal=command.goal,
                protect_instructors=command.protect_instructors,
                allow_time_change_instructors=command.allow_time_change_instructors,
                locked_room_days=[
                    item.model_dump(mode="json") for item in command.locked_room_days
                ],
                max_tool_calls=command.max_tool_calls,
            )
    except SchedulerCommandRejected as exc:
        raise ApiProblem(400, "PI_RECONCILIATION_SCOPE_REJECTED", exc.message) from exc
    operation = request.app.state.operation_registry.create("pi_reconciliation")
    server = request.scope.get("server") or ("127.0.0.1", 80)
    port = int(server[1])
    if not 1 <= port <= 65535:
        raise ApiProblem(500, "PI_RECONCILIATION_CALLBACK_INVALID", "Pi callback unavailable")
    tool_url = f"http://127.0.0.1:{port}/api/internal/pi-intervention/reconciliation-tool"
    request.app.state.operation_executor.submit(
        run_pi_reconciliation_operation,
        context=context,
        registry=request.app.state.operation_registry,
        operation_id=operation.id,
        investigation=investigation,
        model=command.model,
        provider=command.provider or None,
        thinking=command.thinking_level or None,
        tool_url=tool_url,
        capability_store=request.app.state.pi_reconciliation_capabilities,
    )
    return ApiEnvelope(
        data=SchedulerOptimizeAccepted(operation_id=operation.id, status="queued"),
        workspace_version=command.expected_version,
    )


@router.post(
    "/reconciliation/{investigation_id}/decision",
    response_model=ApiEnvelope[ResolutionAdvice],
)
def decide_reconciliation_investigation(
    investigation_id: str,
    command: ReconciliationDecisionRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[ResolutionAdvice]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            decide_reconciliation(
                context,
                investigation_id=investigation_id,
                decision=command.decision,
                note=command.note,
            )
            advice = build_resolution_view(context)
            workspace_version = compute_workspace_version(base_dir, context=context)
    except PiReconciliationError as exc:
        raise ApiProblem(400, "PI_RECONCILIATION_DECISION_REJECTED", str(exc)) from exc
    except SchedulerCommandRejected as exc:
        raise ApiProblem(400, "PI_RECONCILIATION_DECISION_REJECTED", exc.message) from exc
    return ApiEnvelope(data=ResolutionAdvice(**advice), workspace_version=workspace_version)


@router.post(
    "/reconciliation/{investigation_id}/apply",
    response_model=ApiEnvelope[ResolutionAdvice],
)
def apply_reconciliation_investigation(
    investigation_id: str,
    command: ReconciliationApplyRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[ResolutionAdvice]:
    base_dir = request.app.state.config.base_dir
    apply_warnings: list[str] = []
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            _result, record_update_error = apply_reconciliation(
                context,
                investigation_id=investigation_id,
                simulation_id=command.simulation_id,
                expected_version=command.expected_version,
                confirmed_teacher_aliases=command.confirmed_teacher_aliases,
                confirmed_confirmation_ids=command.confirmed_confirmation_ids,
                authorized_sacrifice_aliases=command.authorized_sacrifice_aliases,
                note=command.note,
            )
            if record_update_error:
                apply_warnings.append(
                    "The schedule change was applied and saved, but its task record "
                    f"could not be updated: {record_update_error}"
                )
            advice = build_resolution_view(context)
            workspace_version = compute_workspace_version(base_dir, context=context)
    except (PiReconciliationError, SchedulerCommandRejected) as exc:
        message = exc.message if isinstance(exc, SchedulerCommandRejected) else str(exc)
        raise ApiProblem(400, "PI_RECONCILIATION_APPLY_REJECTED", message) from exc
    except SchedulerPersistenceConflict as exc:
        current = compute_workspace_version(base_dir, context=context)
        raise WorkspaceChanged(expected=command.expected_version, current=current) from exc
    return ApiEnvelope(
        data=ResolutionAdvice(**advice),
        workspace_version=workspace_version,
        warnings=apply_warnings,
    )


@internal_router.post("/reconciliation-tool")
def use_pi_reconciliation_tool(
    command: ReconciliationToolRequest,
    request: Request,
    capability: str = Header(alias="X-PI-Agent-Capability"),
    context: SchedulerContext = Depends(get_scheduler_context),
):
    store = request.app.state.pi_reconciliation_capabilities
    try:
        scope = store.resolve(capability)
        if command.action == "inspect":
            focus_aliases = command.params.get("focus_aliases")
            if focus_aliases is not None and (
                not isinstance(focus_aliases, list)
                or any(not isinstance(item, str) or not item.strip() for item in focus_aliases)
            ):
                raise PiReconciliationError("focus_aliases must be a list of aliases.")
            result = store.inspect(capability, focus_aliases or scope.get("focus_aliases") or None)
        elif command.action == "simulate":
            params = ReconciliationSimulateParams.model_validate(command.params)
            current = compute_workspace_version(request.app.state.config.base_dir, context=context)
            if current != scope["workspace_version"]:
                raise PiReconciliationError("The reconciliation snapshot is stale; refresh the investigation.")
            result = store.simulate(
                capability,
                [item.model_dump(mode="json") for item in params.changes],
            )
        else:
            params = ReconciliationSubmitParams.model_validate(command.params)
            result = store.submit(capability, params.model_dump(mode="json"))
        return {"data": result, "error": None}
    except ValidationError as exc:
        raise ApiProblem(
            422,
            "PI_RECONCILIATION_TOOL_INPUT_INVALID",
            "Reconciliation tool input is invalid",
            details={"errors": exc.errors(include_url=False)},
        ) from exc
    except PiReconciliationError as exc:
        raise ApiProblem(403, "PI_RECONCILIATION_CAPABILITY_REJECTED", str(exc)) from exc
    except PackageRejected as exc:
        raise ApiProblem(400, "PI_RECONCILIATION_TOOL_REJECTED", str(exc)) from exc
