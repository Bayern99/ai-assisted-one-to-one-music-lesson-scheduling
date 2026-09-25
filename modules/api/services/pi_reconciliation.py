"""Run-scoped Pi investigation for Step 4 linked schedule reconciliation."""

from __future__ import annotations

import copy
import json
import re
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
    _clock,
    _event_day,
    _event_placement,
    _instrument,
    _room_accepts,
    _teacher,
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


RECONCILIATION_PROMPT_VERSION = "pi-step4-reconciliation-v6"
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
- The operator goal is a preference for what to explore, not a Python rule.
  Hard constraints are only protect_teacher_aliases and
  time_change_exception_teacher_aliases. Never treat free-text goal as a
  lock, a protection, or a time-change exception.
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
- If protect_teacher_aliases or time-change exceptions are set, obey those
  Python constraints. The goal text may name a person to investigate first;
  it does not forbid any legal package on its own.
- Do not repeat an equivalent package, do not retry a rule rejection in new
  wording, and do not search without a reason.
- A follow-up is continued directed discussion, not a chat session and not a
  new authority. Read prior_thread, then obey the new operator goal. Python
  still validates every package. Empty new goal means continue the last thread.
- Submit exactly one brief. A bounded search that found nothing is not proof the
  day is impossible.
- If a preservation package exists, it must be the primary recommendation; a
  sacrifice package may only be the fallback.

Operator communication (the brief is read by a non-technical scheduling
coordinator, not an engineer):
- Write title, focus_question, rationale, trade_offs, limitations,
  pending_decisions details, unknowns, and agent_note in Chinese, in plain
  everyday words.
- Never put internal aliases (issue-N, assignment-N, block-N, teacher-N),
  simulation ids, hashes, or Python failure codes in operator-facing prose.
  Refer to lessons as "某老师 HH:MM 的课" and to rooms by name.
- focus_question is one sentence naming the actual decision: what is being
  chosen and between whom. Example shape: "14:00–16:00 只有 CC407 可以排
  Voice，今天应该优先安排 Marco 的 2 节还是 Zhao 的 2 节？"
- Numbers in prose must match the simulated results exactly. If the primary
  places 5 lessons, never write 4.
- unknowns lists only facts that could change the conclusion, phrased as what
  is not verified. Never state an unverified requirement as absent.
- agent_note is optional: at most one quiet sentence of的倾向 with the reason.
  Do not label options "primary"/"fallback" for the operator; the UI is
  neutral A/B.
- When the operator expresses confusion, the next brief must explain the same
  decision more concretely (names, times, rooms) — never answer confusion
  with a shorter or vaguer summary.
