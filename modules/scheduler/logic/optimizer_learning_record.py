"""Persistent evidence for optimizer runs and finalized human interventions."""

from __future__ import annotations

import copy
import hashlib
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from modules import __version__
from modules.scheduler.logic import unresolved_assignment_primitives
from modules.shared.time_parser import TimeParser


FILE_NAME = "optimizer_learning_records.json"
SCHEMA_VERSION = 2


class OptimizerLearningRecordError(RuntimeError):
    """Raised when an active optimizer run cannot be found in the ledger."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dashboard_version() -> str:
    return __version__


def _opaque_key(kind: str, value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digest = hashlib.sha256(f"{kind}:{text}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _load_ledger(loader) -> dict[str, Any]:
    payload = loader.get_data(FILE_NAME)
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "runs": []}
    runs = payload.get("runs")
    return {
        "schema_version": SCHEMA_VERSION,
        "runs": copy.deepcopy(runs) if isinstance(runs, list) else [],
    }


def _save_ledger(loader, ledger: dict[str, Any]) -> None:
    # ponytail: whole-file JSON suits semester-scale use; move to SQLite only
    # when concurrent writers or thousands of optimizer runs make this costly.
    loader.save_data(FILE_NAME, ledger)


def _find_run(ledger: dict[str, Any], run_id: str) -> dict[str, Any]:
    record = next(
        (
            item
            for item in reversed(ledger["runs"])
            if isinstance(item, dict) and item.get("run_id") == run_id
        ),
        None,
    )
    if record is None:
        raise OptimizerLearningRecordError(
            f"Optimizer learning record {run_id} was not found"
        )
    return record


def _allocation_metrics(
    assignments: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    *,
    duplicate_count: int = 0,
    preserved_pin_count: int = 0,
    downgraded_pin_count: int = 0,
    downgraded_pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assigned_count = len(assignments)
    unresolved_count = len(unresolved)
    total = assigned_count + unresolved_count
    failure_counts = Counter(
        str(item.get("reason_code") or "unknown")
        for item in unresolved
        if isinstance(item, dict)
    )
    return {
        "assigned": assigned_count,
        "unresolved": unresolved_count,
        "duplicates": int(duplicate_count),
        "allocation_rate": round(assigned_count / total, 4) if total else 0.0,
        "failure_counts": dict(sorted(failure_counts.items())),
        "preserved_pin_count": max(0, int(preserved_pin_count)),
        "downgraded_pin_count": max(0, int(downgraded_pin_count)),
        "downgraded_pins": copy.deepcopy(downgraded_pins or []),
    }


def _privacy_safe_rules(rules: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(rules.get(key, {}))
        for key in ("priorities", "constraints", "room_types")
    }
    for key in (
        "instructor_preferred_rooms",
        "instructor_priority",
        "instructor_time_change_eligibility",
    ):
        source = rules.get(key)
        result[key] = (
            {
                _opaque_key("instructor", name): copy.deepcopy(value)
                for name, value in source.items()
                if _opaque_key("instructor", name)
            }
            if isinstance(source, dict)
            else {}
        )
    return result


def _privacy_safe_provenance(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    uploads = source.get("uploads") if isinstance(source.get("uploads"), dict) else {}
    syncs = (
        source.get("master_data_sync")
        if isinstance(source.get("master_data_sync"), dict)
        else {}
    )
    return {
        "uploads": {
            str(slot): {
                key: item.get(key)
                for key in ("digest", "uploaded_at")
                if item.get(key) is not None
            }
            for slot, item in uploads.items()
            if isinstance(item, dict)
        },
        "master_data_sync": {
            str(target): {
                key: item.get(key)
                for key in ("workbook_digest", "status", "synced_at")
                if item.get(key) is not None
            }
            for target, item in syncs.items()
            if isinstance(item, dict)
        },
    }


def _failure_evidence(unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for item in unresolved:
        if not isinstance(item, dict):
            continue
        context = unresolved_assignment_primitives.build_context(item)
        evidence.append(
            {
                "request_key": _opaque_key(
                    "request",
                    context.get("source_request_id"),
                ),
                "instructor_key": _opaque_key(
                    "instructor",
                    context.get("instructor"),
                ),
                "reason_code": str(item.get("reason_code") or "unknown"),
                "type": context.get("type"),
                "instrument": context.get("instrument"),
                "duration_minutes": context.get("duration_minutes"),
                "original_day": context.get("original_day"),
                "original_time": context.get("original_time"),
                "preferred_venues": list(context.get("preferred_venues") or []),
                "room_types": list(context.get("room_types") or []),
            }
        )
    return evidence


def _placement(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    start, end = TimeParser.event_clock_pair(value, default=(None, None))
    day = TimeParser.event_primary_js_day(value, default=None)
    raw_day = value.get("day")
    if day is None and isinstance(raw_day, int) and not isinstance(raw_day, bool):
        day = raw_day
    return {
        "room": value.get("resourceId") or value.get("room_id") or value.get("room"),
        "day": day,
        "start": start,
        "end": end,
    }


def _record_context(record: dict[str, Any]) -> dict[str, Any]:
    previous = record.get("prev_state")
    if not isinstance(previous, dict):
        return {}
    if record.get("action") == "assign":
        return unresolved_assignment_primitives.build_context(previous)
    props = previous.get("extendedProps")
    props = props if isinstance(props, dict) else {}
    raw = previous.get("raw_row")
    raw = raw if isinstance(raw, dict) else {}
    return {
        "source_request_id": (
            record.get("source_request_id")
            or previous.get("source_request_id")
            or props.get("source_request_id")
            or record.get("slot_id")
        ),
        "instructor": props.get("Instructor") or raw.get("Instructor"),
        "type": previous.get("type"),
        "instrument": (
            props.get("Instrument")
            or raw.get("Instrument")
            or previous.get("instrument")
        ),
    }


def _summarize_history_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    action = str(record.get("action") or "unknown")
    if action == "compound":
        children = [
            summary
            for item in record.get("records", [])
            if (summary := _summarize_history_record(item)) is not None
        ]
        return {
            "intervention_id": str(record.get("intervention_id") or "").strip(),
            "action": "compound",
            "label": str(record.get("label") or ""),
            "decision_note": str(record.get("decision_note") or "").strip(),
            "pi_plan_package_id": str(record.get("pi_plan_package_id") or "").strip() or None,
            "pi_plan_profile": str(record.get("pi_plan_profile") or "").strip() or None,
            "pi_plan_action_ids": [
                str(item) for item in record.get("pi_plan_action_ids") or []
            ],
            "pi_plan_outcome": str(record.get("pi_plan_outcome") or "").strip() or None,
            "pi_plan_revalidation": copy.deepcopy(
                record.get("pi_plan_revalidation") or {}
            ),
            "children": children,
        }

    context = _record_context(record)
    before = _placement(record.get("prev_state"))
    after = _placement(record.get("new_state"))
    confirmation = (
        (record.get("new_state") or {}).get("extendedProps", {})
        if isinstance(record.get("new_state"), dict)
        else {}
    )
    confirmation = (
        confirmation.get("teacher_time_change_confirmation", {})
        if isinstance(confirmation, dict)
        else {}
    )
    return {
        "intervention_id": str(record.get("intervention_id") or "").strip(),
        "pi_proposal_id": str(record.get("pi_proposal_id") or "").strip() or None,
        "action": action,
        "request_key": _opaque_key(
            "request",
            context.get("source_request_id"),
        ),
        "instructor_key": _opaque_key(
            "instructor",
            context.get("instructor"),
        ),
        "type": context.get("type"),
        "instrument": context.get("instrument"),
        "reason_code": (
            (record.get("prev_state") or {}).get("reason_code")
            if isinstance(record.get("prev_state"), dict)
            else None
        ),
        "before": before,
        "after": after,
        "room_changed": bool(
            before and after and before.get("room") != after.get("room")
        ),
        "time_changed": bool(
            before
            and after
            and any(
                before.get(key) != after.get(key)
                for key in ("day", "start", "end")
            )
        ),
        "teacher_confirmation_recorded": bool(
            isinstance(confirmation, dict) and confirmation.get("confirmed")
        ),
        "decision_note": str(record.get("decision_note") or "").strip(),
    }


def _upsert_intervention_event(
    run: dict[str, Any],
    history_record: dict[str, Any],
    *,
    active: bool,
    fallback_id: str = "",
) -> dict[str, Any] | None:
    summary = _summarize_history_record(history_record)
    if summary is None:
        return None
    intervention_id = str(summary.get("intervention_id") or fallback_id).strip()
    if not intervention_id:
        return None
    summary["intervention_id"] = intervention_id
    events = run.setdefault("intervention_events", [])
    if not isinstance(events, list):
        events = run["intervention_events"] = []
    existing = next(
        (
            item
            for item in events
            if isinstance(item, dict)
            and item.get("intervention_id") == intervention_id
        ),
        None,
    )
    recorded_at = (
        existing.get("recorded_at")
        if isinstance(existing, dict)
        else _utc_now()
    )
    stable_event = {
        **summary,
        "active": active,
        "recorded_at": recorded_at,
    }
    if isinstance(existing, dict) and all(
        existing.get(key) == value for key, value in stable_event.items()
    ):
        return existing
    event = {
        **stable_event,
        "updated_at": _utc_now(),
    }
    if existing is None:
        events.append(event)
    else:
        existing.clear()
        existing.update(event)
        event = existing
    return event


def _public_run(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    public = {
        key: copy.deepcopy(record.get(key))
        for key in (
            "run_id",
            "status",
            "started_at",
            "completed_at",
            "finalized_at",
            "duration_ms",
            "input_workspace_version",
            "dashboard_version",
            "baseline",
            "outcome",
        )
    }
    attempts = record.get("reconciliation_attempts")
    public["reconciliation_attempts"] = (
        copy.deepcopy(attempts) if isinstance(attempts, list) else []
    )
    return public


def stage_optimizer_learning_recovery(
    *,
    run_id: str,
    input_workspace_version: str,
    state: dict[str, Any],
    rules: dict[str, Any],
    duplicate_count: int,
    started_at: str,
    completed_at: str | None = None,
    duration_ms: int = 0,
    dashboard_version: str | None = None,
    preserved_pin_count: int = 0,
    downgraded_pin_count: int = 0,
    downgraded_pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Put the baseline in the canonical Step 4 session before it is saved."""
    edit_session = state.get("step4_edit_session")
    if not isinstance(edit_session, dict):
        raise OptimizerLearningRecordError(
            "Optimizer learning recovery requires an active Step 4 session"
        )
    assignments = list(edit_session.get("assignments", []) or [])
    unresolved = list(edit_session.get("unassigned_lessons", []) or [])
    record = {
        "run_id": run_id,
        "status": "open",
        "started_at": started_at,
        "completed_at": completed_at or _utc_now(),
        "finalized_at": None,
        "duration_ms": max(0, int(duration_ms)),
        "input_workspace_version": input_workspace_version,
        "dashboard_version": dashboard_version or _dashboard_version(),
        "baseline": _allocation_metrics(
            assignments,
            unresolved,
            duplicate_count=duplicate_count,
            preserved_pin_count=preserved_pin_count,
            downgraded_pin_count=downgraded_pin_count,
            downgraded_pins=downgraded_pins,
        ),
        "failure_evidence": _failure_evidence(unresolved),
        "rules_snapshot": _privacy_safe_rules(rules),
        "rules_trace": copy.deepcopy(state.get("scheduler_rules_trace") or {}),
        "source_provenance": _privacy_safe_provenance(
            state.get("scheduler_data_provenance")
        ),
        "intervention_events": [],
        "interventions": [],
        "reconciliation_attempts": [],
        "outcome": None,
    }
    edit_session["optimizer_learning_recovery"] = copy.deepcopy(record)
    return record


