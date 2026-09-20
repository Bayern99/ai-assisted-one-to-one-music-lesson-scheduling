def score_room_unified(
    *,
    room_id,
    req,
    room_types,
    rules,
    normalize_instrument_type,
):
    room_supported_types = room_types.get(room_id, [])
    student_type = normalize_instrument_type(req["instrument"])

    if student_type not in room_supported_types:
        return -1

    base = 0
    for room_type in room_supported_types:
        if room_type in rules.get("priorities", {}):
            base = max(base, rules["priorities"][room_type].get(student_type, 0))

    if base <= 0:
        return -1

    score = base * 10
    if room_id in req["prefs"]:
        score += 50

    instructor_name = req.get("inst", "")
    instructor_prefs = rules.get("instructor_preferred_rooms", {}).get(instructor_name) or []
    if room_id in instructor_prefs:
        score += 30

    return score


def compatible_room_ids(
    *,
    room_ids,
    req,
    score_room,
):
    compatible = []
    for room_id in room_ids:
        if score_room(room_id, req) > 0:
            compatible.append(room_id)
    return compatible
