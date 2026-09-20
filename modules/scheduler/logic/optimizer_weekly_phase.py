"""Weekly orchestration helpers extracted from optimizer.py.

Coordinate already-normalized weekly placement groups. A group is assigned
only when one room can take every placeable lesson; otherwise the whole group
is handed to Resolve. Cross-room path search and greedy partial fills are not
weekly placement.
"""

from modules.scheduler.logic.rules_schema import DEFAULT_INSTRUCTOR_PRIORITY

NO_SINGLE_ROOM_FOR_GROUP = "no_single_room_for_group"
NO_SINGLE_ROOM_FOR_GROUP_MESSAGE = (
    "No single-room placement for this instructor-day group"
)


def _is_protected_lesson(lesson):
    return bool(
        lesson.get("pinned") or lesson.get("locked") or lesson.get("committed")
    )


def _block_priority(block, instructor_priority, normalize_instrument_type):
    inst_type = "Instrumental"
    if block.get("lessons"):
        inst_type = normalize_instrument_type(block["lessons"][0].get("instrument", ""))

    inst_score = 1
    if inst_type in ["Piano", "Voice"]:
        inst_score = 3
    elif inst_type == "Percussion":
        inst_score = 2

    priority_score = instructor_priority.get(
        block.get("inst"),
        DEFAULT_INSTRUCTOR_PRIORITY,
    )
    return (inst_score, priority_score, block.get("duration", 0))


def schedule_weekly_blocks(
    blocks,
    room_ids,
    instructor_priority,
    normalize_instrument_type,
    can_assign,
    score_room,
    create_assignment,
    classify_unassigned_reason,
    append_unassigned,
):
    logs = [f"📦 Phase 1: Scheduling {len(blocks)} Weekly Blocks..."]
    ordered_blocks = sorted(
        blocks,
        key=lambda block: _block_priority(block, instructor_priority, normalize_instrument_type),
        reverse=True,
    )

    for block in ordered_blocks:
        inst = block["inst"]
        day = block["day"]
        lessons = block["lessons"]
        placeable = [lesson for lesson in lessons if not _is_protected_lesson(lesson)]
        if not placeable:
            continue
        block_candidates = []

        for room_id in room_ids:
            possible = True
            aggregate_score = 0
            for lesson in placeable:
                if not can_assign(room_id, day, lesson["start"], lesson["end"]):
                    possible = False
                    break
                score = score_room(room_id, lesson)
                if score < 0:
                    possible = False
                    break
                aggregate_score += score

            if possible:
                aggregate_score += 100
                block_candidates.append((aggregate_score, room_id))

        if block_candidates:
            block_candidates.sort(key=lambda item: item[0], reverse=True)
            best_room = block_candidates[0][1]
            for lesson in placeable:
                create_assignment(lesson, best_room)
            continue

        group_id = f"weekly-group:{inst}:{day}:{placeable[0].get('id', 'block')}"
        logs.append(
            f"    ⚠️ No single-room placement: {inst} (Day {day}); "
            f"handing {len(placeable)} lessons to Resolve."
        )
        for lesson in placeable:
            reason_code, reason = classify_unassigned_reason(lesson)
            # Group handoff replaces only the generic feasibility fallback; keep
            # precise structural codes (window, prefs, room type, locks).
            if reason_code == "no_time_feasible_room":
                reason_code = NO_SINGLE_ROOM_FOR_GROUP
                reason = NO_SINGLE_ROOM_FOR_GROUP_MESSAGE
            payload = dict(lesson)
            payload["placement_group_id"] = group_id
            payload["placement_group_size"] = len(placeable)
            append_unassigned(payload, reason, reason_code)

    return logs
