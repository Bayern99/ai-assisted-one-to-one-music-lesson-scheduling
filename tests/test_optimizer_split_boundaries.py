from pathlib import Path

from modules.scheduler.logic.optimizer import RoomAllocator, UNASSIGNED_REASON_MESSAGES


def test_optimizer_public_contract_returns_triplet_for_empty_inputs():
    allocator = RoomAllocator([], [], [], {}, rules_source_path="/tmp/rules.json")

    assignments, duplicates, logs = allocator.optimize(None, None)

    assert assignments == []
    assert duplicates == []
    assert isinstance(logs, list)
    assert logs
    assert "Rules Source:" in logs[0]


def test_optimizer_reason_code_registry_stays_stable():
    assert set(UNASSIGNED_REASON_MESSAGES) == {
        "normalization_failed",
        "missing_student_no",
        "duplicate_student",
        "missing_day_or_time",
        "unsupported_weekday",
        "invalid_studio_date",
        "malformed_class_time",
        "invalid_course_time",
        "invalid_preferred_venue",
        "no_room_type_match",
        "blocked_by_locked_context",
        "rule_constraint_rejection",
        "outside_scheduling_window",
        "no_time_feasible_room",
        "preempted_by_higher_priority_block",
        "no_single_room_for_group",
    }


def test_optimizer_semantics_callers_do_not_rebuild_room_type_overrides_inline():
    optimizer_source = Path("modules/scheduler/logic/optimizer.py").read_text(encoding="utf-8")
    validator_source = Path("modules/scheduler/logic/conflict_validator.py").read_text(encoding="utf-8")
    preflight_source = Path("modules/scheduler/logic/preflight.py").read_text(encoding="utf-8")

    assert "build_optimizer_init_lines" in optimizer_source
    assert "build_weekly_assignment" in optimizer_source
    assert "solve_fragmented_block_min_switches" in optimizer_source
    assert "prepare_weekly_lessons" in optimizer_source
    assert "group_lessons_into_blocks" in optimizer_source
    assert "can_assign_against_bookings" in optimizer_source
    assert "prepare_studio_requests" in optimizer_source
    assert "append_unassigned_entry" in optimizer_source
    assert "build_weekly_rejection_entry" in optimizer_source
    assert "build_studio_failed_unassigned" in optimizer_source
    assert "build_studio_failure_header" in optimizer_source
    assert "build_studio_saturation_intro" in optimizer_source
    assert "build_room_occupant_line" in optimizer_source
    assert "build_studio_summary_line" in optimizer_source
    assert "schedule_weekly_blocks" in optimizer_source
    assert "assign_studio_requests" in optimizer_source
    assert "build_block_linkage_map" in optimizer_source
    assert "register_block_groups" in optimizer_source
    assert "get_conflicting_events" in optimizer_source
    assert "relocate_whole_block" in optimizer_source
    assert "evict_whole_block" in optimizer_source
    assert "resolve_grandmaster_conflicts" in optimizer_source
    assert "check_food_chain" in optimizer_source
    assert "score_room_unified" in optimizer_source
    assert "compatible_room_ids" in optimizer_source
    assert "classify_unassigned_reason" in optimizer_source

    assert "build_room_profile_map" in optimizer_source
    assert "build_room_profile_map" in validator_source
    assert "build_room_profiles" in preflight_source

    assert "rules.get('room_types'" not in optimizer_source
    assert 'rules.get("room_types"' not in optimizer_source
    assert "rules.get('room_types'" not in validator_source
    assert 'rules.get("room_types"' not in validator_source
    assert "rules.get('room_types'" not in preflight_source
    assert 'rules.get("room_types"' not in preflight_source


def test_room_location_module_stays_semantics_only():
    source = Path("modules/scheduler/logic/room_location.py").read_text(encoding="utf-8")

    assert "_score_room_unified" not in source
    assert "rules.get('priorities'" not in source
    assert 'rules.get("priorities"' not in source
    assert "instructor_priority" not in source


def test_orchestration_helpers_do_not_redefine_policy_cores():
    weekly_source = Path("modules/scheduler/logic/optimizer_weekly_phase.py").read_text(encoding="utf-8")
    studio_source = Path("modules/scheduler/logic/optimizer_studio_assignment.py").read_text(encoding="utf-8")
    linkage_source = Path("modules/scheduler/logic/optimizer_block_linkage.py").read_text(encoding="utf-8")
    conflicts_source = Path("modules/scheduler/logic/optimizer_preemption_conflicts.py").read_text(encoding="utf-8")
    relocation_source = Path("modules/scheduler/logic/optimizer_preemption_relocation.py").read_text(encoding="utf-8")
    eviction_source = Path("modules/scheduler/logic/optimizer_preemption_eviction.py").read_text(encoding="utf-8")
    resolution_source = Path("modules/scheduler/logic/optimizer_preemption_resolution.py").read_text(encoding="utf-8")
    food_chain_source = Path("modules/scheduler/logic/optimizer_preemption_food_chain.py").read_text(encoding="utf-8")
    scoring_source = Path("modules/scheduler/logic/optimizer_scoring.py").read_text(encoding="utf-8")
    reason_routing_source = Path("modules/scheduler/logic/optimizer_reason_routing.py").read_text(encoding="utf-8")

    assert "_score_room_unified" not in weekly_source
    assert "_score_room_unified" not in studio_source
    assert "_score_room_unified" not in linkage_source
    assert "_score_room_unified" not in conflicts_source
    assert "_score_room_unified" not in relocation_source
    assert "_score_room_unified" not in eviction_source
    assert "_score_room_unified" not in resolution_source
    assert "_score_room_unified" not in food_chain_source
    assert "_classify_unassigned_reason" not in scoring_source
    assert "_blocked_by_locked_context" not in scoring_source
    assert "_blocked_by_locked_context" not in reason_routing_source
    assert "_append_unassigned" not in reason_routing_source
    assert "_resolve_with_grandmaster_logic" not in weekly_source
    assert "_resolve_with_grandmaster_logic" not in studio_source
    assert "_resolve_with_grandmaster_logic" not in linkage_source
    assert "_resolve_with_grandmaster_logic" not in conflicts_source
    assert "_resolve_with_grandmaster_logic" not in relocation_source
    assert "_resolve_with_grandmaster_logic" not in eviction_source
    assert "_normalize_instrument_type" not in resolution_source
    assert "_parse_event_times" not in resolution_source
    assert "_resolve_with_grandmaster_logic" not in food_chain_source
    assert "_parse_event_times" not in food_chain_source
    assert "food chain" not in weekly_source.lower()
    assert "food chain" not in studio_source.lower()
    assert "food chain" not in linkage_source.lower()
    assert "food chain" not in conflicts_source.lower()
    assert "food chain" not in relocation_source.lower()
    assert "food chain" not in eviction_source.lower()
    assert "logs.append" not in conflicts_source
    assert "append_unassigned" not in relocation_source
    assert "logs.append" not in eviction_source
    assert "logs.append" not in food_chain_source
    assert "append_unassigned" not in food_chain_source
    assert "append_unassigned" not in scoring_source
    assert "logs.append" not in scoring_source
    assert "logs.append" not in reason_routing_source


def test_legacy_modules_are_removed_from_scheduler_logic():
    for relpath in (
        "modules/scheduler/logic/validation.py",
        "modules/scheduler/logic/gap_analysis.py",
        "modules/scheduler/logic/csp.py",
        "modules/scheduler/logic/legacy_csp_adapter.py",
    ):
        assert not Path(relpath).exists()
