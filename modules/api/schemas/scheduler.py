from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assignment(BaseModel):
    """Persisted calendar events retain their legacy scheduling fields."""

    model_config = ConfigDict(extra="allow")

    id: str
    proposal_start: Optional[str] = None
    proposal_end: Optional[str] = None


class Room(BaseModel):
    """Persisted room records retain installation-specific metadata."""

    model_config = ConfigDict(extra="allow")

    id: str


class Issue(_StrictModel):
    id: str
    source_request_id: str
    reason_code: str
    message: str
    assignment_id: Optional[str] = None
    instructor: Optional[str] = None
    course_code: Optional[str] = None
    student_name: Optional[str] = None
    student_id: Optional[str] = None
    type: str
    instrument: Optional[str] = None
    duration_minutes: int = Field(ge=1)
    original_day: Optional[int] = Field(default=None, ge=0, le=6)
    original_start: Optional[str] = None
    original_end: Optional[str] = None
    proposal_start: Optional[str] = None
    proposal_end: Optional[str] = None
    original_time: Optional[str] = None
    original_date: Optional[str] = None
    preferred_venues: list[str] = Field(default_factory=list)
    room_types: list[str] = Field(default_factory=list)
    reason: str
    placement_group_id: Optional[str] = None
    placement_group_size: Optional[int] = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    reservation_label: Optional[Literal["reservation_internal", "contention"]] = None
    magnet_room: Optional[str] = None
    reservation_note: Optional[str] = None


class IssueGroup(_StrictModel):
    reason_code: str
    label: str
    count: int
    items: list[Issue]


class DraftState(_StrictModel):
    dirty: bool
    can_undo: bool
    can_redo: bool
    validation_state: Optional[Literal["editing", "staged", "finalized"]] = "staged"
    unsealed: Optional[bool] = False
    authority_stale: Optional[bool] = False
    save_status: Optional[Literal["saved", "degraded", "failed"]] = "saved"


class ReservationClassification(_StrictModel):
    label: Literal["reservation_internal", "contention"]
    magnet_room: Optional[str] = None
    reservation_note: Optional[str] = None


class SchedulerMetrics(_StrictModel):
    assigned: int
    unresolved: int
    source_gaps: int


class SchedulerSourcePreference(_StrictModel):
    instructor: str
    request_count: int = Field(ge=0)
    room_variants: list[list[str]]
    unknown_rooms: list[str]


class SchedulerSessionView(_StrictModel):
    active_stage: Literal[
        "lectures",
        "import",
        "rules",
        "optimize",
        "resolve",
        "export",
    ]
    assignments: list[Assignment]
    issues: list[IssueGroup]
    rooms: list[Room]
    instructors: list[str]
    draft: DraftState
    metrics: SchedulerMetrics
    reservation_classifications: dict[str, ReservationClassification] = Field(
        default_factory=dict
    )
    validation_authority: list[Assignment] = Field(default_factory=list)
    source_preferences: list[SchedulerSourcePreference] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
    operating_window: dict[str, Any] = Field(default_factory=dict)


class SchedulerMoveValidationRequest(_StrictModel):
    room: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
    day: int = Field(ge=0, le=6, strict=True)
    start: str
    end: str


class SchedulerMoveRequest(SchedulerMoveValidationRequest):
    expected_version: str
    teacher_confirmed: bool = False
    teacher_confirmation_note: str = Field(default="", max_length=500)
    decision_note: str = Field(default="", max_length=500)


class SchedulerIssueAssignmentValidationRequest(SchedulerMoveValidationRequest):
    pass


class SchedulerIssueAssignmentRequest(SchedulerIssueAssignmentValidationRequest):
    expected_version: str
    teacher_confirmed: bool = False
    teacher_confirmation_note: str = Field(default="", max_length=500)
    decision_note: str = Field(default="", max_length=500)


class SchedulerMoveValidationResult(_StrictModel):
    success: bool
    message: Optional[str] = None
    proposal_start: Optional[str] = None
    proposal_end: Optional[str] = None
    start_norm: Optional[str] = None
    end_norm: Optional[str] = None
    specific_date: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    requires_teacher_confirmation: bool = False
    teacher_confirmation_message: Optional[str] = None


