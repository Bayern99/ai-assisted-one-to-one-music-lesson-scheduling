"""Path-solving helpers extracted from optimizer.py.

This module only contains structural seams for weekly block path search. It
must remain policy-neutral: callers provide availability and scoring callbacks.
"""


def solve_fragmented_block_min_switches(lessons, candidate_rooms, can_assign, score_room):
    """Viterbi-style path search that minimizes room switches for a block."""
    if not lessons:
        return []
    if not candidate_rooms:
        return []

    candidate_rooms = list(candidate_rooms)

    valid_matrix = []
    day = lessons[0]["day"]

    for lesson in lessons:
        row = {}
        for room_id in candidate_rooms:
            if can_assign(room_id, day, lesson["start"], lesson["end"]):
                score = score_room(room_id, lesson)
                row[room_id] = score if score > 0 else 0
            else:
                row[room_id] = 0
        valid_matrix.append(row)

    switch_cost = 1000
    dp = [{}]
    path = [{}]

    any_valid_start = False
    for room_id in candidate_rooms:
        score = valid_matrix[0][room_id]
        if score > 0:
            dp[0][room_id] = -score
            path[0][room_id] = None
            any_valid_start = True
        else:
            dp[0][room_id] = float("inf")

    if not any_valid_start:
        return []

    for idx in range(1, len(lessons)):
        dp.append({})
        path.append({})
        any_valid_step = False

        for curr_room in candidate_rooms:
            score = valid_matrix[idx][curr_room]
            if score <= 0:
                dp[idx][curr_room] = float("inf")
                continue

            best_cost = float("inf")
            best_prev = None

            for prev_room in candidate_rooms:
                prev_cost = dp[idx - 1][prev_room]
                if prev_cost == float("inf"):
                    continue

                transition_cost = switch_cost if prev_room != curr_room else 0
                current_cost = prev_cost + transition_cost - score

                if current_cost < best_cost:
                    best_cost = current_cost
                    best_prev = prev_room

            dp[idx][curr_room] = best_cost
            path[idx][curr_room] = best_prev
            if best_prev is not None or idx == 0:
                any_valid_step = True

        if not any_valid_step:
            return []

    last_idx = len(lessons) - 1
    final_room = min(candidate_rooms, key=lambda room_id: dp[last_idx][room_id])
    if dp[last_idx][final_room] == float("inf"):
        return []

    room_path = [final_room]
    curr_room = final_room
    for idx in range(last_idx, 0, -1):
        curr_room = path[idx][curr_room]
        if curr_room is None:
            return []
        room_path.append(curr_room)
    room_path.reverse()

    return list(zip(lessons, room_path))
