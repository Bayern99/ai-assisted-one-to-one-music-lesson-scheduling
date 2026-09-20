from modules.scheduler.logic.optimizer import RoomAllocator, UNASSIGNED_REASON_MESSAGES


def _make_allocator():
    allocator = RoomAllocator(
        students=[],
        rooms=[
            {"id": "R1", "types": ["Piano"]},
            {"id": "R2", "types": ["Piano", "Voice"]},
            {"id": "R3", "types": ["Voice"]},
        ],
        existing_bookings=[],
        rules={
            "room_types": {},
            "priorities": {
                "Piano": {"Piano": 10, "Voice": 2},
                "Voice": {"Voice": 8, "Piano": 1},
            },
            "constraints": {},
            "instructor_preferred_rooms": {
                "Dr. Pref": ["R2"],
            },
            "instructor_priority": {},
        },
    )
    allocator.assignments = []
    allocator.unassigned = []
    return allocator


def test_score_room_unified_returns_negative_one_for_hard_type_mismatch():
    allocator = _make_allocator()

    score = allocator._score_room_unified(
        "R3",
        {"instrument": "Piano", "prefs": [], "inst": "Instructor 0001"},
    )

    assert score == -1


def test_score_room_unified_returns_negative_one_when_priority_matrix_has_no_positive_base():
    allocator = _make_allocator()
    allocator.rules["priorities"] = {
        "Piano": {"Piano": 0},
        "Voice": {"Voice": 0},
    }

    score = allocator._score_room_unified(
        "R1",
        {"instrument": "Piano", "prefs": [], "inst": "Instructor 0001"},
    )

    assert score == -1


def test_score_room_unified_adds_student_and_instructor_preference_bonuses():
    allocator = _make_allocator()

    score = allocator._score_room_unified(
        "R2",
        {"instrument": "Voice", "prefs": ["R2"], "inst": "Dr. Pref"},
    )

    assert score == 160


def test_compatible_room_ids_preserves_room_iteration_order_for_positive_scores():
    allocator = _make_allocator()

    compatible = allocator._compatible_room_ids(
        {"instrument": "Voice", "prefs": [], "inst": "Instructor 0001"},
    )

    assert compatible == ["R2", "R3"]


def test_classify_unassigned_reason_flags_invalid_preferred_venue_before_other_checks():
    allocator = _make_allocator()

    reason_code, reason = allocator._classify_unassigned_reason(
        {"instrument": "Piano", "prefs": ["UNKNOWN_ROOM"], "inst": "Instructor 0001", "start": 10, "end": 11},
    )

    assert reason_code == "invalid_preferred_venue"
    assert reason == UNASSIGNED_REASON_MESSAGES["invalid_preferred_venue"]


def test_classify_unassigned_reason_returns_no_room_type_match_when_no_compatible_room():
    allocator = _make_allocator()

    reason_code, reason = allocator._classify_unassigned_reason(
        {"instrument": "Percussion", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
    )

    assert reason_code == "no_room_type_match"
    assert reason == UNASSIGNED_REASON_MESSAGES["no_room_type_match"]


def test_classify_unassigned_reason_returns_rule_constraint_rejection_before_locked_context():
    allocator = _make_allocator()
    allocator.rules["constraints"] = {"time_range": {"start": "08:00", "end": "09:00"}}

    reason_code, reason = allocator._classify_unassigned_reason(
        {"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
    )

    assert reason_code == "outside_scheduling_window"
    assert reason == UNASSIGNED_REASON_MESSAGES["outside_scheduling_window"]


def test_classify_unassigned_reason_returns_blocked_by_locked_context_when_compatible_rooms_are_all_locked(monkeypatch):
    allocator = _make_allocator()
    monkeypatch.setattr(allocator, "_blocked_by_locked_context", lambda req, specific_date=None: True)

    reason_code, reason = allocator._classify_unassigned_reason(
        {"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
    )

    assert reason_code == "blocked_by_locked_context"
    assert reason == UNASSIGNED_REASON_MESSAGES["blocked_by_locked_context"]


def test_classify_unassigned_reason_falls_back_to_no_time_feasible_room():
    allocator = _make_allocator()

    reason_code, reason = allocator._classify_unassigned_reason(
        {"instrument": "Piano", "prefs": [], "inst": "Instructor 0001", "start": 10, "end": 11},
    )

    assert reason_code == "no_time_feasible_room"
    assert reason == UNASSIGNED_REASON_MESSAGES["no_time_feasible_room"]
