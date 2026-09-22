from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolutionSummary(_StrictModel):
    total: int = Field(ge=0)
    cases: int = Field(ge=0)
    place_now: int = Field(ge=0)
    same_day_alternative: int = Field(ge=0)
    blocked: int = Field(ge=0)
    waiting: int = Field(ge=0)


class ResolutionOption(_StrictModel):
    room: str
    day: int = Field(ge=0, le=6)
    start: str
    end: str
    preferred: bool
    time_changed: bool
    requires_teacher_confirmation: bool
    shift_minutes: Optional[int] = None


class ResolutionIssueAdvice(_StrictModel):
    issue_id: str
    label: str
    type: str
    status: Literal["place_now", "same_day_alternative", "blocked"]
    reason: str
    time_change_allowed: bool
    options: list[ResolutionOption]
    cross_day_options: list[ResolutionOption] = Field(default_factory=list)
    rejection_trace: list[dict] = Field(default_factory=list)
    placement_group_id: Optional[str] = None
    placement_group_size: Optional[int] = Field(default=None, ge=1)
    single_room: Optional[bool] = None


class ResolutionInterventionGroup(_StrictModel):
    group_id: str
    issue_ids: list[str]
    case_ids: list[str]
    days: list[int] = Field(default_factory=list, min_length=1)
    size: int = Field(ge=1)
    over_limit: bool
    relation_reasons: list[str]
    recommended: bool


class ResolutionCase(_StrictModel):
    id: str
    instructor: str
    day: Optional[int] = Field(default=None, ge=0, le=6)
    date: Optional[str] = None
    waiting: bool
    waiting_note: str
    issues: list[ResolutionIssueAdvice]


class PianoLeverageMove(_StrictModel):
    assignment_id: str
    label: str
    from_room: str
    from_day: int = Field(ge=0, le=6)
    from_start: str
    from_end: str
    to_room: str
    to_day: int = Field(ge=0, le=6)
    to_start: str
    to_end: str


class PianoLeverageFill(_StrictModel):
    issue_id: str
    label: str
    instructor: str
    room: str
    day: int = Field(ge=0, le=6)
    start: str
    end: str


class PianoLeverageProposal(_StrictModel):
    id: str
    instructor: str
    target_room: str
    target_day: int = Field(ge=0, le=6)
    target_start: str
    target_end: str
    gain: int = Field(ge=1)
    moves: list[PianoLeverageMove]
    fills: list[PianoLeverageFill]


class ResolutionInterventionConstraint(_StrictModel):
    constraint_id: str
    type: Literal[
        "protect_teacher_day",
        "avoid_day",
        "max_teacher_confirmations",
        "prefer_room_only",
    ]
    instructor: Optional[str] = None
    day: Optional[int] = None
    value: Optional[int] = None
    source: Literal["human_confirmed"]
    created_at: str


class ReconciliationTeacherConfirmation(_StrictModel):
    teacher_alias: str
    confirmation_id: str


class ReconciliationSacrifice(_StrictModel):
    subject_alias: str
    teacher_alias: str
    label: str = ""
    day: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    room: Optional[str] = None


class ReconciliationPlacement(_StrictModel):
    room: Optional[str] = None
    day: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None


class ReconciliationChangeRow(_StrictModel):
    subject_alias: str
    group_alias: str
    group_size: int = 1
    kind: Literal["block", "assignment", "issue"]
    action: Literal["move", "place", "withdraw"]
    teacher: str = ""
    label: str = ""
    from_placement: Optional[ReconciliationPlacement] = Field(default=None, alias="from")
    to: Optional[ReconciliationPlacement] = None
    time_changed: bool = False
    room_changed: bool = False
    is_sacrifice: bool = False

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ReconciliationSplitDay(_StrictModel):
    teacher_alias: str
    day: Optional[int] = None
    rooms: list[str] = Field(default_factory=list)


