"""Run-scoped Pi investigation for Step 4 linked schedule reconciliation."""

from __future__ import annotations

import copy
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from modules.api.services.pi_optimizer_intervention import (
    PiOptimizerInterventionError,
    PiRpcResult,
    PiRpcTimeout,
    run_pi_rpc,
)
from modules.api.services.scheduler import restore_scheduler_state
from modules.api.services.workspace import compute_workspace_version
from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.reconciliation_investigation import (
    ReconciliationInvestigation,
    public_record_from_persisted,
)
from modules.scheduler.logic.resolution_package import (
    PackageRejected,
    normalize_package_changes,
    package_hash,
)
from modules.scheduler.logic.reservation_classifier import (
    RESERVATION_INTERNAL,
    classify_unresolved_reservations,
)
from modules.scheduler.logic.session_state import (
    ensure_step4_edit_session,
    persist_scheduler_session,
)
from modules.scheduler.logic.step4_service import build_step4_runtime


RECONCILIATION_PROMPT_VERSION = "pi-step4-reconciliation-v5"
MAX_STORED_RECONCILIATION_PLANS = 3
DECISION_MEMORY_KEY = "reconciliation_decision_memory"
MAX_DECISION_MEMORY = 32
RECONCILIATION_TOOL_NAMES = (
    "inspect_reconciliation",
    "simulate_reconciliation_package",
    "submit_reconciliation_brief",
)
RECONCILIATION_SYSTEM_PROMPT = """You are a bounded Step 4 reconciliation investigator.
Python is the scheduling authority. Use tools with exact subject aliases
(issue-N, assignment-N, block-N). Instructor names in the snapshot are real
roster names; student identities stay aliased. Never ask for or infer student
names, hidden rules, or external facts.

Non-negotiable premises:
- Scheduled times are fixed. Date, start, end and duration stay as they are.
  Rooms are the normal adjustment dimension. Never move a lesson to another day.
- Time-change exceptions are listed in the task premises. Even then, try every
  reasonable fixed-time package first; only use an authorized exception when no
  acceptable fixed-time package exists, and say so in the brief.
- Preserve every already assigned lesson whenever a feasible package can do so.
  A teacher having to use a second room on the same day is a disclosed cost, not
  a forbidden move; report it rather than hiding it.
- If no preserve-all package is feasible, you may sandbox a trade-off package
  that leaves a named assigned lesson unresolved. Label it explicitly as a
  sacrifice; the operator must authorize each sacrificed lesson separately.
- One teacher's consent never covers another teacher or another package.

Work with purpose:
- Inspect the whole day once, then test a small number of genuinely different
  complete packages. Every further test must answer a real question: unblock
  important work, remove a clear cost, or confirm a condition a package depends on.
- The operator goal in the task premises is a real constraint. If it says move
  instrumental work first and keep piano/voice in place, a package that places
  the legally available work is a valid primary even when harder lessons remain.
- available_rooms are Python-legal empty rooms. incompatible_empty_rooms are
  occupancy-empty rooms that room-type rules reject. Those are emergency options
  for a human exception, never legal simulate targets. If legal rooms are
  exhausted, put that in pending_decisions as exception_authorization; do not
  treat it as a feasible package and do not call the day impossible.
- candidate_rooms are currently empty legal rooms. An empty list sets
  swap_required: the block can still move if another block leaves that room in
  the same package. It is not immovable.
- room_type_mismatch means that room is illegal for this instrument. Do not
  retry the same illegal room. Python will not waive room types.
- unknown_subject_alias, missing_subject_alias, empty_package, and
  duplicate_subject are package-shape errors. Read rejection and resubmit a
  complete alias+target list. Do not ask the operator how placement works.
- If the operator goal names an instructor and rooms, that is the primary
  work. Do not substitute an easier unrelated placement package.
- Do not repeat an equivalent package, do not retry a rule rejection in new
  wording, and do not search without a reason.
- A follow-up is continued directed discussion, not a chat session and not a
  new authority. Read prior_thread, then obey the new operator goal. Python
  still validates every package. Empty new goal means continue the last thread.
- Submit exactly one brief. A bounded search that found nothing is not proof the
  day is impossible.
- If a preservation package exists, it must be the primary recommendation; a
  sacrifice package may only be the fallback.
"""
RECONCILIATION_TASK_PROMPT = """Investigate this day's linked Step 4 adjustment work.
Start with inspect_reconciliation to see the whole day, its teacher-day blocks,
the conflict neighbourhood, and which rooms are free right now.
Follow the operator goal in the task premises. candidate_rooms and
available_rooms are currently empty legal rooms, not the only legal final-state
targets. swap_required means simulate a swapped final state; do not treat the
block as immovable. A complete package may swap two blocks that occupy each
other.
Then sandbox-test complete packages through simulate_reconciliation_package.
Each package must include every move that package needs; do not drop a
prerequisite and apply the rest. A chain that does not depend on a waiting
confirmation may be the primary package; keep dependent waiting work in
remaining_issues. Independent legally placeable work must be recommended even
when specialised lessons still need a human exception.
incompatible_empty_rooms are occupancy facts, not applyable targets. If the
only remaining option is an otherwise illegal room type, ask for
exception_authorization; do not simulate it as feasible.
Follow any prior operator decisions in the task premises: do not re-propose a
package the operator already rejected unless new evidence changes it.
Then submit one brief with exactly one main recommendation when a placing
package exists, the complete change list, the remaining unresolved work, and
whatever genuinely needs a human decision. Use pending_decisions for missing
facts, business trade-offs, and emergency room-type exceptions. Teacher
confirmations and sacrifice authorizations are derived from the chosen package.
Stop at the bounded search budget. Report budget exhaustion as an interrupted
investigation, never as a proven impossibility.
"""


