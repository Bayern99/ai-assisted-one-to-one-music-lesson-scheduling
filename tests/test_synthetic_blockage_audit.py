import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from modules.shared.data_loader import DataLoader
from modules.scheduler.logic.synthetic_blockage_audit import (
    audit_scheduler_state,
    build_booking_migration_plan,
    inspect_rules_health,
)


FIXTURE_DIR = Path("tests/fixtures/synthetic_blockage_audit")


def _weekly_df(rows):
    return pd.DataFrame(rows)


def test_inspect_rules_health_flags_probe_only_rules_as_degenerated():
    health = inspect_rules_health(
        {"probe": "scheduling_rules.json"},
        source_path="data/scheduling_rules.json",
    )

    assert health["rules_corrupted_or_degenerated"] is True
    assert health["status"] == "degenerated"
    assert "probe" in health["unknown_top_level_keys"]
    assert "priorities" in health["missing_canonical_top_level_keys"]
    assert "priorities" in health["canonical_rules_snapshot"]


def test_build_booking_migration_plan_classifies_legacy_and_transient_scheduler_items():
    raw_bookings = [
        {"id": "lec_1", "type": "lecture"},
        {"id": "legacy_weekly", "type": "committed_weekly"},
        {"id": "legacy_studio", "type": "committed_studio"},
        {"id": "committed_studio_old", "type": "studio", "committed": True},
        {"id": "draft_weekly", "type": "weekly_lesson"},
        {"id": "jury_hold", "type": "jury_hold"},
    ]

    plan = build_booking_migration_plan(raw_bookings, include_entries=True)
    by_id = {entry["id"]: entry for entry in plan["entries"]}

    assert by_id["lec_1"]["action"] == "keep_locked"
    assert by_id["legacy_weekly"]["action"] == "canonicalize_locked"
    assert by_id["legacy_weekly"]["canonical_type"] == "weekly_lesson"
    assert by_id["legacy_studio"]["action"] == "canonicalize_locked"
    assert by_id["legacy_studio"]["canonical_type"] == "studio_class"
    assert by_id["committed_studio_old"]["action"] == "canonicalize_locked"
    assert by_id["draft_weekly"]["action"] == "exclude_from_active_lock_set"
    assert by_id["jury_hold"]["action"] == "keep_locked"
    assert plan["summary"]["action_counts"]["canonicalize_locked"] == 3


def test_audit_scheduler_state_returns_structured_blockage_summary():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)
        loader.save_data(
            "students.json",
            [{"student_id": "S1", "name_en": "Student 0001", "instructor": "Instructor 0001", "type": "Piano"}],
        )
        loader.save_data("rooms.json", [{"id": "CC105", "type": "Percussion"}])
        loader.save_data("bookings.json", [])
        loader.save_data("semester_config.json", {"start_date": "2026-02-24", "end_date": "2026-06-30"})
        loader.save_data("instructors.json", [{"name": "Instructor 0001"}])
        loader.save_data("scheduling_rules.json", {"probe": "scheduling_rules.json"})

        weekly_df = _weekly_df(
            [
                {
                    "Student Name": "Student 0001",
                    "Student No": "S1",
                    "Instructor": "Instructor 0001",
                    "Study Year": "1",
                    "Course Code": "MUS101 (Piano)",
                    "Day of Week": "Monday",
                    "Class Time": "09:00-10:00",
                    "Preferred Venue": "UNKNOWN_ROOM",
                }
            ]
        )

        report = audit_scheduler_state(
            loader,
            weekly_df,
            pd.DataFrame(),
            previous_snapshot={"generated_assignments": [{"id": "old_1"}, {"id": "old_2"}]},
        )

        assert report["rules_health"]["rules_corrupted_or_degenerated"] is True
        assert report["optimizer_blockage_summary"]["generated_assignments"] == 0
        assert report["optimizer_blockage_summary"]["unassigned_lessons"] == 1
        assert report["optimizer_blockage_summary"]["reason_code_counts"]["invalid_preferred_venue"] == 1
        assert report["blocking_hotspots"]["invalid_preferred_venues"][0]["venue"] == "UNKNOWN_ROOM"
        assert report["comparative_regression"]["generated_delta"] == -2


def test_audit_scheduler_state_replays_frozen_live_snapshot():
    if not FIXTURE_DIR.exists():
        raise AssertionError("missing live blockage fixture directory")

    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        os.makedirs(base_dir, exist_ok=True)
        for file_name in (
            "session_cache.json",
            "bookings.json",
            "students.json",
            "rooms.json",
            "scheduling_rules.json",
            "semester_config.json",
            "instructors.json",
        ):
            shutil.copy2(FIXTURE_DIR / file_name, os.path.join(base_dir, file_name))

        with open(os.path.join(base_dir, "session_cache.json"), "r", encoding="utf-8") as fh:
            snapshot = json.load(fh)

        loader = DataLoader(base_dir=base_dir)
        report = audit_scheduler_state(
            loader,
            pd.DataFrame(snapshot["wk_df"]),
            pd.DataFrame(snapshot["stu_df"]),
            previous_snapshot=snapshot,
        )

        assert report["rules_health"]["rules_corrupted_or_degenerated"] is True
        assert report["booking_health"]["legacy_type_counts"]["committed_weekly"] > 0
        assert report["booking_health"]["legacy_type_counts"]["committed_studio"] > 0
        assert report["optimizer_blockage_summary"]["generated_assignments"] == 0
        assert report["optimizer_blockage_summary"]["unassigned_lessons"] == len(snapshot["wk_df"])
        assert report["comparative_regression"]["generated_delta"] < 0
