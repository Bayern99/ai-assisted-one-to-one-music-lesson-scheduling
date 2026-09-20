import os
import tempfile

from modules.scheduler.context import build_scheduler_context


def test_build_scheduler_context_uses_injected_base_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=os.path.join(tmpdir, "data"))

        assert context.loader.base_dir == os.path.join(tmpdir, "data")
        assert context.session_manager.base_dir == os.path.join(tmpdir, "data")
        assert context.rules_path.endswith("scheduling_rules.json")


def test_scheduler_context_save_and_load_rules_follow_canonical_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        context = build_scheduler_context(base_dir=os.path.join(tmpdir, "data"))

        saved_rules, saved_path = context.save_rules(
            {
                "constraints": {
                    "time_range": {"start": "09:00"},
                    "mystery_flag": True,
                },
                "experimental": {"junk": True},
            }
        )
        loaded_rules = context.load_rules()

        assert saved_path.endswith("scheduling_rules.json")
        assert "experimental" not in saved_rules
        assert "mystery_flag" not in saved_rules["constraints"]
        assert loaded_rules["constraints"]["time_range"]["start"] == "09:00"
        trace = loaded_rules["_rules_meta"]
        assert trace["source_path"].endswith("scheduling_rules.json")
