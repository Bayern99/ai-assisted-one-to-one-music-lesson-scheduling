from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from modules.api.dependencies import get_scheduler_context
from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.product import (
    DashboardData,
    SourceDataExportArtifact,
    SourceDataExportBuildResult,
    SourceDataImportApplyRequest,
    SourceDataImportPreview,
    SourceDataImportResult,
    SourceDataRecord,
    SourceDataView,
    SemesterConfigUpdateRequest,
    SemesterConfigView,
    StudentBulkDeleteRequest,
    StudentBulkDeleteResult,
    StudentDeleteRequest,
    StudentDeleteResult,
    StudentRecord,
    StudentUpdateRequest,
)
from modules.api.security import require_session
from modules.api.services import info_hub
from modules.api.services.imports import ImportPreviewNotFound
from modules.api.services.workspace import (
    WorkspaceChanged,
    compute_workspace_version,
    read_workspace_snapshot,
    require_current_version,
)
from modules.api.services.info_hub import InvalidSourceImport, ParsedSourceImport
from modules.info_hub.logic.student_service import (
    DuplicateStudentId,
    StudentNotFound,
    StudentSaveFailed,
)
from modules.scheduler.context import SchedulerContext


router = APIRouter(tags=["info-hub"], dependencies=[Depends(require_session)])
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _student_not_found(exc: StudentNotFound) -> ApiProblem:
    return ApiProblem(
        status_code=404,
        code="STUDENT_NOT_FOUND",
        message="Student not found",
        details={"student_id": exc.student_id},
    )


def _duplicate_student_id(exc: DuplicateStudentId) -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="DUPLICATE_STUDENT_ID",
        message="Student ID is duplicated",
        details={"student_id": exc.student_id},
    )


@router.get("/dashboard", response_model=ApiEnvelope[DashboardData])
def get_dashboard(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[DashboardData]:
    (summary, semester_config), workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: (
            info_hub.load_dashboard(context, request.app.state.config.base_dir),
            info_hub.load_semester_config(context),
        ),
    )
    return ApiEnvelope(
        data=DashboardData.model_validate({
            **asdict(summary),
            "semester_config": semester_config,
        }),
        workspace_version=workspace_version,
    )


@router.patch("/dashboard/semester-config", response_model=ApiEnvelope[SemesterConfigView])
def patch_semester_config(
    command: SemesterConfigUpdateRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SemesterConfigView]:
    if command.start_date > command.last_day:
        raise ApiProblem(422, "INVALID_SEMESTER_RANGE", "Semester start must be on or before the last class day")
    if command.jury_start > command.jury_end:
        raise ApiProblem(422, "INVALID_JURY_RANGE", "Jury start must be on or before jury end")
    with context.mutation_lock:
        require_current_version(
            request.app.state.config.base_dir,
            command.expected_version,
            context=context,
        )
        payload = command.model_dump(exclude={"expected_version"}, mode="json")
        info_hub.save_semester_config(context, payload)
        version = compute_workspace_version(request.app.state.config.base_dir, context=context)
    return ApiEnvelope(
        data=SemesterConfigView.model_validate(payload),
        workspace_version=version,
    )


@router.get("/students", response_model=ApiEnvelope[list[StudentRecord]])
def get_students(
    request: Request,
    query: str = "",
    instrument: str = "",
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[list[StudentRecord]]:
    students, workspace_version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: info_hub.load_students(
            context,
            query=query,
            instrument=instrument,
        ),
    )
    return ApiEnvelope(
        data=[StudentRecord.model_validate(student) for student in students],
        workspace_version=workspace_version,
    )


