"""Run-scoped, privacy-minimised Step 4 reconciliation investigation.

The module is intentionally concrete: one immutable snapshot, one alias
registry, three operations, and an in-memory simulation registry.  API and Pi
adapters call this module; they do not reimplement scheduler validation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.resolution_package import (
    PackageRejected,
    confirmation_key,
    normalize_package_changes,
    package_hash,
)
from modules.scheduler.logic.resolution_availability import ResolutionAvailability
from modules.scheduler.logic.rules_schema import TRACE_KEY
from modules.scheduler.logic.teacher_day_package import (
    build_teacher_day_package,
    validate_teacher_day_placement,
)
from modules.scheduler.logic.schedule_change_policy import (
    instructor_time_change_status,
)
from modules.scheduler.logic.step4_service import Step4DraftController
from modules.scheduler.logic.validation_authority import (
    VALIDATION_AUTHORITY_KEY,
    build_occupancy_assignments,
)
from modules.shared.time_parser import TimeParser


INVESTIGATION_VERSION = "reconciliation-investigator-v1"
MAX_TOOL_CALLS = 20
MAX_PACKAGE_CHANGES = 64
PENDING_DECISION_KINDS = (
    "business_tradeoff",
    "missing_fact",
    "exception_authorization",
    "other",
)

# Operator-facing prose (brief title/rationale/trade-offs/decisions) is written
# for a non-technical scheduling coordinator. Internal aliases, simulation ids,
# and Python failure codes leak machine context into human decisions, so the
# brief validator rejects them and asks Pi to rewrite in plain words.
_OPERATOR_PROSE_DENIED = re.compile(
    r"\b(?:issue|assignment|block|teacher)-\d+\b"
    r"|\b[0-9a-f]{8,}\b"
    r"|\b(?:hard_conflict|locked_room_window|room_type_mismatch"
    r"|time_change_not_authorized|teacher_time_change_not_allowed"
    r"|cross_day_out_of_scope|protected_subject|unknown_subject_alias"
    r"|missing_subject_alias|empty_package|duplicate_subject|package_rejected"
    r"|authorization_required|teacher_confirmation_required"
    r"|subject_not_in_snapshot|swap_required|same_teacher_overlap"
    r"|requested_slot_occupied|compatible_room_occupant"
    r"|candidate_rooms|available_rooms|incompatible_empty_rooms"
    r"|recommendation_ready|no_feasible_package_found|budget_exhausted"
    r"|dominates|dominated|dominance|pareto|primary|fallback|simulation"
    r"|snapshot|sandbox|alias|package|metrics|unresolved|subject)\b",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _operator_prose_violation(field: str, text: str) -> str | None:
    """Return a rewrite instruction when operator prose leaks internal context."""
    hit = _OPERATOR_PROSE_DENIED.search(text or "")
    if hit is None:
        return None
    return (
        f"{field} contains internal identifier '{hit.group(0)}'. "
        "Rewrite it for the operator in plain words: teacher names, times, "
        "and rooms only; never internal aliases, ids, or failure codes."
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clock(value, *, prefer_end=False):
    return TimeParser.normalize_clock(value, prefer_end=prefer_end)


def _event_day(event):
    return TimeParser.event_primary_js_day(event, default=None)


def _event_placement(event):
    start, end = TimeParser.event_clock_pair(event, default=(None, None))
    return {
        "room": str(event.get("resourceId") or event.get("room_id") or "").strip(),
        "day": _event_day(event),
        "start": start,
        "end": end,
    }


def _interval(placement):
    start = TimeParser.to_minutes(placement.get("start"), default=None)
    end = TimeParser.to_minutes(placement.get("end"), default=None)
    if start is None or end is None or end <= start:
        return None
    return start, end


def _overlap(left, right):
    if left.get("day") != right.get("day"):
        return False
    first = _interval(left)
    second = _interval(right)
    return bool(first and second and max(first[0], second[0]) < min(first[1], second[1]))


def _teacher(event_or_issue):
    props = event_or_issue.get("extendedProps") if isinstance(event_or_issue.get("extendedProps"), dict) else {}
    raw = event_or_issue.get("raw_row") if isinstance(event_or_issue.get("raw_row"), dict) else {}
    return str(
        props.get("Instructor")
        or event_or_issue.get("instructor")
        or event_or_issue.get("inst")
        or raw.get("Instructor")
        or ""
    ).strip()


def _instrument(event_or_issue):
    props = event_or_issue.get("extendedProps") if isinstance(event_or_issue.get("extendedProps"), dict) else {}
    return str(
        props.get("Instrument")
        or event_or_issue.get("instrument")
        or ""
    ).strip()


def _room_accepts(rules, room_id, instrument):
    room_types = (rules.get("room_types") or {}) if isinstance(rules, dict) else {}
    allowed = room_types.get(room_id)
    if not isinstance(allowed, (list, tuple, set)) or not allowed:
        return True
    instrument = str(instrument or "").casefold()
    return any(instrument and instrument in str(item).casefold() for item in allowed)


def _teacher_key(value):
    return str(value or "").strip().casefold()


_CJK_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")


def _stable_subject_id(kind, item):
    if kind == "issue":
        return unresolved_assignment_primitives.issue_id(item)
    return str(item.get("id") or "").strip()


def _clock_minutes(value):
    return f"{int(value) // 60:02d}:{int(value) % 60:02d}"


def _public_failure_code(message):
    """Map Python's rejection message to a stable, non-identifying code."""
    lowered = str(message or "").casefold()
    if "unknown room" in lowered:
        return "unknown_room"
    if "unknown reconciliation subject alias" in lowered:
        return "unknown_subject_alias"
    if "needs a subject alias" in lowered:
        return "missing_subject_alias"
    if "at least one change" in lowered:
        return "empty_package"
    if "appears more than once" in lowered:
        return "duplicate_subject"
    if "locked" in lowered:
        return "locked_room_window"
    if "protected" in lowered:
        return "protected_subject"
    if "another day" in lowered or "cross-day" in lowered:
        return "cross_day_out_of_scope"
    if "time-change authorization" in lowered or "time-change exception" in lowered:
        return "time_change_not_authorized"
    if "room type mismatch" in lowered:
        return "room_type_mismatch"
    if "authorization" in lowered:
        return "authorization_required"
    if "not in the explicit time-change proposal pool" in lowered:
        return "teacher_time_change_not_allowed"
    if "conflict" in lowered or "occupied" in lowered:
        return "hard_conflict"
    if "teacher confirmation" in lowered:
        return "teacher_confirmation_required"
    if "subject" in lowered and ("present" in lowered or "editable" in lowered):
        return "subject_not_in_snapshot"
    return "package_rejected"


def _public_package_hash(normalized):
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _explicit_locks(assignments):
    """Keep only canonical occupancy locks; stale L1 is not current occupancy."""
    return build_occupancy_assignments(assignments or [], [])


