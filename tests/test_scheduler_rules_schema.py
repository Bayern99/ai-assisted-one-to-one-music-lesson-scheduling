from modules.scheduler.logic.rules_schema import (
    DEFAULT_RULES,
    TRACE_KEY,
    canonicalize_rules_for_save,
    get_rules_trace,
    normalize_rules,
)


def test_normalize_rules_uses_canonical_defaults():
    rules = normalize_rules({})

    assert rules["constraints"]["room_stability_weight"] == 8
    assert rules["constraints"]["enforce_instructor_blocks"] is True
    assert rules["instructor_preferred_rooms"] == {}
    assert rules["instructor_priority"] == {}
    assert rules["instructor_time_change_eligibility"] == {}
    assert rules["priorities"]["Non-Piano"]["Voice"] == 8
    assert rules["priorities"]["Piano"]["Non-Piano"] == 5


def test_normalize_rules_preserves_extra_priority_entries():
    raw_rules = {
        "priorities": {
            "CustomRoom": {"CustomStudent": 7},
            "Non-Piano": {"Voice": 9},
        },
        "constraints": {"time_range": {"start": "09:00"}},
    }

    rules = normalize_rules(raw_rules)

    assert rules["priorities"]["CustomRoom"]["CustomStudent"] == 7
    assert rules["priorities"]["Non-Piano"]["Voice"] == 9
    assert rules["constraints"]["time_range"]["start"] == "09:00"
    assert rules["constraints"]["time_range"]["end"] == "23:00"
    assert rules["constraints"]["room_stability_weight"] == 8
    assert DEFAULT_RULES["priorities"]["Instrumental"]["Non-Piano"] == 8


def test_canonicalize_rules_for_save_drops_unknown_keys_and_keeps_allowed_compat():
    raw_rules = {
        "priorities": {
            "Piano": {"Piano": 9},
            "Non-Piano": {"Voice": 7},
            "ShadowRoom": {"Ghost": 3},
        },
        "constraints": {
            "time_range": {"start": "09:00"},
            "room_stability_weight": 4,
            "totally_unused_knob": 999,
        },
        "room_types": {"CC105": ["Piano"]},
        "instructor_priority": {"Prof A": 10},
        "instructor_time_change_eligibility": {
            "Prof A": False,
            "Prof B": True,
        },
        "debug_blob": {"junk": True},
    }

    saved = canonicalize_rules_for_save(raw_rules, source_path="/tmp/scheduling_rules.json")

    assert "debug_blob" not in saved
    assert saved["constraints"]["room_stability_weight"] == 4
    assert "totally_unused_knob" not in saved["constraints"]
    assert saved["priorities"]["Non-Piano"]["Voice"] == 7
    assert saved["instructor_time_change_eligibility"] == {
        "Prof A": False,
        "Prof B": True,
    }
    assert "ShadowRoom" not in saved["priorities"]


def test_normalize_rules_exposes_trace_metadata():
    rules = normalize_rules(
        {"rogue": 1, "constraints": {"unused_flag": True}},
        source_path="/tmp/runtime_shadow/scheduling_rules.json",
    )

    trace = get_rules_trace(rules)

    assert TRACE_KEY in rules
    assert trace["source_path"].endswith("scheduling_rules.json")
    assert "rogue" in trace["ignored_top_level_keys"]
    assert "constraints.unused_flag" in trace["ignored_nested_keys"]
