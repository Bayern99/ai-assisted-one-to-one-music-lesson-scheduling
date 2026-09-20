import tempfile

import pandas as pd

from modules.scheduler.context import build_scheduler_context
from modules.scheduler.logic.preflight import (
    collect_optimizer_preflight,
    inspect_room_inventory_health,
)


def test_inspect_room_inventory_health_flags_all_general_rooms_as_degenerated():
    health = inspect_room_inventory_health(
        [
            {"id": "R1", "type": "General"},
            {"id": "R2", "type": ["General"]},
        ]
    )

    assert health["rooms_corrupted_or_degenerated"] is True
    assert health["status"] == "degenerated"
    assert health["all_rooms_general"] is True
    assert health["specialized_room_count"] == 0


def test_collect_optimizer_preflight_blocks_probe_rules_and_general_only_rooms():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=tmpdir)
        context.loader.save_data("rooms.json", [{"id": "R1", "type": "General"}])
        context.loader.save_data("scheduling_rules.json", {"probe": "scheduling_rules.json"})

        preflight = collect_optimizer_preflight(
            context.loader,
            default_rules=context.default_rules,
        )

        assert preflight["is_blocked"] is True
        assert preflight["rules_health"]["rules_corrupted_or_degenerated"] is True
        assert preflight["room_health"]["rooms_corrupted_or_degenerated"] is True
        assert len(preflight["issues"]) == 2


def test_collect_optimizer_preflight_accepts_general_room_when_override_restores_effective_types():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=tmpdir)
        context.loader.save_data("rooms.json", [{"id": "R1", "type": "General"}])
        context.loader.save_data(
            "scheduling_rules.json",
            {"room_types": {"R1": ["Piano"]}},
        )

        preflight = collect_optimizer_preflight(
            context.loader,
            default_rules=context.default_rules,
        )

        assert preflight["room_health"]["rooms_corrupted_or_degenerated"] is False
        assert not any(
            "Room inventory has no specialized room types." in issue
            for issue in preflight["issues"]
        )


def test_collect_optimizer_preflight_blocks_instructor_time_conflicts():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=tmpdir)
        context.loader.save_data("rooms.json", [{"id": "R1", "type": "Piano"}])
        context.loader.save_data(
            "scheduling_rules.json",
            {"room_types": {"R1": ["Piano"]}},
        )
        weekly = pd.DataFrame(
            [
                {
                    "Instructor": "Instructor 0001",
                    "Day of Week": "Monday",
                    "Class Time": "10:00-11:00",
                },
                {
                    "Instructor": "Instructor 0001",
                    "Day of Week": "Monday",
                    "Class Time": "10:30-11:30",
                },
            ]
        )

        preflight = collect_optimizer_preflight(
            context.loader,
            default_rules=context.default_rules,
            weekly_df=weekly,
        )

        assert preflight["is_blocked"] is True
        assert len(preflight["instructor_conflicts"]) == 1
        assert any("instructor time conflicts" in issue for issue in preflight["issues"])
        assert any(
            "Instructor 0001" in issue and "10:00-11:00" in issue
            for issue in preflight["issues"]
        )


def test_collect_optimizer_preflight_uses_public_loader_json_interface():
    class DummyLoader:
        def preferred_data_path(self, name):
            assert name == "scheduling_rules.json"
            return "/tmp/scheduling_rules.json"

        def load_json_data(self, name, default_value=None):
            assert name == "scheduling_rules.json"
            return {"room_types": {"R1": ["Piano"]}}

        def get_data(self, name):
            assert name == "rooms.json"
            return [{"id": "R1", "type": "General"}]

    preflight = collect_optimizer_preflight(DummyLoader(), default_rules={})

    assert preflight["rules_health"]["rules_corrupted_or_degenerated"] is False
    assert preflight["room_health"]["rooms_corrupted_or_degenerated"] is False
    assert preflight["is_blocked"] is False
