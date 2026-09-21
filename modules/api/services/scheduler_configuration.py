from __future__ import annotations

import io
from typing import Any

import pandas as pd

from modules.api.errors import ApiProblem
from modules.scheduler.logic import lecture_service
from modules.scheduler.logic.reconciliation_checker import reconcile_assignments
from modules.scheduler.logic.rules_schema import get_rules_trace
from modules.scheduler.logic.session_state import ensure_step4_edit_session
from modules.shared.field_schema import DAY_MAP_EN_SHORT
from modules.shared.scheduler_data_service import parse_lectures_from_csv
from modules.shared.time_parser import TimeParser


LECTURE_CSV_REQUIRED_COLUMNS = frozenset({"Class Schedule"})
LECTURE_DUPLICATE_COLUMNS = (
    "Course Code",
    "Course Title & Session",
    "Teachers",
    "Class Schedule",
    "Classroom",
)


def load_rules(context: Any) -> dict:
    canonical = context.load_rules()
    trace = get_rules_trace(canonical)
    source_path = trace.get("source_path") or context.loader.preferred_data_path(
        "scheduling_rules.json"
    )
    return {
        "rules": canonical,
        "source_path": str(source_path),
        "trace": trace,
        "impact": _workspace_rules_impact(context),
    }


def _workspace_rules_impact(context: Any) -> dict:
    """Snapshot of the scheduler layers the saved rules will (and won't) affect.

    Rules are a canonical document: they govern the next Optimizer run and every
    validation pass, but they never rewrite existing layers by themselves. The
    frontend renders these facts so the operator can see exactly what a save
    means for the draft, the staged authority, and finalized output.
    """
    from modules.api.services.scheduler import restore_scheduler_state
    from modules.scheduler.logic.validation_authority import (
        authority_assignments,
        authority_stale,
    )

    state = restore_scheduler_state(context)
    edit_session = ensure_step4_edit_session(state)
    staged = authority_assignments(edit_session)
    return {
        "draft_assignment_count": len(edit_session.get("assignments") or []),
        "draft_unresolved_count": len(edit_session.get("unassigned_lessons") or []),
        "draft_dirty": bool(edit_session.get("dirty")),
        "staged_assignment_count": len(staged),
        "staged": bool(staged),
        "authority_stale": authority_stale(edit_session),
        "finalized": bool(state.get("round_committed")),
        "has_source_data": bool(state.get("wk_df") is not None),
    }


def save_rules(context: Any, rules: dict) -> dict:
    canonical, path = context.save_rules(rules)
    trace = get_rules_trace(context.load_rules())
    return {
        "rules": canonical,
        "source_path": str(path),
        "trace": trace,
        "impact": _workspace_rules_impact(context),
    }


def reconcile_scheduler_data(context: Any) -> dict:
    # Reuse the same persisted scheduler state that powers the Resolution
    # workspace. This keeps the diagnostic read-only and version-bound.
    from modules.api.services.scheduler import restore_scheduler_state

    state = restore_scheduler_state(context)
    weekly = state.get("wk_df")
    studio = state.get("stu_df")
    edit_session = ensure_step4_edit_session(state)
    assignments = list(edit_session.get("assignments", []) or [])
    unresolved = list(edit_session.get("unassigned_lessons", []) or [])
    report = reconcile_assignments(
        weekly,
        assignments,
        studio_df=studio,
        unresolved=unresolved,
        strict_identity=False,
    )
    source_row_count = sum(
        len(frame)
        for frame in (weekly, studio)
        if frame is not None and not getattr(frame, "empty", False)
    )
    return {
        "source_row_count": source_row_count,
        "source_request_count": report["source_request_count"],
        "assignment_count": len(assignments),
        "assigned_count": report["assigned_count"],
        "unresolved_count": report["unresolved_count"],
        "accounted_request_count": report["accounted_request_count"],
        "matches": report["matches"],
        "missing": report["missing"],
        "phantom": report["phantom"],
        "duplicates": report["duplicates"],
        "is_valid": report["is_valid"],
        "missing_source_request_ids": report["missing_source_request_ids"],
        "phantom_source_request_ids": report["phantom_source_request_ids"],
        "duplicate_assigned_source_request_ids": report[
            "duplicate_assigned_source_request_ids"
        ],
        "duplicate_unresolved_source_request_ids": report[
            "duplicate_unresolved_source_request_ids"
        ],
        "dual_state_source_request_ids": report["dual_state_source_request_ids"],
        "missing_source_id_locations": report["missing_source_id_locations"],
        "missing_count": len(report["missing_source_request_ids"]),
        "phantom_count": len(report["phantom_source_request_ids"]),
        "duplicate_assigned_count": len(
            report["duplicate_assigned_source_request_ids"]
        ),
        "duplicate_unresolved_count": len(
            report["duplicate_unresolved_source_request_ids"]
        ),
        "dual_state_count": len(report["dual_state_source_request_ids"]),
        "missing_source_id_count": len(report["missing_source_id_locations"]),
        "blocking_reason_codes": report["blocking_reason_codes"],
    }