"""
RECONCILIATION_TASK_PROMPT = """Investigate this day's linked Step 4 adjustment work.
Start with inspect_reconciliation to see the whole day, its teacher-day blocks,
the conflict neighbourhood, and which rooms are free right now.
Follow the operator goal as the current question, not as a Python lock.
Hard constraints are only the protect and time-change lists in the task.
candidate_rooms and
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
The brief must include focus_question (one Chinese sentence naming the decision),
and may include unknowns and agent_note. Write all operator prose in Chinese
plain words; internal aliases, ids, and failure codes are rejected and must be
rewritten.
Stop at the bounded search budget. Report budget exhaustion as an interrupted
investigation, never as a proven impossibility.
"""



_PROTECT_INTENT = re.compile(r"不要动|别动|不许动|保护|先不动")
_TIME_CHANGE_INTENT = re.compile(r"改时|改时间")
_NAME_SKIP = {"mr", "ms", "mrs", "dr", "miss"}


def _name_mentioned(text, name):
    folded = text.casefold()
    if name.casefold() in folded:
        return True
    parts = [part for part in re.split(r"[\s.]+", name) if len(part) >= 3 and part.casefold() not in _NAME_SKIP]
    return any(part.casefold() in folded for part in parts)


def extract_operator_constraints(text, teachers):
    """Turn protect / time-change phrasing into Python constraint lists.

    Clause-scoped: "不要动 Zhao，WANG 可以改时" protects Zhao only.
    Unmatched text stays a preference in goal; it is not a lock.
    """
    text = str(text or "").strip()
    names = sorted({str(item).strip() for item in teachers if str(item).strip()}, key=len, reverse=True)
    protect, allow = [], []
    if not text or not names:
        return protect, allow
    clauses = [part.strip() for part in re.split(r"[，。；;\n]+", text) if part.strip()] or [text]
    for clause in clauses:
        folded = clause.casefold()
        full = [name for name in names if name.casefold() in folded]
        mentioned = full or [name for name in names if _name_mentioned(clause, name)]
        mentioned = [
            name for name in mentioned
            if not any(name != other and name.casefold() in other.casefold() for other in mentioned)
        ]
        if not mentioned:
            continue
        if _PROTECT_INTENT.search(clause):
            for name in mentioned:
                if name not in protect:
                    protect.append(name)
        if _TIME_CHANGE_INTENT.search(clause):
            for name in mentioned:
                if name not in allow:
                    allow.append(name)
    return protect, allow


def _known_teachers(runtime):
    names = []
    session = getattr(runtime, "edit_session", None) or {}
    for event in session.get("assignments") or []:
        teacher = _teacher(event) if isinstance(event, dict) else ""
        if teacher and teacher not in names:
            names.append(teacher)
    for issue in session.get("unassigned_lessons") or []:
        if not isinstance(issue, dict):
            continue
        teacher = str(unresolved_assignment_primitives.build_context(issue).get("instructor") or "").strip()
        if teacher and teacher not in names:
            names.append(teacher)
    return names


def _union_names(*groups):
    seen = []
    for group in groups:
        for item in group or []:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.append(name)
    return seen


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
    progress: Callable[..., None] | None = None
    started: float = 0.0
    first_valid_at: float | None = None
    rejected_simulations: int = 0


class PiReconciliationCapabilityStore:
    """Short-lived server-owned state for one reconciliation investigation."""

    def __init__(self) -> None:
        self._tokens = TimedTokenStore(
            error_factory=lambda: PiReconciliationError(
                "The reconciliation capability is invalid or expired."
            ),
            min_ttl_seconds=60,
        )

    def create(
        self,
        investigation: ReconciliationInvestigation,
        *,
        ttl_seconds: int = 600,
        progress: Callable[..., None] | None = None,
        started: float = 0.0,
    ) -> str:
        return self._tokens.create(
            _Capability(
                run_id=investigation.run_id,
                investigation=investigation,
                progress=progress,
                started=started,
            ),
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
            self._emit(item, "inspection_started", "Analyzing the day's schedule")
            try:
                result = item.investigation.inspect_reconciliation(focus_aliases)
            except PackageRejected as exc:
                self._emit(item, "inspection_rejected", "Inspection rejected by Python", {"reason": str(exc)})
                raise
            self._record(item, "inspect_reconciliation", {
                "subjects": len(result.get("subjects") or []),
                "edges": len(result.get("edges") or []),
            })
            self._emit(item, "inspection_completed", "Occupancy inspected", {
                "subjects": len(result.get("subjects") or []),
                "edges": len(result.get("edges") or []),
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
            self._emit(item, "investigation_closed", "Investigation closed at a bound", {
                "bound": bound,
                "termination": result.get("termination"),
            })
            return result
        return self._tokens.mutate(token, _run)

    def _emit(self, item: _Capability, type: str, label: str, detail: dict[str, Any] | None = None) -> None:
        # Python is the authoritative progress source; a broken observer must
        # never break scheduling work.
        if item.progress is None:
            return
        try:
            item.progress(type, label, detail or {})
        except Exception:
            pass

    def stats(self, token: str) -> dict[str, Any]:
        item = self._tokens.get(token)
        return {
            "rejected_simulations": item.rejected_simulations,
            "first_valid_at": item.first_valid_at,
        }

    def reject(self, token: str, *, type: str, label: str, reason: str) -> None:
        """Record a rejection decided before the store method could run."""
        def _run(item: _Capability):
            item.rejected_simulations += 1
            self._emit(item, type, label, {"reason": reason})
        return self._tokens.mutate(token, _run)
    def simulate(self, token: str, changes) -> dict[str, Any]:
        def _run(item: _Capability):
            self._emit(item, "simulation_started", "Simulating a candidate package", {
                "change_count": len(changes or []),
            })
            try:
                result = _model_safe_simulation(item.investigation.simulate_package(changes))
            except PackageRejected as exc:
                item.rejected_simulations += 1
                self._emit(item, "simulation_rejected", "Package rejected by Python validation", {"reason": str(exc)})
                raise
            self._record(item, "simulate_reconciliation_package", {
                "simulation_id": result.get("simulation_id"),
                "status": result.get("status"),
                "feasible": bool(result.get("feasible")),
                "duplicate": bool(result.get("duplicate")),
                "change_count": len(result.get("normalized_changes") or []),
            })
            if result.get("rejection"):
                item.rejected_simulations += 1
                self._emit(item, "simulation_rejected", "Package rejected by Python validation", {
                    "reason": str(result.get("rejection") or ""),
                    "failure_codes": list(result.get("failure_codes") or []),
                })
                return result
            if result.get("status") in {"feasible", "conditional"} and item.first_valid_at is None:
                item.first_valid_at = monotonic()
                self._emit(item, "first_valid_candidate", "Found a valid candidate", {
                    "simulation_id": result.get("simulation_id"),
                    "elapsed_ms": round((item.first_valid_at - item.started) * 1000) if item.started else 0,
                })
            self._emit(item, "simulation_completed", "Candidate package validated", {
                "simulation_id": result.get("simulation_id"),
                "status": result.get("status"),
                "feasible": bool(result.get("feasible")),
                "duplicate": bool(result.get("duplicate")),
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
            self._emit(item, "brief_submitted", "Brief submitted", {
                "brief_id": result.get("brief_id"),
                "termination": result.get("termination"),
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
    extracted_protect, extracted_allow = extract_operator_constraints(goal, _known_teachers(runtime))
    protect_instructors = _union_names(protect_instructors, extracted_protect)
    allow_time_change_instructors = _union_names(allow_time_change_instructors, extracted_allow)
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


def _rpc_event_to_progress(event: dict[str, Any]):
    """Map a raw Pi RPC stream event to an operation progress tuple, or None.

    These events are model-adjacent liveness evidence only; the authoritative
    business progress is emitted by the capability store in Python.
    """
    event_type = str(event.get("type") or "")
    if event_type == "agent_start":
        return ("agent_alive", "Pi agent started", {})
    if event_type == "turn_start":
        return ("turn_activity", "Model working", {})
    if event_type == "tool_execution_start":
        return ("model_tool_request", "Model requested a tool", {
            "tool": str(event.get("toolName") or ""),
        })
    if event_type == "tool_execution_end":
        return ("model_tool_end", "Tool execution finished", {
            "tool": str(event.get("toolName") or ""),
            "is_error": bool(event.get("isError")),
        })
    if event_type == "auto_retry_start":
        return ("provider_retry", "Provider retrying", {
            "attempt": int(event.get("attempt") or 0),
            "max_attempts": int(event.get("maxAttempts") or 0),
            "delay_ms": int(event.get("delayMs") or 0),
        })
    if event_type == "auto_retry_end":
        return ("provider_retry_end", "Provider retry finished", {
            "attempt": int(event.get("attempt") or 0),
            "success": bool(event.get("success")),
        })
    if event_type == "agent_settled":
        return ("agent_settled", "Pi finished", {})
    if event_type == "process_spawn":
        return ("process_spawned", "Pi process started", {
            "spawn_ms": int(event.get("spawn_ms") or 0),
        })
    if event_type == "first_agent_activity":
        return ("first_agent_activity", "Pi first response", {
            "elapsed_ms": int(event.get("elapsed_ms") or 0),
        })
    return None


def _rpc_metadata(rpc_result, rpc_failure, op_started):
    if rpc_result is not None:
        return {
            "pi_version": rpc_result.pi_version,
            "provider": rpc_result.provider,
            "model": rpc_result.model,
            "latency_ms": rpc_result.latency_ms,
            "usage": dict(rpc_result.usage or {}),
        }
    latency = getattr(rpc_failure, "latency_ms", None) if rpc_failure is not None else None
    if latency is None:
        latency = round((monotonic() - op_started) * 1000) if op_started else 0
    return {
        "pi_version": "",
        "provider": str(getattr(rpc_failure, "provider", "") or "") if rpc_failure else "",
        "model": str(getattr(rpc_failure, "model", "") or "") if rpc_failure else "",
        "latency_ms": int(latency),
        "usage": dict(getattr(rpc_failure, "usage", {}) or {}) if rpc_failure else {},
    }


def _failure_status(rpc_failure):
    if rpc_failure is None:
        return "completed", None
    reason = str(getattr(rpc_failure, "reason", "timeout") or "timeout")
    return {
        "timeout": ("timeout", "runtime_timeout"),
        "exited": ("crash", "crash"),
        "interrupted": ("interrupted", "interrupted"),
    }.get(reason, ("failed", "error"))


def _progress_metrics(record, stats, op_started):
    simulations = record.get("simulations") if isinstance(record.get("simulations"), dict) else {}
    valid = 0
    for item in simulations.values():
        public = item.get("public") if isinstance(item, dict) else None
        if isinstance(public, dict) and public.get("status") in {"feasible", "conditional"}:
            valid += 1
    task = record.get("task") if isinstance(record.get("task"), dict) else {}
    first_valid_at = (stats or {}).get("first_valid_at")
    return {
        "tool_calls": int(record.get("tool_calls") or 0),
        "tool_call_budget": int(task.get("tool_call_budget") or 0),
        "simulation_count": len(simulations),
        "valid_candidates": valid,
        "rejected_candidates": int((stats or {}).get("rejected_simulations") or 0),
        "first_valid_candidate_ms": (
            round((first_valid_at - op_started) * 1000)
            if first_valid_at and op_started
            else None
        ),
    }


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
    op_started = monotonic()

    def progress(type: str, label: str, detail: dict[str, Any] | None = None) -> None:
        registry.emit(operation_id, type=type, source="python", label=label, detail=detail)

    token = capability_store.create(investigation, progress=progress, started=op_started)
    failure = ""
    record = None
    rpc_result = None
    rpc_failure: PiRpcTimeout | None = None
    try:
        registry.start(operation_id, phase="investigating")
        progress("investigation_started", "Investigation started", {"day": investigation.day})

        def on_rpc_event(event: dict[str, Any]) -> None:
            mapped = _rpc_event_to_progress(event)
            if mapped is None:
                return
            event_type, label, detail = mapped
            registry.emit(operation_id, type=event_type, source="pi_rpc", label=label, detail=detail)

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
                on_event=on_rpc_event,
            )
        except PiRpcTimeout as exc:
            rpc_failure = exc
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
        operation_status, rpc_termination = _failure_status(rpc_failure)
        if rpc_failure is not None:
            progress(
                "investigation_interrupted",
                "Investigation stopped at a runtime bound",
                {"reason": rpc_termination or "error"},
            )
        meta = _rpc_metadata(rpc_result, rpc_failure, op_started)
        record.update({
            "agent_run_id": operation_id,
            "operation_status": operation_status,
            **meta,
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
            "termination": rpc_termination or str(brief.get("termination") or ""),
            "latency_ms": meta["latency_ms"],
            "provider": meta["provider"],
            "model": meta["model"],
            "usage": meta["usage"],
            **_progress_metrics(record, capability_store.stats(token), op_started),
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
                **_rpc_metadata(None, None, op_started),
            })
            registry.start(operation_id, phase="saving_reconciliation")
            with context.mutation_lock:
                _persist_private_investigation(context, record)
                _record_attempt(context, investigation.run_id, record, operation_id=operation_id)
                workspace_version = compute_workspace_version(context.loader.base_dir, context=context)
            brief = record.get("brief") or {}
            registry.complete(operation_id, result={
                "run_id": investigation.run_id,
                "investigation_id": investigation.investigation_id,
                "workspace_version": workspace_version,
                "termination": str(brief.get("termination") or ""),
                "latency_ms": record.get("latency_ms") or 0,
                "provider": record.get("provider") or "",
                "model": record.get("model") or "",
                "usage": record.get("usage") or {},
                **_progress_metrics(record, capability_store.stats(token), op_started),
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
        registry.fail(operation_id, error=failure, result={
            "termination": "error",
            **_progress_metrics(record, None, op_started),
        })
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
        registry.fail(operation_id, error=failure, result={
            "termination": "crash",
            **_progress_metrics(record or {}, None, op_started),
        })
    finally:
        capability_store.revoke(token)


def _outcome_key(public):
    rows = []
    for change in public.get("changes") or []:
        if not isinstance(change, dict):
            continue
        to = change.get("to") or {}
        rows.append((
            str(change.get("subject_alias") or ""),
            str(change.get("action") or ""),
            str(to.get("room") or ""),
            str(to.get("day") or ""),
            _clock(to.get("start")),
            _clock(to.get("end")),
        ))
    return sorted(rows)


def _common_normalized(left, right):
    """Shared changes of two packages: same subject, same target, same action."""

    def freeze(items):
        table = {}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            target = item.get("target") if isinstance(item.get("target"), dict) else None
            table[str(item.get("subject_alias") or "")] = {
                "subject_alias": item.get("subject_alias"),
                "target": copy.deepcopy(target),
                "withdraw": bool(item.get("withdraw")),
            }
        return table

    left_table = freeze(left)
    right_table = freeze(right)
    common = []
    for subject_id, change in left_table.items():
        other = right_table.get(subject_id)
        if other is None:
            continue
        if other["withdraw"] != change["withdraw"]:
            continue
        if not change["withdraw"] and other["target"] != change["target"]:
            continue
        common.append(copy.deepcopy(change))
    return common



def _change_identity(row):
    to = row.get("to") or {}
    return (
        str(row.get("subject_alias") or ""),
        str(row.get("action") or ""),
        str(to.get("room") or ""),
        str(to.get("day") or ""),
        _clock(to.get("start")),
        _clock(to.get("end")),
        str(row.get("group_alias") or ""),
    )


def _option_diffs(changes, common_changes):
    common_keys = {_change_identity(row) for row in common_changes or []}
    if not common_keys:
        return copy.deepcopy(changes or [])
    return [copy.deepcopy(row) for row in changes or [] if _change_identity(row) not in common_keys]


def _remaining_phrase(public, display):
    items = (public.get("state_after") or {}).get("unresolved") or []
    if not items:
        return "无"
    counts = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        alias = str(item.get("teacher_alias") or "")
        name = str((display or {}).get(alias) or alias or "未排")
        counts[name] = counts.get(name, 0) + 1
    return "、".join(f"{name} {count} 节" for name, count in sorted(counts.items()))


def _comparison_rows(options, teacher_days):
    if len(options) < 2:
        return []
    rows = []
    remaining = [str(item.get("_remaining") or "无") for item in options]
    if len(set(remaining)) > 1:
        rows.append({"label": "仍未安排", "values": remaining})
    for day in teacher_days or []:
        teacher = str(day.get("teacher") or "")
        for row in day.get("rows") or []:
            variants = row.get("variants") or {}
            shown = []
            for option in options:
                room = variants.get(option["option_id"]) if option["option_id"] in variants else row.get("room")
                shown.append(str(room) if room else "未排")
            if len(set(shown)) > 1:
                rows.append({
                    "label": f"{teacher} {row.get('start') or ''}–{row.get('end') or ''}".strip(),
                    "values": shown,
                })
    def metric_row(label, key):
        values = []
        for option in options:
            count = int((option.get("metrics") or {}).get(key) or 0)
            values.append("无" if count == 0 else f"{count} 节")
        if len(set(values)) > 1:
            rows.append({"label": label, "values": values})
    metric_row("已有课移动", "moved_assignments")
    metric_row("时间变化", "time_changed_assignments")
    metric_row("牺牲", "sacrificed_assignments")
    conflicts = []
    for option in options:
        count = int((option.get("metrics") or {}).get("hard_conflict_count") or 0)
        conflicts.append("无" if count == 0 else f"{count} 项")
    if len(set(conflicts)) > 1:
        rows.append({"label": "硬冲突", "values": conflicts})
    return rows


def _previous_same_day_record(runtime, record):
    plans = (getattr(runtime, "edit_session", None) or {}).get("reconciliation_plans") or {}
    current_id = str(record.get("investigation_id") or "")
    day = record.get("day")
    candidates = []
    if not isinstance(plans, dict):
        return None
    for item in plans.values():
        if not isinstance(item, dict) or item.get("day") != day:
            continue
        if str(item.get("investigation_id") or "") == current_id:
            continue
        if not isinstance(item.get("brief"), dict):
            continue
        candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return candidates[0]


def _revision_view(record, runtime, options, common):
    protect = [str(item).strip() for item in (record.get("protect_teachers") or []) if str(item).strip()]
    allow = [str(item).strip() for item in (record.get("allow_time_change_teachers") or []) if str(item).strip()]
    instruction = str(record.get("goal") or "").strip()
    effects = []
    if protect:
        effects.append({"code": "protect_applied", "text": f"已转为硬约束：保护 {'、'.join(protect)} 当天已有安排。"})
    if allow:
        effects.append({"code": "time_change_applied", "text": f"已转为硬约束：允许 {'、'.join(allow)} 改时间。"})
    previous = _previous_same_day_record(runtime, record)
    if previous:
        prev_brief = previous.get("brief") or {}
        prev_sims = previous.get("simulations") if isinstance(previous.get("simulations"), dict) else {}
        prev_count = 0
        for key in (prev_brief.get("primary_simulation_id"), prev_brief.get("fallback_simulation_id")):
            public = (prev_sims.get(str(key or "")) or {}).get("public") or {}
            if public.get("status") in {"feasible", "conditional"}:
                prev_count += 1
        new_count = len(options)
        if prev_count > new_count:
            effects.append({"code": "option_eliminated", "text": f"新约束下可行方案从 {prev_count} 个变为 {new_count} 个。"})
        prev_primary = (prev_sims.get(str(prev_brief.get("primary_simulation_id") or "")) or {}).get("public") or {}
        prev_fallback = (prev_sims.get(str(prev_brief.get("fallback_simulation_id") or "")) or {}).get("public") or {}
        prev_common = []
        if prev_count >= 2:
            prev_common = _common_normalized(
                prev_primary.get("normalized_changes") or [],
                prev_fallback.get("normalized_changes") or [],
            )
        new_common = (common or {}).get("changes") or []
        if prev_common and new_common:
            if len(prev_common) == len(new_common):
                effects.append({"code": "common_kept", "text": "共同部分仍然可行。"})
            else:
                effects.append({"code": "common_changed", "text": "共同部分有变化，需要重新确认。"})
        elif prev_common and not new_common:
            effects.append({"code": "common_lost", "text": "此前的共同部分在新约束下不再成立。"})
        elif instruction and not any(item["code"] == "option_eliminated" for item in effects):
            effects.append({"code": "continued", "text": "在同一条决定上继续调查；可行方案集合没有因新约束改变。"})
    if not effects:
        return None
    return {
        "instruction": instruction,
        "protect_teachers": protect,
        "allow_time_change_teachers": allow,
        "effects": effects,
    }


def build_decision_brief(record, runtime):
    """Project a persisted investigation into the operator Decision Brief view.

    Facts (options, common part, teacher days, room views, counts) are derived
    from the Python snapshot and stored simulations only. Model prose is
    confined to focus.question, unknowns, and agent_note, which the brief
    validator keeps in plain operator language. Returns None when the record
    cannot be rehydrated — the Decision Brief must never block advice.
    """
    try:
        investigation = ReconciliationInvestigation.from_persisted(record, runtime)
    except Exception:
        return None
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else None
    if not brief:
        return None
    snapshot = investigation._snapshot or {}
    raw_simulations = record.get("simulations")
    simulations = {}
    if isinstance(raw_simulations, dict):
        simulations = raw_simulations
    elif isinstance(raw_simulations, list):
        for item in raw_simulations:
            if isinstance(item, dict):
                sim_id = item.get("simulation_id")
                if sim_id:
                    if "public" in item and isinstance(item["public"], dict):
                        simulations[str(sim_id)] = item
                    else:
                        simulations[str(sim_id)] = {"public": item}
    if not simulations and getattr(investigation, "_simulations", None):
        simulations = investigation._simulations

    def public_of(simulation_id):
        item = simulations.get(str(simulation_id))
        return item.get("public") if isinstance(item, dict) and isinstance(item.get("public"), dict) else None

    options = []
    for option_id, source, simulation_id in (
        ("a", "primary", brief.get("primary_simulation_id")),
        ("b", "fallback", brief.get("fallback_simulation_id")),
    ):
        if not simulation_id:
            continue
        public = public_of(simulation_id)
        if not public or public.get("status") not in {"feasible", "conditional"}:
            continue
        options.append({
            "option_id": option_id,
            "source": source,
            "simulation_id": str(simulation_id),
            "changes": copy.deepcopy(public.get("changes") or []),
            "metrics": copy.deepcopy(public.get("metrics") or {}),
            "required_teacher_aliases": [
                str(item.get("teacher_alias") or "")
                for item in (public.get("required_teacher_confirmations") or [])
                if isinstance(item, dict) and item.get("teacher_alias")
            ],
            "sacrifice_aliases": [
                str(item.get("subject_alias") or "")
                for item in (public.get("sacrifices") or [])
                if isinstance(item, dict) and item.get("subject_alias")
            ],
            "_outcome": _outcome_key(public),
            "_normalized": copy.deepcopy(public.get("normalized_changes") or []),
            "_remaining": _remaining_phrase(public, investigation._teacher_display or {}),
        })
    if len(options) == 2 and options[0]["_outcome"] == options[1]["_outcome"]:
        # Identical outcomes are one choice, not two.
        options = options[:1]

    if len(options) == 1:
        # If we have only 1 option (e.g. fallback was omitted or duplicate),
        # look for any other distinct feasible simulation to provide Option B
        primary_sim_id = options[0]["simulation_id"]
        candidates = []
        for other_id, other_sim in simulations.items():
            if str(other_id) == primary_sim_id:
                continue
            other_pub = other_sim.get("public") if isinstance(other_sim, dict) else None
            if not other_pub or other_pub.get("status") not in {"feasible", "conditional"}:
                continue
            outcome = _outcome_key(other_pub)
            if outcome == options[0]["_outcome"]:
                continue
            candidates.append((str(other_id), other_pub, outcome))
        if candidates:
            # Pick best alternative by resolved_delta descending, then room_switches ascending
            candidates.sort(
                key=lambda x: (
                    -int((x[1].get("metrics") or {}).get("resolved_delta") or 0),
                    int((x[1].get("metrics") or {}).get("room_switches") or 0),
                )
            )
            best_fallback_id, best_pub, best_outcome = candidates[0]
            options.append({
                "option_id": "b",
                "source": "fallback",
                "simulation_id": best_fallback_id,
                "changes": copy.deepcopy(best_pub.get("changes") or []),
                "metrics": copy.deepcopy(best_pub.get("metrics") or {}),
                "required_teacher_aliases": [
                    str(item.get("teacher_alias") or "")
                    for item in (best_pub.get("required_teacher_confirmations") or [])
                    if isinstance(item, dict) and item.get("teacher_alias")
                ],
                "sacrifice_aliases": [
                    str(item.get("subject_alias") or "")
                    for item in (best_pub.get("sacrifices") or [])
                    if isinstance(item, dict) and item.get("subject_alias")
                ],
                "_outcome": best_outcome,
                "_normalized": copy.deepcopy(best_pub.get("normalized_changes") or []),
                "_remaining": _remaining_phrase(best_pub, investigation._teacher_display or {}),
            })

    common = None
    common_changes = []
    if len(options) == 2:
        common_normalized = _common_normalized(options[0]["_normalized"], options[1]["_normalized"])
        if common_normalized:
            common_aliases = {str(item.get("subject_alias") or "") for item in common_normalized}
            # changes rows are keyed by raw subject id with the alias in
            # group_alias; normalized_changes are alias-addressed. Match both.
            common_ids = set(common_aliases)
            for alias in common_aliases:
                mapping = investigation._alias_to_subject.get(alias)
                if mapping:
                    common_ids.add(str(mapping[1]))
            common_changes = [
                row for row in options[0]["changes"]
                if str(row.get("subject_alias") or "") in common_ids
                or str(row.get("group_alias") or "") in common_aliases
            ]
            common = {
                "changes": copy.deepcopy(common_changes),
                "required_teacher_aliases": sorted(
                    set(options[0]["required_teacher_aliases"]) & set(options[1]["required_teacher_aliases"])
                ),
                "sacrifice_aliases": sorted(
                    set(options[0]["sacrifice_aliases"]) & set(options[1]["sacrifice_aliases"])
                ),
            }
    for option in options:
        option["diffs"] = _option_diffs(option.get("changes") or [], common_changes)

    teacher_days = _decision_teacher_days(investigation, options)
    room_views = _decision_room_views(investigation, options)
    comparison = _comparison_rows(options, teacher_days)
    revision = _revision_view(record, runtime, options, common)

    unknowns = [
        {"subject": str(item.get("subject") or ""), "note": str(item.get("note") or "")}
        for item in (brief.get("unknowns") or [])
        if isinstance(item, dict)
    ]
    if brief.get("termination") == "no_feasible_package_found" or not options:
        status = "no_package"
    elif len(options) >= 2:
        status = "choice"
    elif unknowns:
        status = "missing_info"
    else:
        status = "ready"
    question = str(brief.get("focus_question") or "").strip()
    if status == "choice" and (not question or "中断" in question or "Search cap" in question or "上限" in question):
        question = "需要在两个可行方案之间做选择。"
    elif not question:
        question = {
            "ready": "这个方案已经通过验证，可以直接执行。",
            "choice": "需要在两个可行方案之间做选择。",
            "missing_info": "还缺少可能改变结论的信息，暂不宜直接执行。",
            "no_package": "当前没有可行的完整方案。",
        }[status]
    for option in options:
        option.pop("_outcome", None)
        option.pop("_normalized", None)
        option.pop("_remaining", None)
    return {
        "focus": {"question": question, "status": status},
        "options": options,
        "common": common,
        "comparison": comparison,
        "revision": revision,
        "teacher_days": teacher_days,
        "room_views": room_views,
        "unknowns": unknowns,
        "agent_note": str(brief.get("agent_note") or "").strip(),
    }


def _decision_teacher_days(investigation, options):
    """Compact per-teacher day rows for teachers touched by the options.

    Includes unchanged lessons so the operator sees each affected teacher's
    whole day, not only the moved rows.
    """
    snapshot = investigation._snapshot or {}
    day = investigation.day
    display = investigation._teacher_display or {}
    change_maps = {}
    for option in options:
        change_maps[option["option_id"]] = {
            str(row.get("subject_alias") or ""): row
            for row in option.get("changes") or []
            if isinstance(row, dict)
        }
    involved = []
    for option in options:
        for row in option.get("changes") or []:
            teacher = str(row.get("teacher") or "").strip()
            if teacher and teacher not in involved:
                involved.append(teacher)
    if not involved:
        return []

    def variant_rooms(subject_id, base_room):
        variants = {}
        for option in options:
            row = change_maps[option["option_id"]].get(subject_id)
            if row is None:
                variants[option["option_id"]] = base_room or None
            elif row.get("action") == "withdraw":
                variants[option["option_id"]] = None
            else:
                to = row.get("to") or {}
                variants[option["option_id"]] = str(to.get("room") or "") or None
        return variants

    rows_by_teacher = {}
    for event in snapshot.get("assignments") or []:
        if not isinstance(event, dict) or _event_day(event) != day:
            continue
        teacher = _teacher(event)
        if teacher not in involved:
            continue
        placement = _event_placement(event)
        subject_id = str(event.get("id") or "")
        variants = variant_rooms(subject_id, str(placement.get("room") or ""))
        states = []
        for option in options:
            row = change_maps[option["option_id"]].get(subject_id)
            states.append("withdrawn" if row and row.get("action") == "withdraw" else "moved" if row else "unchanged")
        state = states[0] if len(set(states)) == 1 else "moved"
        rows_by_teacher.setdefault(teacher, []).append({
            "start": _clock(placement.get("start")),
            "end": _clock(placement.get("end"), prefer_end=True),
            "room": str(placement.get("room") or ""),
            "label": investigation._event_label(event),
            "state": state,
            "variants": variants if len(options) == 2 else {},
        })
    for issue in snapshot.get("unassigned_lessons") or []:
        if not isinstance(issue, dict):
            continue
        context = unresolved_assignment_primitives.build_context(issue)
        teacher = str(context.get("instructor") or "").strip()
        if teacher not in involved or context.get("original_day") != day:
            continue
        subject_id = unresolved_assignment_primitives.issue_id(issue)
        variants = variant_rooms(subject_id, "")
        states = []
        for option in options:
            row = change_maps[option["option_id"]].get(subject_id)
            states.append("placed" if row and row.get("action") == "place" else "unplaced")
        state = states[0] if len(set(states)) == 1 else "unplaced"
        rows_by_teacher.setdefault(teacher, []).append({
            "start": _clock(context.get("original_start")),
            "end": _clock(context.get("original_end"), prefer_end=True),
            "room": "",
            "label": investigation._issue_label(issue),
            "state": state,
            "variants": variants if len(options) == 2 else {},
        })
    teacher_days = []
    for teacher in involved:
        rows = sorted(
            rows_by_teacher.get(teacher) or [],
            key=lambda row: (row["start"], row["end"]),
        )
        teacher_days.append({"teacher": teacher, "rows": rows})
    return teacher_days


def _decision_room_views(investigation, options):
    """Room capability and same-day occupancy for rooms the options touch."""
    snapshot = investigation._snapshot or {}
    rules = snapshot.get("rules") or {}
    day = investigation.day
    rooms = []
    instruments_by_room = {}
    for option in options:
        for row in option.get("changes") or []:
            if not isinstance(row, dict):
                continue
            to = row.get("to") or {}
            room = str(to.get("room") or "").strip() if row.get("action") != "withdraw" else ""
            if not room:
                room = str((row.get("from") or {}).get("room") or "").strip()
            if not room or room in rooms:
                if room:
                    instruments_by_room.setdefault(room, set())
                continue
            rooms.append(room)
            instruments_by_room.setdefault(room, set())
    for option in options:
        for row in option.get("changes") or []:
            if not isinstance(row, dict):
                continue
            subject_id = str(row.get("subject_alias") or "")
            instrument = _lesson_instrument(snapshot, subject_id)
            to = row.get("to") or {}
            room = str(to.get("room") or "").strip() if row.get("action") != "withdraw" else str((row.get("from") or {}).get("room") or "").strip()
            if room and instrument:
                instruments_by_room.setdefault(room, set()).add(instrument)
    views = []
    for room in rooms:
        accepts = sorted({
            instrument
            for instrument in instruments_by_room.get(room) or set()
            if _room_accepts(rules, room, instrument)
        })
        busy = []
        for event in snapshot.get("assignments") or []:
            if not isinstance(event, dict) or _event_day(event) != day:
                continue
            placement = _event_placement(event)
            if str(placement.get("room") or "") != room:
                continue
            busy.append({
                "start": _clock(placement.get("start")),
                "end": _clock(placement.get("end"), prefer_end=True),
                "label": _teacher(event),
            })
        views.append({
            "room": room,
            "accepts": accepts,
            "busy": sorted(busy, key=lambda item: (item["start"], item["end"])),
        })
    return views


def _lesson_instrument(snapshot, subject_id):
    for event in snapshot.get("assignments") or []:
        if isinstance(event, dict) and str(event.get("id") or "") == subject_id:
            return _instrument(event)
    for issue in snapshot.get("unassigned_lessons") or []:
        if not isinstance(issue, dict):
            continue
        if unresolved_assignment_primitives.issue_id(issue) == subject_id:
            context = unresolved_assignment_primitives.build_context(issue)
            return context.get("instrument")
    return None


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
            public["decision_brief"] = build_decision_brief(record, runtime)
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
    scope: str = "option",
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
    scope = str(scope or "option").strip()
    apply_simulation_id = str(simulation_id or "")
    raw_changes = []
    if scope == "common":
        # Apply only the shared part of the two options. Python re-validates the
        # shared changes in a fresh simulation at apply time; the operator never
        # needs the model to have pre-simulated the common package.
        primary_public = (simulations.get(str(brief.get("primary_simulation_id") or "")) or {}).get("public") or {}
        fallback_public = (simulations.get(str(brief.get("fallback_simulation_id") or "")) or {}).get("public") or {}
        common = _common_normalized(
            primary_public.get("normalized_changes") or [],
            fallback_public.get("normalized_changes") or [],
        )
        if not common:
            raise PiReconciliationError("这两个方案没有可单独执行的共同部分。")
        fresh = investigation.simulate_package(common, human_revision=True)
        if not fresh.get("feasible"):
            raise PiReconciliationError("共同部分在重新验证时没有通过；请改用完整方案。")
        public = fresh
        apply_simulation_id = "common"
        raw_changes = investigation.raw_changes_for(common)
    else:
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
        raw_changes = investigation.raw_changes_for(public.get("normalized_changes") or [])
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
    if scope == "common":
        # The common package is re-validated at apply time, so its confirmation
        # ids were never shown to the operator; confirm by teacher alias instead.
        required_alias_set = {alias for alias in required_ids.values() if alias}
        submitted_aliases = {
            str(alias).strip() for alias in (confirmed_teacher_aliases or []) if str(alias).strip()
        }
        if required_alias_set - submitted_aliases:
            raise PiReconciliationError(
                "Every affected teacher must confirm the shared changes before apply."
            )
        confirmed_teachers = [
            reverse_aliases[alias]
            for alias in sorted(required_alias_set or submitted_aliases)
            if alias in reverse_aliases
        ]
    elif required_ids:
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
            "simulation_id": apply_simulation_id,
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


def reconciliation_operation_id(context, investigation_id: str) -> str | None:
    """The operation that produced an investigation record, for error correlation."""
    try:
        _state, _runtime, record = _rehydrate(context, investigation_id)
    except PiReconciliationError:
        return None
    value = str(record.get("agent_run_id") or "")
    return value or None
