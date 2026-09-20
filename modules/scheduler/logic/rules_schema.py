import copy
from datetime import datetime, timezone

from modules.shared.time_parser import TimeParser


ROOM_CATS = ["Piano", "Percussion", "Voice", "Instrumental"]
STUDENT_CATS = ["Piano", "Percussion", "Voice", "Instrumental"]
LEGACY_PRIORITY_KEYS = ["Non-Piano"]
TRACE_KEY = "_rules_meta"

DEFAULT_RULES = {
    "priorities": {
        "Piano": {"Piano": 10, "Non-Piano": 5, "Voice": 5, "Percussion": 0, "Instrumental": 5},
        "Percussion": {"Percussion": 10, "Non-Piano": 0, "Voice": 0, "Piano": 0, "Instrumental": 0},
        "Non-Piano": {"Non-Piano": 10, "Voice": 8, "Piano": 5, "Percussion": 0, "Instrumental": 8},
        "Voice": {"Voice": 10, "Non-Piano": 8, "Piano": 5, "Percussion": 0, "Instrumental": 8},
        "Instrumental": {"Instrumental": 10, "Voice": 5, "Piano": 5, "Percussion": 0, "Non-Piano": 8},
    },
    "constraints": {
        "time_range": {"start": "08:00", "end": "23:00"},
        "min_break_between_lessons": 0,
        "enforce_instructor_blocks": True,
        "room_stability_weight": 8,
    },
    "room_types": {},
    "instructor_preferred_rooms": {},
    "instructor_priority": {},
    "instructor_time_change_eligibility": {},
}

CANONICAL_TOP_LEVEL_KEYS = [
    "priorities",
    "constraints",
    "room_types",
    "instructor_preferred_rooms",
    "instructor_priority",
    "instructor_time_change_eligibility",
]
CANONICAL_CONSTRAINT_KEYS = [
    "time_range",
    "min_break_between_lessons",
    "enforce_instructor_blocks",
]
ALLOWED_COMPAT_CONSTRAINT_KEYS = ["room_stability_weight"]
ALLOWED_ROOM_TYPE_VALUES = set(ROOM_CATS)
HIDDEN_UI_FIELDS = ["constraints.room_stability_weight"]
DEFAULT_INSTRUCTOR_PRIORITY = 5


def _deep_merge_dict(base, override):
    if not isinstance(base, dict):
        return copy.deepcopy(override)
    if not isinstance(override, dict):
        return copy.deepcopy(base)

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _allowed_priority_room_keys():
    return ROOM_CATS + LEGACY_PRIORITY_KEYS