class SchedulerExpectedVersionRequest(_StrictModel):
    expected_version: str


class SchedulerInterventionRequest(SchedulerExpectedVersionRequest):
    decision_note: str = Field(default="", max_length=500)


class SchedulerUnassignBlockRequest(SchedulerInterventionRequest):
    assignment_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=80, strip_whitespace=True)]] = Field(
        min_length=1,
        max_length=24,
    )


class SchedulerExportArtifact(_StrictModel):
    artifact_id: str
    filename: str
    mime_type: str


class SchedulerExportBuildResult(_StrictModel):
    artifacts: list[SchedulerExportArtifact]
    failed_assignments: list[dict[str, Any]] = Field(default_factory=list)


class SchedulerRoundStartResult(_StrictModel):
    locked_assignments: list[Assignment]


class SchedulerImportPreview(_StrictModel):
    preview_id: str
    slot: Literal["weekly", "studio"]
    file_name: str
    sheet_name: str
    row_count: int
    columns: list[str]
    instructor_conflicts: list[dict[str, Any]]
    blocking_errors: list[str]


SchedulerSheetRole = Literal[
    "Weekly Schedule",
    "Studio Schedule",
    "Student Info",
    "Instructor",
    "Room",
    "Course Code",
    "Unknown",
]


class SchedulerWorkbookSheetPreview(_StrictModel):
    sheet_name: str
    normalized_name: str
    role: SchedulerSheetRole
    header_row: int = Field(ge=1)
    row_count: int = Field(ge=0)
    columns: list[str]
    sample_rows: list[dict[str, Any]]
    warnings: list[str]
    blocking_errors: list[str]


class SchedulerWorkbookImportPreview(_StrictModel):
    preview_id: str
    file_name: str
    file_size: int = Field(ge=0)
    fingerprint: str
    sheets: list[SchedulerWorkbookSheetPreview]
    warnings: list[str]
    blocking_errors: list[str]
    instructor_conflicts: list[dict[str, Any]]
    possible_instructor_duplicates: list[list[str]] = Field(default_factory=list)


class SchedulerImportApplyRequest(_StrictModel):
    preview_id: str
    expected_version: str
    fingerprint: Optional[str] = None


class SchedulerImportResult(_StrictModel):
    state_key: Literal["wk_df", "stu_df"]
    sheet_name: str
    row_count: int
    workbook_digest: str
    sync_results: dict[str, Any]
    session: SchedulerSessionView


class SchedulerWorkbookImportResult(_StrictModel):
    state_keys: list[Literal["wk_df", "stu_df"]]
    sheet_names: dict[Literal["weekly", "studio"], str]
    row_counts: dict[Literal["weekly", "studio"], int]
    fingerprint: str
    sync_results: dict[str, Any]
    session: SchedulerSessionView


class SchedulerOptimizeRequest(_StrictModel):
    expected_version: str
    rerun_mode: Optional[Literal["fresh", "preserve_pinned"]] = None


class SchedulerOptimizeAccepted(_StrictModel):
    operation_id: str
    status: Literal["queued"]


class SchedulerOptimizerPreflight(_StrictModel):
    rules_health: dict[str, Any]
    room_health: dict[str, Any]
    instructor_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str]
    is_blocked: bool
    source_health: dict[str, Any] = Field(default_factory=dict)
    draft_health: dict[str, Any] = Field(default_factory=dict)


class OptimizerRunMetrics(_StrictModel):
    assigned: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    allocation_rate: float = Field(ge=0, le=1)
    failure_counts: dict[str, int]
    expected_requests: int = Field(default=0, ge=0)
    accounted_requests: int = Field(default=0, ge=0)
    reconciliation_anomaly_count: int = Field(default=0, ge=0)
    rerun_mode: str = "fresh"
    preserved_pin_count: int = Field(default=0, ge=0)
    downgraded_pin_count: int = Field(default=0, ge=0)
    downgraded_pins: list[dict[str, Any]] = Field(default_factory=list)


