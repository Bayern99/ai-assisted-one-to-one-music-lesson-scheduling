"""Read-only decision support for unresolved Step 4 lessons."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.intervention_scope import build_related_intervention_groups
from modules.scheduler.logic.resolution_availability import ResolutionAvailability
from modules.scheduler.logic.schedule_change_policy import instructor_allows_time_change
from modules.scheduler.logic.reservation_classifier import (
    RESERVATION_INTERNAL,
    classify_unresolved_reservations,
)
from modules.shared.time_parser import TimeParser


def _case_id(instructor, day_key):
    digest = hashlib.sha256(f"{instructor}|{day_key}".encode("utf-8")).hexdigest()[:12]
    return f"case-{digest}"


def _clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _issue_advice(
    context,
    issue_id,
    status,
    reason,
    options,
    *,
    time_change_allowed,
    cross_day_options=None,
    rejection_trace=None,
):
    return dict(
        issue_id=issue_id,
        label=context.get("student_name") or context.get("course_code") or issue_id,
        type=context.get("type") or "unknown",
        status=status,
        reason=reason,
        options=options,
        cross_day_options=list(cross_day_options or []),
        time_change_allowed=time_change_allowed,
        rejection_trace=list(rejection_trace or [])[:12],
        placement_group_id=None,
        placement_group_size=None,
        single_room=None,
    )


def _proposal_interval(context):
    start = TimeParser.to_minutes(context.get("original_start"), default=None)
    end = TimeParser.to_minutes(
        context.get("original_end"),
        default=None,
        prefer_end=True,
    )
    proposal = TimeParser.course_proposal_from_occupancy(start, end)
    if proposal is None:
        return None
    return (
        TimeParser.to_minutes(proposal[0], default=None),
        TimeParser.to_minutes(proposal[1], default=None, prefer_end=True),
    )


def _time_bounds(rules):
    time_range = (rules.get("constraints") or {}).get("time_range") or {}
    start = TimeParser.to_minutes(time_range.get("start"), default=8 * 60)
    end = TimeParser.to_minutes(time_range.get("end"), default=23 * 60)
    if start is None or end is None or end <= start:
        return 8 * 60, 23 * 60
    return start, end


def _strict_room_options(
    runtime,
    availability,
    context,
    day,
    start_min,
    end_min,
    *,
    rejection_trace=None,
):
    proposal = TimeParser.course_request_interval(
        f"{_clock(start_min)}-{_clock(end_min)}"
    )
    if proposal is None:
        return [], False
    final_start, final_end = TimeParser.normalize_course_interval(
        f"{_clock(start_min)}-{_clock(end_min)}"
    )
    window_start, window_end = _time_bounds(runtime.normalized_rules)
    if final_start < window_start or final_end > window_end:
        if rejection_trace is not None:
            rejection_trace.append(
                {
                    "code": "outside_time_range",
                    "room": None,
                    "blocker_id": None,
                    "blocker_kind": "canonical_rule",
                    "movable": False,
                }
            )
        return [], True
    instructor_free = availability.teacher_free(
        instructor=context.get("instructor"),
        day=day,
        start=final_start,
        end=final_end,
        date=context.get("original_date"),
    )
    if not instructor_free:
        if rejection_trace is not None:
            rejection_trace.append(
                {
                    "code": "instructor_conflict",
                    "room": None,
                    "blocker_id": None,
                    "blocker_kind": "scheduled_instructor",
                    "movable": False,
                }
            )
        return [], False

    preferred = context.get("preferred_venues") or []
    room_ids = [str(room.get("id")) for room in runtime.rooms_cache if room.get("id")]
    room_ids.sort(key=lambda room: (room not in preferred, room))
    options = []
    for room in room_ids:
        if not availability.room_free(
            room=room,
            day=day,
            start=final_start,
            end=final_end,
            date=context.get("original_date"),
        ):
            if rejection_trace is not None:
                blocker = availability._validator.check_conflict(
                    room,
                    day,
                    final_start,
                    final_end,
                    specific_date=context.get("original_date"),
                )
                blocker_id = str(blocker.get("id") or "") if isinstance(blocker, dict) else ""
                locked = bool(isinstance(blocker, dict) and blocker.get("is_locked_lecture"))
                editable_ids = {
                    str(item.get("id"))
                    for item in runtime.edit_session.get("assignments", []) or []
                    if item.get("id") is not None
                }
                rejection_trace.append(
                    {
                        "code": "locked_lecture" if locked else "room_occupied",
                        "room": room,
                        "blocker_id": blocker_id or None,
                        "blocker_kind": "locked_lecture" if locked else "scheduled_assignment",
                        "movable": bool(blocker_id and blocker_id in editable_ids and not locked),
                    }
                )
            continue
        rules = availability.room_allowed(room, context.get("instrument"))
        if not rules.get("allowed", True):
            if rejection_trace is not None:
                rejection_trace.append(
                    {
                        "code": "room_incompatible",
                        "room": room,
                        "blocker_id": None,
                        "blocker_kind": "room_rule",
                        "movable": False,
                    }
                )
            continue
        options.append(
            {
                "room": room,
                "day": day,
                "start": _clock(start_min),
                "end": _clock(end_min),
                "preferred": room in preferred,
                "time_changed": False,
                "requires_teacher_confirmation": False,
            }
        )
    return options, True


def _cross_day_options(runtime, availability, context, original_day, start, end):
    if context.get("original_date"):
        return []

    window_start, window_end = _time_bounds(runtime.normalized_rules)
    proposal_window_start = ((window_start + 29) // 30) * 30
    proposal_window_end = (window_end // 30) * 30
    duration = end - start
    if proposal_window_end - proposal_window_start < duration:
        return []

    days = sorted(
        (day for day in range(1, 6) if day != original_day),
        key=lambda day: (abs(day - original_day), day),
    )
    candidate_starts = sorted(
        range(proposal_window_start, proposal_window_end - duration + 1, 30),
        key=lambda candidate: (abs(candidate - start), candidate),
    )
    cross_context = {**context, "original_date": None}
    alternatives = []
    for day in days:
        for candidate_start in candidate_starts:
            options, _ = _strict_room_options(
                runtime,
                availability,
                cross_context,
                day,
                candidate_start,
                candidate_start + duration,
            )
            for option in options:
                option["time_changed"] = True
                option["requires_teacher_confirmation"] = True
                alternatives.append(option)
    alternatives.sort(
        key=lambda option: (
            abs(option["day"] - original_day),
            abs(TimeParser.to_minutes(option["start"]) - start),
            not option["preferred"],
            option["day"],
            option["start"],
            option["room"],
        )
    )
    return alternatives[:3]


def _advise_issue(runtime, availability, unresolved):
    context = unresolved_assignment_primitives.build_context(unresolved)
    issue_id = unresolved_assignment_primitives.issue_id(unresolved)
    time_change_allowed = instructor_allows_time_change(runtime.normalized_rules, context.get("instructor"))
    day = context.get("original_day")
    proposal = _proposal_interval(context)
    rejection_trace = []
    if day not in range(7) or proposal is None:
        return _issue_advice(context, issue_id, "blocked", "Missing a usable original day or time.", [],
                             time_change_allowed=time_change_allowed,
                             rejection_trace=rejection_trace)
    start, end = proposal

    original_options, teacher_free = _strict_room_options(
        runtime,
        availability,
        context,
        day,
        start,
        end,
        rejection_trace=rejection_trace,
    )
    if original_options:
        return _issue_advice(
            context,
            issue_id,
            "place_now",
            "Original time is available in a compatible room.",
            original_options[:3],
            time_change_allowed=time_change_allowed,
            rejection_trace=rejection_trace,
        )

    if not time_change_allowed:
        return _issue_advice(
            context,
            issue_id,
            "blocked",
            (
                "Original-time options only are enabled for this instructor; "
                "no compatible room is currently available at that time."
            ),
            [],
            time_change_allowed=False,
            rejection_trace=rejection_trace,
        )

    cross_day_options = _cross_day_options(
        runtime,
        availability,
        context,
        day,
        start,
        end,
    )
    window_start, window_end = _time_bounds(runtime.normalized_rules)
    proposal_window_start = ((window_start + 29) // 30) * 30
    proposal_window_end = (window_end // 30) * 30
    alternatives = []
    candidate_starts = sorted(
        range(proposal_window_start, proposal_window_end - 60 + 1, 30),
        key=lambda candidate: (abs(candidate - start), candidate),
    )
    accepted_distance = None
    for candidate_start in candidate_starts:
        if candidate_start == start:
            continue
        distance = abs(candidate_start - start)
        if len(alternatives) >= 3 and accepted_distance is not None and distance > accepted_distance:
            break
        options, _ = _strict_room_options(
            runtime,
            availability,
            context,
            day,
            candidate_start,
            candidate_start + 60,
            rejection_trace=rejection_trace,
        )
        for option in options:
            option["time_changed"] = True
            option["requires_teacher_confirmation"] = True
            option["shift_minutes"] = candidate_start - start
            alternatives.append(option)
        if alternatives:
            accepted_distance = distance
    alternatives.sort(
        key=lambda option: (
            abs(option["shift_minutes"]),
            not option["preferred"],
            option["start"],
            option["room"],
        )
    )
    if alternatives:
        reason = (
            "Teacher is occupied at the original time; same-day alternatives exist."
            if not teacher_free
            else "No compatible room is free at the original time; same-day alternatives exist."
        )
        return _issue_advice(
            context,
            issue_id,
            "same_day_alternative",
            reason,
            alternatives[:3],
            time_change_allowed=True,
            cross_day_options=cross_day_options,
            rejection_trace=rejection_trace,
        )

    return _issue_advice(
        context,
        issue_id,
        "blocked",
        (
            "Teacher is occupied and no compatible same-day alternative was found; "
            "cross-day alternatives exist."
            if not teacher_free and cross_day_options
            else "No compatible room is available in the same-day search window; "
            "cross-day alternatives exist."
            if cross_day_options
            else (
                "Teacher is occupied and no compatible same-day alternative was found."
                if not teacher_free
                else "No compatible room is available in the same-day search window."
            )
        ),
        [],
        time_change_allowed=True,
        cross_day_options=cross_day_options,
        rejection_trace=rejection_trace,
    )


def _placement_group_id(unresolved):
    return str(unresolved.get("placement_group_id") or "").strip()


def _original_time_rooms(advice):
    return {
        option["room"]
        for option in advice.get("options") or []
        if option.get("room") and not option.get("time_changed")
    }


def _apply_placement_group_policy(items, issue_advice):
    grouped = defaultdict(list)
    for unresolved, advice in zip(items, issue_advice):
        group_id = _placement_group_id(unresolved)
        if not group_id:
            continue
        grouped[group_id].append(advice)

    for group_id, members in grouped.items():
        size = len(members)
        if size < 2:
            members[0]["placement_group_id"] = group_id
            members[0]["placement_group_size"] = size
            continue
        shared_rooms = set.intersection(*(_original_time_rooms(item) for item in members))
        if shared_rooms:
            for advice in members:
                advice["options"] = [
                    option
                    for option in advice.get("options") or []
                    if option.get("room") in shared_rooms and not option.get("time_changed")
                ]
                advice["status"] = "place_now"
                advice["reason"] = (
                    "Original times fit one room for this placement group; "
                    "keep every lesson in the same room."
                )
                advice["cross_day_options"] = []
                advice["placement_group_id"] = group_id
                advice["placement_group_size"] = size
                advice["single_room"] = True
            continue
        for advice in members:
            advice["status"] = "blocked"
            advice["options"] = []
            advice["cross_day_options"] = []
            advice["reason"] = (
                "No single-room placement for this instructor-day group; "
                "assigning separate rooms would split the group."
            )
            advice["placement_group_id"] = group_id
            advice["placement_group_size"] = size
            advice["single_room"] = False


def _reservation_internal_issue_ids(runtime):
    labels = classify_unresolved_reservations(
        list(runtime.edit_session.get("assignments") or []),
        list(runtime.edit_session.get("unassigned_lessons") or []),
    )
    parked = set()
    for item in runtime.edit_session.get("unassigned_lessons") or []:
        if not isinstance(item, dict):
            continue
        payload = labels.get(str(item.get("id") or "")) or {}
        if str(payload.get("label") or "") != RESERVATION_INTERNAL:
            continue
        parked.add(unresolved_assignment_primitives.issue_id(item))
    return parked


def _group_cases(runtime):
    parked = _reservation_internal_issue_ids(runtime)
    unresolved = [
        item
        for item in (runtime.edit_session.get("unassigned_lessons", []) or [])
        if unresolved_assignment_primitives.issue_id(item) not in parked
    ]
    grouped = defaultdict(list)
    contexts = {}
    for item in unresolved:
        context = unresolved_assignment_primitives.build_context(item)
        day_key = context.get("original_date") or context.get("original_day")
        key = (context.get("instructor") or "Unknown instructor", str(day_key))
        grouped[key].append(item)
        contexts[key] = context
    return unresolved, grouped, contexts


def resolution_case_ids(runtime):
    _unresolved, grouped, _contexts = _group_cases(runtime)
    return {_case_id(instructor, day_key) for instructor, day_key in grouped}


def build_resolution_advice(runtime):
    from modules.scheduler.logic.piano_leverage import build_piano_leverage_proposals

    unresolved, grouped, contexts = _group_cases(runtime)
    waiting = runtime.edit_session.get("resolution_waiting", {}) or {}
    availability = ResolutionAvailability(runtime)

    cases = []
    summary = {"total": len(unresolved), "cases": len(grouped), "place_now": 0,
               "same_day_alternative": 0, "blocked": 0, "waiting": 0}
    for (instructor, day_key), items in sorted(grouped.items()):
        case_id = _case_id(instructor, day_key)
        issue_advice = [_advise_issue(runtime, availability, item) for item in items]
        _apply_placement_group_policy(items, issue_advice)
        for item in issue_advice:
            summary[item["status"]] += 1
        waiting_entry = waiting.get(case_id) if isinstance(waiting, dict) else None
        is_waiting = isinstance(waiting_entry, dict) and waiting_entry.get("status") == "waiting"
        if is_waiting:
            summary["waiting"] += 1
        context = contexts[(instructor, day_key)]
        cases.append(
            {
                "id": case_id,
                "instructor": instructor,
                "day": context.get("original_day"),
                "date": context.get("original_date"),
                "waiting": is_waiting,
                "waiting_note": (waiting_entry or {}).get("note", ""),
                "issues": issue_advice,
            }
        )
    cases.sort(
        key=lambda case: (
            case["waiting"],
            -sum(item["status"] == "place_now" for item in case["issues"]),
            case["instructor"],
            case["date"] or str(case["day"]),
        )
    )
    return {
        "summary": summary,
        "cases": cases,
        "intervention_groups": build_related_intervention_groups(cases),
        "piano_leverage": build_piano_leverage_proposals(runtime),
    }