class PiReconciliationError(RuntimeError):
    """Raised when a run-scoped reconciliation capability is invalid."""


# Real instructor and lesson labels exist for the operator's local review, not
# for the model: the Pi-facing tool surface stays alias-only.
_MODEL_HIDDEN_SIMULATION_KEYS = ("changes",)


def _model_safe_simulation(result: dict[str, Any]) -> dict[str, Any]:
    safe = copy.deepcopy(result) if isinstance(result, dict) else result
    if isinstance(safe, dict):
        for key in _MODEL_HIDDEN_SIMULATION_KEYS:
            safe.pop(key, None)
    return safe



@dataclass
class TimedTokenStore:
    """Thread-safe map of opaque tokens to values with TTL expiry."""

    error_factory: Callable[[], Exception]
    min_ttl_seconds: int = 60

    def __post_init__(self) -> None:
        self._items: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

    def create(self, value: Any, *, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._items[token] = (
                value,
                monotonic() + max(self.min_ttl_seconds, int(ttl_seconds)),
            )
        return token

    def get(self, token: str) -> Any:
        with self._lock:
            return self._get_unlocked(token)

    def mutate(self, token: str, mutator: Callable[[Any], Any]) -> Any:
        with self._lock:
            value = self._get_unlocked(token)
            return mutator(value)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._items.pop(str(token or ""), None)

    def _get_unlocked(self, token: str) -> Any:
        key = str(token or "")
        item = self._items.get(key)
        if item is None or item[1] <= monotonic():
            self._items.pop(key, None)
            raise self.error_factory()
        return item[0]


@dataclass
class _Capability:
    run_id: str
    investigation: ReconciliationInvestigation
    tool_events: list[dict[str, Any]] = field(default_factory=list)


class PiReconciliationCapabilityStore:
    """Short-lived server-owned state for one reconciliation investigation."""

    def __init__(self) -> None:
        self._tokens = TimedTokenStore(
            error_factory=lambda: PiReconciliationError(
                "The reconciliation capability is invalid or expired."
            ),
            min_ttl_seconds=60,
        )

    def create(self, investigation: ReconciliationInvestigation, *, ttl_seconds: int = 600) -> str:
        return self._tokens.create(
            _Capability(run_id=investigation.run_id, investigation=investigation),
            ttl_seconds=ttl_seconds,
        )

    def resolve(self, token: str) -> dict[str, Any]:
        item = self._tokens.get(token)
        investigation = item.investigation
        return {
            "run_id": item.run_id,
            "investigation_id": investigation.investigation_id,
            "workspace_version": investigation.workspace_version,
            "snapshot_hash": investigation.snapshot_hash,
            "scope_type": investigation.scope_type,
            "scope_id": investigation.scope_id,
            "focus_aliases": investigation.focus_aliases(),
            "brief_submitted": investigation.public_record().get("brief") is not None,
        }

    def inspect(self, token: str, focus_aliases=None) -> dict[str, Any]:
        def _run(item: _Capability):
            result = item.investigation.inspect_reconciliation(focus_aliases)
            self._record(item, "inspect_reconciliation", {
                "subjects": len(result.get("subjects") or []),
                "edges": len(result.get("edges") or []),
            })
            return result
        return self._tokens.mutate(token, _run)

    def simulate(self, token: str, changes) -> dict[str, Any]:
        def _run(item: _Capability):
            result = _model_safe_simulation(item.investigation.simulate_package(changes))
            self._record(item, "simulate_reconciliation_package", {
                "simulation_id": result.get("simulation_id"),
                "status": result.get("status"),
                "feasible": bool(result.get("feasible")),
                "duplicate": bool(result.get("duplicate")),
                "change_count": len(result.get("normalized_changes") or []),
            })
            return result
        return self._tokens.mutate(token, _run)

    def submit(self, token: str, params: dict[str, Any]) -> dict[str, Any]:
        def _run(item: _Capability):
            result = item.investigation.submit_reconciliation_brief(params)
            self._record(item, "submit_reconciliation_brief", {
                "brief_id": result.get("brief_id"),
                "termination": result.get("termination"),
                "simulation_count": result.get("coverage", {}).get("simulation_count", 0),
            })
            return result
        return self._tokens.mutate(token, _run)

    def close_at_bound(self, token: str, *, bound: str = "runtime") -> dict[str, Any]:
        def _run(item: _Capability):
            result = item.investigation.close_at_server_bound(bound=bound)
            self._record(item, "close_at_server_bound", {
                "brief_id": result.get("brief_id"),
                "termination": result.get("termination"),
                "bound": bound,
            })
            return result
        return self._tokens.mutate(token, _run)

    def _record(self, item: _Capability, tool: str, result: dict[str, Any]) -> None:
        item.tool_events.append({"tool": tool, "result": copy.deepcopy(result)})

    def snapshot(self, token: str) -> dict[str, Any]:
        item = self._tokens.get(token)
        record = item.investigation.persisted_record()
        record["tool_events"] = copy.deepcopy(item.tool_events)
        return record

    def public_record(self, token: str, *, current_snapshot_hash=None):
        item = self._tokens.get(token)
        return item.investigation.public_record(current_snapshot_hash=current_snapshot_hash)

    def revoke(self, token: str) -> None:
        self._tokens.revoke(token)


def _teacher_alias_of(investigation, name):
    key = str(name or "").strip().casefold()
    for teacher, alias in investigation._teacher_aliases.items():
        if teacher == key:
            return alias
    return ""


def _decision_from_record(record):
    if not isinstance(record, dict):
        return None
    task = record.get("task") if isinstance(record.get("task"), dict) else {}
    day = record.get("day") if isinstance(record.get("day"), int) else task.get("day")
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else {}
    status = str(brief.get("status") or "")
    operation = str(record.get("operation_status") or "")
    if status not in {"rejected", "pursuing"} and operation != "applied":
        return None

    if operation == "applied":
        selected_ids = [str((record.get("apply_result") or {}).get("simulation_id") or "")]
    else:
        selected_ids = [
            str(brief.get(key) or "")
            for key in ("primary_simulation_id", "fallback_simulation_id")
        ]
    simulations = record.get("simulations") if isinstance(record.get("simulations"), dict) else {}
    raw_aliases = record.get("alias_to_subject")
    raw_aliases = raw_aliases if isinstance(raw_aliases, dict) else {}
    packages = []
    subject_ids = set()
    for simulation_id in dict.fromkeys(item for item in selected_ids if item):
        simulation = simulations.get(simulation_id)
        if not isinstance(simulation, dict):
            continue
        raw_changes = copy.deepcopy(simulation.get("raw_changes") or [])
        if not raw_changes:
            for change in (simulation.get("public") or {}).get("normalized_changes") or []:
                mapping = raw_aliases.get(str(change.get("subject_alias")))
                if not isinstance(mapping, (list, tuple)) or len(mapping) != 2 or mapping[0] == "block":
                    continue
                projected = copy.deepcopy(change)
                projected["subject_alias"] = str(mapping[1])
                raw_changes.append(projected)
        try:
            canonical = normalize_package_changes(raw_changes)
        except PackageRejected:
            continue
        for change in canonical:
            subject_ids.add(str(change["subject_alias"]))
        packages.append(
            {
                "simulation_id": simulation_id,
                "package_hash": package_hash(canonical),
                "changes": canonical,
            }
        )
    return {
        "day": day,
        "status": "applied" if operation == "applied" else status,
        "decided_at": str(brief.get("decided_at") or record.get("created_at") or ""),
        "note": str(brief.get("decision_note") or record.get("failure") or ""),
        "subject_ids": sorted(subject_ids),
        "packages": packages,
    }


def _prior_day_decisions(edit_session, day: int):
    """Operator decisions for the same day, in canonical subject ids."""
    decisions = []
    seen = set()
    records = list((edit_session.get("reconciliation_plans") or {}).values())
    records.extend(edit_session.get(DECISION_MEMORY_KEY) or [])
    for record in records:
        item = (
            record
            if isinstance(record, dict)
            and "status" in record
            and ("subject_ids" in record or "packages" in record)
            else _decision_from_record(record)
        )
        if not item or item.get("day") != day:
            continue
        key = (
            item.get("status"),
            item.get("decided_at"),
            tuple(package.get("package_hash") for package in item.get("packages") or []),
            tuple(item.get("subject_ids") or []),
        )
        if key in seen:
            continue
        seen.add(key)
        decisions.append(
            {
                "status": item["status"],
                "decided_at": item["decided_at"],
                "note": item.get("note") or "",
                "subject_ids": list(item.get("subject_ids") or []),
                "packages": copy.deepcopy(item.get("packages") or []),
            }
        )
    return decisions


def _last_day_thread(edit_session, day: int):
    """Last same-day investigation, so a follow-up can continue the discussion."""
    records = [
        item
        for item in (edit_session.get("reconciliation_plans") or {}).values()
        if isinstance(item, dict)
        and item.get("day") == day
        and isinstance(item.get("brief"), dict)
    ]
    if not records:
        return None
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    record = records[0]
    brief = record["brief"]
    goals = []
    for item in records[:3]:
        goal = str(item.get("goal") or "").strip()[:600]
        if goal and goal not in goals:
            goals.append(goal)
    display = record.get("teacher_display") if isinstance(record.get("teacher_display"), dict) else {}
    alias_to_subject = record.get("alias_to_subject") if isinstance(record.get("alias_to_subject"), dict) else {}
    remaining_ids = []
    for item in brief.get("remaining_issues") or []:
        if not isinstance(item, dict):
            continue
        mapping = alias_to_subject.get(str(item.get("subject_alias") or ""))
        if isinstance(mapping, (list, tuple)) and len(mapping) == 2 and mapping[0] == "issue":
            remaining_ids.append(str(mapping[1]))
    pending = []
    for item in brief.get("pending_decisions") or []:
        if not isinstance(item, dict):
            continue
        alias = str(item.get("teacher_alias") or "")
        pending.append({
            "kind": str(item.get("kind") or "other"),
            "detail": str(item.get("detail") or "")[:400],
            "teacher": str(display.get(alias) or alias or ""),
        })
    codes = []
    simulations = record.get("simulations") or {}
    values = simulations.values() if isinstance(simulations, dict) else simulations
    for sim in values:
        public = sim.get("public") if isinstance(sim, dict) and isinstance(sim.get("public"), dict) else sim
        if not isinstance(public, dict):
            continue
        for code in public.get("failure_codes") or []:
            text = str(code or "").strip()
            if text and text not in codes:
                codes.append(text)
    return {
        "goal": goals[0] if goals else str(record.get("goal") or ""),
        "goals": goals,
        "termination": str(brief.get("termination") or ""),
        "failure_codes": codes[:8],
        "pending": pending[:8],
        "remaining_issue_ids": remaining_ids[:24],
    }


def build_reconciliation_investigation(
    context,
    *,
    expected_version: str,
    day: int,
    goal: str = "",
    protect_instructors=(),
    allow_time_change_instructors=(),
    locked_room_days=(),
    max_tool_calls: int | None = None,
) -> ReconciliationInvestigation:
    """Build one whole-day investigation from the current Python-owned runtime."""
    from modules.scheduler.logic.resolution_advice import build_resolution_advice
    from modules.api.services.scheduler import SchedulerCommandRejected

    state = restore_scheduler_state(context)
    runtime = build_step4_runtime(context, state)
    run_id = str(runtime.edit_session.get("optimizer_run_id") or "").strip()
    if not run_id:
        raise SchedulerCommandRejected("An active optimizer run is required for reconciliation.")
    if day not in range(7):
        raise SchedulerCommandRejected("A valid day is required for reconciliation.")
    advice = build_resolution_advice(runtime)
    cases = list(advice.get("cases") or [])
    # Reservation-internal rows are not operator work: Python already explains
    # why they stay unresolved, so they are not re-opened as a task.
    reservation_labels = classify_unresolved_reservations(
        list(runtime.edit_session.get("assignments") or []),
        list(runtime.edit_session.get("unassigned_lessons") or []),
    )
    parked_issue_ids = set()
    for item in runtime.edit_session.get("unassigned_lessons") or []:
        if not isinstance(item, dict):
            continue
        payload = reservation_labels.get(str(item.get("id") or "")) or {}
        if str(payload.get("label") or "") == RESERVATION_INTERNAL:
            parked_issue_ids.add(
                unresolved_assignment_primitives.issue_id(item)
            )
    selected = [
        case
        for case in cases
        if case.get("day") == day and not case.get("waiting")
    ]
    issue_ids = [
        issue.get("issue_id")
        for case in selected
        for issue in case.get("issues") or []
        if issue.get("issue_id") and issue.get("issue_id") not in parked_issue_ids
    ]
    if not issue_ids:
        parked = [
            case for case in cases if case.get("day") == day and case.get("waiting")
        ]
        if parked:
            raise SchedulerCommandRejected(
                "Every unresolved lesson on this day is parked in Waiting; "
                "clear the waiting note before investigating again."
            )
        if parked_issue_ids:
            raise SchedulerCommandRejected(
                "This day has no unresolved lessons needing reconciliation; "
                "the remaining rows are reservation-internal."
            )
        raise SchedulerCommandRejected("This day has no unresolved lessons needing reconciliation.")
    if str(expected_version) != compute_workspace_version(context.loader.base_dir, context=context):
        raise SchedulerCommandRejected("The workspace changed; refresh before investigating.")
    investigation = ReconciliationInvestigation(
        runtime,
        workspace_version=expected_version,
        run_id=run_id,
        day=day,
        issue_ids=issue_ids,
        goal=goal,
        protect_teachers=protect_instructors,
        protect_subject_ids=(),
        allow_time_change_teachers=allow_time_change_instructors,
        locked_room_days=locked_room_days,
        prior_decisions=_prior_day_decisions(runtime.edit_session, day),
        prior_thread=_last_day_thread(runtime.edit_session, day),
        max_tool_calls=max_tool_calls,
    )
    known = set(investigation._teacher_aliases)
    for label, names in (
        ("protect", protect_instructors),
        ("time-change exception", allow_time_change_instructors),
    ):
        unknown = sorted(
            str(name) for name in names if str(name or "").strip().casefold() not in known
        )
        if unknown:
            raise SchedulerCommandRejected(
                f"Unknown instructor for the {label} list: {unknown[0]}"
            )
    return investigation


def _persist_private_investigation(context, record: dict[str, Any]) -> None:
    state = restore_scheduler_state(context)
    edit_session = ensure_step4_edit_session(state)
    run_id = str(edit_session.get("optimizer_run_id") or "").strip()
    if run_id != str(record.get("run_id") or ""):
        raise PiReconciliationError("The optimizer run changed before reconciliation was saved.")
    plans = edit_session.setdefault("reconciliation_plans", {})
    plans[str(record["investigation_id"])] = copy.deepcopy(record)
    # ponytail: keep only the active recent attempts; the full audit trail lives
    # in the optimizer ledger, so old snapshots are dead weight in the session.
    if len(plans) > MAX_STORED_RECONCILIATION_PLANS:
        ordered = sorted(
            plans.items(),
            key=lambda item: str((item[1] or {}).get("created_at") or ""),
            reverse=True,
        )
        memory = list(edit_session.get(DECISION_MEMORY_KEY) or [])
        for _investigation_id, evicted in ordered[MAX_STORED_RECONCILIATION_PLANS:]:
            compact = _decision_from_record(evicted)
            if compact:
                memory.append(compact)
        edit_session["reconciliation_plans"] = dict(ordered[:MAX_STORED_RECONCILIATION_PLANS])
        # ponytail: compact decision rows, not full snapshots; raise if a term exceeds this.
        edit_session[DECISION_MEMORY_KEY] = memory[-MAX_DECISION_MEMORY:]
    expected = state.get("scheduler_session_revision") or state.get("scheduler_session_mtime")
    outcome = persist_scheduler_session(context.session_manager, state, expected_mtime=expected)
    if getattr(outcome, "status", "") == "conflict":
        raise PiReconciliationError("The scheduler session changed before reconciliation was saved.")


def _record_attempt(context, run_id: str, record: dict[str, Any], *, operation_id: str, failure: str = "") -> None:
    from modules.scheduler.logic.optimizer_learning_record import record_reconciliation_attempt

    public = copy.deepcopy(record)
    public.pop("teacher_display", None)
    public.pop("snapshot", None)
    public.update({"agent_run_id": operation_id})
    if failure:
        public["operation_status"] = "failed"
        public["failure"] = failure[:500]
    record_reconciliation_attempt(context.loader, run_id=run_id, investigation=public)


def _operator_rpc_prompt(investigation: ReconciliationInvestigation) -> str:
    """Put the compact operator turn in the RPC prompt, the actual user message."""
    task = investigation.model_task()
    payload = {
        "goal": task.get("goal") or "",
        "prior_thread": task.get("prior_thread"),
    }
    if not payload["goal"] and not payload["prior_thread"]:
        return RECONCILIATION_TASK_PROMPT
    return (
        RECONCILIATION_TASK_PROMPT
        + "\nOperator turn (aliases only; inspect for current occupancy):\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def run_pi_reconciliation_operation(
    *,
    context,
    registry,
    operation_id: str,
    investigation: ReconciliationInvestigation,
    model: str,
    tool_url: str,
    capability_store: PiReconciliationCapabilityStore,
    provider: str | None = None,
    thinking: str | None = None,
    rpc_runner: Callable[..., PiRpcResult] | None = None,
    provider_extension: str | None = None,
    tool_extension: str | None = None,
) -> None:
    """Run Pi, persist the private snapshot locally, and ledger public evidence."""
    token = capability_store.create(investigation)
    failure = ""
    record = None
    try:
        registry.start(operation_id, phase="investigating")
        rpc_result = None
        try:
            rpc_result = (rpc_runner or run_pi_rpc)(
                _operator_rpc_prompt(investigation),
                model=model,
                provider=provider,
                thinking=thinking,
                provider_extension=provider_extension,
                tool_extension=tool_extension or str(Path(__file__).with_name("pi_reconciliation_extension.js")),
                tool_names=RECONCILIATION_TOOL_NAMES,
                system_prompt=RECONCILIATION_SYSTEM_PROMPT,
                environment={
                    "PI_RECONCILIATION_TOOL_URL": tool_url,
                    "PI_RECONCILIATION_CAPABILITY": token,
                },
            )
        except PiRpcTimeout:
            rpc_result = None
        if rpc_result is not None and (not rpc_result.provider or not rpc_result.model):
            raise PiReconciliationError("Pi returned incomplete provider/model metadata.")
        record = capability_store.snapshot(token)
        if not isinstance(record.get("brief"), dict):
            capability_store.close_at_bound(
                token,
                bound="runtime" if rpc_result is None else "unterminated",
            )
            record = capability_store.snapshot(token)
        brief = record.get("brief")
        if not isinstance(brief, dict):
            raise PiReconciliationError("Pi finished without submitting a reconciliation brief.")
        record.update({
            "agent_run_id": operation_id,
            "operation_status": "completed",
            "pi_version": getattr(rpc_result, "pi_version", "") or "",
            "provider": getattr(rpc_result, "provider", "") or "",
            "model": getattr(rpc_result, "model", "") or "",
            "latency_ms": getattr(rpc_result, "latency_ms", 0) or 0,
            "usage": getattr(rpc_result, "usage", {}) or {},
        })
        registry.start(operation_id, phase="saving_reconciliation")
        with context.mutation_lock:
            _persist_private_investigation(context, record)
            _record_attempt(context, investigation.run_id, record, operation_id=operation_id)
            workspace_version = compute_workspace_version(context.loader.base_dir, context=context)
        registry.complete(operation_id, result={
            "run_id": investigation.run_id,
            "investigation_id": investigation.investigation_id,
            "workspace_version": workspace_version,
        })
    except (PiReconciliationError, PiOptimizerInterventionError) as exc:
        if record is None:
            record = capability_store.snapshot(token)
        if (
            not isinstance(exc, PiReconciliationError)
            and isinstance(record.get("brief"), dict)
        ):
            record.update({
                "agent_run_id": operation_id,
                "operation_status": "completed",
                "pi_version": "",
                "provider": "",
                "model": "",
                "latency_ms": 0,
                "usage": {},
            })
            registry.start(operation_id, phase="saving_reconciliation")
            with context.mutation_lock:
                _persist_private_investigation(context, record)
                _record_attempt(context, investigation.run_id, record, operation_id=operation_id)
                workspace_version = compute_workspace_version(context.loader.base_dir, context=context)
            registry.complete(operation_id, result={
                "run_id": investigation.run_id,
                "investigation_id": investigation.investigation_id,
                "workspace_version": workspace_version,
            })
            return
        failure = str(exc)
        try:
            record["operation_status"] = "failed"
            with context.mutation_lock:
                _persist_private_investigation(context, record)
                _record_attempt(context, investigation.run_id, record, operation_id=operation_id, failure=failure)
        except Exception:
            pass
        registry.fail(operation_id, error=failure)
    except Exception:
        failure = "Pi reconciliation failed unexpectedly; no schedule was changed."
        try:
            record = capability_store.snapshot(token)
            record["operation_status"] = "failed"
            record["failure"] = failure
            with context.mutation_lock:
                _persist_private_investigation(context, record)
                _record_attempt(context, investigation.run_id, record, operation_id=operation_id, failure=failure)
        except Exception:
            pass
        registry.fail(operation_id, error=failure)
    finally:
        capability_store.revoke(token)


def get_reconciliation_public_record(context, runtime):
    plans = runtime.edit_session.get("reconciliation_plans")
    if not isinstance(plans, dict) or not plans:
        return None
    # Insertion order breaks created_at ties, so a fresh investigation created in
    # the same second still wins over the previous one.
    records = [
        (str(item.get("created_at") or ""), index, item)
        for index, item in enumerate(plans.values())
        if isinstance(item, dict)
    ]
    records.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    for _created_at, _index, record in records:
        current_hash = ReconciliationInvestigation.snapshot_hash_for_runtime(
            runtime,
            record.get("scope_issue_ids") or None,
        )
        public = public_record_from_persisted(
            record,
            current_snapshot_hash=current_hash,
        )
        if public:
            return public
    return None


def _rehydrate(context, investigation_id):
    state = restore_scheduler_state(context)
    edit_session = ensure_step4_edit_session(state)
    plans = edit_session.get("reconciliation_plans") or {}
    record = plans.get(str(investigation_id)) if isinstance(plans, dict) else None
    if not isinstance(record, dict):
        raise PiReconciliationError("The reconciliation investigation is no longer available.")
    runtime = build_step4_runtime(context, state)
    return state, runtime, record


def decide_reconciliation(context, *, investigation_id: str, decision: str, note: str = ""):
    state, runtime, record = _rehydrate(context, investigation_id)
    investigation = ReconciliationInvestigation.from_persisted(record, runtime)
    result = investigation.set_decision(decision, note=note)
    record.update(investigation.persisted_record())
    record["operation_status"] = "completed"
    _persist_private_investigation(context, record)
    return result


def apply_reconciliation(
    context,
    *,
    investigation_id: str,
    simulation_id: str,
    expected_version: str,
    confirmed_teacher_aliases: list[str],
    authorized_sacrifice_aliases=(),
    confirmed_confirmation_ids=(),
    note: str = "",
):
    state, runtime, record = _rehydrate(context, investigation_id)
    current_hash = ReconciliationInvestigation.snapshot_hash_for_runtime(
        runtime,
        record.get("scope_issue_ids") or None,
    )
    if current_hash != record.get("snapshot_hash"):
        raise PiReconciliationError("The schedule changed; the reconciliation package must be revalidated.")
    investigation = ReconciliationInvestigation.from_persisted(record, runtime)
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else {}
    # One whole-package approval is enough; a separate "pursue" step adds no
    # decision. A rejected brief stays rejected until the day is investigated again.
    if brief.get("status") not in {"proposed", "pursuing"}:
        raise PiReconciliationError(
            "This reconciliation brief was rejected; investigate the day again before applying."
        )
    simulations = record.get("simulations") if isinstance(record.get("simulations"), dict) else {}
    simulation = simulations.get(str(simulation_id))
    if not isinstance(simulation, dict) or not isinstance(simulation.get("public"), dict):
        raise PiReconciliationError("The selected reconciliation simulation is unavailable.")
    public = simulation["public"]
    if public.get("status") not in {"feasible", "conditional"}:
        raise PiReconciliationError("Only a feasible or conditional simulation can be applied.")
    selected_ids = {
        str(brief.get("primary_simulation_id") or ""),
        str(brief.get("fallback_simulation_id") or ""),
    }
    if str(simulation_id) not in selected_ids:
        raise PiReconciliationError("The selected simulation is not part of the pursued brief.")
    reverse_aliases = {
        str(alias): teacher
        for teacher, alias in (record.get("teacher_aliases") or {}).items()
    }
    required_confirmations = [
        item
        for item in (public.get("required_teacher_confirmations") or [])
        if isinstance(item, dict) and item.get("confirmation_id")
    ]
    required_ids = {
        str(item["confirmation_id"]): str(item.get("teacher_alias") or "")
        for item in required_confirmations
    }
    submitted_ids = {
        str(item).strip() for item in (confirmed_confirmation_ids or []) if str(item).strip()
    }
    if required_ids:
        if set(required_ids) - submitted_ids:
            raise PiReconciliationError(
                "Every affected teacher must confirm the exact reconciliation package before apply."
            )
        if submitted_ids - set(required_ids):
            raise PiReconciliationError("Teacher confirmation does not belong to this package.")
        confirmed_teachers = [
            reverse_aliases[alias]
            for alias in required_ids.values()
            if alias in reverse_aliases
        ]
    else:
        confirmed_teachers = [
            reverse_aliases[alias]
            for alias in confirmed_teacher_aliases
            if alias in reverse_aliases
        ]
    if len(confirmed_teachers) != len(set(confirmed_teachers)):
        raise PiReconciliationError("Duplicate teacher confirmations are not allowed.")
    sacrifice_aliases = {
        str(item).strip() for item in (authorized_sacrifice_aliases or []) if str(item).strip()
    }
    offered = {
        str(item.get("subject_alias")) for item in (public.get("sacrifices") or [])
    }
    if public.get("requires_sacrifice_authorization") and not offered <= sacrifice_aliases:
        raise PiReconciliationError(
            "This package leaves an already scheduled lesson unresolved; "
            "authorize each listed sacrifice before applying."
        )
    raw_changes = investigation.raw_changes_for(public.get("normalized_changes") or [])
    authorized_ids = []
    for item in raw_changes:
        if not item.get("withdraw"):
            continue
        raw_id = str(item["subject_alias"])
        alias = investigation._alias_for("assignment", raw_id) or ""
        if alias and alias in sacrifice_aliases:
            authorized_ids.append(raw_id)
    result = runtime.draft_controller.apply_reconciliation_package(
        state,
        raw_changes,
        confirmed_teachers=confirmed_teachers,
        confirmation_note=note,
        decision_note=note,
        authorized_sacrifice_subject_ids=authorized_ids,
    )
    if not result.success:
        raise PiReconciliationError(result.message)
    # The schedule is applied and persisted. Updating the task record afterwards is
    # bookkeeping: if it fails the operator must still be told the truth, and the
    # stale snapshot hash blocks a second apply of this package.
    record_update_error = ""
    try:
        record.update(investigation.persisted_record())
        record["operation_status"] = "applied"
        record["apply_result"] = {
            "simulation_id": simulation_id,
            "metrics": copy.deepcopy(public.get("metrics") or {}),
            "changes": investigation.applied_change_view(result.records),
            "sacrifices": copy.deepcopy(public.get("sacrifices") or []),
            "split_teacher_days": copy.deepcopy(public.get("split_teacher_days") or []),
            "authorized_sacrifice_aliases": sorted(sacrifice_aliases),
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _persist_private_investigation(context, record)
    except Exception as exc:
        record_update_error = str(exc)
    return result, record_update_error
