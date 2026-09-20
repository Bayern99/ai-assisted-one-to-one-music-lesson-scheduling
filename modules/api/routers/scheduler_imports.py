from __future__ import annotations

import hashlib
from typing import Any, Literal, Optional, Union

import pandas as pd
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import ValidationError

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    SchedulerImportApplyRequest,
    SchedulerImportPreview,
    SchedulerImportResult,
    SchedulerSessionView,
    SchedulerWorkbookImportPreview,
    SchedulerWorkbookImportResult,
    SchedulerWorkbookSheetPreview,
)
from modules.api.security import require_session
from modules.api.services.imports import (
    AtomicImportApplyFailed,
    ImportPreview,
    ImportPreviewNotFound,
    InvalidWorkbookSchema,
    StoredImportPreview,
    WorkbookImportPreview,
    apply_preview,
    build_import_preview,
    build_workbook_import_preview,
)
from modules.api.services.scheduler import build_scheduler_view, restore_scheduler_state
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    read_workspace_snapshot,
    require_current_version,
)
from modules.scheduler.context import SchedulerContext
from modules.scheduler.logic.instructor_time_integrity import format_instructor_conflict


router = APIRouter(
    prefix="/scheduler/import",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)

SchedulerPreviewResponse = Union[
    SchedulerImportPreview,
    SchedulerWorkbookImportPreview,
]
SchedulerApplyResponse = Union[
    SchedulerImportResult,
    SchedulerWorkbookImportResult,
]


def _sample_value(value: Any) -> Any:
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _workbook_preview_response(
    preview: WorkbookImportPreview,
) -> SchedulerWorkbookImportPreview:
    summaries = []
    for sheet in preview.parsed_workbook.sheets:
        sample_rows = [
            {
                str(column): _sample_value(value)
                for column, value in row.items()
            }
            for row in sheet.frame.head(5).to_dict(orient="records")
        ]
        summaries.append(
            SchedulerWorkbookSheetPreview(
                sheet_name=sheet.sheet_name,
                normalized_name=sheet.normalized_name,
                role=sheet.role,
                header_row=sheet.header_row,
                row_count=len(sheet.frame),
                columns=[str(column) for column in sheet.frame.columns],
                sample_rows=sample_rows,
                warnings=sheet.warnings,
                blocking_errors=sheet.blocking_errors,
            )
        )
    return SchedulerWorkbookImportPreview(
        preview_id=preview.id,
        file_name=preview.file_name,
        file_size=preview.file_size,
        fingerprint=preview.fingerprint,
        sheets=summaries,
        warnings=preview.parsed_workbook.warnings,
        blocking_errors=preview.parsed_workbook.blocking_errors
        + [format_instructor_conflict(item) for item in preview.instructor_conflicts],
        instructor_conflicts=preview.instructor_conflicts,
        possible_instructor_duplicates=preview.possible_instructor_duplicates,
    )


@router.post(
    "/preview",
    response_model=ApiEnvelope[SchedulerPreviewResponse],
)
async def preview_scheduler_import(
    request: Request,
    slot: Optional[Literal["weekly", "studio"]] = None,
    file: UploadFile = File(...),
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerPreviewResponse]:
    file_name = file.filename or "upload.xlsx"
    file_bytes = await file.read()
    try:
        def build_preview():
            if slot is None:
                return build_workbook_import_preview(file_name, file_bytes)
            state = restore_scheduler_state(context)
            counterpart = state.get("stu_df" if slot == "weekly" else "wk_df")
            return build_import_preview(
                slot,
                file_name,
                file_bytes,
                counterpart=counterpart,
            )

        preview, workspace_version = read_workspace_snapshot(
            request.app.state.config.base_dir,
            context,
            build_preview,
        )
    except InvalidWorkbookSchema as exc:
        raise ApiProblem(
            status_code=400,
            code="INVALID_WORKBOOK_SCHEMA",
            message=str(exc),
        ) from exc
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="INVALID_WORKBOOK",
            message=str(exc),
        ) from exc

    request.app.state.import_preview_store.put(
        preview,
        source_version=workspace_version,
    )
    if isinstance(preview, ImportPreview):
        response_data: SchedulerPreviewResponse = SchedulerImportPreview(
            preview_id=preview.id,
            slot=preview.slot,
            file_name=preview.file_name,
            sheet_name=preview.sheet_name,
            row_count=preview.row_count,
            columns=preview.columns,
            instructor_conflicts=preview.instructor_conflicts,
            blocking_errors=[
                format_instructor_conflict(item)
                for item in preview.instructor_conflicts
            ],
        )
    else:
        response_data = _workbook_preview_response(preview)
    return ApiEnvelope(data=response_data, workspace_version=workspace_version)


