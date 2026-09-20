def classify_unassigned_reason(
    *,
    req,
    room_ids,
    compatible_room_ids,
    check_global_constraints,
    blocked_by_locked_context,
    reason_messages,
    specific_date=None,
):
    prefs = [str(pref).strip() for pref in (req.get("prefs") or []) if str(pref).strip()]
    if prefs and all(pref not in room_ids for pref in prefs):
        return "invalid_preferred_venue", reason_messages["invalid_preferred_venue"]

    if not check_global_constraints(req.get("start", 0), req.get("end", 0)):
        return "outside_scheduling_window", reason_messages["outside_scheduling_window"]

    compatible = compatible_room_ids(req)
    if not compatible:
        return "no_room_type_match", reason_messages["no_room_type_match"]

    if blocked_by_locked_context(req, specific_date=specific_date):
        return "blocked_by_locked_context", reason_messages["blocked_by_locked_context"]

    return "no_time_feasible_room", reason_messages["no_time_feasible_room"]
