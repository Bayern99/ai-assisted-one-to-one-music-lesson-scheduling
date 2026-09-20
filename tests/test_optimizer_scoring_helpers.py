from modules.scheduler.logic.optimizer_scoring import (
    compatible_room_ids,
    score_room_unified,
)


def _normalize_instrument_type(raw_type):
    value = str(raw_type or "").strip().lower()
    if "piano" in value:
        return "Piano"
    if "voice" in value or "vocal" in value:
        return "Voice"
    if "percussion" in value:
        return "Percussion"
    return "Instrumental"


def test_score_room_unified_returns_negative_one_for_hard_type_mismatch():
    score = score_room_unified(
        room_id="R3",
        req={"instrument": "Piano", "prefs": [], "inst": "Instructor 0001"},
        room_types={"R3": ["Voice"]},
        rules={"priorities": {"Voice": {"Voice": 8}}},
        normalize_instrument_type=_normalize_instrument_type,
    )

    assert score == -1


def test_score_room_unified_adds_student_and_instructor_preference_bonuses():
    score = score_room_unified(
        room_id="R2",
        req={"instrument": "Voice", "prefs": ["R2"], "inst": "Dr. Pref"},
        room_types={"R2": ["Piano", "Voice"]},
        rules={
            "priorities": {
                "Piano": {"Voice": 2},
                "Voice": {"Voice": 8},
            },
            "instructor_preferred_rooms": {"Dr. Pref": ["R2"]},
        },
        normalize_instrument_type=_normalize_instrument_type,
    )

    assert score == 160


def test_row_and_global_preferences_stay_independent_across_same_instructor_requests():
    rules = {
        "priorities": {"Piano": {"Piano": 10}},
        "instructor_preferred_rooms": {"Dr. Pref": ["R2"]},
    }
    room_types = {
        "R1": ["Piano"],
        "R2": ["Piano"],
        "R3": ["Piano"],
    }

    def score(room_id, row_preferences):
        return score_room_unified(
            room_id=room_id,
            req={
                "instrument": "Piano",
                "prefs": row_preferences,
                "inst": "Dr. Pref",
            },
            room_types=room_types,
            rules=rules,
            normalize_instrument_type=_normalize_instrument_type,
        )

    assert score("R1", ["R1"]) == 150  # row preference only: +50
    assert score("R2", ["R1"]) == 130  # global preference only: +30
    assert score("R2", ["R2"]) == 180  # both bonuses remain additive
    assert score("R2", ["R3"]) == 130
    assert score("R3", ["R3"]) == 150


def test_compatible_room_ids_preserves_room_iteration_order_for_positive_scores():
    compatible = compatible_room_ids(
        room_ids=["R1", "R2", "R3"],
        req={"instrument": "Voice", "prefs": [], "inst": "Instructor 0001"},
        score_room=lambda room_id, req: {"R1": -1, "R2": 20, "R3": 10}[room_id],
    )

    assert compatible == ["R2", "R3"]
