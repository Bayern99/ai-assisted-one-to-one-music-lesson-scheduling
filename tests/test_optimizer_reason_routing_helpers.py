from modules.scheduler.logic.optimizer import UNASSIGNED_REASON_MESSAGES
from modules.scheduler.logic.optimizer_reason_routing import classify_unassigned_reason


def test_classify_unassigned_reason_flags_invalid_preferred_venue_before_other_checks():
    reason_code, reason = classify_unassigned_reason(
        req={"instrument": "Piano", "prefs": ["UNKNOWN_ROOM"], "inst": "Instructor 0001", "start": 10, "end": 11},
        room_ids={"R1": {}, "R2": {}},
        compatible_room_ids=lambda req: ["R1"],
        check_global_constraints=lambda start, end: True,
        blocked_by_locked_context=lambda req, specific_date=None: False,
        reason_messages=UNASSIGNED_REASON_MESSAGES,
    )

    assert reason_code == "invalid_preferred_venue"
    assert reason == UNASSIGNED_REASON_MESSAGES["invalid_preferred_venue"]


def test_classify_unassigned_reason_returns_no_room_type_match_when_no_compatible_room():
    reason_code, reason = classify_unassigned_reason(
        req={"instrument": "Percussion", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
        room_ids={"R1": {}, "R2": {}},
        compatible_room_ids=lambda req: [],
        check_global_constraints=lambda start, end: True,
        blocked_by_locked_context=lambda req, specific_date=None: False,
        reason_messages=UNASSIGNED_REASON_MESSAGES,
    )

    assert reason_code == "no_room_type_match"
    assert reason == UNASSIGNED_REASON_MESSAGES["no_room_type_match"]


def test_classify_unassigned_reason_returns_rule_constraint_rejection_before_locked_context():
    reason_code, reason = classify_unassigned_reason(
        req={"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
        room_ids={"R1": {}, "R2": {}},
        compatible_room_ids=lambda req: ["R1"],
        check_global_constraints=lambda start, end: False,
        blocked_by_locked_context=lambda req, specific_date=None: True,
        reason_messages=UNASSIGNED_REASON_MESSAGES,
    )

    assert reason_code == "outside_scheduling_window"
    assert reason == UNASSIGNED_REASON_MESSAGES["outside_scheduling_window"]


def test_classify_unassigned_reason_returns_blocked_by_locked_context_when_compatible_rooms_are_all_locked():
    reason_code, reason = classify_unassigned_reason(
        req={"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
        room_ids={"R1": {}, "R2": {}},
        compatible_room_ids=lambda req: ["R1"],
        check_global_constraints=lambda start, end: True,
        blocked_by_locked_context=lambda req, specific_date=None: True,
        reason_messages=UNASSIGNED_REASON_MESSAGES,
    )

    assert reason_code == "blocked_by_locked_context"
    assert reason == UNASSIGNED_REASON_MESSAGES["blocked_by_locked_context"]


def test_classify_unassigned_reason_falls_back_to_no_time_feasible_room():
    reason_code, reason = classify_unassigned_reason(
        req={"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
        room_ids={"R1": {}, "R2": {}},
        compatible_room_ids=lambda req: ["R1"],
        check_global_constraints=lambda start, end: True,
        blocked_by_locked_context=lambda req, specific_date=None: False,
        reason_messages=UNASSIGNED_REASON_MESSAGES,
    )

    assert reason_code == "no_time_feasible_room"
    assert reason == UNASSIGNED_REASON_MESSAGES["no_time_feasible_room"]