def _allowed_priority_student_keys():
    return STUDENT_CATS + LEGACY_PRIORITY_KEYS


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate_rules_payload(raw_rules):
    """Return trust-boundary errors without mutating or normalizing the payload."""
    if not isinstance(raw_rules, dict):
        return ["rules must be an object"]

    errors = []
    constraints = raw_rules.get("constraints")
    if constraints is not None and not isinstance(constraints, dict):
        errors.append("constraints must be an object")
        constraints = {}
    constraints = constraints or {}

    time_range = constraints.get("time_range")
    if time_range is not None and not isinstance(time_range, dict):
        errors.append("constraints.time_range must be an object")
    elif isinstance(time_range, dict):
        start = time_range.get("start", "08:00")
        end = time_range.get("end", "23:00")
        start_min = TimeParser.to_minutes(start, default=None)
        end_min = TimeParser.to_minutes(end, default=None)
        if start_min is None or not str(start).strip().endswith(":00"):
            errors.append("constraints.time_range.start must be HH:00")
        if end_min is None or not str(end).strip().endswith(":00"):
            errors.append("constraints.time_range.end must be HH:00")
        if start_min is not None and end_min is not None and end_min <= start_min:
            errors.append("constraints.time_range.start must be before end")

    for key in ("min_break_between_lessons", "room_stability_weight"):
        if key in constraints:
            try:
                int(constraints[key])
            except (TypeError, ValueError):
                errors.append(f"constraints.{key} must be an integer")
    if "enforce_instructor_blocks" in constraints and not isinstance(
        constraints["enforce_instructor_blocks"], bool
    ):
        errors.append("constraints.enforce_instructor_blocks must be boolean")

    priorities = raw_rules.get("priorities")
    if priorities is not None and not isinstance(priorities, dict):
        errors.append("priorities must be an object")
        priorities = {}
    for room_type, student_map in (priorities or {}).items():
        if not isinstance(student_map, dict):
            errors.append(f"priorities.{room_type} must be an object")
            continue
        for student_type, value in student_map.items():
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                errors.append(f"priorities.{room_type}.{student_type} must be an integer")
                continue
            if not 0 <= numeric <= 10:
                errors.append(f"priorities.{room_type}.{student_type} must be between 0 and 10")

    room_types = raw_rules.get("room_types")
    if room_types is not None and not isinstance(room_types, dict):
        errors.append("room_types must be an object")
    elif isinstance(room_types, dict):
        for room_id, values in room_types.items():
            if not isinstance(values, list) or any(
                value not in ALLOWED_ROOM_TYPE_VALUES for value in values
            ):
                errors.append(f"room_types.{room_id} must contain known room types")

    for key in ("instructor_preferred_rooms", "instructor_priority", "instructor_time_change_eligibility"):
        value = raw_rules.get(key)
        if value is not None and not isinstance(value, dict):
            errors.append(f"{key} must be an object")
    instructor_priority = raw_rules.get("instructor_priority") or {}
    if isinstance(instructor_priority, dict):
        for instructor, value in instructor_priority.items():
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                errors.append(f"instructor_priority.{instructor} must be an integer")
                continue
            if not 0 <= numeric <= 10:
                errors.append(f"instructor_priority.{instructor} must be between 0 and 10")

    preferred = raw_rules.get("instructor_preferred_rooms") or {}
    if isinstance(preferred, dict):
        for instructor, values in preferred.items():
            if not isinstance(values, list):
                errors.append(f"instructor_preferred_rooms.{instructor} must be a list")

    eligibility = raw_rules.get("instructor_time_change_eligibility") or {}
    if isinstance(eligibility, dict):
        for instructor, value in eligibility.items():
            if not isinstance(value, bool):
                errors.append(
                    f"instructor_time_change_eligibility.{instructor} must be boolean"
                )
    return errors


