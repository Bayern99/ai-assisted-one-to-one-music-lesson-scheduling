import copy
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from modules.api.dependencies import get_scheduler_context
from modules.api.schemas.common import ApiEnvelope
from modules.api.schemas.scheduler import (
    SchedulerExportArtifact,
    SchedulerExportBuildResult,
)
from modules.api.security import require_session
from modules.api.services.scheduler import restore_scheduler_state
from modules.api.services.workspace import read_workspace_snapshot
from modules.scheduler.context import SchedulerContext
from modules.scheduler.logic.export_artifacts import (
    build_download_artifacts,
    build_instructor_bundle_zip,
)
from modules.scheduler.logic.session_state import get_step4_unassigned_lessons


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MIME = "application/zip"

router = APIRouter(
    prefix="/scheduler/exports",
    tags=["scheduler"],
    dependencies=[Depends(require_session)],
)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@router.post(
    "/build",
    response_model=ApiEnvelope[SchedulerExportBuildResult],
)
def build_scheduler_exports(
    request: Request,
    context: SchedulerContext = Depends(get_scheduler_context),
) -> ApiEnvelope[SchedulerExportBuildResult]:
    base_dir = request.app.state.config.base_dir

    def read_inputs():
        state = restore_scheduler_state(context)
        return {
            "bookings": copy.deepcopy(context.loader.load_bookings()),
            "unassigned": copy.deepcopy(get_step4_unassigned_lessons(state)),
            "students": copy.deepcopy(context.loader.get_data("students.json")),
            "instructors": copy.deepcopy(
                context.loader.get_data("instructors.json")
            ),
            "uploaded_studio_df": copy.deepcopy(state.get("stu_df")),
        }

    inputs, workspace_version = read_workspace_snapshot(
        base_dir,
        context,
        read_inputs,
    )

    student_map = {
        str(student.get("student_id", "")): student
        for student in inputs["students"]
        if isinstance(student, dict)
    }
    valid_instructors = [
        instructor.get("name")
        for instructor in inputs["instructors"]
        if isinstance(instructor, dict) and instructor.get("name")
    ]
    built = build_download_artifacts(
        inputs["bookings"],
        inputs["unassigned"],
        student_map,
        valid_instructors,
        uploaded_studio_df=inputs["uploaded_studio_df"],
    )
    descriptors = []
    for filename, content in built.files.items():
        artifact_id = request.app.state.artifact_registry.register(
            scope="scheduler",
            filename=filename,
            mime_type=XLSX_MIME,
            content=content,
        )
        descriptors.append(
            SchedulerExportArtifact(
                artifact_id=artifact_id,
                filename=filename,
                mime_type=XLSX_MIME,
            )
        )
    instructor_bundle = build_instructor_bundle_zip(
        pd.DataFrame(built.preview_records)
    )
    bundle_id = request.app.state.artifact_registry.register(
        scope="scheduler",
        filename="Instructor_Schedules.zip",
        mime_type=ZIP_MIME,
        content=instructor_bundle,
    )
    descriptors.append(
        SchedulerExportArtifact(
            artifact_id=bundle_id,
            filename="Instructor_Schedules.zip",
            mime_type=ZIP_MIME,
        )
    )
    failed_assignments = _json_safe(inputs["unassigned"])
    return ApiEnvelope(
        data=SchedulerExportBuildResult(
            artifacts=descriptors,
            failed_assignments=failed_assignments,
        ),
        workspace_version=workspace_version,
    )


@router.get("/{artifact_id}")
def download_scheduler_export(request: Request, artifact_id: str) -> Response:
    artifact = request.app.state.artifact_registry.get(
        artifact_id,
        scope="scheduler",
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="ARTIFACT_NOT_FOUND")
    return Response(
        content=artifact.content,
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": 'attachment; filename="{0}"'.format(
                artifact.filename
            )
        },
    )
