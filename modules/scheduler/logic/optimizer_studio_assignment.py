"""Studio assignment orchestration helpers extracted from optimizer.py.

These helpers coordinate already-normalized studio requests without redefining
room scoring or relocation policy.
"""

from modules.scheduler.logic.optimizer_diagnostics import (
    build_room_occupant_line,
    build_studio_failure_header,
    build_studio_saturation_intro,
    build_studio_summary_line,
)
from modules.scheduler.logic.rules_schema import DEFAULT_INSTRUCTOR_PRIORITY


def assign_studio_requests(
    requests,
    room_ids,
    instructor_priority,
    merge_requests,
    can_assign,
    score_room,
    resolve_preferred_room_conflict,
    append_assignment,
    append_unassigned,
    build_failure_reason,
    describe_room_occupant,
):
    def sort_key(request):
        priority = instructor_priority.get(
            request["inst"],
            DEFAULT_INSTRUCTOR_PRIORITY,
        )
        return (request["date"], -priority, request["start"])

    ordered_requests = sorted(requests, key=sort_key)
    merged_requests = merge_requests(ordered_requests)
    logs = []
    success_count = 0

    for request in merged_requests:
        candidates = []

        if request["prefs"]:
            preferred_room_id = next(
                (
                    room_id
                    for room_id in request["prefs"]
                    if room_id in room_ids and score_room(room_id, request) > 0
                ),
                None,
            )
            if preferred_room_id is not None:
                if not can_assign(preferred_room_id, request):
                    resolve_preferred_room_conflict(preferred_room_id, request)
                if can_assign(preferred_room_id, request):
                    append_assignment(request, preferred_room_id)
                    success_count += 1
                    continue

        for room_id in room_ids:
            if not can_assign(room_id, request):
                continue
            score = score_room(room_id, request)
            if score > 0:
                candidates.append((score, room_id))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            append_assignment(request, candidates[0][1])
            success_count += 1
            continue

        logs.append(build_studio_failure_header(request))
        logs.append(build_studio_saturation_intro(request))
        for room_id in room_ids:
            occupant = describe_room_occupant(request, room_id)
            if occupant is None:
                continue
            logs.append(build_room_occupant_line(room_id, occupant))

        reason_code, reason = build_failure_reason(request)
        append_unassigned(request, reason, reason_code)

    logs.append(build_studio_summary_line(success_count, len(merged_requests)))
    return logs
