"""Preview high-ROI Piano block moves without mutating the Step 4 draft."""

from __future__ import annotations

import copy
import hashlib

from modules.scheduler.logic import (
    manual_override_primitives,
    unresolved_assignment_primitives,
)
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.instructor_time_integrity import instructor_is_available
from modules.scheduler.logic.schedule_change_policy import instructor_allows_time_change
from modules.scheduler.logic.teacher_day_package import (
    build_teacher_day_package,
    validate_teacher_day_placement,
)
from modules.scheduler.logic.validation_authority import build_occupancy_assignments
from modules.shared.time_parser import TimeParser


TARGET_ROOM = "R101"
MAX_PACKAGE_GAP_MINUTES = 60
WORKING_DAYS = range(1, 6)


def _occupying_assignments(runtime):
    return build_occupancy_assignments(
        runtime.locked_context_assignments,
        runtime.edit_session.get("assignments", []) or [],
    )


def _clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def _event_info(event):
    if event.get("type") == "studio_class":
        return None
    props = event.get("extendedProps") or {}
    instructor = str(props.get("Instructor") or "").strip()
    days = event.get("daysOfWeek") or []
    start, end = TimeParser.event_to_minute_range(event, default=None)
    instrument = manual_override_primitives.resolve_slot_instrument(event)
    if (
        not instructor
        or len(days) != 1
        or days[0] not in range(7)
        or start is None
        or end is None
        or end <= start
        or "piano" not in str(instrument).lower()
    ):
        return None
    return {"event": event, "instructor": instructor, "day": days[0],
            "start": start, "end": end}


def _piano_blocks(assignments):
    grouped = {}
    for event in assignments:
        info = _event_info(event)
        if info:
            grouped.setdefault((info["instructor"], info["day"]), []).append(info)
    blocks = []
    for items in grouped.values():
        items.sort(key=lambda item: (item["start"], item["end"], item["event"]["id"]))
        current = []
        for item in items:
            if current and item["start"] - current[-1]["end"] > MAX_PACKAGE_GAP_MINUTES:
                blocks.append(current)
                current = []
            current.append(item)
        if current:
            blocks.append(current)
    return [block for block in blocks if len(block) >= 2]


def _bounds(rules):
    values = (rules.get("constraints") or {}).get("time_range") or {}
    start = TimeParser.to_minutes(values.get("start"), default=8 * 60)
    end = TimeParser.to_minutes(values.get("end"), default=23 * 60)
    return start, end