@router.post(
    "/apply",
    response_model=ApiEnvelope[SchedulerApplyResponse],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": SchedulerImportApplyRequest.model_json_schema()
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": [
                            "file",
                            "preview_id",
                            "fingerprint",
                            "expected_version",
                        ],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "preview_id": {"type": "string"},
                            "fingerprint": {"type": "string"},
                            "expected_version": {"type": "string"},
                        },
                    }
                },
            },
        }
    },
)
async def apply_scheduler_import(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerApplyResponse]:
    base_dir = request.app.state.config.base_dir
    content_type = request.headers.get("content-type", "").lower()
    uploaded_bytes = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        preview_id = str(form.get("preview_id") or "")
        expected_version = str(form.get("expected_version") or "")
        fingerprint = str(form.get("fingerprint") or "")
        uploaded_file = form.get("file")
        if (
            not preview_id
            or not expected_version
            or not fingerprint
            or uploaded_file is None
            or not hasattr(uploaded_file, "read")
        ):
            raise ApiProblem(
                status_code=422,
                code="INVALID_IMPORT_APPLY",
                message="Workbook apply requires file, fingerprint, preview_id, and expected_version",
            )
        uploaded_bytes = await uploaded_file.read()
        try:
            command = SchedulerImportApplyRequest(
                preview_id=preview_id,
                expected_version=expected_version,
                fingerprint=fingerprint,
            )
        except ValidationError as exc:
            raise ApiProblem(
                status_code=422,
                code="INVALID_IMPORT_APPLY",
                message="Invalid workbook apply fields",
                details={"validation": exc.errors()},
            ) from exc
    else:
        try:
            command = SchedulerImportApplyRequest(**(await request.json()))
        except (ValidationError, ValueError, TypeError) as exc:
            raise ApiProblem(
                status_code=422,
                code="INVALID_IMPORT_APPLY",
                message="Invalid scheduler import apply request",
            ) from exc

    if uploaded_bytes is not None:
        stored = request.app.state.import_preview_store.get(command.preview_id)
        if stored is None:
            raise ApiProblem(
                status_code=404,
                code="IMPORT_PREVIEW_NOT_FOUND",
                message="Import preview not found or expired",
            )
        preview_fingerprint = getattr(stored.preview, "fingerprint", None)
        uploaded_fingerprint = hashlib.sha256(uploaded_bytes).hexdigest()
        if (
            not preview_fingerprint
            or command.fingerprint != preview_fingerprint
            or uploaded_fingerprint != preview_fingerprint
        ):
            raise ApiProblem(
                status_code=409,
                code="IMPORT_FILE_CHANGED",
                message="Workbook changed after preview; preview the file again",
                details={
                    "preview_fingerprint": preview_fingerprint,
                    "uploaded_fingerprint": uploaded_fingerprint,
                },
            )

    def apply_locked(
        entry: StoredImportPreview,
    ) -> tuple[dict, SchedulerSessionView, str]:
        with context.mutation_lock:
            current_version = require_current_version(
                base_dir,
                command.expected_version,
                context=context,
            )
            if entry.source_version != current_version:
                raise WorkspaceChanged(
                    expected=entry.source_version,
                    current=current_version,
                )
            result = apply_preview(
                context,
                restore_scheduler_state(context),
                entry.preview,
            )
            session = build_scheduler_view(context)
            workspace_version = compute_workspace_version(
                base_dir,
                context=context,
            )
        return result, session, workspace_version

    try:
        result, session, workspace_version = (
            request.app.state.import_preview_store.consume(
                command.preview_id,
                apply_locked,
            )
        )
    except ImportPreviewNotFound as exc:
        raise ApiProblem(
            status_code=404,
            code="IMPORT_PREVIEW_NOT_FOUND",
            message="Import preview not found or expired",
        ) from exc
    except InvalidWorkbookSchema as exc:
        raise ApiProblem(
            status_code=400,
            code="INVALID_WORKBOOK_SCHEMA",
            message=str(exc),
        ) from exc
    except AtomicImportApplyFailed as exc:
        current_version = compute_workspace_version(
            base_dir,
            context=context,
        )
        if exc.rollback_complete and (
            exc.conflicting_paths
            or current_version != command.expected_version
        ):
            raise WorkspaceChanged(
                expected=command.expected_version,
                current=current_version,
            ) from exc
        raise ApiProblem(
            status_code=422,
            code="IMPORT_APPLY_FAILED",
            message="Scheduler workbook could not be applied atomically",
            details={"reason": str(exc)},
        ) from exc

    if isinstance(result, dict) and "state_key" in result:
        response_data: SchedulerApplyResponse = SchedulerImportResult(
            session=session,
            **result,
        )
    else:
        response_data = SchedulerWorkbookImportResult(
            session=session,
            **result,
        )
    return ApiEnvelope(
        data=response_data,
        workspace_version=workspace_version,
        warnings=session.warnings,
    )
