from __future__ import annotations

import copy
from dataclasses import dataclass, field
from contextlib import nullcontext
from datetime import datetime, timezone
from time import monotonic
from typing import Callable, Optional

from modules.scheduler.logic.optimizer_learning_record import (
    stage_optimizer_learning_recovery,
)
from modules.scheduler.logic.preflight import collect_optimizer_preflight
from modules.scheduler.logic.rules_schema import get_rules_trace
from modules.scheduler.logic.session_state import (
    SCHEDULER_SESSION_REVISION_KEY,
    persist_scheduler_session,
    reset_step4_edit_session,
)
from modules.scheduler.logic.workflow_service import build_locked_context
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.instructor_time_integrity import audit_canonical_schedule
from modules.scheduler.logic.reconciliation_checker import verify_candidate_state
from modules.scheduler.logic.provenance import active_workbook_provenance
from modules.scheduler.logic.provenance import SCHEDULER_PROVENANCE_KEY
from modules.scheduler.logic.session_state import ensure_step4_edit_session
from modules.scheduler.logic.source_requests import source_request_ids
from modules.shared.time_parser import TimeParser


class OptimizerInputError(ValueError):
    """Raised when the optimizer cannot safely run with the current inputs."""


class OptimizerPersistenceError(RuntimeError):
    """Raised when a completed optimizer run cannot become canonical state."""

    def __init__(self, message: str, result: "OptimizerRunResult") -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class OptimizerRunResult:
    assignment_count: int
    unassigned_count: int
    duplicate_count: int
    logs: list[str]
    rules_trace: dict
    rules_snapshot: dict
    duplicates: list[dict] = field(default_factory=list)
    rerun_mode: str = "fresh"
    preserved_pin_count: int = 0
    downgraded_pin_count: int = 0
    downgraded_pins: list[dict] = field(default_factory=list)


PhaseCallback = Callable[[str], None]
VersionGuard = Callable[[], None]


def _assignment_source_id(assignment):
    props = assignment.get("extendedProps")
    props = props if isinstance(props, dict) else {}
    return assignment.get("source_request_id") or props.get("source_request_id")


def _validate_pinned_assignments(state, rules, rooms, existing_assignments=None):
    edit_session = ensure_step4_edit_session(state)
    pins = [
        copy.deepcopy(item)
        for item in edit_session.get("assignments", []) or []
        if isinstance(item, dict) and item.get("pinned") is True
    ]
    valid_source_ids = source_request_ids(state.get("wk_df"), state.get("stu_df"))
    room_ids = {
        str(room.get("id"))
        for room in rooms or []
        if isinstance(room, dict) and room.get("id")
    }
    time_range = rules.get("constraints", {}).get("time_range", {})
    lower = TimeParser.to_minutes(time_range.get("start"), default=None)
    upper = TimeParser.to_minutes(time_range.get("end"), default=None)
    reasons_by_index = {}

    def add_reason(index, reason):
        reasons_by_index.setdefault(index, set()).add(reason)

    source_indexes = {}
    for index, pin in enumerate(pins):
        source_id = str(_assignment_source_id(pin) or "").strip()
        if not source_id or source_id not in valid_source_ids:
            add_reason(index, "source_request_missing")
        source_indexes.setdefault(source_id, []).append(index)
        room_id = str(pin.get("resourceId") or pin.get("room_id") or "").strip()
        if room_id not in room_ids:
            add_reason(index, "room_missing")
        raw_start, raw_end = TimeParser.event_to_minute_range(pin, default=None)
        interval = TimeParser.canonical_course_occupancy(raw_start, raw_end)
        if interval is None:
            add_reason(index, "noncanonical_occupancy")
        elif lower is None or upper is None or interval[0] < lower or interval[1] > upper:
            add_reason(index, "outside_scheduling_window")

    for source_id, indexes in source_indexes.items():
        if source_id and len(indexes) > 1:
            for index in indexes:
                add_reason(index, "locked_context_conflict")

    preliminary = [pin for index, pin in enumerate(pins) if index not in reasons_by_index]
    if preliminary:
        validator = ConflictValidator(
            {
                "assignments": list(existing_assignments or []) + preliminary,
                "lectures": [],
                "rooms": rooms,
                "rules": rules,
            }
        )
        pin_ids = {str(pin.get("id")) for pin in preliminary}
        for index, pin in enumerate(pins):
            if index in reasons_by_index:
                continue
            props = pin.get("extendedProps") if isinstance(pin.get("extendedProps"), dict) else {}
            room_id = str(pin.get("resourceId") or pin.get("room_id") or "").strip()
            if not validator.validate_rules(
                room_id,
                props.get("normalized_instrument") or props.get("Instrument", ""),
            ).get("allowed", True):
                add_reason(index, "room_type_mismatch")
                continue
            start_min, end_min = TimeParser.event_to_minute_range(pin, default=None)
            specific_date = TimeParser.event_specific_date(pin)
            day = (pin.get("daysOfWeek") or [None])[0]
            if specific_date:
                day = TimeParser.to_js_weekday(specific_date, default=day)
            conflict = validator.check_conflict(
                room_id,
                day,
                start_min,
                end_min,
                specific_date=specific_date,
                exclude_id=pin.get("id"),
            )
            if conflict:
                add_reason(
                    index,
                    "room_conflict" if str(conflict.get("id")) in pin_ids else "locked_context_conflict",
                )

        valid_after_room = [
            pin for index, pin in enumerate(pins) if index not in reasons_by_index
        ]
        teacher_conflicts = audit_canonical_schedule(
            list(existing_assignments or []) + valid_after_room
        )
        index_by_id = {
            str(pin.get("id")): index
            for index, pin in enumerate(pins)
            if index not in reasons_by_index
        }
        for conflict in teacher_conflicts:
            for side in ("left", "right"):
                index = index_by_id.get(str(conflict[side].get("id")))
                if index is not None:
                    add_reason(index, "teacher_conflict")

    valid_pins = [pin for index, pin in enumerate(pins) if index not in reasons_by_index]
    downgraded_pins = [
        {
            "source_request_id": str(_assignment_source_id(pins[index]) or ""),
            "reason_codes": sorted(reasons),
        }
        for index, reasons in sorted(reasons_by_index.items())
    ]
    return valid_pins, downgraded_pins