def _snapshot_hash(snapshot):
    payload = copy.deepcopy(snapshot) if isinstance(snapshot, dict) else snapshot
    if isinstance(payload, dict):
        # `_rules_meta` carries a load timestamp, so it can never define identity.
        payload["rules"] = {
            key: value
            for key, value in (payload.get("rules") or {}).items()
            if key != TRACE_KEY
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dominates(left, right):
    """Pareto dominance for the package metric vector."""
    left_metrics = left.get("metrics") or {}
    right_metrics = right.get("metrics") or {}
    benefits = ("resolved_delta",)
    costs = (
        "remaining_unresolved",
        "moved_assignments",
        "time_changed_assignments",
        "teacher_day_splits",
        "total_shift_minutes",
        "non_preferred_placements",
        "room_switches",
        "affected_instructor_count",
        "required_confirmation_count",
        "repeat_time_change_burden",
        "hard_conflict_count",
        "sacrificed_assignments",
    )
    no_worse = all(left_metrics.get(key, 0) >= right_metrics.get(key, 0) for key in benefits)
    no_worse = no_worse and all(left_metrics.get(key, 0) <= right_metrics.get(key, 0) for key in costs)
    strictly_better = any(left_metrics.get(key, 0) > right_metrics.get(key, 0) for key in benefits)
    strictly_better = strictly_better or any(left_metrics.get(key, 0) < right_metrics.get(key, 0) for key in costs)
    return no_worse and strictly_better


def _package_requires_sacrifice(public):
    metrics = public.get("metrics") or {}
    return bool(public.get("requires_sacrifice_authorization")) or int(
        metrics.get("sacrificed_assignments") or 0
    ) > 0


def _package_preserves_existing_placements(public):
    if public.get("status") not in {"feasible", "conditional"}:
        return False
    return not _package_requires_sacrifice(public)


def _places_unresolved(public):
    """True when a sandbox result is a real candidate, not a no-progress reshuffle."""
    if not isinstance(public, dict) or public.get("status") not in {"feasible", "conditional"}:
        return False
    metrics = public.get("metrics") or {}
    if int(metrics.get("resolved_delta") or 0) > 0:
        return True
    return int(metrics.get("sacrificed_assignments") or 0) > 0


class ReconciliationInvestigation:
    """One immutable Step 4 investigation session."""

    def __init__(
        self,
        runtime,
        *,
        workspace_version: str,
        run_id: str,
        day: int,
        issue_ids=None,
        scope_type="day",
        scope_id=None,
        goal="",
        protect_teachers=(),
        protect_subject_ids=(),
        allow_time_change_teachers=(),
        locked_room_days=(),
        prior_decisions=(),
        prior_thread=None,
        max_tool_calls=None,
    ):
        self.investigation_id = uuid.uuid4().hex
        self.snapshot_id = uuid.uuid4().hex
        self.workspace_version = str(workspace_version)
        self.run_id = str(run_id)
        self.scope_type = str(scope_type or "day")
        self.scope_id = str(scope_id or f"day-{int(day)}")
        self.day = int(day)
        self.created_at = _utc_now()
        self._runtime = runtime
        self.goal = str(goal or "").strip()
        self._protect_teachers = {_teacher_key(item) for item in protect_teachers if _teacher_key(item)}
        self._protect_subject_ids = {str(item).strip() for item in protect_subject_ids if str(item).strip()}
        self._allow_time_change_teachers = {
            _teacher_key(item) for item in allow_time_change_teachers if _teacher_key(item)
        }
        self._locked_room_days = {
            (str(item.get("room") or "").strip(), int(item.get("day")))
            for item in locked_room_days
            if isinstance(item, dict) and str(item.get("room") or "").strip()
            and isinstance(item.get("day"), int)
            and int(item["day"]) in range(7)
        }
        self.max_tool_calls = int(max_tool_calls) if max_tool_calls else MAX_TOOL_CALLS
        self._max_tool_calls = max(1, min(self.max_tool_calls, MAX_TOOL_CALLS))
        self._prior_decisions = [
            {
                "status": str(item.get("status") or ""),
                "decided_at": str(item.get("decided_at") or ""),
                "note": str(item.get("note") or "")[:400],
                "subject_ids": [
                    str(value) for value in item.get("subject_ids") or []
                    if str(value).strip()
                ],
                "packages": copy.deepcopy(item.get("packages") or []),
            }
            for item in prior_decisions or []
            if isinstance(item, dict)
        ]
        self._prior_thread = self._normalize_prior_thread(prior_thread)
        all_unresolved = copy.deepcopy(runtime.edit_session.get("unassigned_lessons", []) or [])
        requested_issue_ids = {str(item).strip() for item in (issue_ids or []) if str(item).strip()}
        self._scope_issue_ids = requested_issue_ids or None
        selected_unresolved = (
            [
                item for item in all_unresolved
                if unresolved_assignment_primitives.issue_id(item) in requested_issue_ids
            ]
            if requested_issue_ids
            else all_unresolved
        )
        if requested_issue_ids and len(selected_unresolved) != len(requested_issue_ids):
            missing = sorted(requested_issue_ids - {
                unresolved_assignment_primitives.issue_id(item) for item in selected_unresolved
            })
            raise PackageRejected(f"Unknown reconciliation issue: {missing[0]}")
        self._snapshot = {
            "assignments": copy.deepcopy(runtime.edit_session.get("assignments", []) or []),
            "unassigned_lessons": selected_unresolved,
            "locked_context_assignments": _explicit_locks(runtime.locked_context_assignments),
            "booked_lectures": copy.deepcopy(runtime.booked_lectures or []),
            "rooms": copy.deepcopy(runtime.rooms_cache or []),
            "rules": copy.deepcopy(runtime.normalized_rules or {}),
        }
        self.snapshot_hash = _snapshot_hash(self._snapshot)
        self._aliases: dict[str, str] = {}
        self._alias_to_subject: dict[str, tuple[str, str]] = {}
        self._teacher_aliases: dict[str, str] = {}
        self._teacher_display: dict[str, str] = {}
        self._simulations: dict[str, dict[str, Any]] = {}
        self._brief: dict[str, Any] | None = None
        self._inspected: set[str] = set()
        self._tool_calls = 0
        self._blocks: dict[str, dict[str, Any]] = {}
        self._availability_index = None
        self._build_aliases()

    def _day_assignments(self):
        """Every placed lesson on the selected day: the whole-day work object."""
        return [
            assignment
            for assignment in self._snapshot["assignments"]
            if isinstance(assignment, dict)
            and assignment.get("id")
            and _event_day(assignment) == self.day
        ]

    def focus_aliases(self):
        return [
            self._alias_for("issue", unresolved_assignment_primitives.issue_id(item))
            for item in self._snapshot["unassigned_lessons"]
            if self._alias_for("issue", unresolved_assignment_primitives.issue_id(item))
        ]

    @property
    def tool_calls(self):
        return self._tool_calls

    @property
    def snapshot(self):
        return copy.deepcopy(self._snapshot)

    @staticmethod
    def snapshot_hash_for_runtime(runtime, issue_ids=None):
        unresolved = copy.deepcopy(runtime.edit_session.get("unassigned_lessons", []) or [])
        selected = {str(item).strip() for item in (issue_ids or []) if str(item).strip()}
        if selected:
            unresolved = [
                item for item in unresolved
                if unresolved_assignment_primitives.issue_id(item) in selected
            ]
        return _snapshot_hash(
            {
                "assignments": copy.deepcopy(runtime.edit_session.get("assignments", []) or []),
                "unassigned_lessons": unresolved,
                "locked_context_assignments": _explicit_locks(runtime.locked_context_assignments),
                "booked_lectures": copy.deepcopy(runtime.booked_lectures or []),
                "rooms": copy.deepcopy(runtime.rooms_cache or []),
                "rules": copy.deepcopy(runtime.normalized_rules or {}),
            }
        )

    def _consume_tool_call(self, *, allow_after_brief=False, is_report=False):
        """Count exploration calls only; the final brief is always allowed."""
        if self._brief is not None and not allow_after_brief:
            raise PackageRejected("This reconciliation investigation has already submitted its brief.")
        if is_report:
            return
        if self._tool_calls >= self._max_tool_calls:
            raise PackageRejected("Pi reconciliation tool-call budget exhausted.")
        self._tool_calls += 1

    def _build_aliases(self):
        subjects = []
        for item in self._snapshot["unassigned_lessons"]:
            if isinstance(item, dict):
                subjects.append(("issue", _stable_subject_id("issue", item), item))
        for item in self._day_assignments():
            if isinstance(item, dict) and item.get("id"):
                subjects.append(("assignment", _stable_subject_id("assignment", item), item))
        for kind in ("issue", "assignment"):
            counter = 0
            for item_kind, subject_id, _item in sorted(
                (entry for entry in subjects if entry[0] == kind),
                key=lambda value: value[1],
            ):
                counter += 1
                alias = f"{kind}-{counter}"
                self._aliases[f"{item_kind}:{subject_id}"] = alias
                self._alias_to_subject[alias] = (item_kind, subject_id)

        teachers = sorted(
            {
                name.casefold(): name
                for kind, _subject_id, item in subjects
                if (name := self._teacher_for_item(kind, item))
            }.values(),
            key=str.casefold,
        )
        # Instructors stay on the model surface as roster names; only students
        # and lesson rows are aliased. teacher_display is an identity map so the
        # operator UI can keep using the same lookup.
        self._teacher_aliases = {teacher.casefold(): teacher for teacher in teachers}
        self._teacher_display = {teacher: teacher for teacher in teachers}
        self._build_blocks()

    def _build_blocks(self):
        """Group the whole day into complete teacher-day blocks (the moving unit)."""
        self._blocks = {}
        for alias, block in self._blocks_from(self._day_assignments(), initial=True).items():
            self._blocks[alias] = block
            self._alias_to_subject[alias] = ("block", alias)

    def _known_block_alias(self, teacher, day):
        key = (_teacher_key(teacher), day)
        for alias, block in self._blocks.items():
            if (_teacher_key(block["teacher"]), block["day"]) == key:
                return alias
        return None

    def _blocks_from(self, assignments, *, initial=False):
        """Deterministic teacher-day blocks for one assignment list."""
        grouped = {}
        for assignment in assignments:
            if not isinstance(assignment, dict) or not assignment.get("id"):
                continue
            teacher = _teacher(assignment)
            day = _event_day(assignment)
            if not teacher or day not in range(7):
                continue
            grouped.setdefault((teacher.casefold(), day), {
                "teacher": teacher,
                "day": day,
                "events": [],
            })["events"].append(assignment)
        blocks = {}
        used = set(self._blocks)
        for index, key in enumerate(sorted(grouped), start=1):
            entry = grouped[key]
            events = sorted(
                entry["events"],
                key=lambda event: (
                    TimeParser.to_minutes(
                        TimeParser.event_clock_pair(event, default=(None, None))[0],
                        default=0,
                    ),
                    str(event.get("id")),
                ),
            )
            try:
                package = build_teacher_day_package(events)
            except ValueError:
                # A malformed teacher-day block stays visible as single events.
                continue
            alias = (
                None if initial else self._known_block_alias(entry["teacher"], entry["day"])
            )
            if alias is None:
                alias = f"block-{index}"
                while alias in used or alias in blocks:
                    index += 1
                    alias = f"block-{index}"
            used.add(alias)
            blocks[alias] = {
                "alias": alias,
                "teacher": entry["teacher"],
                "day": entry["day"],
                "events": events,
                "package": package,
            }
        return blocks

    def _availability(self):
        if self._availability_index is None:
            # Teacher occupancy needs the whole board, not just the selected day.
            self._availability_index = self._availability_from(
                self._snapshot["locked_context_assignments"],
                self._snapshot["assignments"],
                self._runtime.validator,
            )
        return self._availability_index

    @staticmethod
    def _availability_from(locked_context_assignments, assignments, validator):
        return ResolutionAvailability(SimpleNamespace(
            locked_context_assignments=locked_context_assignments,
            edit_session={"assignments": assignments},
            validator=validator,
        ))

    def _block_room(self, block):
        rooms = {
            str(event.get("resourceId") or event.get("room") or "").strip()
            for event in block["events"]
        }
        return rooms.pop() if len(rooms) == 1 else ""

    def _room_locked(self, room_id, day):
        return (str(room_id or "").strip(), int(day)) in self._locked_room_days

    def _block_candidate_rooms(self, block, availability=None):
        """Rooms the whole teacher-day block can move into unchanged in time."""
        availability = availability or self._availability()
        current_room = self._block_room(block)
        candidates = []
        for room in self._snapshot["rooms"]:
            room_id = str(room.get("id") or "").strip()
            if not room_id or room_id == current_room or self._room_locked(room_id, block["day"]):
                continue
            if all(
                self._block_event_fits(availability, block["day"], event, room_id)
                for event in block["events"]
            ):
                candidates.append(room_id)
        return candidates

    def _block_event_fits(self, availability, day, event, room_id):
        start, end = TimeParser.event_clock_pair(event, default=(None, None))
        start_min = TimeParser.to_minutes(start, default=None)
        end_min = TimeParser.to_minutes(end, default=None, prefer_end=True)
        if start_min is None or end_min is None or end_min <= start_min:
            return False
        if self._room_locked(room_id, day):
            return False
        if not availability.room_allowed(room_id, _instrument(event)).get("allowed", True):
            return False
        return availability.room_free(
            room=room_id,
            day=day,
            start=start_min,
            end=end_min,
            date=TimeParser.event_specific_date(event),
        )

    def _issue_room_sets(self, availability, issue):
        """Legal empty rooms vs occupancy-empty rooms that room-type rules reject."""
        context = unresolved_assignment_primitives.build_context(issue)
        day = context.get("original_day")
        start = TimeParser.to_minutes(context.get("original_start"), default=None)
        end = TimeParser.to_minutes(context.get("original_end"), default=None, prefer_end=True)
        if day not in range(7) or start is None or end is None or end <= start:
            return [], []
        instrument = context.get("instrument")
        available = []
        incompatible_empty = []
        for room in self._snapshot["rooms"]:
            room_id = str(room.get("id") or "").strip()
            if not room_id or self._room_locked(room_id, day):
                continue
            if not availability.room_free(
                room=room_id,
                day=day,
                start=start,
                end=end,
                date=context.get("original_date"),
            ):
                continue
            if availability.room_allowed(room_id, instrument).get("allowed", True):
                available.append(room_id)
            else:
                incompatible_empty.append(room_id)
        # ponytail: occupancy fact for human emergency exceptions, not a legal target list
        return available, incompatible_empty[:12]

    def _teacher_permitted(self, permitted, teacher):
        return _teacher_key(teacher) in permitted

    def _enforce_permits(self, items):
        """Reject protected targets, cross-day moves, and unpermitted time changes."""
        for item in items:
            alias = item["subject_alias"]
            mapping = self._alias_to_subject.get(alias)
            kind, subject_id = mapping
            if item.get("withdraw"):
                block = self._blocks.get(alias) if kind == "block" else None
                teacher = block["teacher"] if block else self._teacher_for_subject(kind, subject_id)
                if subject_id in self._protect_subject_ids or _teacher_key(teacher) in self._protect_teachers:
                    raise PackageRejected(f"Subject {alias} is protected for this task.")
                if block is not None:
                    member_ids = {str(event.get("id")) for event in block["events"]}
                    if member_ids & self._protect_subject_ids:
                        raise PackageRejected(f"Block {alias} contains a protected lesson.")
                continue
            block = self._blocks.get(alias) if kind == "block" else None
            if block is not None:
                teacher = block["teacher"]
                before = {"day": block["day"], "start": None, "end": None}
                if _teacher_key(teacher) in self._protect_teachers or any(
                    str(event.get("id")) in self._protect_subject_ids for event in block["events"]
                ):
                    raise PackageRejected(f"Block {alias} is protected for this task.")
            else:
                subject = self._subject_item(kind, subject_id)
                teacher = self._teacher_for_item(kind, subject)
                if subject_id in self._protect_subject_ids or _teacher_key(teacher) in self._protect_teachers:
                    raise PackageRejected(f"Subject {alias} is protected for this task.")
                before = self._placement_for_item(kind, subject)
            target = item["target"]
            target_day = target.get("day")
            if before.get("day") is None:
                raise PackageRejected(
                    f"Subject {alias} has no usable original day; fix its source data first."
                )
            if target_day is None or int(target_day) != int(before["day"]):
                raise PackageRejected(
                    f"Subject {alias} cannot move to another day; cross-day changes stay with the operator."
                )
            if block is not None:
                continue
            changed = (
                _clock(target.get("start")) != before.get("start")
                or _clock(target.get("end"), prefer_end=True) != before.get("end")
            )
            if changed and not self._teacher_permitted(self._allow_time_change_teachers, teacher):
                raise PackageRejected(
                    "Changing a scheduled time needs an explicit time-change exception for this teacher."
                )

    def _teacher_for_subject(self, kind, subject_id):
        subject = self._subject_item(kind, subject_id)
        return self._teacher_for_item(kind, subject)

    @staticmethod
    def _teacher_for_item(kind, subject):
        if kind == "issue":
            return str(unresolved_assignment_primitives.build_context(subject).get("instructor") or "").strip()
        return _teacher(subject)

    @staticmethod
    def _placement_for_item(kind, subject):
        if kind == "issue":
            return {
                "room": None,
                "day": unresolved_assignment_primitives.build_context(subject).get("original_day"),
                "start": _clock(unresolved_assignment_primitives.build_context(subject).get("original_start")),
                "end": _clock(unresolved_assignment_primitives.build_context(subject).get("original_end"), prefer_end=True),
            }
        placement = _event_placement(subject)
        return {
            "room": placement.get("room"),
            "day": placement.get("day"),
            "start": _clock(placement.get("start")),
            "end": _clock(placement.get("end"), prefer_end=True),
        }

    def _expand_block_change(self, block, target):
        """Translate one block move into per-event final-state changes."""
        room = str(target.get("room") or target.get("resourceId") or "").strip()
        if not room:
            raise PackageRejected(f"Block {block['alias']} needs a target room.")
        if self._room_locked(room, block["day"]):
            raise PackageRejected(f"Room {room} is locked for day {block['day']} in this task.")
        day = target.get("day")
        if day is not None:
            try:
                day = int(day)
            except (TypeError, ValueError) as exc:
                raise PackageRejected(f"Invalid day for block {block['alias']}.") from exc
            if day != block["day"]:
                raise PackageRejected(
                    "Teacher-day blocks keep their original day; a cross-day change stays with the operator."
                )
        intervals = block["package"]["source_intervals"]
        placements = [
            {
                "event_id": str(event.get("id")),
                "day": block["day"],
                "start": _clock_minutes(interval["start"]),
                "end": _clock_minutes(interval["end"]),
                "room": room,
            }
            for event, interval in zip(block["events"], intervals)
        ]
        validation = validate_teacher_day_placement(block["package"], placements)
        if not validation["valid"]:
            raise PackageRejected(
                "Teacher-day package integrity: " + ", ".join(validation["errors"])
            )
        return [
            {
                "subject_alias": placement["event_id"],
                "target": {
                    "room": room,
                    "day": block["day"],
                    "start": placement["start"],
                    "end": placement["end"],
                },
            }
            for placement in placements
        ]

    def _normalize_public_changes(self, changes):
        """Normalize a mixed package of block moves, subject changes, and withdrawals."""
        if not isinstance(changes, list) or not changes:
            raise PackageRejected("A reconciliation package must contain at least one change.")
        normalized = []
        seen = set()
        subject_entries = []
        for raw in changes:
            if not isinstance(raw, dict):
                raise PackageRejected("Each reconciliation change must be an object.")
            subject = str(
                raw.get("subject_alias")
                or raw.get("subject_id")
                or raw.get("assignment_id")
                or raw.get("issue_id")
                or ""
            ).strip()
            if not subject:
                raise PackageRejected("Each reconciliation change needs a subject alias.")
            if subject in seen:
                raise PackageRejected(f"Subject {subject} appears more than once in the package.")
            seen.add(subject)
            mapping = self._alias_to_subject.get(subject)
            if mapping is None:
                raise PackageRejected(f"Unknown reconciliation subject alias: {subject}")
            if raw.get("withdraw"):
                if mapping[0] == "issue":
                    raise PackageRejected(
                        f"Subject {subject} is already unresolved and cannot be withdrawn."
                    )
                target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
                if target.get("room") or raw.get("room"):
                    raise PackageRejected(
                        f"Subject {subject} cannot both withdraw and move."
                    )
                normalized.append({"subject_alias": subject, "withdraw": True})
                continue
            if mapping[0] != "block":
                subject_entries.append(raw)
                continue
            block = self._blocks[subject]
            target = raw.get("target") if isinstance(raw.get("target"), dict) else raw
            room = str(target.get("room") or target.get("resourceId") or "").strip()
            if not room:
                raise PackageRejected(f"Block {subject} needs a target room.")
            day = target.get("day")
            if day is not None:
                try:
                    day = int(day)
                except (TypeError, ValueError) as exc:
                    raise PackageRejected(f"Invalid day for block {subject}.") from exc
                if day != block["day"]:
                    raise PackageRejected(
                        "Teacher-day blocks keep their original day; a cross-day change stays with the operator."
                    )
            normalized.append({
                "subject_alias": subject,
                "target": {"room": room, "day": block["day"]},
            })
        if subject_entries:
            normalized.extend(normalize_package_changes(subject_entries))
        return sorted(normalized, key=lambda item: item["subject_alias"])

    def _prior_decision_aliases(self):
        """Map compact canonical decisions onto this investigation's aliases."""
        decisions = []
        for item in self._prior_decisions:
            aliases = {
                alias
                for alias in (
                    self._alias_for("assignment", subject_id)
                    or self._alias_for("issue", subject_id)
                    for subject_id in item.get("subject_ids") or []
                )
                if alias
            }
            packages = []
            for package in item.get("packages") or []:
                changes = []
                applicable = True
                for change in package.get("changes") or []:
                    subject_id = str(change.get("subject_alias") or "")
                    alias = self._alias_for("assignment", subject_id) or self._alias_for(
                        "issue", subject_id
                    )
                    if not alias:
                        applicable = False
                        continue
                    aliases.add(alias)
                    projected = copy.deepcopy(change)
                    projected["subject_alias"] = alias
                    changes.append(projected)
                if changes:
                    packages.append(
                        {
                            "package_hash": str(package.get("package_hash") or ""),
                            "changes": changes,
                            "applicable": applicable,
                        }
                    )
            decisions.append(
                {
                    "status": item["status"],
                    "decided_at": item["decided_at"],
                    "note": item["note"],
                    "subject_aliases": sorted(aliases),
                    "packages": packages,
                }
            )
        return decisions

    def _model_safe_text(self, value):
        text = str(value or "")
        replacements = {}
        for kind, items in (
            ("assignment", self._snapshot["assignments"]),
            ("issue", self._snapshot["unassigned_lessons"]),
        ):
            for item in items:
                subject_id = _stable_subject_id(kind, item)
                alias = self._alias_for(kind, subject_id)
                if not alias:
                    continue
                props = item.get("extendedProps") if isinstance(item.get("extendedProps"), dict) else {}
                context = unresolved_assignment_primitives.build_context(item) if kind == "issue" else {}
                values = {
                    subject_id,
                    unresolved_assignment_primitives.source_request_id(item),
                    item.get("title"),
                    item.get("student"),
                    item.get("student_name"),
                    props.get("Student"),
                    props.get("Student Name"),
                    context.get("student_name"),
                    item.get("email"),
                    props.get("Email"),
                    item.get("phone"),
                    props.get("Phone"),
                }
                for private in values:
                    private = str(private or "").strip()
                    if private:
                        replacements[private] = alias
        for private, alias in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if _CJK_NAME_RE.fullmatch(private):
                text = text.replace(private, alias)
                continue
            text = re.sub(
                rf"(?<!\w){re.escape(private)}(?!\w)",
                alias,
                text,
                flags=re.IGNORECASE,
            )
        text = re.sub(r"(?<![\w@])[^\s@]+@[^\s@]+\.[^\s@]+", "[redacted]", text)
        return re.sub(
            r"(?<!\w)(?:\+\d[\d ().-]{6,}\d|\(?\d{3}\)?[ -]\d{3}[ -]\d{4})(?!\w)",
            "[redacted]",
            text,
        )

    def _normalize_prior_thread(self, thread):
        if not isinstance(thread, dict):
            return None
        pending = []
        for item in thread.get("pending") or []:
            if not isinstance(item, dict):
                continue
            pending.append({
                "kind": str(item.get("kind") or "other"),
                "detail": str(item.get("detail") or "")[:400],
                "teacher": str(item.get("teacher") or "").strip(),
            })
            if len(pending) >= 8:
                break
        codes = []
        for code in thread.get("failure_codes") or []:
            text = str(code or "").strip()
            if text and text not in codes:
                codes.append(text)
            if len(codes) >= 8:
                break
        remaining = []
        for subject_id in thread.get("remaining_issue_ids") or []:
            value = str(subject_id or "").strip()
            if value and value not in remaining:
                remaining.append(value)
            if len(remaining) >= 24:
                break
        goals = []
        raw_goals = thread.get("goals") or []
        if not raw_goals and thread.get("goal"):
            raw_goals = [thread.get("goal")]
        for item in raw_goals:
            value = str(item or "").strip()[:600]
            if value and value not in goals:
                goals.append(value)
            if len(goals) >= 3:
                break
        return {
            "goal": goals[0] if goals else str(thread.get("goal") or "")[:600],
            "goals": goals,
            "termination": str(thread.get("termination") or ""),
            "failure_codes": codes,
            "pending": pending,
            "remaining_issue_ids": remaining,
        }

    def _prior_thread_view(self):
        thread = self._prior_thread
        if not thread:
            return None
        pending = []
        for item in thread["pending"]:
            alias = self._teacher_alias(item["teacher"]) if item["teacher"] else ""
            pending.append({
                "kind": item["kind"],
                "detail": item["detail"],
                "teacher_alias": alias if alias and alias != "teacher-unknown" else None,
            })
        remaining = [
            alias
            for alias in (
                self._alias_for("issue", subject_id)
                for subject_id in thread["remaining_issue_ids"]
            )
            if alias
        ]
        return {
            "goal": thread["goal"],
            "goals": list(thread.get("goals") or []),
            "termination": thread["termination"],
            "failure_codes": list(thread["failure_codes"]),
            "pending_decisions": pending,
            "remaining_issue_aliases": remaining,
        }

    def public_task(self):
        """Local task premises; model callers must use model_task()."""
        task = {
            "goal": self.goal,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "day": self.day,
            "time_is_fixed": True,
            "protect_teacher_aliases": sorted(
                self._teacher_alias(name) for name in self._protect_teachers
            ),
            "protect_subject_aliases": sorted(
                alias
                for alias in (
                    self._alias_for("assignment", subject_id)
                    for subject_id in self._protect_subject_ids
                )
                if alias
            ),
            "time_change_exception_teacher_aliases": sorted(
                self._teacher_alias(name) for name in self._allow_time_change_teachers
            ),
            "locked_room_days": [
                {"room": room, "day": day}
                for room, day in sorted(self._locked_room_days)
            ],
            "tool_calls_used": self._tool_calls,
            "tool_call_budget": self._max_tool_calls,
            "sacrifice_requires_authorization": True,
            "prior_decisions": self._prior_decision_aliases(),
        }
        thread = self._prior_thread_view()
        if thread:
            task["prior_thread"] = thread
        return task

    def model_task(self):
        """Pi-facing premises with known identities replaced by run aliases."""
        task = self.public_task()
        task["goal"] = self._model_safe_text(task["goal"])
        for decision in task["prior_decisions"]:
            decision["note"] = self._model_safe_text(decision.get("note"))
        thread = task.get("prior_thread")
        if thread:
            thread["goal"] = self._model_safe_text(thread.get("goal"))
            thread["goals"] = [self._model_safe_text(item) for item in thread.get("goals") or []]
            for item in thread.get("pending_decisions") or []:
                item["detail"] = self._model_safe_text(item.get("detail"))
        return task

    def _subject_total(self):
        return sum(1 for kind, _value in self._alias_to_subject.values() if kind != "block")

    def _alias_for(self, kind, subject_id):
        return self._aliases.get(f"{kind}:{subject_id}")

    def _teacher_alias(self, teacher):
        key = str(teacher or "").strip()
        if not key:
            return "teacher-unknown"
        return self._teacher_aliases.get(key.casefold(), "teacher-unknown")

    def _subject_item(self, kind, subject_id):
        collection = self._snapshot["unassigned_lessons"] if kind == "issue" else self._snapshot["assignments"]
        return next(
            (
                item
                for item in collection
                if _stable_subject_id(kind, item) == subject_id
            ),
        )

    def _build_controller(self):
        edit_session = {
            "assignments": copy.deepcopy(self._snapshot["assignments"]),
            "unassigned_lessons": copy.deepcopy(self._snapshot["unassigned_lessons"]),
            "history": [],
            "redo_stack": [],
            "dirty": False,
            VALIDATION_AUTHORITY_KEY: {
                "assignments": copy.deepcopy(self._snapshot["locked_context_assignments"]),
                "unassigned_lessons": copy.deepcopy(self._snapshot["unassigned_lessons"]),
            },
        }
        assignments = self._snapshot["locked_context_assignments"] + edit_session["assignments"]
        validator = ConflictValidator(
            {
                "assignments": assignments,
                "lectures": copy.deepcopy(self._snapshot["booked_lectures"]),
                "rooms": copy.deepcopy(self._snapshot["rooms"]),
                "rules": copy.deepcopy(self._snapshot["rules"]),
            }
        )
        return Step4DraftController(
            session_mgr=getattr(self._runtime, "session_mgr", None),
            validator=validator,
            edit_session=edit_session,
            locked_context_assignments=copy.deepcopy(self._snapshot["locked_context_assignments"]),
            booked_lectures=copy.deepcopy(self._snapshot["booked_lectures"]),
            normalized_rules=copy.deepcopy(self._snapshot["rules"]),
        )

    def _external_subject(self, kind, item):
        subject_id = _stable_subject_id(kind, item)
        alias = self._alias_for(kind, subject_id)
        teacher = self._teacher_for_item(kind, item)
        if kind == "issue":
            context = unresolved_assignment_primitives.build_context(item)
            placement = {
                "room": None,
                "day": context.get("original_day"),
                "start": context.get("original_start"),
                "end": context.get("original_end"),
            }
            status = instructor_time_change_status(self._snapshot["rules"], teacher)
            available, incompatible = self._issue_room_sets(self._availability(), item)
            return {
                "subject_alias": alias,
                "kind": kind,
                "editable": True,
                "teacher_alias": self._teacher_alias(teacher),
                "type": context.get("type") or "unknown",
                "instrument": context.get("instrument"),
                "day": placement["day"],
                "start": placement["start"],
                "end": placement["end"],
                "preferred_rooms": list(context.get("preferred_venues") or []),
                "time_change_status": status,
                "available_rooms": available,
                "incompatible_empty_rooms": incompatible,
            }
        placement = _event_placement(item)
        status = instructor_time_change_status(self._snapshot["rules"], teacher)
        return {
            "subject_alias": alias,
            "kind": kind,
            "editable": True,
            "teacher_alias": self._teacher_alias(teacher),
            "type": item.get("type") or "unknown",
            "instrument": _instrument(item),
            "room": placement["room"],
            "day": placement["day"],
            "start": placement["start"],
            "end": placement["end"],
            "time_change_status": status,
            "withdrawable": self._is_withdrawable("assignment", subject_id, teacher),
        }

    def _is_withdrawable(self, kind, subject_id, teacher):
        if subject_id in self._protect_subject_ids:
            return False
        if _teacher_key(teacher) in self._protect_teachers:
            return False
        return kind == "assignment"

    def _subjects(self):
        subjects = []
        for kind in ("issue", "assignment"):
            collection = (
                self._snapshot["unassigned_lessons"]
                if kind == "issue"
                else self._day_assignments()
            )
            for item in collection:
                if isinstance(item, dict):
                    subject = self._external_subject(kind, item)
                    if subject.get("subject_alias"):
                        subjects.append(subject)
        return sorted(subjects, key=lambda item: item["subject_alias"])

    def _edges(self, subjects):
        """Conflict neighbourhood of the unresolved work, not every subject pair."""
        issues = [item for item in subjects if item["kind"] == "issue"]
        others = [item for item in subjects if item["kind"] != "issue"]
        edges = []
        for issue in issues:
            issue_placement = {
                "room": issue.get("room"),
                "day": issue.get("day"),
                "start": issue.get("start"),
                "end": issue.get("end"),
            }
            for other in others:
                other_placement = {
                    "room": other.get("room"),
                    "day": other.get("day"),
                    "start": other.get("start"),
                    "end": other.get("end"),
                }
                reasons = []
                if issue["teacher_alias"] == other["teacher_alias"] and _overlap(
                    issue_placement, other_placement
                ):
                    reasons.append("same_teacher_overlap")
                if _overlap(issue_placement, other_placement):
                    reasons.append("requested_slot_occupied")
                    if _room_accepts(
                        self._snapshot["rules"], other.get("room"), issue.get("instrument")
                    ):
                        reasons.append("compatible_room_occupant")
                if reasons:
                    edges.append(
                        {
                            "from": issue["subject_alias"],
                            "to": other["subject_alias"],
                            "reasons": sorted(set(reasons)),
                        }
                    )
        return edges

    def inspect_reconciliation(self, focus_aliases=None):
        self._consume_tool_call()
        focus = [str(item).strip() for item in (focus_aliases or []) if str(item).strip()]
        subjects = self._subjects()
        known = {item["subject_alias"] for item in subjects}
        # A block alias stands for its member events, so focus can be mixed.
        expanded_focus = set()
        for alias in focus:
            block = self._blocks.get(alias)
            if block is not None:
                expanded_focus.update(
                    self._alias_for("assignment", str(event.get("id")))
                    for event in block["events"]
                )
            else:
                expanded_focus.add(alias)
        unknown = sorted(
            alias
            for alias in expanded_focus
            if alias not in known and alias not in self._blocks
        )
        if unknown:
            raise PackageRejected(f"Unknown reconciliation subject alias: {unknown[0]}")
        focus = sorted(expanded_focus - set(self._blocks))
        edges = self._edges(subjects)
        selected = set(focus)
        if selected:
            changed = True
            while changed:
                changed = False
                for edge in edges:
                    if edge["from"] in selected or edge["to"] in selected:
                        before = len(selected)
                        selected.update((edge["from"], edge["to"]))
                        changed = changed or len(selected) != before
        else:
            selected = known
        self._inspected.update(selected)
        visible_subjects = [item for item in subjects if item["subject_alias"] in selected]
        blocks = []
        for alias in sorted(self._blocks):
            block = self._blocks[alias]
            member_aliases = [
                self._alias_for("assignment", str(event.get("id")))
                for event in block["events"]
            ]
            if selected and not set(item for item in member_aliases if item) & selected:
                continue
            candidates = self._block_candidate_rooms(block)
            blocks.append({
                "subject_alias": alias,
                "teacher_alias": self._teacher_alias(block["teacher"]),
                "day": block["day"],
                "room": self._block_room(block),
                "intervals": [
                    {
                        "start": _clock_minutes(interval["start"]),
                        "end": _clock_minutes(interval["end"]),
                    }
                    for interval in block["package"]["source_intervals"]
                ],
                "event_aliases": [item for item in member_aliases if item],
                "candidate_rooms": candidates,
                "swap_required": not candidates,
                "withdrawable": self._is_withdrawable("assignment", "", block["teacher"]) and not any(
                    str(event.get("id")) in self._protect_subject_ids for event in block["events"]
                ),
            })
        return {
            "investigation_id": self.investigation_id,
            "snapshot_id": self.snapshot_id,
            "subjects": visible_subjects,
            "blocks": blocks,
            "edges": [
                edge
                for edge in edges
                if edge["from"] in selected and edge["to"] in selected
            ],
            "case_index": [
                {
                    "subject_alias": item["subject_alias"],
                    "teacher_alias": item["teacher_alias"],
                    "kind": item["kind"],
                    "day": item.get("day"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "time_change_status": item.get("time_change_status"),
                }
                for item in subjects
                if item["kind"] == "issue"
            ],
            "availability": {
                "working_window": copy.deepcopy(
                    (self._snapshot["rules"].get("constraints") or {}).get("time_range")
                    or {"start": "08:00", "end": "23:00"}
                ),
                "teacher_aliases": sorted(set(item["teacher_alias"] for item in visible_subjects)),
            },
            "coverage": {
                "subjects_inspected": len(self._inspected),
                "subjects_total": len(subjects),
                "uninspected_count": max(0, len(subjects) - len(self._inspected)),
                "teacher_day_blocks": len(self._blocks),
            },
            "task": self.model_task(),
        }

    def _resolve_external_changes(self, changes):
        normalized = self._normalize_public_changes(changes)
        self._enforce_permits(normalized)
        raw = []
        for item in normalized:
            mapping = self._alias_to_subject.get(item["subject_alias"])
            if not mapping:
                raise PackageRejected(f"Unknown reconciliation subject alias: {item['subject_alias']}")
            kind, subject_id = mapping
            if item.get("withdraw"):
                if kind == "block":
                    block = self._blocks[item["subject_alias"]]
                    raw.extend(
                        {"subject_alias": str(event.get("id")), "withdraw": True}
                        for event in block["events"]
                    )
                else:
                    raw.append({"subject_alias": subject_id, "withdraw": True})
                continue
            if kind == "block":
                raw.extend(self._expand_block_change(self._blocks[item["subject_alias"]], item["target"]))
                continue
            if kind == "assignment":
                editable = any(str(candidate.get("id")) == subject_id for candidate in self._snapshot["assignments"])
            else:
                editable = any(unresolved_assignment_primitives.issue_id(candidate) == subject_id for candidate in self._snapshot["unassigned_lessons"])
            if not editable:
                raise PackageRejected(f"Subject {item['subject_alias']} is not editable in Step 4.")
            raw.append({
                "subject_alias": subject_id,
                "target": copy.deepcopy(item["target"]),
            })
        if len(raw) > MAX_PACKAGE_CHANGES:
            raise PackageRejected(
                f"A reconciliation package may contain at most {MAX_PACKAGE_CHANGES} placement changes."
            )
        return normalized, raw

    def raw_changes_for(self, changes):
        """Translate alias-addressed changes back to internal subject IDs."""
        _normalized, raw = self._resolve_external_changes(changes)
        return raw

    def _rejected_simulation(self, message, **extra):
        """Report invalid package input as a reviewable result, not a crash."""
        return {
            "simulation_id": uuid.uuid4().hex,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "status": "infeasible",
            "feasible": False,
            "normalized_changes": [],
            "package_hash": None,
            "metrics": {
                "resolved_delta": 0,
                "remaining_unresolved": len(self._snapshot["unassigned_lessons"]),
                "hard_conflict_count": 1,
                "sacrificed_assignments": 0,
            },
            "required_teacher_confirmations": [],
            "warnings": [],
            "failure_codes": [_public_failure_code(message)],
            "rejection": self._model_safe_text(str(message or ""))[:240],
            "sacrifices": [],
            "changes": [],
            "split_teacher_days": [],
            "requires_sacrifice_authorization": False,
            "same_day_time_change": False,
            "state_after": self.state_view(),
            **extra,
        }

    def state_view(self, controller=None):
        """Where everything stands now, or after a kept-state package."""
        known_issues = {
            key.split(":", 1)[1]: alias
            for key, alias in self._aliases.items()
            if key.startswith("issue:")
        }
        if controller is None:
            assignments = self._day_assignments()
            unresolved = self._snapshot["unassigned_lessons"]
            availability = self._availability()
        else:
            assignments = [
                item for item in controller._assignments
                if _event_day(item) == self.day
            ]
            unresolved = [
                item for item in controller._unassigned_lessons
                if unresolved_assignment_primitives.issue_id(item) in known_issues
            ]
            availability = self._availability_from(
                self._snapshot["locked_context_assignments"],
                controller._assignments,
                controller.validator,
            )
        blocks = []
        for alias, block in sorted(self._blocks_from(assignments).items()):
            rooms = self._block_candidate_rooms(block, availability)
            blocks.append({
                "subject_alias": alias,
                "teacher_alias": self._teacher_alias(block["teacher"]),
                "day": block["day"],
                "room": self._block_room(block),
                "candidate_rooms": rooms,
                "swap_required": not rooms,
            })
        issues = []
        present = set()
        for issue in unresolved:
            issue_id = unresolved_assignment_primitives.issue_id(issue)
            alias = known_issues.get(issue_id)
            if not alias:
                continue
            present.add(alias)
            context = unresolved_assignment_primitives.build_context(issue)
            available, incompatible = self._issue_room_sets(availability, issue)
            issues.append({
                "subject_alias": alias,
                "teacher_alias": self._teacher_alias(context.get("instructor")),
                "day": context.get("original_day"),
                "start": _clock(context.get("original_start")),
                "end": _clock(context.get("original_end"), prefer_end=True),
                "available_rooms": available,
                "incompatible_empty_rooms": incompatible,
            })
        return {
            "unresolved": sorted(issues, key=lambda item: item["subject_alias"]),
            "blocks": blocks,
            "placed_issue_aliases": sorted(alias for alias in known_issues.values() if alias not in present),
        }

    def _sacrifice_view(self, raw_result, raw_changes):
        """Map withdrawn raw subjects back to aliases for explicit disclosure."""
        withdrawn = set(raw_result.get("withdrawn_subject_ids") or [])
        if not withdrawn:
            return []
        placements = {}
        for item in raw_changes:
            if not item.get("withdraw"):
                continue
            subject_id = str(item["subject_alias"])
            original = next(
                (
                    candidate for candidate in self._snapshot["assignments"]
                    if str(candidate.get("id")) == subject_id
                ),
                None,
            )
            if original is None:
                continue
            placement = _event_placement(original)
            placements[subject_id] = {
                "subject_alias": self._alias_for("assignment", subject_id) or subject_id,
                "teacher_alias": self._teacher_alias(_teacher(original)),
                "label": self._event_label(original),
                "day": placement.get("day"),
                "start": placement.get("start"),
                "end": placement.get("end"),
                "room": placement.get("room"),
            }
        return [placements[key] for key in sorted(placements)]

    def _event_label(self, event):
        return str(event.get("title") or event.get("id") or "").strip()

    def _issue_label(self, issue):
        context = unresolved_assignment_primitives.build_context(issue)
        return str(
            context.get("student_name")
            or context.get("course_code")
            or unresolved_assignment_primitives.issue_id(issue)
        ).strip()

    def _change_view(self, normalized, raw_changes):
        """Local display projection: one row per affected lesson.

        Carries real instructor and lesson labels for the operator's review;
        the ledger projection strips these fields.
        """
        group_of = {}
        for item in normalized:
            alias = item["subject_alias"]
            mapping = self._alias_to_subject.get(alias)
            if mapping is None:
                continue
            kind, subject_id = mapping
            if kind == "block":
                block = self._blocks[alias]
                for event in block["events"]:
                    group_of[str(event.get("id"))] = (alias, len(block["events"]))
            else:
                group_of[str(subject_id)] = (alias, 1)

        assignments_by_id = {
            str(event.get("id")): event for event in self._snapshot["assignments"]
        }
        issues_by_id = {
            unresolved_assignment_primitives.issue_id(item): item
            for item in self._snapshot["unassigned_lessons"]
        }
        rows = []
        for raw in raw_changes:
            raw_id = str(raw.get("subject_alias"))
            withdrawn = bool(raw.get("withdraw"))
            group_alias, group_size = group_of.get(raw_id, (raw_id, 1))
            assignment = assignments_by_id.get(raw_id)
            issue = issues_by_id.get(raw_id)
            if assignment is not None:
                teacher = _teacher(assignment)
                label = self._event_label(assignment)
                from_placement = _event_placement(assignment)
                action = "withdraw" if withdrawn else "move"
                subject_kind = "assignment"
            elif issue is not None:
                context = unresolved_assignment_primitives.build_context(issue)
                teacher = str(context.get("instructor") or "").strip()
                label = self._issue_label(issue)
                from_placement = {
                    "room": None,
                    "day": context.get("original_day"),
                    "start": _clock(context.get("original_start")),
                    "end": _clock(context.get("original_end"), prefer_end=True),
                }
                action = "place"
                subject_kind = "issue"
            else:
                continue
            target = raw.get("target") if isinstance(raw.get("target"), dict) else None
            to_placement = None if withdrawn or target is None else {
                "room": str(target.get("room") or "").strip(),
                "day": target.get("day"),
                "start": _clock(target.get("start")),
                "end": _clock(target.get("end"), prefer_end=True),
            }
            time_changed = bool(
                to_placement
                and (
                    to_placement["day"] != from_placement["day"]
                    or to_placement["start"] != _clock(from_placement["start"])
                    or to_placement["end"] != _clock(from_placement["end"], prefer_end=True)
                )
            )
            rows.append(
                {
                    "subject_alias": raw_id,
                    "group_alias": group_alias,
                    "group_size": group_size,
                    "kind": "block" if group_size > 1 else subject_kind,
                    "action": action,
                    "teacher": teacher,
                    "label": label,
                    "from": from_placement,
                    "to": to_placement,
                    "time_changed": time_changed,
                    "room_changed": bool(
                        to_placement
                        and str(from_placement.get("room") or "") != to_placement["room"]
                    ),
                    "is_sacrifice": withdrawn,
                }
            )
        return sorted(rows, key=lambda row: (row["group_alias"], row["subject_alias"]))

    def applied_change_view(self, records):
        """Actual change rows built from the canonical mutation records.

        The apply path revalidates a package, so the operator's report must come
        from what was really written rather than from the earlier prediction.
        """
        rows = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            action = str(record.get("action") or "")
            before = record.get("prev_state") if isinstance(record.get("prev_state"), dict) else None
            after = record.get("new_state") if isinstance(record.get("new_state"), dict) else None
            event = after or before
            if event is None:
                continue
            if action == "assign":
                row_action, subject_kind = "place", "issue"
            elif action == "unassign":
                row_action, subject_kind = "withdraw", "assignment"
            elif action == "move":
                row_action, subject_kind = "move", "assignment"
            else:
                continue
            teacher = str(record.get("teacher") or "").strip() or _teacher(after or before or {})
            label = self._event_label(event) if subject_kind == "assignment" else self._issue_label(event)
            from_placement = (
                self._placement_for_item("issue", before)
                if subject_kind == "issue"
                else _event_placement(before or event)
            )
            to_placement = None if row_action == "withdraw" else _event_placement(after or event)
            day = (to_placement or from_placement).get("day")
            group_alias = f"{teacher}|{day}|{row_action}" if row_action == "move" else str(record.get("slot_id") or label)
            time_changed = bool(
                to_placement
                and (
                    to_placement.get("day") != from_placement.get("day")
                    or _clock(to_placement.get("start")) != _clock(from_placement.get("start"))
                    or _clock(to_placement.get("end"), prefer_end=True)
                    != _clock(from_placement.get("end"), prefer_end=True)
                )
            )
            rows.append(
                {
                    "subject_alias": str(record.get("slot_id") or record.get("issue_id") or label),
                    "group_alias": group_alias,
                    "group_size": 1,
                    "kind": subject_kind,
                    "action": row_action,
                    "teacher": teacher,
                    "label": label,
                    "from": from_placement,
                    "to": to_placement,
                    "time_changed": time_changed,
                    "room_changed": bool(
                        to_placement
                        and str(from_placement.get("room") or "") != str(to_placement.get("room") or "")
                    ),
                    "is_sacrifice": row_action == "withdraw",
                }
            )
        sizes = {}
        for row in rows:
            if row["action"] == "move":
                sizes[row["group_alias"]] = sizes.get(row["group_alias"], 0) + 1
        for row in rows:
            if row["action"] == "move":
                row["group_size"] = sizes[row["group_alias"]]
                row["kind"] = "block" if row["group_size"] > 1 else "assignment"
        return rows

    def simulate_package(self, changes, *, human_revision=False):
        self._consume_tool_call(allow_after_brief=human_revision)
        try:
            normalized, raw_changes = self._resolve_external_changes(changes)
        except PackageRejected as exc:
            return self._rejected_simulation(exc)
        external_hash = _public_package_hash(normalized)
        for simulation in self._simulations.values():
            if simulation.get("package_hash") == external_hash:
                duplicate = copy.deepcopy(simulation["public"])
                duplicate["duplicate"] = True
                return duplicate
        controller = self._build_controller()
        try:
            raw_result = controller.simulate_reconciliation_package(raw_changes, keep_state=True)
        except PackageRejected as exc:
            # Invalid input is a reviewable result, never a crash at the tool boundary.
            return self._rejected_simulation(exc)
        state_after = self.state_view(controller)
        required = []
        for requirement in raw_result.get("required_teacher_confirmations") or []:
            teacher = str(requirement.get("teacher") or "").strip()
            required.append(
                {
                    "teacher_alias": self._teacher_alias(teacher),
                    "confirmation_id": confirmation_key(
                        self._teacher_alias(teacher),
                        external_hash,
                        self.workspace_version,
                    ),
                }
            )
        simulation_id = uuid.uuid4().hex
        sacrifices = self._sacrifice_view(raw_result, raw_changes)
        change_rows = self._change_view(normalized, raw_changes)
        split_days = [
            {
                "teacher_alias": self._teacher_alias(item.get("teacher_key")),
                "day": item.get("day"),
                "rooms": list(item.get("rooms") or []),
            }
            for item in raw_result.get("split_teacher_days") or []
        ]
        public = {
            "simulation_id": simulation_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "status": raw_result.get("status"),
            "feasible": bool(raw_result.get("feasible")),
            "normalized_changes": copy.deepcopy(normalized),
            "package_hash": external_hash,
            "metrics": copy.deepcopy(raw_result.get("metrics") or {}),
            "required_teacher_confirmations": required,
            "sacrifices": sacrifices,
            "changes": change_rows,
            "split_teacher_days": split_days,
            "same_day_time_change": any(row["time_changed"] for row in change_rows),
            "requires_sacrifice_authorization": bool(
                raw_result.get("requires_sacrifice_authorization")
            ),
            "state_after": copy.deepcopy(state_after),
            "warnings": [
                "teacher_confirmation_required"
                if "teacher" in str(item).casefold()
                else (
                    "sacrifice_authorization_required"
                    if "unresolved" in str(item).casefold()
                    else "package_warning"
                )
                for item in (raw_result.get("warnings") or [])
            ],
            "failure_codes": [
                _public_failure_code(item)
                for item in (raw_result.get("failure_codes") or [])
            ],
        }
        self._simulations[simulation_id] = {
            "public": public,
            "raw_changes": raw_changes,
            "raw_result": raw_result,
            "package_hash": external_hash,
            "source": "human_revision" if human_revision else "pi",
        }
        return copy.deepcopy(public)

    def submit_reconciliation_brief(self, params, *, bound_hit=False):
        self._consume_tool_call(is_report=True)
        if self._brief is not None:
            raise PackageRejected("A reconciliation brief was already submitted.")
        params = params if isinstance(params, dict) else {}
        termination = str(params.get("termination") or "recommendation_ready")
        allowed_termination = {"recommendation_ready", "no_feasible_package_found", "budget_exhausted"}
        if termination not in allowed_termination:
            raise PackageRejected("Invalid reconciliation brief termination reason.")
        primary_id = str(params.get("primary_simulation_id") or "").strip() or None
        fallback_id = str(params.get("fallback_simulation_id") or "").strip() or None
        selected = [item for item in (primary_id, fallback_id) if item]
        if len(selected) != len(set(selected)):
            raise PackageRejected("Primary and fallback simulations must be distinct.")
        if termination == "recommendation_ready" and not primary_id:
            raise PackageRejected("A recommendation-ready brief needs a primary simulation.")
        if termination == "no_feasible_package_found" and selected:
            raise PackageRejected("A no-package brief cannot reference a recommendation.")
        if termination == "no_feasible_package_found" and any(
            _places_unresolved(item.get("public") or {})
            for item in self._simulations.values()
        ):
            raise PackageRejected("A placing package was already found and must not be reported as absent.")
        if termination == "budget_exhausted" and not bound_hit and self._tool_calls < self._max_tool_calls:
            raise PackageRejected("Budget exhaustion can be reported only after the exploration limit is reached.")
        simulations = []
        for simulation_id in selected:
            simulation = self._simulations.get(simulation_id)
            if simulation is None:
                raise PackageRejected("Brief referenced an unknown simulation.")
            if simulation["public"]["status"] not in {"feasible", "conditional"}:
                raise PackageRejected("Brief can reference only feasible or conditional simulations.")
            simulations.append(simulation)
        if termination == "recommendation_ready" and not simulations:
            raise PackageRejected("A recommendation-ready brief needs a feasible primary simulation.")
        if len(simulations) == 2 and _dominates(simulations[1]["public"], simulations[0]["public"]):
            raise PackageRejected("Fallback strictly dominates the selected primary simulation.")
        primary_simulation = next((item for item in simulations if item["public"]["simulation_id"] == primary_id), None)
        if primary_simulation is not None and _package_requires_sacrifice(primary_simulation["public"]):
            if any(
                item["public"]["simulation_id"] != primary_id
                and _package_preserves_existing_placements(item["public"])
                for item in self._simulations.values()
                if isinstance(item, dict) and isinstance(item.get("public"), dict)
            ):
                raise PackageRejected(
                    "A preservation package was already found; it must be the primary recommendation."
                )
        if termination != "recommendation_ready" and simulations and not primary_id:
            raise PackageRejected("A submitted simulation must be named as the primary package.")
        pending_decisions = []
        for item in params.get("pending_decisions") or []:
            if not isinstance(item, dict):
                raise PackageRejected("Each pending decision must be an object.")
            kind = str(item.get("kind") or "").strip()
            if kind not in PENDING_DECISION_KINDS:
                raise PackageRejected(f"Unknown pending decision kind: {kind or '(empty)'}")
            alias = str(item.get("teacher_alias") or "").strip()
            resolved = self._teacher_aliases.get(alias.casefold()) if alias else None
            if alias and resolved is None:
                raise PackageRejected(f"Unknown instructor in pending decision: {alias}")
            detail = str(item.get("detail") or "").strip()[:400]
            violation = _operator_prose_violation("Pending decision detail", detail)
            if violation:
                raise PackageRejected(violation)
            pending_decisions.append(
                {
                    "kind": kind,
                    "detail": detail,
                    "teacher_alias": resolved,
                }
            )
        remaining_issues = []
        remaining_aliases = set()
        alias_to_issue = {
            alias: key.split(":", 1)[1]
            for key, alias in self._aliases.items()
            if key.startswith("issue:")
        }
        for item in params.get("remaining_issues") or []:
            if not isinstance(item, dict):
                raise PackageRejected("Each remaining issue must be an object.")
            alias = str(item.get("subject_alias") or "").strip()
            if alias not in alias_to_issue:
                raise PackageRejected(f"Unknown unresolved alias in remaining issues: {alias}")
            if alias in remaining_aliases:
                raise PackageRejected(f"Duplicate unresolved alias in remaining issues: {alias}")
            remaining_aliases.add(alias)
            issue = next(
                (
                    candidate
                    for candidate in self._snapshot["unassigned_lessons"]
                    if unresolved_assignment_primitives.issue_id(candidate) == alias_to_issue[alias]
                ),
                None,
            )
            context = unresolved_assignment_primitives.build_context(issue or {})
            remaining_issues.append(
                {
                    "subject_alias": alias,
                    "reason": str(item.get("reason") or "").strip()[:300],
                    "teacher_alias": self._teacher_alias(context.get("instructor")),
                    "label": self._issue_label(issue) if issue is not None else alias,
                }
            )
        brief_id = uuid.uuid4().hex
        selected_simulations = {simulation["public"]["simulation_id"]: simulation for simulation in simulations}
        primary_simulation = selected_simulations.get(str(primary_id)) if primary_id else None
        primary_public = (primary_simulation or {}).get("public") or {}
        if primary_simulation is not None:
            expected_remaining = {
                item["subject_alias"]
                for item in (primary_public.get("state_after") or {}).get("unresolved") or []
            }
        else:
            expected_remaining = set(alias_to_issue)
        if remaining_aliases != expected_remaining:
            missing = sorted(expected_remaining - remaining_aliases)
            extra = sorted(remaining_aliases - expected_remaining)
            detail = []
            if missing:
                detail.append(f"missing: {', '.join(missing)}")
            if extra:
                detail.append(f"not unresolved: {', '.join(extra)}")
            raise PackageRejected(
                "The brief must account for every unresolved lesson left by its result exactly; "
                + "; ".join(detail)
                + "."
            )
        if termination == "no_feasible_package_found":
            issue_aliases = set(alias_to_issue)
            if not issue_aliases or not issue_aliases <= self._inspected:
                raise PackageRejected(
                    "A no-package brief requires inspection of every unresolved lesson in the day."
                )
        title = str(params.get("title") or "").strip() or "排课协调建议"
        if len(title) > 80:
            raise PackageRejected("Brief title must be at most 80 characters.")
        violation = _operator_prose_violation("Brief title", title)
        if violation:
            raise PackageRejected(violation)
        rationale = str(params.get("rationale") or "").strip()
        if len(rationale) > 800:
            raise PackageRejected("Brief rationale must be at most 800 characters.")
        violation = _operator_prose_violation("Brief rationale", rationale)
        if violation:
            raise PackageRejected(violation)
        trade_offs = []
        for item in params.get("trade_offs") or []:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > 200:
                raise PackageRejected("Each trade-off must be at most 200 characters.")
            violation = _operator_prose_violation("Trade-off", text)
            if violation:
                raise PackageRejected(violation)
            trade_offs.append(text)
        if len(trade_offs) > 6:
            raise PackageRejected("A brief carries at most 6 trade-offs.")
        limitations = []
        for item in params.get("limitations") or []:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > 200:
                raise PackageRejected("Each limitation must be at most 200 characters.")
            violation = _operator_prose_violation("Limitation", text)
            if violation:
                raise PackageRejected(violation)
            limitations.append(text)
        if len(limitations) > 6:
            raise PackageRejected("A brief carries at most 6 limitations.")
        focus_question = str(params.get("focus_question") or "").strip()
        if termination in {"recommendation_ready", "no_feasible_package_found"}:
            if not focus_question:
                raise PackageRejected(
                    "The brief needs focus_question: one plain sentence telling the "
                    "operator what decision this brief is about."
                )
            if not _CJK_RE.search(focus_question):
                raise PackageRejected(
                    "focus_question must be written in Chinese for the operator."
                )
        if len(focus_question) > 120:
            raise PackageRejected("focus_question must be at most 120 characters.")
        violation = _operator_prose_violation("focus_question", focus_question)
        if violation:
            raise PackageRejected(violation)
        unknowns = []
        for item in params.get("unknowns") or []:
            if not isinstance(item, dict):
                raise PackageRejected("Each unknown must be an object.")
            subject = str(item.get("subject") or "").strip()
            if not subject:
                raise PackageRejected("Each unknown needs a short subject.")
            if len(subject) > 60:
                raise PackageRejected("Each unknown subject must be at most 60 characters.")
            note = str(item.get("note") or "").strip()
            if len(note) > 200:
                raise PackageRejected("Each unknown note must be at most 200 characters.")
            for field, text in (("Unknown subject", subject), ("Unknown note", note)):
                violation = _operator_prose_violation(field, text)
                if violation:
                    raise PackageRejected(violation)
            unknowns.append({"subject": subject, "note": note})
        if len(unknowns) > 5:
            raise PackageRejected("A brief carries at most 5 unknowns.")
        agent_note = str(params.get("agent_note") or "").strip()
        if len(agent_note) > 200:
            raise PackageRejected("agent_note must be at most 200 characters.")
        violation = _operator_prose_violation("agent_note", agent_note)
        if violation:
            raise PackageRejected(violation)
        self._brief = {
            "brief_id": brief_id,
            "investigation_id": self.investigation_id,
            "snapshot_id": self.snapshot_id,
            "status": "proposed",
            "termination": termination,
            "primary_simulation_id": primary_id,
            "fallback_simulation_id": fallback_id,
            "title": title,
            "focus_question": focus_question,
            "agent_note": agent_note,
            "unknowns": unknowns,
            "rationale": rationale,
            "trade_offs": trade_offs,
            "limitations": limitations,
            "pending_decisions": pending_decisions,
            "remaining_issues": remaining_issues,
            "same_day_time_change": bool(primary_public.get("same_day_time_change")),
            "sacrifices": copy.deepcopy(primary_public.get("sacrifices") or []),
            "requires_sacrifice_authorization": bool(
                primary_public.get("requires_sacrifice_authorization")
            ),
            "coverage": {
                "subjects_inspected": len(self._inspected),
                "subjects_total": self._subject_total(),
                "uninspected_count": max(0, self._subject_total() - len(self._inspected)),
                "simulation_count": len(self._simulations),
            },
            "created_at": _utc_now(),
        }
        return copy.deepcopy(self._brief)

    def close_at_server_bound(self, *, bound="runtime"):
        """Python-owned close when a real bound is hit and Pi did not submit."""
        if self._brief is not None:
            return copy.deepcopy(self._brief)
        placing = [
            item
            for item in self._simulations.values()
            if _places_unresolved(item.get("public") or {})
        ]
        placing.sort(
            key=lambda item: (
                0 if _package_preserves_existing_placements(item["public"]) else 1,
                -int((item["public"].get("metrics") or {}).get("resolved_delta") or 0),
                int((item["public"].get("metrics") or {}).get("remaining_unresolved") or 0),
                int((item["public"].get("metrics") or {}).get("room_switches") or 0),
            )
        )
        primary = placing[0] if placing else None
        primary_id = str(((primary or {}).get("public") or {}).get("simulation_id") or "") or None
        public = (primary or {}).get("public") or {}
        if primary is not None:
            expected = {
                str(item.get("subject_alias") or "")
                for item in (public.get("state_after") or {}).get("unresolved") or []
                if str(item.get("subject_alias") or "")
            }
        else:
            expected = {
                alias
                for key, alias in self._aliases.items()
                if key.startswith("issue:")
            }
        remaining_issues = [
            {
                "subject_alias": alias,
                "reason": "Search bound reached before this lesson was placed.",
            }
            for alias in sorted(expected)
        ]
        return self.submit_reconciliation_brief(
            {
                "termination": "budget_exhausted",
                "primary_simulation_id": primary_id or "",
                "title": "调查中断，但已有可用方案" if primary_id else "调查达到上限",
                "focus_question": (
                    "调查在达到上限前被中断；已验证的方案仍可应用，未覆盖的部分需要重新调查。"
                    if primary_id
                    else "调查在达到上限前被中断，没有形成可执行方案；已完成的检查保留作参考。"
                ),
                "rationale": (
                    "搜索在中断前已验证一个可以减少未排课时的方案，可直接应用。"
                    if primary_id
                    else "搜索在中断前没有完成。已完成的沙箱检查结果保留；未覆盖的路径不能证明今天无法安排。"
                ),
                "limitations": [
                    f"在达到上限前共进行了 {self._tool_calls} 次探索调用。"
                ],
                "remaining_issues": remaining_issues,
            },
            bound_hit=True,
        )

    def set_decision(self, decision, *, note=""):
        if self._brief is None:
            raise PackageRejected("No reconciliation brief is available.")
        decision = str(decision or "").strip()
        if decision not in {"pursuing", "rejected"}:
            raise PackageRejected("Decision must be pursuing or rejected.")
        self._brief["status"] = decision
        self._brief["decision_note"] = str(note or "").strip()
        self._brief["decided_at"] = _utc_now()
        return copy.deepcopy(self._brief)

    def public_record(self, *, current_snapshot_hash=None):
        # The Step 4 session file is itself part of the workspace version, so
        # staleness is decided by the schedule snapshot, not by that version.
        stale = bool(
            current_snapshot_hash and str(current_snapshot_hash) != self.snapshot_hash
        )
        return {
            "investigation_id": self.investigation_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "workspace_version": self.workspace_version,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "day": self.day,
            "stale": stale,
            "status": "stale" if stale else ("completed" if self._brief else "running"),
            "created_at": self.created_at,
            "tool_calls": self._tool_calls,
            "task": self.public_task(),
            "teacher_display": copy.deepcopy(self._teacher_display),
            "coverage": {
                "subjects_inspected": len(self._inspected),
                "subjects_total": self._subject_total(),
                "uninspected_count": max(0, self._subject_total() - len(self._inspected)),
                "simulation_count": len(self._simulations),
            },
            "simulations": [copy.deepcopy(item["public"]) for item in self._simulations.values()],
            "brief": copy.deepcopy(self._brief),
        }

    def persisted_record(self):
        """Return local-only state suitable for Step 4 session persistence."""
        return {
            "investigation_id": self.investigation_id,
            "investigation_version": INVESTIGATION_VERSION,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "run_id": self.run_id,
            "workspace_version": self.workspace_version,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "scope_issue_ids": sorted(self._scope_issue_ids or []),
            "day": self.day,
            "created_at": self.created_at,
            "goal": self.goal,
            "protect_teachers": sorted(self._protect_teachers),
            "protect_subject_ids": sorted(self._protect_subject_ids),
            "allow_time_change_teachers": sorted(self._allow_time_change_teachers),
            "locked_room_days": [
                {"room": room, "day": day}
                for room, day in sorted(self._locked_room_days)
            ],
            "max_tool_calls": self._max_tool_calls,
            "task": self.public_task(),
            "teacher_display": copy.deepcopy(self._teacher_display),
            "snapshot": copy.deepcopy(self._snapshot),
            "aliases": copy.deepcopy(self._aliases),
            "alias_to_subject": copy.deepcopy(self._alias_to_subject),
            "teacher_aliases": copy.deepcopy(self._teacher_aliases),
            "prior_decisions": copy.deepcopy(self._prior_decisions),
            "prior_thread": copy.deepcopy(self._prior_thread),
            "simulations": copy.deepcopy(self._simulations),
            "brief": copy.deepcopy(self._brief),
            "inspected": sorted(self._inspected),
            "tool_calls": self._tool_calls,
        }

    @classmethod
    def from_persisted(cls, record, runtime):
        """Rehydrate a session for review, human revision, or apply."""
        obj = cls.__new__(cls)
        obj.investigation_id = str(record.get("investigation_id") or "")
        obj.snapshot_id = str(record.get("snapshot_id") or "")
        obj.snapshot_hash = str(record.get("snapshot_hash") or _snapshot_hash(record.get("snapshot") or {}))
        obj.workspace_version = str(record.get("workspace_version") or "")
        obj.scope_type = str(record.get("scope_type") or "day")
        obj.scope_id = str(record.get("scope_id") or "day")
        day = record.get("day")
        if not isinstance(day, int) or day not in range(7):
            task = record.get("task") if isinstance(record.get("task"), dict) else {}
            day = task.get("day")
        if not isinstance(day, int) or day not in range(7):
            snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
            day = next(
                (
                    _event_day(item)
                    for key in ("unassigned_lessons", "assignments")
                    for item in snapshot.get(key) or []
                    if _event_day(item) is not None
                ),
                None,
            )
        obj.day = day if isinstance(day, int) else 0
        scope_issue_ids = {str(item).strip() for item in (record.get("scope_issue_ids") or []) if str(item).strip()}
        obj._scope_issue_ids = scope_issue_ids or None
        obj.run_id = str(record.get("run_id") or "")
        obj.created_at = str(record.get("created_at") or "")
        obj.goal = str(record.get("goal") or "")
        obj._protect_teachers = {_teacher_key(item) for item in (record.get("protect_teachers") or []) if _teacher_key(item)}
        obj._protect_subject_ids = {str(item).strip() for item in (record.get("protect_subject_ids") or []) if str(item).strip()}
        obj._allow_time_change_teachers = {
            _teacher_key(item) for item in (record.get("allow_time_change_teachers") or []) if _teacher_key(item)
        }
        obj._prior_decisions = copy.deepcopy(record.get("prior_decisions") or [])
        obj._prior_thread = obj._normalize_prior_thread(record.get("prior_thread"))
        obj._locked_room_days = {
            (str(item.get("room") or "").strip(), int(item.get("day")))
            for item in (record.get("locked_room_days") or [])
            if isinstance(item, dict) and str(item.get("room") or "").strip() and isinstance(item.get("day"), int)
        }
        obj._max_tool_calls = int(record.get("max_tool_calls") or MAX_TOOL_CALLS)
        obj._teacher_display = {
            str(alias): str(name)
            for alias, name in (record.get("teacher_display") or {}).items()
        }
        obj._runtime = runtime
        obj._snapshot = copy.deepcopy(record.get("snapshot") or {})
        obj._aliases = copy.deepcopy(record.get("aliases") or {})
        raw_aliases = record.get("alias_to_subject") or {}
        obj._alias_to_subject = {
            str(alias): tuple(value)
            for alias, value in raw_aliases.items()
            if isinstance(value, (list, tuple)) and len(value) == 2
        }
        obj._teacher_aliases = copy.deepcopy(record.get("teacher_aliases") or {})
        obj._simulations = copy.deepcopy(record.get("simulations") or {})
        obj._brief = copy.deepcopy(record.get("brief")) if isinstance(record.get("brief"), dict) else None
        obj._inspected = set(record.get("inspected") or [])
        obj._tool_calls = int(record.get("tool_calls") or 0)
        obj._blocks = {}
        obj._availability_index = None
        if not obj._teacher_display:
            obj._teacher_display = {
                alias: alias for alias in obj._teacher_aliases.values()
            }
        obj._build_blocks()
        return obj


def public_record_from_persisted(
    record,
    *,
    current_snapshot_hash=None,
):
    if not isinstance(record, dict):
        return None
    stale = bool(
        current_snapshot_hash
        and str(current_snapshot_hash) != str(record.get("snapshot_hash") or "")
    )
    simulations = record.get("simulations") if isinstance(record.get("simulations"), dict) else {}
    raw_aliases = record.get("alias_to_subject") if isinstance(record.get("alias_to_subject"), dict) else {}
    aliases = {
        alias: value
        for alias, value in raw_aliases.items()
        if not (isinstance(value, (list, tuple)) and value and value[0] == "block")
    }
    inspected = record.get("inspected") if isinstance(record.get("inspected"), list) else []
    brief = copy.deepcopy(record.get("brief")) if isinstance(record.get("brief"), dict) else None
    status = record.get("operation_status") or ("stale" if stale else ("completed" if brief else "running"))
    return {
        "investigation_id": record.get("investigation_id"),
        "snapshot_id": record.get("snapshot_id"),
        "snapshot_hash": record.get("snapshot_hash"),
        "workspace_version": record.get("workspace_version"),
        "scope_type": record.get("scope_type") or "day",
        "scope_id": record.get("scope_id") or "day",
        "day": record.get("day"),
        "stale": stale,
        "status": status,
        "created_at": record.get("created_at"),
        "tool_calls": int(record.get("tool_calls") or 0),
        "task": copy.deepcopy(record.get("task")) or None,
        "teacher_display": copy.deepcopy(record.get("teacher_display")) or {},
        "coverage": {
            "subjects_inspected": len(inspected),
            "subjects_total": len(aliases),
            "uninspected_count": max(0, len(aliases) - len(inspected)),
            "simulation_count": len(simulations),
        },
        "simulations": [
            copy.deepcopy(item.get("public"))
            for item in simulations.values()
            if isinstance(item, dict) and isinstance(item.get("public"), dict)
        ],
        "brief": brief,
        "apply_result": copy.deepcopy(record.get("apply_result"))
        if isinstance(record.get("apply_result"), dict)
        else None,
    }