class ReconciliationSimulation(_StrictModel):
    simulation_id: str
    snapshot_id: str
    snapshot_hash: str
    status: Literal["feasible", "conditional", "infeasible"]
    feasible: bool
    normalized_changes: list[dict]
    package_hash: str
    metrics: dict
    required_teacher_confirmations: list[ReconciliationTeacherConfirmation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    sacrifices: list[ReconciliationSacrifice] = Field(default_factory=list)
    changes: list[ReconciliationChangeRow] = Field(default_factory=list)
    split_teacher_days: list[ReconciliationSplitDay] = Field(default_factory=list)
    same_day_time_change: bool = False
    requires_sacrifice_authorization: bool = False
    state_after: dict = Field(default_factory=dict)


class ReconciliationPendingDecisionView(_StrictModel):
    kind: str
    detail: str = ""
    teacher_alias: Optional[str] = None


class ReconciliationUnknownView(_StrictModel):
    subject: str = ""
    note: str = ""


class ReconciliationRemainingIssue(_StrictModel):
    subject_alias: str
    reason: str = ""
    teacher_alias: Optional[str] = None
    label: str = ""


class ReconciliationBrief(_StrictModel):
    brief_id: str
    investigation_id: str
    snapshot_id: str
    status: Literal["proposed", "pursuing", "rejected"]
    termination: Literal["recommendation_ready", "no_feasible_package_found", "budget_exhausted"]
    primary_simulation_id: Optional[str] = None
    fallback_simulation_id: Optional[str] = None
    title: str
    focus_question: str = ""
    agent_note: str = ""
    unknowns: list[ReconciliationUnknownView] = Field(default_factory=list)
    rationale: str
    trade_offs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    coverage: dict
    created_at: str
    sacrifices: list[ReconciliationSacrifice] = Field(default_factory=list)
    requires_sacrifice_authorization: bool = False
    same_day_time_change: bool = False
    pending_decisions: list[ReconciliationPendingDecisionView] = Field(default_factory=list)
    remaining_issues: list[ReconciliationRemainingIssue] = Field(default_factory=list)
    decision_note: Optional[str] = None
    decided_at: Optional[str] = None


class ReconciliationPriorThread(_StrictModel):
    goal: str = ""
    goals: list[str] = Field(default_factory=list)
    termination: str = ""
    failure_codes: list[str] = Field(default_factory=list)
    pending_decisions: list[ReconciliationPendingDecisionView] = Field(default_factory=list)
    remaining_issue_aliases: list[str] = Field(default_factory=list)


class ReconciliationTaskPremises(_StrictModel):
    goal: str = ""
    scope_type: str = "day"
    scope_id: str = "day"
    day: Optional[int] = None
    time_is_fixed: bool = True
    protect_teacher_aliases: list[str] = Field(default_factory=list)
    protect_subject_aliases: list[str] = Field(default_factory=list)
    time_change_exception_teacher_aliases: list[str] = Field(default_factory=list)
    locked_room_days: list[dict] = Field(default_factory=list)
    tool_calls_used: int = 0
    tool_call_budget: int = 0
    sacrifice_requires_authorization: bool = True
    prior_decisions: list[dict] = Field(default_factory=list)
    prior_thread: Optional[ReconciliationPriorThread] = None


class ReconciliationApplyResult(_StrictModel):
    simulation_id: str = ""
    metrics: dict = Field(default_factory=dict)
    changes: list[ReconciliationChangeRow] = Field(default_factory=list)
    sacrifices: list[ReconciliationSacrifice] = Field(default_factory=list)
    split_teacher_days: list[ReconciliationSplitDay] = Field(default_factory=list)
    authorized_sacrifice_aliases: list[str] = Field(default_factory=list)
    applied_at: str = ""


class DecisionBriefFocus(_StrictModel):
    question: str = ""
    status: Literal["ready", "choice", "missing_info", "no_package"] = "ready"


class DecisionBriefOption(_StrictModel):
    option_id: str
    source: str
    simulation_id: str
    changes: list[ReconciliationChangeRow] = Field(default_factory=list)
    diffs: list[ReconciliationChangeRow] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    required_teacher_aliases: list[str] = Field(default_factory=list)
    sacrifice_aliases: list[str] = Field(default_factory=list)


class DecisionBriefCommon(_StrictModel):
    changes: list[ReconciliationChangeRow] = Field(default_factory=list)
    required_teacher_aliases: list[str] = Field(default_factory=list)
    sacrifice_aliases: list[str] = Field(default_factory=list)


class DecisionBriefTeacherRow(_StrictModel):
    start: str = ""
    end: str = ""
    room: Optional[str] = None
    label: str = ""
    state: str = "unchanged"
    variants: dict[str, Optional[str]] = Field(default_factory=dict)


class DecisionBriefTeacherDay(_StrictModel):
    teacher: str
    rows: list[DecisionBriefTeacherRow] = Field(default_factory=list)


class DecisionBriefRoomBusy(_StrictModel):
    start: str = ""
    end: str = ""
    label: str = ""


class DecisionBriefRoomView(_StrictModel):
    room: str
    accepts: list[str] = Field(default_factory=list)
    busy: list[DecisionBriefRoomBusy] = Field(default_factory=list)


class DecisionBriefComparisonRow(_StrictModel):
    label: str
    values: list[str] = Field(default_factory=list)


class DecisionBriefRevisionEffect(_StrictModel):
    code: str = ""
    text: str = ""


class DecisionBriefRevision(_StrictModel):
    instruction: str = ""
    protect_teachers: list[str] = Field(default_factory=list)
    allow_time_change_teachers: list[str] = Field(default_factory=list)
    effects: list[DecisionBriefRevisionEffect] = Field(default_factory=list)


class ReconciliationDecisionBrief(_StrictModel):
    focus: DecisionBriefFocus
    options: list[DecisionBriefOption] = Field(default_factory=list)
    common: Optional[DecisionBriefCommon] = None
    comparison: list[DecisionBriefComparisonRow] = Field(default_factory=list)
    revision: Optional[DecisionBriefRevision] = None
    teacher_days: list[DecisionBriefTeacherDay] = Field(default_factory=list)
    room_views: list[DecisionBriefRoomView] = Field(default_factory=list)
    unknowns: list[ReconciliationUnknownView] = Field(default_factory=list)
    agent_note: str = ""


class ReconciliationInvestigationView(_StrictModel):
    investigation_id: str
    snapshot_id: str
    snapshot_hash: str
    workspace_version: str
    scope_type: str
    scope_id: str
    day: Optional[int] = None
    stale: bool
    status: Literal["running", "completed", "failed", "applied", "stale", "timeout", "interrupted", "crash"]
    created_at: str
    tool_calls: int = Field(ge=0)
    coverage: dict
    simulations: list[ReconciliationSimulation] = Field(default_factory=list)
    brief: Optional[ReconciliationBrief] = None
    decision_brief: Optional[ReconciliationDecisionBrief] = None
    task: Optional[ReconciliationTaskPremises] = None
    teacher_display: dict[str, str] = Field(default_factory=dict)
    apply_result: Optional[ReconciliationApplyResult] = None


class PiRuntimeChoice(_StrictModel):
    provider: str
    model: str


class PiRuntimeView(_StrictModel):
    provider: str
    model: str
    thinking_level: str = "off"
    thinking_levels: list[str] = Field(default_factory=list)
    choices: list[PiRuntimeChoice] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)


class ResolutionAdvice(_StrictModel):
    summary: ResolutionSummary
    cases: list[ResolutionCase]
    intervention_groups: list[ResolutionInterventionGroup] = Field(default_factory=list)
    intervention_constraints: list[ResolutionInterventionConstraint] = Field(default_factory=list)
    causal_diagnosis: dict = Field(default_factory=dict)
    piano_leverage: list[PianoLeverageProposal]
    pi_available: bool = False
    pi_runtime: Optional[PiRuntimeView] = None
    pi_reconciliation: Optional[ReconciliationInvestigationView] = None
    day_instructors: dict[str, list[str]] = Field(default_factory=dict)


class ResolutionWaitingRequest(_StrictModel):
    expected_version: str
    waiting: bool
    note: str = Field(default="", max_length=500)


class PianoLeverageApplyRequest(_StrictModel):
    expected_version: str
    teacher_confirmed: bool = False
    confirmation_note: str = Field(default="", max_length=500)
