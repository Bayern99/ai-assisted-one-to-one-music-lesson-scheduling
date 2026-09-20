from __future__ import annotations

from datetime import date
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ContinueAction(_StrictModel):
    page_title: str
    continue_path: str
    continue_label: str
    timestamp: Optional[str] = None
    page_icon: Optional[str] = None


class DashboardCounts(_StrictModel):
    students: int = Field(ge=0)
    instructors: int = Field(ge=0)
    rooms: int = Field(ge=0)
    bookings: int = Field(ge=0)


class DashboardSession(_StrictModel):
    active_step: Optional[str] = None
    round_committed: bool
    draft_dirty: bool


class SemesterConfigView(_StrictModel):
    start_date: date
    last_day: date
    jury_start: date
    jury_end: date


class SemesterConfigUpdateRequest(SemesterConfigView):
    expected_version: NonEmptyVersion


class DashboardData(_StrictModel):
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    continue_action: Optional[ContinueAction] = None
    counts: DashboardCounts
    session: DashboardSession
    health: Dict[str, Any] = Field(default_factory=dict)
    semester_config: SemesterConfigView


class StudentRecord(BaseModel):
    """Persisted student rows retain source metadata on read responses."""

    model_config = ConfigDict(extra="allow")

    student_id: str
    name_en: str = ""
    name_ch: str = ""
    display_name: str = ""
    year: int = 0
    instructor: str = ""
    instrument: str = ""
    type: str = ""
    course_code: str = ""
    status: str = ""


class StudentUpdateRequest(_StrictModel):
    expected_version: NonEmptyVersion
    name_en: str = None
    name_ch: str = None
    display_name: str = None
    year: int = Field(default=None, ge=0)
    instructor: str = None
    instrument: str = None
    type: str = None
    course_code: str = None
    status: str = None


class StudentDeleteRequest(_StrictModel):
    expected_version: NonEmptyVersion


class StudentDeleteResult(_StrictModel):
    deleted_student_id: str


class StudentBulkDeleteRequest(_StrictModel):
    expected_version: NonEmptyVersion
    student_ids: list[NonEmptyText] = Field(min_length=1)


class StudentBulkDeleteResult(_StrictModel):
    deleted_student_ids: list[str]


SourceDataset = Literal["students", "instructors", "rooms", "courses", "conveners"]


class SourceDataRecord(BaseModel):
    """Source tables retain their canonical, dataset-specific columns."""

    model_config = ConfigDict(extra="allow")


class SourceDataView(_StrictModel):
    dataset: SourceDataset
    records: list[SourceDataRecord]


class SourceDataImportPreview(_StrictModel):
    preview_id: str
    dataset: Literal["students", "rooms", "conveners"]
    file_name: str
    columns: list[str]
    row_count: int = Field(ge=0)
    sample: list[SourceDataRecord] = Field(default_factory=list)


class SourceDataImportApplyRequest(_StrictModel):
    preview_id: NonEmptyText
    expected_version: NonEmptyVersion


class SourceDataImportResult(_StrictModel):
    dataset: Literal["students", "rooms", "conveners"]
    records_written: int = Field(ge=0)


class SourceDataExportArtifact(_StrictModel):
    artifact_id: str
    filename: str
    mime_type: str


class SourceDataExportBuildResult(_StrictModel):
    artifacts: list[SourceDataExportArtifact]


class JurySessionView(_StrictModel):
    id: str
    name: str
    instrument_filter: list[str]
    cohort_filter: list[str]
    room_id: str
    date: str
    time_slot: str
    time_start: str
    jury_panel: list[str]
    jury_captain: str
    students: list[str]
    room_assistant: str
    captain_suggestion: Optional[str] = None


class JurySessionUpdateRequest(_StrictModel):
    session_id: NonEmptyText
    expected_version: NonEmptyVersion
    date: str = None
    time_slot: str = None
    time_start: str = None
    room_id: str = None
    jury_panel: list[NonEmptyText] = None
    jury_captain: str = None


