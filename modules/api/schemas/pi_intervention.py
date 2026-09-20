from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PiReviewDraftRequest(_StrictModel):
    expected_version: str


class PiReviewDraftConflict(_StrictModel):
    left: str
    right: str
    message: str


class PiReviewDraftView(_StrictModel):
    status: Literal["ready", "blocked", "integrity_blocked"]
    summary: dict[str, Any]
    conflicts: list[PiReviewDraftConflict]
    warnings: list[str]
    integrity: dict[str, Any]


class ReconciliationLockedRoomDay(_StrictModel):
    room: str = Field(min_length=1)
    day: int = Field(ge=0, le=6)


class ReconciliationInvestigateRequest(_StrictModel):
    expected_version: str
    model: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="", max_length=64)
    thinking_level: str = Field(default="", max_length=16)
    day: int = Field(ge=0, le=6)
    goal: str = Field(default="", max_length=600)
    protect_instructors: list[str] = Field(default_factory=list, max_length=24)
    allow_time_change_instructors: list[str] = Field(default_factory=list, max_length=24)
    locked_room_days: list[ReconciliationLockedRoomDay] = Field(
        default_factory=list, max_length=24,
    )
    max_tool_calls: Optional[int] = Field(default=None, ge=1, le=20)


class ReconciliationDecisionRequest(_StrictModel):
    expected_version: str
    decision: Literal["pursuing", "rejected"]
    note: str = Field(default="", max_length=500)


class ReconciliationApplyRequest(_StrictModel):
    expected_version: str
    simulation_id: str = Field(min_length=1)
    confirmed_teacher_aliases: list[str] = Field(default_factory=list, max_length=16)
    confirmed_confirmation_ids: list[str] = Field(default_factory=list, max_length=16)
    authorized_sacrifice_aliases: list[str] = Field(default_factory=list, max_length=24)
    note: str = Field(default="", max_length=500)


class ReconciliationToolRequest(_StrictModel):
    action: Literal["inspect", "simulate", "submit"]
    params: dict[str, Any]


class ReconciliationChangeTarget(_StrictModel):
    room: str = Field(min_length=1)
    day: Optional[int] = Field(default=None, ge=0, le=6)
    start: Optional[str] = None
    end: Optional[str] = None


class ReconciliationChange(_StrictModel):
    subject_alias: str = Field(min_length=1)
    target: Optional[ReconciliationChangeTarget] = None
    withdraw: bool = False


class ReconciliationSimulateParams(_StrictModel):
    changes: list[ReconciliationChange] = Field(min_length=1, max_length=16)


class ReconciliationPendingDecision(_StrictModel):
    kind: Literal[
        "business_tradeoff",
        "missing_fact",
        "exception_authorization",
        "other",
    ]
    detail: str = Field(default="", max_length=400)
    teacher_alias: Optional[str] = None


class ReconciliationRemainingIssue(_StrictModel):
    subject_alias: str = Field(min_length=1)
    reason: str = Field(default="", max_length=300)


class ReconciliationSubmitParams(_StrictModel):
    termination: Literal[
        "recommendation_ready",
        "no_feasible_package_found",
        "budget_exhausted",
    ]
    primary_simulation_id: Optional[str] = None
    fallback_simulation_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1200)
    trade_offs: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    pending_decisions: list[ReconciliationPendingDecision] = Field(
        default_factory=list, max_length=8
    )
    remaining_issues: list[ReconciliationRemainingIssue] = Field(
        default_factory=list, max_length=24
    )