def _candidate_targets(source_day, source_start, span, rules):
    lower, upper = _bounds(rules)
    lower = ((lower + 29) // 30) * 30
    upper = (upper // 30) * 30
    days = sorted(
        (day for day in WORKING_DAYS if day != source_day),
        key=lambda day: (abs(day - source_day), day < source_day, day),
    )
    starts = sorted(
        range(lower, upper - span + 1, 30),
        key=lambda start: (abs(start - source_start), start < source_start, start),
    )
    for day in days:
        for start in starts:
            yield day, start


def _place_block(runtime, block, day, target_start, remaining):
    source_start = min(item["start"] for item in block)
    placed = []
    validator = ConflictValidator(
        {
            "assignments": remaining,
            "lectures": runtime.booked_lectures,
            "rooms": runtime.rooms_cache,
            "rules": runtime.normalized_rules,
        }
    )
    for item in block:
        start = target_start + item["start"] - source_start
        end = target_start + item["end"] - source_start
        interval = TimeParser.canonical_course_occupancy(start, end)
        if interval is None:
            return None
        start, end = interval
        if not instructor_is_available(
            remaining + placed,
            instructor=item["instructor"],
            day=day,
            start_min=start,
            end_min=end,
        ):
            return None
        if validator.check_conflict(TARGET_ROOM, day, start, end):
            return None
        rules_check = validator.validate_rules(
            TARGET_ROOM,
            manual_override_primitives.resolve_slot_instrument(item["event"]),
        )
        if not rules_check.get("allowed", True):
            return None
        moved = copy.deepcopy(item["event"])
        manual_override_primitives.apply_move(
            moved, TARGET_ROOM, day, _clock(start), _clock(end)
        )
        placed.append(moved)
        validator.assignments = remaining + placed
    return placed


def _fill_released_slots(runtime, block, placed, remaining):
    freed = [
        {
            "room": item["event"].get("resourceId"),
            "day": item["day"],
            "start": item["start"],
            "end": item["end"],
        }
        for item in block
    ]
    working = remaining + placed
    validator = ConflictValidator(
        {
            "assignments": working,
            "lectures": runtime.booked_lectures,
            "rooms": runtime.rooms_cache,
            "rules": runtime.normalized_rules,
        }
    )
    fills = []
    for unresolved in runtime.edit_session.get("unassigned_lessons", []):
        context = unresolved_assignment_primitives.build_context(unresolved)
        start = TimeParser.to_minutes(context.get("original_start"), default=None)
        end = TimeParser.to_minutes(
            context.get("original_end"),
            default=None,
            prefer_end=True,
        )
        interval = TimeParser.canonical_course_occupancy(start, end)
        if (
            context.get("type") == "studio_class"
            or "piano" not in str(context.get("instrument") or "").lower()
            or context.get("original_day") not in range(7)
            or interval is None
        ):
            continue
        start, end = interval
        candidates = [
            slot for slot in freed
            if slot["day"] == context["original_day"]
            and slot["start"] <= start
            and slot["end"] >= end
        ]
        preferred = context.get("preferred_venues") or []
        candidates.sort(key=lambda slot: (slot["room"] not in preferred, slot["room"]))
        for slot in candidates:
            if not instructor_is_available(
                working,
                instructor=context.get("instructor"),
                day=slot["day"],
                start_min=start,
                end_min=end,
            ):
                continue
            result = unresolved_assignment_primitives.validate(
                validator,
                unresolved,
                slot["room"],
                slot["day"],
                _clock(start + 30 if end - start == 120 else start),
                _clock(end - 30 if end - start == 120 else end),
            )
            if not result.get("success") or result.get("warnings"):
                continue
            fills.append(
                {
                    "issue_id": unresolved_assignment_primitives.issue_id(unresolved),
                    "label": context.get("student_name") or context.get("course_code") or "Piano lesson",
                    "instructor": context.get("instructor") or "Unknown instructor",
                    "room": slot["room"],
                    "day": slot["day"],
                    "start": _clock(start),
                    "end": _clock(end),
                }
            )
            working.append(result["assignment"])
            validator.assignments = working
            break
    return fills


def _proposal(runtime, block):
    package_ids = {str(item["event"].get("id")) for item in block}
    all_assignments = _occupying_assignments(runtime)
    remaining = [item for item in all_assignments if str(item.get("id")) not in package_ids]
    source_start = min(item["start"] for item in block)
    source_end = max(item["end"] for item in block)
    for day, target_start in _candidate_targets(
        block[0]["day"], source_start, source_end - source_start, runtime.normalized_rules
    ):
        placed = _place_block(runtime, block, day, target_start, remaining)
        if not placed:
            continue
        package = build_teacher_day_package([item["event"] for item in block])
        package_result = validate_teacher_day_placement(
            package,
            [
                {
                    "event_id": item["event"].get("id"),
                    "day": TimeParser.event_primary_js_day(moved, default=None),
                    "start": TimeParser.event_clock_pair(moved)[0],
                    "end": TimeParser.event_clock_pair(moved)[1],
                    "room": moved.get("resourceId"),
                }
                for item, moved in zip(block, placed)
            ],
        )
        if not package_result["valid"]:
            continue
        fills = _fill_released_slots(runtime, block, placed, remaining)
        if not fills:
            return None
        moves = []
        for item, moved in zip(block, placed):
            target_times = TimeParser.event_to_minute_range(moved, default=None)
            moves.append(
                {
                    "assignment_id": str(item["event"].get("id")),
                    "label": str(item["event"].get("title") or item["event"].get("id")),
                    "from_room": str(item["event"].get("resourceId") or ""),
                    "from_day": item["day"],
                    "from_start": _clock(item["start"]),
                    "from_end": _clock(item["end"]),
                    "to_room": TARGET_ROOM,
                    "to_day": day,
                    "to_start": _clock(target_times[0]),
                    "to_end": _clock(target_times[1]),
                }
            )
        identity = "|".join(move["assignment_id"] for move in moves) + f"|{day}|{target_start}"
        return {
            "id": "piano-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
            "instructor": block[0]["instructor"],
            "target_room": TARGET_ROOM,
            "target_day": day,
            "target_start": _clock(target_start),
            "target_end": _clock(target_start + source_end - source_start),
            "gain": len(fills),
            "moves": moves,
            "fills": fills,
        }
    return None


def _block_clears_source_day(runtime, block):
    instructor = block[0]["instructor"]
    source_day = block[0]["day"]
    package_ids = {str(item["event"].get("id")) for item in block}
    assignments = _occupying_assignments(runtime)
    for event in assignments:
        props = event.get("extendedProps") or {}
        if str(props.get("Instructor") or "").strip() != instructor:
            continue
        specific_date = TimeParser.event_specific_date(event)
        days = (
            [TimeParser.to_js_weekday(specific_date, default=None)]
            if specific_date
            else event.get("daysOfWeek", [])
        )
        if source_day in days and str(event.get("id")) not in package_ids:
            return False
    return True


def build_piano_leverage_proposals(runtime):
    room_ids = {str(room.get("id")) for room in runtime.rooms_cache if room.get("id")}
    if TARGET_ROOM not in room_ids:
        return []
    # ponytail: bounded exhaustive search; keep only one best placement per Piano block.
    proposals = [
        proposal
        for block in _piano_blocks(runtime.edit_session.get("assignments", []))
        if instructor_allows_time_change(
            runtime.normalized_rules,
            block[0]["instructor"],
        )
        if _block_clears_source_day(runtime, block)
        if (proposal := _proposal(runtime, block)) is not None
    ]
    return sorted(proposals, key=lambda item: (-item["gain"], len(item["moves"]), item["id"]))[:12]