def _build_trace(raw_rules, source_path=None):
    raw = raw_rules if isinstance(raw_rules, dict) else {}
    ignored_top_level = sorted(key for key in raw.keys() if key not in CANONICAL_TOP_LEVEL_KEYS and key != TRACE_KEY)
    ignored_nested = []

    raw_constraints = raw.get("constraints")
    if isinstance(raw_constraints, dict):
        allowed_constraint_keys = set(CANONICAL_CONSTRAINT_KEYS + ALLOWED_COMPAT_CONSTRAINT_KEYS)
        for key in raw_constraints.keys():
            if key not in allowed_constraint_keys:
                ignored_nested.append(f"constraints.{key}")

    raw_priorities = raw.get("priorities")
    if isinstance(raw_priorities, dict):
        allowed_room_keys = set(_allowed_priority_room_keys())
        allowed_student_keys = set(_allowed_priority_student_keys())
        for room_key, student_map in raw_priorities.items():
            if room_key not in allowed_room_keys:
                ignored_nested.append(f"priorities.{room_key}")
                continue
            if isinstance(student_map, dict):
                for student_key in student_map.keys():
                    if student_key not in allowed_student_keys:
                        ignored_nested.append(f"priorities.{room_key}.{student_key}")

    return {
        "schema_version": 1,
        "source_path": source_path or "",
        "ignored_top_level_keys": ignored_top_level,
        "ignored_nested_keys": sorted(ignored_nested),
        "hidden_ui_fields": list(HIDDEN_UI_FIELDS),
        "normalized_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def get_rules_trace(rules):
    if not isinstance(rules, dict):
        return {}
    trace = rules.get(TRACE_KEY, {})
    return copy.deepcopy(trace) if isinstance(trace, dict) else {}


def normalize_rules(raw_rules, default_rules=None, source_path=None):
    defaults = copy.deepcopy(default_rules if isinstance(default_rules, dict) else DEFAULT_RULES)
    raw = raw_rules if isinstance(raw_rules, dict) else {}
    rules = _deep_merge_dict(defaults, raw)

    for key in (
        "priorities",
        "constraints",
        "room_types",
        "instructor_preferred_rooms",
        "instructor_priority",
        "instructor_time_change_eligibility",
    ):
        if not isinstance(rules.get(key), dict):
            rules[key] = {}

    for room_type in _allowed_priority_room_keys():
        if room_type in defaults.get("priorities", {}) or room_type in rules["priorities"]:
            rules["priorities"].setdefault(room_type, {})
            for student_type in _allowed_priority_student_keys():
                if (
                    student_type in defaults.get("priorities", {}).get(room_type, {})
                    or student_type in rules["priorities"].get(room_type, {})
                ):
                    rules["priorities"][room_type].setdefault(student_type, 0)

    if not isinstance(rules["constraints"].get("time_range"), dict):
        rules["constraints"]["time_range"] = copy.deepcopy(
            defaults.get("constraints", {}).get(
                "time_range",
                {"start": "08:00", "end": "23:00"},
            )
        )
    rules["constraints"]["time_range"].setdefault("start", "08:00")
    rules["constraints"]["time_range"].setdefault("end", "23:00")
    rules["constraints"].setdefault("min_break_between_lessons", 0)
    rules["constraints"].setdefault("room_stability_weight", 8)
    rules["constraints"].setdefault("enforce_instructor_blocks", True)
    rules[TRACE_KEY] = _build_trace(raw, source_path=source_path)

    return rules


def canonicalize_rules_for_save(raw_rules, default_rules=None, source_path=None):
    normalized = normalize_rules(raw_rules, default_rules=default_rules, source_path=source_path)

    saved = {
        "priorities": {},
        "constraints": {
            "time_range": {
                "start": str(normalized["constraints"]["time_range"].get("start", "08:00")),
                "end": str(normalized["constraints"]["time_range"].get("end", "23:00")),
            },
            "min_break_between_lessons": _safe_int(
                0,
                default=0,
            ),
            "enforce_instructor_blocks": bool(
                normalized["constraints"].get("enforce_instructor_blocks", True)
            ),
            "room_stability_weight": _safe_int(
                normalized["constraints"].get("room_stability_weight", 8),
                default=8,
            ),
        },
        "room_types": {},
        "instructor_preferred_rooms": {},
        "instructor_priority": {},
        "instructor_time_change_eligibility": {},
    }

    for room_type in _allowed_priority_room_keys():
        room_map = normalized.get("priorities", {}).get(room_type)
        if not isinstance(room_map, dict):
            continue
        saved["priorities"][room_type] = {}
        for student_type in _allowed_priority_student_keys():
            if student_type in room_map:
                saved["priorities"][room_type][student_type] = _safe_int(room_map.get(student_type), default=0)

    for room_id, raw_types in normalized.get("room_types", {}).items():
        if not room_id:
            continue
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if not isinstance(raw_types, list):
            continue
        clean_types = [room_type for room_type in raw_types if room_type in ALLOWED_ROOM_TYPE_VALUES]
        saved["room_types"][str(room_id)] = clean_types

    for inst_name, raw_rooms in normalized.get("instructor_preferred_rooms", {}).items():
        if not inst_name:
            continue
        if isinstance(raw_rooms, str):
            raw_rooms = [raw_rooms]
        if not isinstance(raw_rooms, list):
            continue
        saved["instructor_preferred_rooms"][str(inst_name)] = [str(room).strip() for room in raw_rooms if str(room).strip()]

    for inst_name, value in normalized.get("instructor_priority", {}).items():
        if not inst_name:
            continue
        saved["instructor_priority"][str(inst_name)] = _safe_int(value, default=5)

    for inst_name, value in normalized.get("instructor_time_change_eligibility", {}).items():
        if not inst_name:
            continue
        saved["instructor_time_change_eligibility"][str(inst_name)] = bool(value)

    return saved
