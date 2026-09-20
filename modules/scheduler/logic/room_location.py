"""Canonical room-location semantics shared by optimizer, Step 2, and validators.

This module is intentionally limited to semantic normalization:
- imported room types
- effective room types after overrides
- override canonicalization
- preferred-room sanitization

Scoring, preferred-room precedence, and preemption policy must live outside this
module so Room Locator policy work can evolve independently from room semantics.
"""

from modules.scheduler.logic.rules_schema import ALLOWED_ROOM_TYPE_VALUES


def _as_string_list(raw_values):
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    if not isinstance(raw_values, list):
        return []
    return [str(value).strip() for value in raw_values if str(value).strip()]


def normalize_room_type_list(raw_values):
    normalized = []
    for value in _as_string_list(raw_values):
        if value in ALLOWED_ROOM_TYPE_VALUES and value not in normalized:
            normalized.append(value)
    return normalized


def build_room_profiles(rooms, rules):
    profiles = {}
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id", "")).strip()
        if not room_id:
            continue
        imported_types = normalize_room_type_list(room.get("types", room.get("type", [])))
        profiles[room_id] = {
            "id": room_id,
            "imported_types": imported_types,
            "effective_types": list(imported_types),
            "has_manual_override": False,
        }

    room_type_overrides = (rules or {}).get("room_types", {})
    if isinstance(room_type_overrides, dict):
        for room_id, raw_types in room_type_overrides.items():
            clean_room_id = str(room_id).strip()
            if not clean_room_id:
                continue
            profile = profiles.setdefault(
                clean_room_id,
                {
                    "id": clean_room_id,
                    "imported_types": [],
                    "effective_types": [],
                    "has_manual_override": False,
                },
            )
            profile["effective_types"] = normalize_room_type_list(raw_types)
            profile["has_manual_override"] = True

    return [profiles[room_id] for room_id in sorted(profiles)]


def build_room_profile_map(rooms, rules):
    return {profile["id"]: profile for profile in build_room_profiles(rooms, rules)}


def effective_room_types_by_id(rooms, rules):
    return {
        room_id: list(profile.get("effective_types", []))
        for room_id, profile in build_room_profile_map(rooms, rules).items()
    }


def canonicalize_room_type_overrides(room_profiles, room_type_overrides):
    imported_by_id = {
        str(profile.get("id", "")).strip(): list(profile.get("imported_types", []))
        for profile in room_profiles or []
        if str(profile.get("id", "")).strip()
    }
    canonical = {}
    if not isinstance(room_type_overrides, dict):
        return canonical

    for room_id, raw_types in room_type_overrides.items():
        clean_room_id = str(room_id).strip()
        if not clean_room_id:
            continue
        normalized_types = normalize_room_type_list(raw_types)
        if normalized_types != imported_by_id.get(clean_room_id, []):
            canonical[clean_room_id] = normalized_types
    return canonical


def sanitize_instructor_preferred_rooms(preferences, valid_room_ids):
    valid_room_ids = {str(room_id).strip() for room_id in valid_room_ids if str(room_id).strip()}
    sanitized = {}
    invalid = {}
    if not isinstance(preferences, dict):
        return sanitized, invalid

    for instructor, raw_rooms in preferences.items():
        clean_instructor = str(instructor).strip()
        if not clean_instructor:
            continue
        requested_rooms = _as_string_list(raw_rooms)
        kept = [room_id for room_id in requested_rooms if room_id in valid_room_ids]
        dropped = [room_id for room_id in requested_rooms if room_id not in valid_room_ids]
        sanitized[clean_instructor] = kept
        if dropped:
            invalid[clean_instructor] = dropped

    return sanitized, invalid
