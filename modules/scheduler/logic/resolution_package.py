"""Atomic in-memory application for Step 4 reconciliation packages.

The generic final-state executor in this module is deliberately shared by
investigation simulation and canonical apply.  Piano leverage remains a
specialised proposal generator, but it uses the same rollback boundary.
"""

import copy
import hashlib
import json
from collections import Counter

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.validation_authority import build_occupancy_assignments
from modules.scheduler.logic.schedule_change_policy import (
    attach_teacher_confirmation,
    context_time_changed,
    event_time_changed,
    instructor_time_change_status,
)
from modules.shared.time_parser import TimeParser


class PackageRejected(Exception):
    pass


PACKAGE_METRIC_KEYS = (
    "resolved_delta",
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


def _clock(value, *, prefer_end=False):
    return TimeParser.normalize_clock(value, prefer_end=prefer_end)


def normalize_package_changes(changes):
    """Normalize declarative final-state targets and reject ambiguous input."""
    if not isinstance(changes, list) or not changes:
        raise PackageRejected("A reconciliation package must contain at least one change.")
    normalized = []
    seen = set()
    for raw in changes:
        if not isinstance(raw, dict):
            raise PackageRejected("Each reconciliation change must be an object.")
        subject = (
            raw.get("subject_alias")
            or raw.get("subject_id")
            or raw.get("assignment_id")
            or raw.get("issue_id")
        )
        subject = str(subject or "").strip()
        if not subject:
            raise PackageRejected("Each reconciliation change needs a subject alias.")
        if subject in seen:
            raise PackageRejected(f"Subject {subject} appears more than once in the package.")
        seen.add(subject)
        if raw.get("withdraw"):
            if raw.get("target") or raw.get("room") or raw.get("start") or raw.get("end"):
                raise PackageRejected(f"Subject {subject} cannot both withdraw and move.")
            normalized.append({"subject_alias": subject, "withdraw": True})
            continue
        target = raw.get("target") if isinstance(raw.get("target"), dict) else raw
        room = str(target.get("room") or target.get("resourceId") or "").strip()
        day = target.get("day")
        if isinstance(day, bool):
            raise PackageRejected(f"Invalid day for subject {subject}.")
        try:
            day = int(day)
        except (TypeError, ValueError) as exc:
            raise PackageRejected(f"Invalid day for subject {subject}.") from exc
        if day not in range(7):
            raise PackageRejected(f"Day must be between 0 and 6 for subject {subject}.")
        start = _clock(target.get("start") or target.get("startTime"))
        end = _clock(target.get("end") or target.get("endTime"), prefer_end=True)
        if not room or not start or not end:
            raise PackageRejected(f"Subject {subject} has an incomplete placement target.")
        start_min = TimeParser.to_minutes(start, default=None)
        end_min = TimeParser.to_minutes(end, default=None)
        if start_min is None or end_min is None or end_min <= start_min:
            raise PackageRejected(f"Subject {subject} has an invalid time range.")
        normalized.append(
            {
                "subject_alias": subject,
                "target": {
                    "room": room,
                    "day": day,
                    "start": start,
                    "end": end,
                },
            }
        )
    return sorted(normalized, key=lambda item: item["subject_alias"])


def package_hash(changes):
    normalized = normalize_package_changes(changes)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def confirmation_key(teacher, package_hash_value, workspace_version):
    payload = f"{str(teacher or '').strip().casefold()}|{package_hash_value}|{workspace_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _teacher_for_assignment(slot):
    props = slot.get("extendedProps") if isinstance(slot.get("extendedProps"), dict) else {}
    return str(props.get("Instructor") or slot.get("instructor") or "").strip()


def _placement_for_assignment(slot):
    day = TimeParser.event_primary_js_day(slot, default=None)
    start, end = TimeParser.event_clock_pair(slot, default=(None, None))
    return {
        "room": str(slot.get("resourceId") or slot.get("room_id") or "").strip(),
        "day": day,
        "start": start,
        "end": end,
    }


def _placement_for_issue(issue):
    context = unresolved_assignment_primitives.build_context(issue)
    return {
        "room": None,
        "day": context.get("original_day"),
        "start": context.get("original_start"),
        "end": context.get("original_end"),
    }


def _minutes(value):
    return TimeParser.to_minutes(value, default=None)


def _shift_minutes(before, target):
    if not before or before.get("day") not in range(7):
        return 0
    before_start = _minutes(before.get("start"))
    target_start = _minutes(target.get("start"))
    if before_start is None or target_start is None:
        return 0
    return abs((target["day"] - before["day"]) * 24 * 60 + target_start - before_start)


def _history_time_change_counts(history):
    counts = Counter()
    for record in history or []:
        if not isinstance(record, dict):
            continue
        if record.get("action") == "compound":
            nested = _history_time_change_counts(record.get("records"))
            counts.update(nested)
            continue
        previous = record.get("prev_state") if isinstance(record.get("prev_state"), dict) else {}
        current = record.get("new_state") if isinstance(record.get("new_state"), dict) else {}
        teacher = _teacher_for_assignment(current or previous)
        before = _placement_for_assignment(previous)
        after = _placement_for_assignment(current)
        if teacher and before.get("day") in range(7) and after.get("day") in range(7):
            if any(before.get(key) != after.get(key) for key in ("day", "start", "end")):
                counts[teacher.casefold()] += 1
    return counts


def _resolve_subject(controller, subject):
    subject = str(subject or "").strip()
    slot = controller._find_slot(controller._assignments, subject)
    if slot:
        return "assignment", slot
    unresolved = controller._find_unresolved(subject)
    if unresolved:
        return "issue", unresolved
    for candidate in controller._unassigned_lessons:
        if unresolved_assignment_primitives.source_request_id(candidate) == subject:
            return "issue", candidate
    raise PackageRejected(f"Subject {subject} is no longer present in the Step 4 snapshot.")


def _metric_template():
    return {key: 0 for key in PACKAGE_METRIC_KEYS}


def _teacher_day_rooms(assignments):
    """Map (instructor, day) to the rooms that instructor-day currently uses."""
    rooms = {}
    for event in assignments or []:
        teacher = _teacher_for_assignment(event).casefold()
        day = TimeParser.event_primary_js_day(event, default=None)
        room = str(event.get("resourceId") or event.get("room_id") or "").strip()
        if not teacher or day not in range(7) or not room:
            continue
        rooms.setdefault((teacher, day), set()).add(room)
    return rooms


def evaluate_reconciliation_package(
    controller,
    changes,
    *,
    confirmed_teachers=(),
    commit=False,
    keep_state=False,
    authorized_sacrifice_subject_ids=(),
):
    """Validate a complete final-state package against the controller.

    ``commit=False`` restores the controller unless ``keep_state`` is set; the
    caller then owns the mutated controller (used to compute post-state
    candidates). ``commit=True`` leaves the validated state in memory for the
    Step 4 command boundary to persist.

    Invalid package input is reported as an ``infeasible`` result instead of
    raising, so simulation and apply share one reviewable failure path.
    """
    state = {"step4_edit_session": controller.edit_session}
    snapshot = controller._snapshot_mutation_state(state)
    confirmed = {str(item or "").strip().casefold() for item in confirmed_teachers}
    authorized_sacrifices = {
        str(item or "").strip() for item in authorized_sacrifice_subject_ids
    }
    metrics = _metric_template()
    required = {}
    warnings = []
    records = []
    withdrawn_subject_ids = []
    affected_teachers = set()
    baseline_unresolved = len(controller._unassigned_lessons)
    assignment_originals = {}
    issue_originals = {}
    split_teacher_days = []
    try:
        normalized = normalize_package_changes(changes)
        resolved = []
        for change in normalized:
            kind, subject = _resolve_subject(controller, change["subject_alias"])
            if change.get("withdraw") and kind != "assignment":
                raise PackageRejected(
                    f"Subject {change['subject_alias']} is not an assigned lesson and cannot be withdrawn."
                )
            resolved.append((change, kind, subject))
            if kind == "assignment":
                assignment_originals[str(subject.get("id"))] = copy.deepcopy(subject)
            else:
                issue_originals[change["subject_alias"]] = copy.deepcopy(subject)

        withdraws = [item for item in resolved if item[0].get("withdraw")]
        others = [item for item in resolved if not item[0].get("withdraw")]
        withdrawn_ids = {str(subject.get("id")) for _change, _kind, subject in withdraws}
        touched_assignment_ids = {
            str(subject.get("id"))
            for _change, kind, subject in others
            if kind == "assignment"
        } - withdrawn_ids
        controller._assignments = [
            item for item in controller._assignments
            if str(item.get("id")) not in touched_assignment_ids
        ]
        controller._sync_validator_state()

        for change, _kind, subject in withdraws:
            teacher = _teacher_for_assignment(subject)
            before = _placement_for_assignment(subject)
            new_state = controller._apply_unassign(
                controller._assignments,
                controller._unassigned_lessons,
                subject,
            )
            controller._sync_validator_state()
            records.append({
                "action": "unassign",
                "slot_id": str(subject.get("id")),
                "prev_state": assignment_originals[str(subject.get("id"))],
                "new_state": copy.deepcopy(new_state),
                "teacher": teacher,
                "time_changed": False,
            })
            withdrawn_subject_ids.append(str(subject.get("id")))
            metrics["sacrificed_assignments"] += 1
            affected_teachers.add(teacher)
            warnings.append(
                "This package leaves an already scheduled lesson unresolved and needs explicit sacrifice authorization."
            )

        for change, kind, subject in others:
            target = change["target"]
            if kind == "assignment":
                original = assignment_originals[str(subject.get("id"))]
                teacher = _teacher_for_assignment(original)
                before = _placement_for_assignment(original)
                validation = controller._validate_move(
                    original,
                    target["room"],
                    target["day"],
                    target["start"],
                    target["end"],
                    teacher_confirmed=True,
                )
                changed = event_time_changed(
                    original,
                    day=target["day"],
                    start=target["start"],
                    end=target["end"],
                )
                if changed:
                    status = instructor_time_change_status(controller.normalized_rules, teacher)
                    if status != "ask_allowed":
                        raise PackageRejected(
                            f"Teacher {teacher or 'unknown'} is not in the explicit time-change proposal pool."
                        )
                    required.setdefault(teacher, confirmation_key(teacher, package_hash(normalized), ""))
                if not validation.get("success"):
                    raise PackageRejected(validation.get("message") or "Assignment move failed validation.")
                current = copy.deepcopy(original)
                controller._apply_move(
                    current,
                    target["room"],
                    target["day"],
                    validation["start_norm"],
                    validation["end_norm"],
                    validation.get("specific_date"),
                )
                controller._assignments.append(current)
                controller._sync_validator_state()
                records.append({
                    "action": "move",
                    "slot_id": str(original.get("id")),
                    "prev_state": original,
                    "new_state": copy.deepcopy(current),
                    "teacher": teacher,
                    "time_changed": bool(changed),
                })
                if changed and teacher.casefold() not in confirmed:
                    warnings.append(f"Teacher confirmation required for {teacher or 'this teacher'}.")
                if changed:
                    metrics["time_changed_assignments"] += 1
                    metrics["total_shift_minutes"] += _shift_minutes(before, target)
                    affected_teachers.add(teacher)
                if before.get("room") != target["room"]:
                    metrics["room_switches"] += 1
                metrics["moved_assignments"] += 1
                preferred = (controller.normalized_rules.get("instructor_preferred_rooms", {}) or {}).get(teacher, [])
                if preferred and target["room"] not in preferred:
                    metrics["non_preferred_placements"] += 1
            else:
                original = issue_originals[change["subject_alias"]]
                context = unresolved_assignment_primitives.build_context(original)
                teacher = str(context.get("instructor") or "").strip()
                before = _placement_for_issue(original)
                changed = context_time_changed(
                    context,
                    day=target["day"],
                    start=target["start"],
                    end=target["end"],
                )
                if changed:
                    status = instructor_time_change_status(controller.normalized_rules, teacher)
                    if status != "ask_allowed":
                        raise PackageRejected(
                            f"Teacher {teacher or 'unknown'} is not in the explicit time-change proposal pool."
                        )
                    required.setdefault(teacher, confirmation_key(teacher, package_hash(normalized), ""))
                validation = controller.validate_assignment(
                    unresolved_assignment_primitives.issue_id(original),
                    target["room"],
                    target["day"],
                    target["start"],
                    target["end"],
                    teacher_confirmed=True,
                )
                if not validation.get("success"):
                    raise PackageRejected(validation.get("message") or "Assignment target failed validation.")
                record = unresolved_assignment_primitives.apply(
                    controller._assignments,
                    controller._unassigned_lessons,
                    controller._find_unresolved(unresolved_assignment_primitives.issue_id(original)),
                    validation["assignment"],
                )
                record["teacher"] = teacher
                record["time_changed"] = bool(changed)
                records.append(record)
                controller._sync_validator_state()
                affected_teachers.add(teacher)
                if changed:
                    metrics["time_changed_assignments"] += 1
                    metrics["total_shift_minutes"] += _shift_minutes(before, target)
                if changed and teacher.casefold() not in confirmed:
                    warnings.append(f"Teacher confirmation required for {teacher or 'this teacher'}.")
                preferred = (controller.normalized_rules.get("instructor_preferred_rooms", {}) or {}).get(teacher, [])
                if preferred and target["room"] not in preferred:
                    metrics["non_preferred_placements"] += 1

        metrics["resolved_delta"] = baseline_unresolved - len(controller._unassigned_lessons)
        metrics["remaining_unresolved"] = len(controller._unassigned_lessons)
        metrics["affected_instructor_count"] = len({item.casefold() for item in affected_teachers if item})
        metrics["required_confirmation_count"] = len(required)
        prior_changes = _history_time_change_counts(controller.edit_session.get("history"))
        metrics["repeat_time_change_burden"] = sum(
            max(0, prior_changes[teacher.casefold()] - 0)
            for teacher in affected_teachers
            if teacher and teacher.casefold() in prior_changes
        )
        metrics["hard_conflict_count"] = 0
        rooms_before = _teacher_day_rooms(
            build_occupancy_assignments(
                controller.locked_context_assignments,
                snapshot["assignments"],
            )
        )
        rooms_after = _teacher_day_rooms(
            build_occupancy_assignments(
                controller.locked_context_assignments,
                controller._assignments,
            )
        )
        for key, after_rooms in rooms_after.items():
            before_rooms = rooms_before.get(key, set())
            if len(after_rooms) < 2 or len(after_rooms) <= len(before_rooms):
                continue
            teacher_key, day = key
            split_teacher_days.append(
                {
                    "teacher_key": teacher_key,
                    "day": day,
                    "rooms": sorted(after_rooms),
                }
            )
        split_teacher_days.sort(key=lambda item: (item["day"], item["teacher_key"]))
        metrics["teacher_day_splits"] = len(split_teacher_days)
        required_teachers = {teacher.casefold() for teacher in required}
        unauthorized_sacrifices = [
            subject_id for subject_id in withdrawn_subject_ids
            if subject_id not in authorized_sacrifices
        ]
        needs_sacrifice_authorization = bool(unauthorized_sacrifices)
        status = "feasible"
        if required and not required_teachers <= confirmed:
            status = "conditional"
        if needs_sacrifice_authorization:
            status = "conditional"
        if commit and required and not required_teachers <= confirmed:
            raise PackageRejected("Every affected teacher must confirm the exact reconciliation package before apply.")
        if commit and needs_sacrifice_authorization:
            raise PackageRejected(
                "This package leaves an already scheduled lesson unresolved; "
                "the listed sacrifice needs its own authorization before apply."
            )
        result = {
            "status": status,
            "feasible": status in {"feasible", "conditional"},
            "normalized_changes": copy.deepcopy(normalized),
            "package_hash": package_hash(normalized),
            "metrics": metrics,
            "required_teacher_confirmations": [
                {"teacher": teacher, "confirmation_id": value}
                for teacher, value in sorted(required.items(), key=lambda item: item[0].casefold())
            ],
            "warnings": sorted(set(warnings)),
            "failure_codes": [],
            "records": records,
            "withdrawn_subject_ids": list(withdrawn_subject_ids),
            "requires_sacrifice_authorization": needs_sacrifice_authorization,
            "unauthorized_sacrifice_subject_ids": unauthorized_sacrifices,
            "split_teacher_days": split_teacher_days,
        }
        if not commit and not keep_state:
            controller._restore_mutation_state(state, snapshot)
        return result
    except Exception as exc:
        controller._restore_mutation_state(state, snapshot)
        if isinstance(exc, PackageRejected):
            return {
                "status": "infeasible",
                "feasible": False,
                "normalized_changes": [],
                "package_hash": None,
                "metrics": {**metrics, "remaining_unresolved": baseline_unresolved, "hard_conflict_count": 1},
                "required_teacher_confirmations": [],
                "warnings": [],
                "failure_codes": [str(exc)],
                "records": [],
                "withdrawn_subject_ids": [],
                "requires_sacrifice_authorization": False,
                "unauthorized_sacrifice_subject_ids": [],
                "split_teacher_days": [],
            }
        raise


def apply_reconciliation_package(
    controller,
    state,
    changes,
    *,
    confirmed_teachers=(),
    decision_note="",
    authorized_sacrifice_subject_ids=(),
):
    result = evaluate_reconciliation_package(
        controller,
        changes,
        confirmed_teachers=confirmed_teachers,
        commit=True,
        authorized_sacrifice_subject_ids=authorized_sacrifice_subject_ids,
    )
    if not result["feasible"] or result["status"] != "feasible":
        controller._sync_validator_state()
        return result
    return result


def apply_piano_leverage_package(controller, proposal, *, confirmation_note=""):
    records = []
    for move in proposal.get("moves", []):
        slot = controller._find_slot(controller._assignments, move["assignment_id"])
        if not slot:
            raise PackageRejected(f"Assignment {move['assignment_id']} no longer exists.")
        validation = controller._validate_move(
            slot,
            move["to_room"],
            move["to_day"],
            move["to_start"],
            move["to_end"],
            teacher_confirmed=True,
        )
        if not validation.get("success") or validation.get("warnings"):
            raise PackageRejected(
                validation.get("message") or "Piano block move no longer passes validation."
            )
        previous = copy.deepcopy(slot)
        new_state = controller._apply_move(
            slot,
            move["to_room"],
            move["to_day"],
            validation["start_norm"],
            validation["end_norm"],
            validation.get("specific_date"),
        )
        props = slot.get("extendedProps") or {}
        attach_teacher_confirmation(
            slot,
            instructor=props.get("Instructor") or slot.get("instructor"),
            note=confirmation_note,
        )
        new_state = copy.deepcopy(slot)
        records.append(
            {
                "action": "move",
                "slot_id": move["assignment_id"],
                "prev_state": previous,
                "new_state": new_state,
            }
        )
        controller._sync_validator_state()

    for fill in proposal.get("fills", []):
        unresolved = controller._find_unresolved(fill["issue_id"])
        if not unresolved:
            raise PackageRejected(f"Issue {fill['issue_id']} no longer exists.")
        validation = controller.validate_assignment(
            fill["issue_id"],
            fill["room"],
            fill["day"],
            fill["start"],
            fill["end"],
        )
        if not validation.get("success") or validation.get("warnings"):
            raise PackageRejected(
                validation.get("message") or "Released slot no longer passes validation."
            )
        records.append(
            unresolved_assignment_primitives.apply(
                controller._assignments,
                controller._unassigned_lessons,
                unresolved,
                validation["assignment"],
            )
        )
        controller._sync_validator_state()
    return records