class OptimizerRunOutcome(OptimizerRunMetrics):
    assigned_change: int
    unresolved_change: int
    allocation_rate_change: float
    intervention_count: int = Field(ge=0)
    decision_note_count: int = Field(ge=0)
    finalize_warning_count: int = Field(ge=0)


class OptimizerLearningRun(_StrictModel):
    run_id: str
    status: Literal["open", "superseded", "finalized"]
    started_at: str
    completed_at: str
    finalized_at: Optional[str] = None
    duration_ms: int = Field(ge=0)
    input_workspace_version: str
    dashboard_version: str
    baseline: OptimizerRunMetrics
    outcome: Optional[OptimizerRunOutcome] = None
    reconciliation_attempts: list[dict[str, Any]] = Field(default_factory=list)


class OptimizerLearningView(_StrictModel):
    latest: Optional[OptimizerLearningRun] = None
    total_runs: int = Field(ge=0)
    finalized_runs: int = Field(ge=0)
    open_runs: int = Field(ge=0)


class SchedulerRulesView(_StrictModel):
    rules: dict[str, Any]
    source_path: str
    trace: dict[str, Any]


class SchedulerRulesSaveRequest(_StrictModel):
    rules: dict[str, Any]
    expected_version: str


class SchedulerReconciliationReport(_StrictModel):
    source_row_count: int
    source_request_count: int = 0
    assignment_count: int
    assigned_count: int = 0
    unresolved_count: int = 0
    accounted_request_count: int = 0
    duplicates: list[dict[str, Any]] = Field(default_factory=list)
    matches: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    phantom: list[dict[str, Any]]
    is_valid: bool = False
    missing_source_request_ids: list[str] = Field(default_factory=list)
    phantom_source_request_ids: list[str] = Field(default_factory=list)
    duplicate_assigned_source_request_ids: list[str] = Field(default_factory=list)
    duplicate_unresolved_source_request_ids: list[str] = Field(default_factory=list)
    dual_state_source_request_ids: list[str] = Field(default_factory=list)
    missing_source_id_locations: list[dict[str, Any]] = Field(default_factory=list)
    missing_count: int = Field(default=0, ge=0)
    phantom_count: int = Field(default=0, ge=0)
    duplicate_assigned_count: int = Field(default=0, ge=0)
    duplicate_unresolved_count: int = Field(default=0, ge=0)
    dual_state_count: int = Field(default=0, ge=0)
    missing_source_id_count: int = Field(default=0, ge=0)
    blocking_reason_codes: list[str] = Field(default_factory=list)


class LectureEvent(BaseModel):
    """Registry lecture events retain their legacy calendar metadata."""

    model_config = ConfigDict(extra="allow")

    id: str
    resourceId: str
    daysOfWeek: list[int]
    startTime: str
    endTime: str
    title: str = ""
    type: Literal["lecture"] = "lecture"
    locked: bool = True


class LectureConflict(_StrictModel):
    room_id: str
    lecture_id: str
    lecture_title: str
    existing_booking_id: str
    existing_booking_title: str
    days_of_week: list[int]
    start_time: str
    end_time: str
    existing_start_time: str
    existing_end_time: str
    message: str


class SchedulerLecturesView(_StrictModel):
    lectures: list[LectureEvent]


class LectureCsvSkippedRow(_StrictModel):
    row_number: int = Field(ge=2)
    code: Literal[
        "missing_schedule",
        "invalid_schedule",
        "invalid_day",
        "invalid_time",
    ]
    message: str
    raw_value: str


class LectureCsvDuplicateRow(_StrictModel):
    row_number: int = Field(ge=2)
    duplicate_of_row: int = Field(ge=2)


class SchedulerLectureCsvPreview(SchedulerLecturesView):
    file_name: str
    source_row_count: int = Field(ge=0)
    skipped_rows: list[LectureCsvSkippedRow]
    duplicate_rows: list[LectureCsvDuplicateRow]
    warnings: list[str]


class SchedulerLectureValidationRequest(_StrictModel):
    lectures: list[LectureEvent]


class SchedulerLectureValidationResult(SchedulerLecturesView):
    conflicts: list[LectureConflict]


class SchedulerLecturesSaveRequest(SchedulerLectureValidationRequest):
    expected_version: str