def load_lectures(context: Any) -> dict:
    return {"lectures": lecture_service.load_lectures(context.loader)}


def _read_lecture_csv(file_bytes: bytes) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ApiProblem(
            status_code=422,
            code="LECTURE_CSV_UNREADABLE",
            message="Lecture CSV could not be read",
            details={"reason": str(exc)},
        ) from exc
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = sorted(LECTURE_CSV_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ApiProblem(
            status_code=400,
            code="LECTURE_CSV_MISSING_COLUMNS",
            message="Lecture CSV is missing required columns",
            details={"missing_columns": missing},
        )
    return frame


def _row_issue(row_number: int, code: str, message: str, raw_value: str) -> dict:
    return {
        "row_number": row_number,
        "code": code,
        "message": message,
        "raw_value": raw_value,
    }


def _lecture_csv_diagnostics(frame: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    skipped_rows = []
    duplicate_rows = []
    first_rows_by_key = {}

    for offset, (_, row) in enumerate(frame.iterrows(), start=2):
        schedule_value = row.get("Class Schedule", "")
        schedule = "" if pd.isna(schedule_value) else str(schedule_value).strip()
        if not schedule:
            skipped_rows.append(
                _row_issue(
                    offset,
                    "missing_schedule",
                    "Class Schedule is empty",
                    schedule,
                )
            )
        else:
            parts = schedule.split(" ")
            if len(parts) < 2:
                skipped_rows.append(
                    _row_issue(
                        offset,
                        "invalid_schedule",
                        "Class Schedule must include weekday and time range",
                        schedule,
                    )
                )
            else:
                day_str = parts[0]
                time_range = parts[1]
                try:
                    start_str, end_str = TimeParser.parse_time_range(time_range)
                except Exception:
                    start_str, end_str = None, None
                if not start_str or not end_str:
                    skipped_rows.append(
                        _row_issue(
                            offset,
                            "invalid_time",
                            "Class Schedule contains an invalid time range",
                            schedule,
                        )
                    )
                elif DAY_MAP_EN_SHORT.get(day_str) is None:
                    skipped_rows.append(
                        _row_issue(
                            offset,
                            "invalid_day",
                            "Class Schedule contains an unsupported weekday",
                            schedule,
                        )
                    )

        duplicate_key = tuple(
            "" if pd.isna(row.get(column)) else str(row.get(column)).strip()
            for column in LECTURE_DUPLICATE_COLUMNS
        )
        duplicate_of = first_rows_by_key.get(duplicate_key)
        if duplicate_of is None:
            first_rows_by_key[duplicate_key] = offset
        else:
            duplicate_rows.append(
                {"row_number": offset, "duplicate_of_row": duplicate_of}
            )

    return skipped_rows, duplicate_rows


def preview_lecture_csv(context: Any, file_name: str, file_bytes: bytes) -> dict:
    frame = _read_lecture_csv(file_bytes)
    skipped_rows, duplicate_rows = _lecture_csv_diagnostics(frame)
    lectures, parser_warning = parse_lectures_from_csv(
        context.loader,
        io.BytesIO(file_bytes),
    )
    warnings = [parser_warning] if parser_warning else []
    if duplicate_rows:
        warnings.append(
            "Detected {0} duplicate lecture row(s); candidates were preserved "
            "for legacy parser parity.".format(len(duplicate_rows))
        )
    if parser_warning and parser_warning.startswith("❌"):
        raise ApiProblem(
            status_code=422,
            code="LECTURE_CSV_UNREADABLE",
            message="Lecture CSV could not be parsed",
            details={"reason": parser_warning},
        )
    if not lectures:
        raise ApiProblem(
            status_code=422,
            code="LECTURE_CSV_EMPTY_RESULT",
            message="Lecture CSV contains no valid lecture candidates",
            details={
                "source_row_count": len(frame),
                "skipped_rows": skipped_rows,
                "warnings": warnings,
            },
        )
    return {
        "file_name": file_name,
        "lectures": lectures,
        "source_row_count": len(frame),
        "skipped_rows": skipped_rows,
        "duplicate_rows": duplicate_rows,
        "warnings": warnings,
    }


def _validated_lectures(context: Any, lectures: list[dict]) -> dict:
    validation = lecture_service.validate_lecture_candidates(
        lectures,
        context.loader.load_bookings() or [],
    )
    if validation["conflicts"]:
        raise ApiProblem(
            status_code=400,
            code="LECTURE_CONFLICT",
            message="Lecture locks overlap existing weekly lessons",
            details=validation,
        )
    return validation


def validate_lectures(context: Any, lectures: list[dict]) -> dict:
    return _validated_lectures(context, lectures)


def save_lectures(context: Any, lectures: list[dict]) -> dict:
    validation = _validated_lectures(context, lectures)
    saved = lecture_service.replace_lectures(
        context.loader,
        validation["lectures"],
    )
    return {
        "lectures": saved["lectures"],
        "warnings": [saved["warning"]] if saved["warning"] else [],
    }