class JurySessionCreateRequest(_StrictModel):
    expected_version: NonEmptyVersion
    name: NonEmptyText
    date: str
    time_slot: str = "Morning"
    time_start: str
    room_id: NonEmptyText
    jury_panel: list[NonEmptyText] = Field(default_factory=list)
    jury_captain: str = ""
    instrument_filter: list[NonEmptyText] = Field(default_factory=list)
    cohort_filter: list[NonEmptyText] = Field(default_factory=list)


class JurySessionDeleteRequest(_StrictModel):
    expected_version: NonEmptyVersion


class JurySessionDeleteResult(_StrictModel):
    deleted_session_id: str


class JuryStudentReorderRequest(_StrictModel):
    expected_version: NonEmptyVersion
    student_ids: list[NonEmptyText]


class JuryScheduleRequest(_StrictModel):
    session_id: NonEmptyText
    start_time: str
    average_duration_minutes: int = Field(default=10, ge=1, le=60)
    break_after_students: int = Field(default=5, ge=0, le=100)
    break_duration_minutes: int = Field(default=10, ge=1, le=60)


class JuryScheduleItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["exam", "break"]
    start: str
    end: str


class JuryScheduleView(_StrictModel):
    session_id: str
    items: list[JuryScheduleItem]


class JuryExportArtifact(_StrictModel):
    artifact_id: str
    filename: str
    mime_type: str


class JuryExportBuildResult(_StrictModel):
    artifacts: list[JuryExportArtifact]


class AssessmentPreviewIssue(_StrictModel):
    student_id: str
    issue: str


class AssessmentImportPreview(_StrictModel):
    preview_id: str
    kind: Literal["continuous", "jury"]
    file_name: str
    columns: list[str]
    row_count: int = Field(ge=0)
    unmatched: list[AssessmentPreviewIssue] = Field(default_factory=list)
    resolved_mapping: dict[str, Optional[str]] = Field(default_factory=dict)


class AssessmentImportInspection(_StrictModel):
    kind: Literal["continuous"] = "continuous"
    file_name: str
    columns: list[str]
    row_count: int = Field(ge=0)
    resolved_mapping: dict[str, Optional[str]]


class ScoreTemplateCategoryView(_StrictModel):
    name: str
    max_score: float
    description: str = ""


class ScoreTemplateView(_StrictModel):
    id: str
    name: str
    semester: str
    instrument_family: str
    categories: list[ScoreTemplateCategoryView]
    total_score: float
    version: str


class ScoreTemplateCategoryInput(_StrictModel):
    name: NonEmptyText
    max_score: int = Field(ge=1, le=100)
    description: str = ""


class ScoreTemplateSaveRequest(_StrictModel):
    expected_version: NonEmptyVersion
    name: NonEmptyText
    semester: Literal["Semester I", "Semester II", "Any"]
    instrument_family: NonEmptyText
    categories: list[ScoreTemplateCategoryInput] = Field(min_length=1)


class ScoreTemplateDeleteRequest(_StrictModel):
    expected_version: NonEmptyVersion


class ScoreTemplateDeleteResult(_StrictModel):
    deleted_template_id: str


class AssessmentImportApplyRequest(_StrictModel):
    preview_id: NonEmptyText
    expected_version: NonEmptyVersion


class GradeOverviewRecord(_StrictModel):
    student_id: str
    name: str
    course_code: str
    weekly_prep: float
    studio: float
    report: float
    jury: float
    total: float
    anomalies: list[str] = Field(default_factory=list)


class AssessmentImportResult(_StrictModel):
    kind: Literal["continuous", "jury"]
    records_written: int = Field(ge=0)
    overview: list[GradeOverviewRecord]


class AssessmentExportArtifact(_StrictModel):
    artifact_id: str
    filename: str
    mime_type: str


class AssessmentExportBuildResult(_StrictModel):
    artifacts: list[AssessmentExportArtifact]
