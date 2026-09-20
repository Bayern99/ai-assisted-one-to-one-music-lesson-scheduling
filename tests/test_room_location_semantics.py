from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.preflight import inspect_room_inventory_health
from modules.scheduler.logic.room_location import (
    build_room_profiles,
    canonicalize_room_type_overrides,
    sanitize_instructor_preferred_rooms,
)


def test_build_room_profiles_merges_imported_and_manual_room_types():
    profiles = build_room_profiles(
        [
            {"id": "R103", "type": "General"},
            {"id": "CC102", "types": ["Piano"]},
        ],
        {"room_types": {"R103": ["Voice"], "CC103": ["Percussion"]}},
    )

    by_id = {profile["id"]: profile for profile in profiles}

    assert by_id["R103"]["imported_types"] == []
    assert by_id["R103"]["effective_types"] == ["Voice"]
    assert by_id["R103"]["has_manual_override"] is True
    assert by_id["CC102"]["imported_types"] == ["Piano"]
    assert by_id["CC102"]["effective_types"] == ["Piano"]
    assert by_id["CC102"]["has_manual_override"] is False
    assert by_id["CC103"]["imported_types"] == []
    assert by_id["CC103"]["effective_types"] == ["Percussion"]


def test_canonicalize_room_type_overrides_drops_redundant_and_keeps_meaningful_overrides():
    room_profiles = build_room_profiles(
        [
            {"id": "R103", "types": ["Piano"]},
            {"id": "CC102", "type": "General"},
        ],
        {"room_types": {}},
    )

    canonical = canonicalize_room_type_overrides(
        room_profiles,
        {
            "R103": [],
            "CC102": ["Voice"],
            "CC103": ["Percussion"],
            "R107": ["Piano"],
        },
    )

    assert canonical == {
        "R103": [],
        "CC102": ["Voice"],
        "CC103": ["Percussion"],
        "R107": ["Piano"],
    }


def test_sanitize_instructor_preferred_rooms_filters_unknown_ids_and_reports_them():
    sanitized, invalid = sanitize_instructor_preferred_rooms(
        {
            "Instructor 0001": ["R103", "CC999"],
            "Dr. B": [],
        },
        ["R103", "CC102"],
    )

    assert sanitized == {
        "Instructor 0001": ["R103"],
        "Dr. B": [],
    }
    assert invalid == {
        "Instructor 0001": ["CC999"],
    }


def test_preflight_room_health_uses_effective_room_types_after_override():
    health = inspect_room_inventory_health(
        [{"id": "R1", "type": "General"}],
        {"room_types": {"R1": ["Piano"]}},
    )

    assert health["rooms_corrupted_or_degenerated"] is False
    assert health["specialized_room_count"] == 1


def test_conflict_validator_uses_effective_room_types_for_rule_validation():
    validator = ConflictValidator(
        {
            "assignments": [],
            "lectures": [],
            "rooms": [{"id": "R1", "type": "General"}],
            "rules": {"room_types": {"R1": ["Piano"]}},
        }
    )

    assert validator.validate_rules("R1", "Piano")["allowed"] is True
    rejected = validator.validate_rules("R1", "Voice")
    assert rejected["allowed"] is False
    assert "Room Type Mismatch" in rejected["reason"]


def test_conflict_validator_rejects_general_room_without_effective_types():
    validator = ConflictValidator(
        {
            "assignments": [],
            "lectures": [],
            "rooms": [{"id": "R1", "type": "General"}],
            "rules": {"room_types": {}},
        }
    )

    rejected = validator.validate_rules("R1", "Piano")
    assert rejected["allowed"] is False
    assert "Room Type Mismatch" in rejected["reason"]


def test_optimizer_uses_effective_room_types_from_room_profiles():
    optimizer = RoomAllocator(
        students=[],
        rooms=[{"id": "R1", "type": "General"}],
        existing_bookings=[],
        rules={
            "room_types": {"R1": ["Piano"]},
            "priorities": {"Piano": {"Piano": 10}},
            "constraints": {},
            "instructor_preferred_rooms": {},
            "instructor_priority": {},
        },
    )

    assert optimizer.room_types["R1"] == ["Piano"]
    assert optimizer._score_room_unified("R1", {"instrument": "Piano", "prefs": [], "inst": ""}) > 0