def apply_semester_bounds(assignments: list[dict], semester_config: dict) -> None:
    start_date = semester_config.get("start_date", "2026-02-24")
    end_date = semester_config.get(
        "end_date",
        semester_config.get("last_day", "2026-06-30"),
    )
    for assignment in assignments:
        assignment["startRecur"] = start_date
        assignment["endRecur"] = end_date


def run_optimizer(
    context,
    state,
    *,
    run_id: Optional[str] = None,
    on_phase: Optional[PhaseCallback] = None,
    version_guard: Optional[VersionGuard] = None,
    commit_lock=None,
    learning_metadata: dict | None = None,
    rerun_mode: str = "fresh",
) -> OptimizerRunResult:
    if state.get("wk_df") is None:
        raise OptimizerInputError("Weekly workbook is required")

    if on_phase is not None:
        on_phase("preflight")
    rules = context.load_rules()
    preflight = collect_optimizer_preflight(
        context.loader,
        default_rules=context.default_rules,
        weekly_df=state.get("wk_df"),
        studio_df=state.get("stu_df"),
        draft=state.get("step4_edit_session"),
    )
    if preflight["is_blocked"]:
        raise OptimizerInputError("; ".join(preflight["issues"]))

    source_workbook_version, source_workbook_digests = active_workbook_provenance(
        state.get(SCHEDULER_PROVENANCE_KEY)
    )
    edit_session = ensure_step4_edit_session(state)

    if on_phase is not None:
        on_phase("optimizing")
    if version_guard is not None:
        version_guard()
    bookings = context.loader.load_bookings()
    locked_context = build_locked_context(bookings)
    optimizer = context.make_optimizer(
        context.loader.get_data("students.json"),
        context.loader.get_data("rooms.json"),
        locked_context,
        rules=rules,
    )
    pinned_assignments = []
    downgraded_pins = []
    if rerun_mode == "preserve_pinned":
        saved_version = str(edit_session.get("source_workbook_version") or "").strip()
        saved_digests = edit_session.get("source_workbook_digests") or {}
        if not source_workbook_version or not saved_version or saved_version != source_workbook_version:
            raise OptimizerInputError(
                "Preserve pinned requires a non-empty matching source workbook version; start a fresh run."
            )
        if saved_digests != source_workbook_digests:
            raise OptimizerInputError(
                "Preserve pinned requires matching source workbook digests; start a fresh run."
            )
        pinned_assignments, downgraded_pins = _validate_pinned_assignments(
            state,
            rules,
            context.loader.load_rooms(),
            existing_assignments=locked_context,
        )
    optimize_kwargs = (
        {"pinned_assignments": pinned_assignments}
        if pinned_assignments
        else {}
    )
    assignments, duplicates, raw_logs = optimizer.optimize(
        state["wk_df"],
        state.get("stu_df"),
        **optimize_kwargs,
    )
    logs = list(raw_logs)
    rules_trace = get_rules_trace(rules)
    ignored = list(rules_trace.get("ignored_top_level_keys", [])) + list(
        rules_trace.get("ignored_nested_keys", [])
    )
    if ignored:
        logs.insert(
            1,
            "ℹ️ Rules normalization ignored: " + ", ".join(ignored),
        )

    apply_semester_bounds(
        assignments,
        context.loader.load_semester_config(),
    )

    candidate = verify_candidate_state(
        state["wk_df"],
        assignments,
        studio_df=state.get("stu_df"),
        unresolved=optimizer.unassigned,
        rooms=context.loader.load_rooms(),
        rules=rules,
        locked_context_assignments=locked_context,
        lectures=[
            event
            for event in bookings
            if event.get("type") in ("lecture", "academic_lecture")
        ],
    )
    if not candidate["is_valid"]:
        reasons = ", ".join(candidate["blocking_reason_codes"])
        raise OptimizerInputError(
            "Optimizer candidate failed integrity verification"
            + (f": {reasons}" if reasons else ".")
        )

    reset_step4_edit_session(
        state,
        assignments=assignments,
        unassigned_lessons=optimizer.unassigned,
        optimizer_run_id=run_id,
        source_workbook_version=source_workbook_version,
        source_workbook_digests=source_workbook_digests,
    )
    state["opt_logs"] = logs
    state["scheduler_rules_trace"] = rules_trace
    state["optimizer_run_summary"] = {
        "rerun_mode": rerun_mode,
        "preserved_pin_count": len(pinned_assignments),
        "downgraded_pin_count": len(downgraded_pins),
        "downgraded_pins": copy.deepcopy(downgraded_pins),
        "assigned_count": len(assignments),
        "unresolved_count": len(optimizer.unassigned),
    }
    if learning_metadata is not None:
        stage_optimizer_learning_recovery(
            run_id=str(run_id or ""),
            input_workspace_version=str(
                learning_metadata.get("input_workspace_version") or ""
            ),
            state=state,
            rules=rules,
            duplicate_count=len(duplicates),
            preserved_pin_count=len(pinned_assignments),
            downgraded_pin_count=len(downgraded_pins),
            downgraded_pins=downgraded_pins,
            started_at=str(learning_metadata.get("started_at") or ""),
            completed_at=datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            duration_ms=round(
                (
                    monotonic()
                    - float(learning_metadata.get("started_clock") or monotonic())
                )
                * 1000
            ),
        )
    result = OptimizerRunResult(
        assignment_count=len(assignments),
        unassigned_count=len(optimizer.unassigned),
        duplicate_count=len(duplicates),
        logs=logs,
        rules_trace=rules_trace,
        rules_snapshot=copy.deepcopy(rules),
        duplicates=list(duplicates),
        rerun_mode=rerun_mode,
        preserved_pin_count=len(pinned_assignments),
        downgraded_pin_count=len(downgraded_pins),
        downgraded_pins=copy.deepcopy(downgraded_pins),
    )
    if on_phase is not None:
        on_phase("persisting")
    with commit_lock if commit_lock is not None else nullcontext():
        if version_guard is not None:
            version_guard()
        try:
            expected_revision = state.get(SCHEDULER_SESSION_REVISION_KEY)
            if expected_revision is None:
                expected_revision = state.get("scheduler_session_mtime")
            save_outcome = persist_scheduler_session(
                context.session_manager,
                state,
                expected_mtime=expected_revision,
            )
        except Exception as exc:
            raise OptimizerPersistenceError(str(exc), result) from exc
        if getattr(save_outcome, "status", None) == "conflict":
            raise OptimizerPersistenceError(
                getattr(save_outcome, "warning", None)
                or "Scheduler session changed while optimizer was running",
                result,
            )

    return result