@router.get("/students/{student_id}", response_model=ApiEnvelope[StudentRecord])
def get_student(
    student_id: str,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[StudentRecord]:
    try:
        student, workspace_version = read_workspace_snapshot(
            request.app.state.config.base_dir,
            context,
            lambda: info_hub.load_student(context, student_id),
        )
    except StudentNotFound as exc:
        raise _student_not_found(exc) from exc
    except DuplicateStudentId as exc:
        raise _duplicate_student_id(exc) from exc
    return ApiEnvelope(
        data=StudentRecord.model_validate(student),
        workspace_version=workspace_version,
    )


@router.patch("/students/{student_id}", response_model=ApiEnvelope[StudentRecord])
def patch_student(
    student_id: str,
    command: StudentUpdateRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[StudentRecord]:
    base_dir = request.app.state.config.base_dir
    changes = command.model_dump(
        exclude={"expected_version"},
        exclude_unset=True,
    )
    if not changes:
        raise ApiProblem(
            status_code=422,
            code="VALIDATION_ERROR",
            message="At least one editable student field is required",
        )
    try:
        with context.mutation_lock:
            require_current_version(
                base_dir,
                command.expected_version,
                context=context,
            )
            info_hub.save_student(context, student_id, changes)
            student = info_hub.load_student(context, student_id)
            workspace_version = compute_workspace_version(
                base_dir,
                context=context,
            )
            warnings = context.loader.get_last_io_metadata("students.json").get(
                "warnings",
                [],
            )
    except StudentNotFound as exc:
        raise _student_not_found(exc) from exc
    except DuplicateStudentId as exc:
        raise _duplicate_student_id(exc) from exc
    except StudentSaveFailed as exc:
        raise ApiProblem(
            status_code=500,
            code="STUDENT_SAVE_FAILED",
            message="Student data could not be saved",
        ) from exc

    return ApiEnvelope(
        data=StudentRecord.model_validate(student),
        workspace_version=workspace_version,
        warnings=warnings,
    )


@router.delete("/students/{student_id}", response_model=ApiEnvelope[StudentDeleteResult])
def delete_student(
    student_id: str,
    command: StudentDeleteRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[StudentDeleteResult]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            deleted_id = info_hub.delete_student(context, student_id)
            workspace_version = compute_workspace_version(base_dir, context=context)
            warnings = context.loader.get_last_io_metadata("students.json").get("warnings", [])
    except StudentNotFound as exc:
        raise _student_not_found(exc) from exc
    except DuplicateStudentId as exc:
        raise _duplicate_student_id(exc) from exc
    except StudentSaveFailed as exc:
        raise ApiProblem(500, "STUDENT_SAVE_FAILED", "Student data could not be saved") from exc
    return ApiEnvelope(
        data=StudentDeleteResult(deleted_student_id=deleted_id),
        workspace_version=workspace_version,
        warnings=warnings,
    )


@router.post("/students/bulk-delete", response_model=ApiEnvelope[StudentBulkDeleteResult])
def bulk_delete_students(
    command: StudentBulkDeleteRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[StudentBulkDeleteResult]:
    base_dir = request.app.state.config.base_dir
    try:
        with context.mutation_lock:
            require_current_version(base_dir, command.expected_version, context=context)
            deleted_ids = info_hub.delete_students(context, command.student_ids)
            workspace_version = compute_workspace_version(base_dir, context=context)
            warnings = context.loader.get_last_io_metadata("students.json").get("warnings", [])
    except StudentNotFound as exc:
        raise _student_not_found(exc) from exc
    except DuplicateStudentId as exc:
        raise _duplicate_student_id(exc) from exc
    except StudentSaveFailed as exc:
        raise ApiProblem(500, "STUDENT_SAVE_FAILED", "Student data could not be saved") from exc
    return ApiEnvelope(
        data=StudentBulkDeleteResult(deleted_student_ids=deleted_ids),
        workspace_version=workspace_version,
        warnings=warnings,
    )


@router.get("/source-data/{dataset}", response_model=ApiEnvelope[SourceDataView])
def get_source_data(
    dataset: str,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SourceDataView]:
    if dataset not in info_hub.SOURCE_FILES:
        raise ApiProblem(404, "SOURCE_DATASET_NOT_FOUND", "Source dataset not found")
    records, version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: info_hub.load_source_dataset(context, dataset),
    )
    return ApiEnvelope(
        data=SourceDataView(
            dataset=dataset,
            records=[SourceDataRecord.model_validate(record) for record in records],
        ),
        workspace_version=version,
    )


@router.post(
    "/source-data/{dataset}/preview",
    response_model=ApiEnvelope[SourceDataImportPreview],
)
async def preview_source_data_import(
    dataset: str,
    request: Request,
    file: UploadFile = File(...),
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SourceDataImportPreview]:
    if dataset not in {"students", "rooms", "conveners"}:
        raise ApiProblem(422, "SOURCE_IMPORT_NOT_SUPPORTED", "This source dataset cannot be imported")
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        preview, version = read_workspace_snapshot(
            request.app.state.config.base_dir,
            context,
            lambda: info_hub.build_source_import_preview(
                dataset,
                file.filename or f"{dataset}.xlsx",
                content,
            ),
        )
    except InvalidSourceImport as exc:
        raise ApiProblem(422, "INVALID_SOURCE_IMPORT", str(exc)) from exc
    request.app.state.import_preview_store.put(preview, source_version=version)
    return ApiEnvelope(
        data=SourceDataImportPreview(
            preview_id=preview.id,
            dataset=preview.dataset,
            file_name=preview.file_name,
            columns=list(preview.columns),
            row_count=len(preview.records),
            sample=[SourceDataRecord.model_validate(record) for record in preview.records[:5]],
        ),
        workspace_version=version,
    )


@router.post(
    "/source-data/import/apply",
    response_model=ApiEnvelope[SourceDataImportResult],
)
def apply_source_data_import(
    command: SourceDataImportApplyRequest,
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SourceDataImportResult]:
    def apply_locked(entry):
        preview = entry.preview
        if not isinstance(preview, ParsedSourceImport):
            raise ImportPreviewNotFound(command.preview_id)
        with context.mutation_lock:
            version = require_current_version(
                request.app.state.config.base_dir,
                command.expected_version,
                context=context,
            )
            if entry.source_version != version:
                raise WorkspaceChanged(expected=entry.source_version, current=version)
            count = info_hub.apply_source_import(context, preview)
            next_version = compute_workspace_version(
                request.app.state.config.base_dir,
                context=context,
            )
            warnings = context.loader.get_last_io_metadata(
                info_hub.SOURCE_FILES[preview.dataset]
            ).get("warnings", [])
        return preview.dataset, count, next_version, warnings

    try:
        dataset, count, version, warnings = request.app.state.import_preview_store.consume(
            command.preview_id,
            apply_locked,
        )
    except ImportPreviewNotFound as exc:
        raise ApiProblem(404, "IMPORT_PREVIEW_NOT_FOUND", "Import preview not found or expired") from exc
    return ApiEnvelope(
        data=SourceDataImportResult(dataset=dataset, records_written=count),
        workspace_version=version,
        warnings=warnings,
    )


@router.post(
    "/source-data/exports/build",
    response_model=ApiEnvelope[SourceDataExportBuildResult],
)
def build_source_data_export(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SourceDataExportBuildResult]:
    (backup_content, student_content), version = read_workspace_snapshot(
        request.app.state.config.base_dir,
        context,
        lambda: (
            info_hub.build_source_backup(context),
            info_hub.build_student_register(context),
        ),
    )
    backup_id = request.app.state.artifact_registry.register(
        scope="source-data",
        filename="Source_Data_Backup.xlsx",
        mime_type=XLSX_MIME,
        content=backup_content,
    )
    students_id = request.app.state.artifact_registry.register(
        scope="source-data",
        filename="Student_Register.xlsx",
        mime_type=XLSX_MIME,
        content=student_content,
    )
    return ApiEnvelope(
        data=SourceDataExportBuildResult(artifacts=[
            SourceDataExportArtifact(
                artifact_id=backup_id,
                filename="Source_Data_Backup.xlsx",
                mime_type=XLSX_MIME,
            ),
            SourceDataExportArtifact(
                artifact_id=students_id,
                filename="Student_Register.xlsx",
                mime_type=XLSX_MIME,
            ),
        ]),
        workspace_version=version,
    )


@router.get("/source-data/exports/{artifact_id}")
def download_source_data_export(request: Request, artifact_id: str) -> Response:
    artifact = request.app.state.artifact_registry.get(artifact_id, scope="source-data")
    if artifact is None:
        raise ApiProblem(404, "ARTIFACT_NOT_FOUND", "Source data export artifact not found")
    return Response(
        content=artifact.content,
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