def record_optimizer_run(
    loader,
    *,
    run_id: str,
    input_workspace_version: str,
    state: dict[str, Any],
    rules: dict[str, Any],
    duplicate_count: int,
    started_at: str,
    completed_at: str | None = None,
    duration_ms: int = 0,
    dashboard_version: str | None = None,
    preserved_pin_count: int = 0,
    downgraded_pin_count: int = 0,
    downgraded_pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Append one optimizer baseline and make it the active Step 4 run."""
    ledger = _load_ledger(loader)
    for existing in ledger["runs"]:
        if isinstance(existing, dict) and existing.get("status") == "open":
            existing["status"] = "superseded"
            existing["superseded_by"] = run_id

    record = stage_optimizer_learning_recovery(
        run_id=run_id,
        input_workspace_version=input_workspace_version,
        state=state,
        rules=rules,
        duplicate_count=duplicate_count,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        dashboard_version=dashboard_version,
        preserved_pin_count=preserved_pin_count,
        downgraded_pin_count=downgraded_pin_count,
        downgraded_pins=downgraded_pins,
    )
    ledger["runs"] = [
        existing
        for existing in ledger["runs"]
        if not isinstance(existing, dict) or existing.get("run_id") != run_id
    ]
    ledger["runs"].append(record)
    _save_ledger(loader, ledger)
    return _public_run(record) or {}
def record_optimizer_intervention(
    loader,
    *,
    state: dict[str, Any],
    history_record: dict[str, Any],
    active: bool,
) -> dict[str, Any] | None:
    """Persist one Step 4 intervention independently of the undo-history cap."""
    edit_session = state.get("step4_edit_session")
    if not isinstance(edit_session, dict):
        return None
    run_id = str(edit_session.get("optimizer_run_id") or "").strip()
    if not run_id:
        return None

    ledger = _load_ledger(loader)
    run = _find_run(ledger, run_id)
    event = _upsert_intervention_event(
        run,
        history_record,
        active=active,
    )
    if event is None:
        return None
    _save_ledger(loader, ledger)
    return copy.deepcopy(event)


def _finalize_record(
    record: dict[str, Any],
    edit_session: dict[str, Any],
    *,
    warnings: list[str] | None = None,
    finalized_at: str | None = None,
) -> None:
    events = record.get("intervention_events")
    events = events if isinstance(events, list) else []
    interventions = [
        copy.deepcopy(item)
        for item in events
        if isinstance(item, dict) and item.get("active") is True
    ]
    final_metrics = _allocation_metrics(
        list(edit_session.get("assignments", []) or []),
        list(edit_session.get("unassigned_lessons", []) or []),
        duplicate_count=int((record.get("baseline") or {}).get("duplicates") or 0),
        preserved_pin_count=int((record.get("baseline") or {}).get("preserved_pin_count") or 0),
        downgraded_pin_count=int((record.get("baseline") or {}).get("downgraded_pin_count") or 0),
        downgraded_pins=(record.get("baseline") or {}).get("downgraded_pins") or [],
    )
    baseline = record.get("baseline")
    baseline = baseline if isinstance(baseline, dict) else {}
    record["status"] = "finalized"
    record["finalized_at"] = finalized_at or _utc_now()
    record["interventions"] = interventions
    record["outcome"] = {
        **final_metrics,
        "assigned_change": final_metrics["assigned"]
        - int(baseline.get("assigned") or 0),
        "unresolved_change": final_metrics["unresolved"]
        - int(baseline.get("unresolved") or 0),
        "allocation_rate_change": round(
            final_metrics["allocation_rate"]
            - float(baseline.get("allocation_rate") or 0.0),
            4,
        ),
        "intervention_count": len(interventions),
        "decision_note_count": sum(
            bool(str(item.get("decision_note") or "").strip())
            for item in interventions
        ),
        "finalize_warning_count": len(warnings or []),
    }


def finalize_optimizer_run(
    loader,
    *,
    state: dict[str, Any],
    warnings: list[str] | None = None,
    finalized_at: str | None = None,
) -> dict[str, Any] | None:
    """Attach the final Step 4 outcome to its optimizer baseline."""
    edit_session = state.get("step4_edit_session")
    if not isinstance(edit_session, dict):
        return None
    run_id = str(edit_session.get("optimizer_run_id") or "").strip()
    if not run_id:
        return None

    ledger = _load_ledger(loader)
    record = _find_run(ledger, run_id)
    for index, item in enumerate(edit_session.get("history", [])):
        if isinstance(item, dict):
            _upsert_intervention_event(
                record,
                item,
                active=True,
                fallback_id=f"legacy-{index}",
            )
    _finalize_record(
        record,
        edit_session,
        warnings=warnings,
        finalized_at=finalized_at,
    )
    _save_ledger(loader, ledger)
    return _public_run(record)


_LEDGER_OMITTED_ATTEMPT_KEYS = (
    "snapshot",
    "aliases",
    "alias_to_subject",
    "teacher_aliases",
    "scope_issue_ids",
    "goal",
    "protect_teachers",
    "protect_subject_ids",
    "allow_time_change_teachers",
    "allow_day_split_teachers",
    "teacher_display",
    "prior_decisions",
)
_LEDGER_TASK_KEYS = (
    "day",
    "scope_type",
    "scope_id",
    "time_is_fixed",
    "tool_calls_used",
    "tool_call_budget",
    "sacrifice_requires_authorization",
    "protect_teacher_aliases",
    "time_change_exception_teacher_aliases",
    "locked_room_days",
)
_LEDGER_OMITTED_SIMULATION_KEYS = ("changes",)


def _ledger_reconciliation_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    """Strip identities and free text from a reconciliation attempt.

    The local Step 4 session keeps the full record, including real instructor
    names and lesson labels for the operator's review. The shared audit ledger
    keeps only alias-based decision evidence.
    """
    for key in _LEDGER_OMITTED_ATTEMPT_KEYS:
        attempt.pop(key, None)
    task = attempt.get("task")
    if isinstance(task, dict):
        attempt["task"] = {key: task[key] for key in _LEDGER_TASK_KEYS if key in task}
    simulations = attempt.get("simulations")
    if isinstance(simulations, dict):
        attempt["simulations"] = [
            copy.deepcopy(item.get("public"))
            for item in simulations.values()
            if isinstance(item, dict) and isinstance(item.get("public"), dict)
        ]
    if isinstance(attempt.get("simulations"), list):
        for simulation in attempt["simulations"]:
            if isinstance(simulation, dict):
                for key in _LEDGER_OMITTED_SIMULATION_KEYS:
                    simulation.pop(key, None)
    apply_result = attempt.get("apply_result")
    if isinstance(apply_result, dict):
        apply_result.pop("changes", None)
    brief = attempt.get("brief")
    if isinstance(brief, dict):
        for collection in (brief.get("remaining_issues"), brief.get("sacrifices")):
            for item in collection or []:
                if isinstance(item, dict):
                    item.pop("label", None)
    return attempt


def record_reconciliation_attempt(
    loader,
    *,
    run_id: str,
    investigation: dict[str, Any],
) -> dict[str, Any]:
    """Persist auditable outcome metadata without storing the private snapshot."""
    ledger = _load_ledger(loader)
    record = _find_run(ledger, run_id)
    attempts = record.setdefault("reconciliation_attempts", [])
    if not isinstance(attempts, list):
        attempts = record["reconciliation_attempts"] = []
    attempt = copy.deepcopy(investigation) if isinstance(investigation, dict) else {}
    attempt_id = str(attempt.get("investigation_id") or uuid.uuid4().hex)
    attempt["investigation_id"] = attempt_id
    attempt.setdefault("recorded_at", _utc_now())
    attempt = _ledger_reconciliation_attempt(attempt)
    attempts[:] = [
        item for item in attempts
        if not (isinstance(item, dict) and item.get("investigation_id") == attempt_id)
    ]
    attempts.append(attempt)
    _save_ledger(loader, ledger)
    return copy.deepcopy(attempt)
def repair_optimizer_learning_record(
    loader,
    *,
    state: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Replay canonical Step 4 evidence when the projection file fell behind."""
    edit_session = state.get("step4_edit_session")
    if not isinstance(edit_session, dict):
        return None
    recovery = edit_session.get("optimizer_learning_recovery")
    if not isinstance(recovery, dict):
        return None
    run_id = str(edit_session.get("optimizer_run_id") or "").strip()
    if not run_id or recovery.get("run_id") != run_id:
        return None

    ledger = _load_ledger(loader)
    before = copy.deepcopy(ledger)
    try:
        record = _find_run(ledger, run_id)
    except OptimizerLearningRecordError:
        for existing in ledger["runs"]:
            if isinstance(existing, dict) and existing.get("status") == "open":
                existing["status"] = "superseded"
                existing["superseded_by"] = run_id
        record = copy.deepcopy(recovery)
        ledger["runs"].append(record)

    evidence = edit_session.get("optimizer_intervention_recovery")
    evidence = evidence if isinstance(evidence, list) else []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or not isinstance(item.get("record"), dict):
            continue
        history_record = item["record"]
        _upsert_intervention_event(
            record,
            history_record,
            active=bool(item.get("active")),
            fallback_id=f"recovered-{index}",
        )

    finalized_at = str(edit_session.get("optimizer_finalized_at") or "").strip()
    if (
        state.get("round_committed")
        and finalized_at
        and (record.get("status") != "finalized" or not record.get("outcome"))
    ):
        _finalize_record(
            record,
            edit_session,
            warnings=list(
                edit_session.get("optimizer_finalize_warnings") or warnings or []
            ),
            finalized_at=finalized_at,
        )
    if ledger != before:
        _save_ledger(loader, ledger)
    return _public_run(record)


def get_optimizer_learning_view(loader) -> dict[str, Any]:
    """Return a small UI-facing summary without raw intervention evidence."""
    runs = _load_ledger(loader)["runs"]
    valid_runs = [item for item in runs if isinstance(item, dict)]
    return {
        "latest": _public_run(valid_runs[-1]) if valid_runs else None,
        "total_runs": len(valid_runs),
        "finalized_runs": sum(item.get("status") == "finalized" for item in valid_runs),
        "open_runs": sum(item.get("status") == "open" for item in valid_runs),
    }
