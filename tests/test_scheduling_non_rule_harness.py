import json
import os
import sys
import tempfile
import time

import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scheduling_non_rule_harness import (  # noqa: E402
    build_locked_context,
    commit_current_round,
    export_current_state,
    persist_editor_state,
    persist_upload_state,
    restore_scheduler_state,
    run_step0_lock_lectures,
    run_step2_rules_roundtrip,
    run_step3_optimize,
    run_step3_optimize_perf_smoke,
    run_step5_export_perf_smoke,
    start_round_two,
)
from modules.shared.data_loader import DataLoader  # noqa: E402
from modules.shared.session_manager import SessionManager  # noqa: E402


FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "scheduler_harness",
)


def _fixture_text(name):
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _fixture_json(name):
    return json.loads(_fixture_text(name))


def _weekly_df(rows):
    return pd.DataFrame(rows)


def _studio_df(rows):
    return pd.DataFrame(rows)


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _test_loader_and_session(tmpdir):
    base_dir = os.path.join(tmpdir, "data")
    return DataLoader(base_dir=base_dir), SessionManager(base_dir=base_dir)


def _students_fixture():
    return [
        {"student_id": "S1", "name_en": "Student 0001", "instrument": "Piano"},
        {"student_id": "S2", "name_en": "Student 0002", "instrument": "Piano"},
    ]


def _rooms_fixture():
    return [
        {"id": "R101", "type": "Piano"},
        {"id": "R102", "type": "Voice"},
    ]


def test_step0_lecture_lock_overwrites_old_lectures_and_preserves_non_lectures():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, _ = _test_loader_and_session(tmpdir)
        loader.save_bookings(
            [
                {
                    "id": "old_lecture",
                    "resourceId": "CC999",
                    "startTime": "08:00:00",
                    "endTime": "09:00:00",
                    "daysOfWeek": [1],
                    "type": "lecture",
                },
                {
                    "id": "keep_weekly",
                    "resourceId": "R102",
                    "startTime": "13:00:00",
                    "endTime": "14:00:00",
                    "daysOfWeek": [1],
                    "type": "weekly_lesson",
                    "extendedProps": {"Instructor": "Keep Me"},
                },
            ]
        )

        result = run_step0_lock_lectures(loader, _fixture_text("lecture_conflict.csv"))
        bookings = result["bookings"]

        lecture_ids = {evt["id"] for evt in bookings if evt.get("type") == "lecture"}
        all_ids = {evt["id"] for evt in bookings}

        assert "old_lecture" not in all_ids
        assert "keep_weekly" in all_ids
        assert len(lecture_ids) == 1
        locked_lecture = next(evt for evt in bookings if evt.get("type") == "lecture")
        assert locked_lecture["resourceId"] == "R101"
        assert locked_lecture["locked"] is True


def test_step0_locked_lectures_block_step3_optimizer_at_same_slot():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)
        run_step0_lock_lectures(loader, _fixture_text("lecture_conflict.csv"))

        weekly_df = _weekly_df(_fixture_json("weekly_duplicate.json")[:1])
        state = run_step3_optimize(
            loader,
            session_mgr,
            weekly_df,
            None,
            students=_students_fixture(),
            rooms=[{"id": "R101", "type": "Piano"}],
            rules={"priorities": {"Piano": {"Piano": 10}}},
        )

        assert state["generated_assignments"] == []
        assert len(state["unassigned_lessons"]) == 1


def test_step1_upload_snapshot_round_trips_weekly_and_studio_names():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, session_mgr = _test_loader_and_session(tmpdir)

        persist_upload_state(
            session_mgr,
            weekly_df=_weekly_df(_fixture_json("weekly_duplicate.json")[:1]),
            studio_df=_studio_df(_fixture_json("studio_upload.json")),
            weekly_file_name="weekly_round_1.xlsx",
            studio_file_name="studio_round_1.xlsx",
        )
        restored = restore_scheduler_state(session_mgr)

        assert isinstance(restored["wk_df"], pd.DataFrame)
        assert isinstance(restored["stu_df"], pd.DataFrame)
        assert restored["weekly_file_name"] == "weekly_round_1.xlsx"
        assert restored["studio_file_name"] == "studio_round_1.xlsx"


def test_step2_rules_round_trip_saves_canonical_keys_and_surfaces_trace():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, _ = _test_loader_and_session(tmpdir)

        result = run_step2_rules_roundtrip(loader, _fixture_json("unsupported_rule_keys.json"))
        rules = result["reloaded_rules"]
        saved = result["saved_rules"]
        trace = result["trace"]

        assert rules["constraints"]["time_range"]["start"] == "09:00"
        assert rules["constraints"]["time_range"]["end"] == "23:00"
        assert "mystery_toggle" not in saved["constraints"]
        assert "experimental" not in saved
        assert "CustomRoom" not in saved["priorities"]
        assert "experimental" in trace["ignored_top_level_keys"]
        assert "constraints.mystery_toggle" in trace["ignored_nested_keys"]
        assert "priorities.CustomRoom" in trace["ignored_nested_keys"]


def test_step2_rules_shadow_file_wins_when_newer():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, _ = _test_loader_and_session(tmpdir)
        primary_path = os.path.join(tmpdir, "data", "scheduling_rules.json")
        shadow_path = loader._shadow_paths("scheduling_rules.json")[0]

        _write_json(primary_path, _fixture_json("rules_primary.json"))
        _write_json(shadow_path, _fixture_json("rules_shadow.json"))

        now = time.time()
        os.utime(primary_path, (now - 60, now - 60))
        os.utime(shadow_path, (now, now))

        loaded = loader.load_rules()
        assert loaded["priorities"]["Piano"]["Piano"] == 10


def test_step3_optimize_snapshot_tracks_duplicates_and_shadow_rules_source():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)
        primary_rules_path = os.path.join(tmpdir, "data", "scheduling_rules.json")
        shadow_rules_path = loader._shadow_paths("scheduling_rules.json")[0]

        _write_json(primary_rules_path, _fixture_json("rules_primary.json"))
        _write_json(shadow_rules_path, _fixture_json("rules_shadow.json"))

        now = time.time()
        os.utime(primary_rules_path, (now - 60, now - 60))
        os.utime(shadow_rules_path, (now, now))

        state = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")),
            None,
            students=_students_fixture(),
            rooms=[{"id": "R101", "type": "Piano"}],
        )

        assert len(state["assignments"]) == 1
        assert len(state["duplicates"]) == 1
        assert len(state["unassigned_lessons"]) == 1
        assert shadow_rules_path in state["opt_logs"][0]


def test_step3_locked_context_normalizes_legacy_committed_types():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, _ = _test_loader_and_session(tmpdir)
        loader.save_bookings(_fixture_json("legacy_committed_bookings.json"))

        locked = build_locked_context(loader.load_bookings())
        locked_by_id = {evt["id"]: evt for evt in locked}

        assert locked_by_id["legacy_weekly"]["type"] == "weekly_lesson"
        assert locked_by_id["legacy_weekly"]["committed"] is True
        assert locked_by_id["legacy_studio"]["type"] == "studio_class"
        assert locked_by_id["legacy_studio"]["committed"] is True


def test_step3_optimize_performance_smoke():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)

        rows = []
        for idx in range(60):
            rows.append(
                {
                    "Student Name": f"Student {idx}",
                    "Student No": f"S{idx}",
                    "Instructor": f"Dr. {idx % 5}",
                    "Study Year": "1",
                    "Course Code": "MUS101 (Piano)",
                    "Day of Week": "Monday" if idx % 2 == 0 else "Tuesday",
                    "Class Time": f"{9 + (idx % 6):02d}:00-{10 + (idx % 6):02d}:00",
                    "Preferred Venue": "R101",
                }
            )

        state, elapsed = run_step3_optimize_perf_smoke(
            loader,
            session_mgr,
            _weekly_df(rows),
            None,
            students=[{"student_id": f"S{idx}", "instrument": "Piano"} for idx in range(60)],
            rooms=[{"id": "R101", "type": "Piano"}, {"id": "R104", "type": "Piano"}],
            rules={"priorities": {"Piano": {"Piano": 10}}},
        )

        assert elapsed < 5.0
        assert len(state["opt_logs"]) > 0


def test_step4_commit_persists_current_round_and_preserves_legacy_context():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)
        loader.save_bookings(_fixture_json("legacy_committed_bookings.json"))

        state = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")[:1]),
            None,
            students=_students_fixture(),
            rooms=[{"id": "R101", "type": "Piano"}],
            rules={"priorities": {"Piano": {"Piano": 10}}},
        )
        final = commit_current_round(loader, session_mgr, state)
        final_ids = {evt["id"] for evt in final}

        assert state["round_committed"] is True
        assert "legacy_weekly" in final_ids
        assert "legacy_studio" in final_ids
        committed_new = [evt for evt in final if evt["id"].startswith("wk_")]
        assert committed_new[0]["committed"] is True


def test_step4_round_two_clears_session_but_keeps_committed_bookings():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)

        state = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")[:1]),
            None,
            students=_students_fixture(),
            rooms=[{"id": "R101", "type": "Piano"}],
            rules={"priorities": {"Piano": {"Piano": 10}}},
        )
        commit_current_round(loader, session_mgr, state)
        start_round_two(state, session_mgr)

        assert session_mgr.load_session() is None
        bookings = loader.load_bookings()
        assert bookings[0]["committed"] is True
        assert state.get("generated_assignments") is None


def test_step4_restore_prefers_newer_shadow_session_snapshot():
    with tempfile.TemporaryDirectory() as tmpdir:
        _, session_mgr = _test_loader_and_session(tmpdir)
        primary_path = os.path.join(tmpdir, "data", session_mgr.FILE_NAME)
        shadow_path = session_mgr._get_shadow_paths()[0]

        _write_json(primary_path, _fixture_json("session_primary.json"))
        _write_json(shadow_path, _fixture_json("session_shadow.json"))

        now = time.time()
        os.utime(primary_path, (now - 60, now - 60))
        os.utime(shadow_path, (now, now))

        restored = restore_scheduler_state(session_mgr)

        assert restored["wk_df"].iloc[0]["Student Name"] == "Shadow Student 0001"
        assert restored["override_history"] == [{"action": "shadow"}]


def test_step5_export_uses_disk_bookings_session_failures_and_studio_dates():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)
        loader.save_bookings(
            [
                {
                    "id": "wk_1",
                    "resourceId": "R101",
                    "startTime": "09:00:00",
                    "endTime": "10:00:00",
                    "daysOfWeek": [1],
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "Instructor": "Instructor 0001",
                        "Student Name": "Student 0001",
                        "Student No": "S1",
                        "Study Year": "1",
                        "Course Code": "MUS101 (Piano)",
                        "day_en": "Monday",
                    },
                },
                {
                    "id": "stu_Instructor 0004_1_0_opt",
                    "resourceId": "R102",
                    "start": "2026-03-30T19:00:00",
                    "end": "2026-03-30T20:00:00",
                    "type": "studio_class",
                    "extendedProps": {
                        "Instructor": "Instructor 0004",
                        "Instrument": "Voice",
                        "day_en": "Monday",
                        "class_time": "19:00-20:00",
                    },
                },
            ]
        )

        state = {
            "stu_df": _studio_df(_fixture_json("studio_upload.json")),
            "unassigned_lessons": [
                {
                    "id": "wk_reject_S2_1",
                    "student": "Student 0002",
                    "reason": "Duplicate Student Entry: S2",
                    "raw_row": {
                        "Instructor": "Dr. Y",
                        "Student Name": "Student 0002",
                        "Student No": "S2",
                        "Study Year": "1",
                        "Course Code": "MUS101 (Piano)",
                        "Day of Week": "Monday",
                        "Class Time": "10:00-11:00",
                    },
                }
            ],
        }
        persist_editor_state(session_mgr, state)
        restored = restore_scheduler_state(session_mgr)

        df = export_current_state(
            loader,
            restored,
            students=_students_fixture(),
            valid_instructors=["Instructor 0001", "Dr. Y", "Instructor 0004"],
        )

        studio_row = df[df["Event Type"] == "Studio Class"].iloc[0]
        assert set(df["Room"]) == {"R101", "R102", "Unassigned"}
        assert studio_row["Date"] == "2026-03-30"


def test_step5_export_prefers_newer_shadow_bookings_after_restore():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)
        primary_path = os.path.join(tmpdir, "data", "bookings.json")
        shadow_path = loader._shadow_paths("bookings.json")[0]

        _write_json(primary_path, _fixture_json("bookings_primary.json"))
        _write_json(shadow_path, _fixture_json("bookings_shadow.json"))

        now = time.time()
        os.utime(primary_path, (now - 60, now - 60))
        os.utime(shadow_path, (now, now))

        persist_editor_state(
            session_mgr,
            {
                "stu_df": pd.DataFrame(),
                "unassigned_lessons": [],
            },
        )
        restored = restore_scheduler_state(session_mgr)
        df = export_current_state(
            loader,
            restored,
            students=_students_fixture(),
            valid_instructors=["Instructor 0001"],
        )

        assert set(df["Room"]) == {"R102"}


def test_step5_export_performance_smoke():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, _ = _test_loader_and_session(tmpdir)

        bookings = []
        for idx in range(200):
            bookings.append(
                {
                    "id": f"wk_{idx}",
                    "resourceId": "R101" if idx % 2 == 0 else "R102",
                    "startTime": f"{9 + (idx % 6):02d}:00:00",
                    "endTime": f"{10 + (idx % 6):02d}:00:00",
                    "daysOfWeek": [1 + (idx % 5)],
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "Instructor": f"Dr. {idx % 10}",
                        "Student Name": f"Student {idx}",
                        "Student No": f"S{idx}",
                        "Study Year": "1",
                        "Course Code": "MUS101 (Piano)",
                        "day_en": "Monday",
                    },
                }
            )
        loader.save_bookings(bookings)

        df, elapsed = run_step5_export_perf_smoke(
            loader,
            {"stu_df": pd.DataFrame(), "unassigned_lessons": []},
            students=[{"student_id": f"S{idx}", "name_en": f"Student {idx}"} for idx in range(200)],
            valid_instructors=[f"Dr. {idx}" for idx in range(10)],
        )

        assert elapsed < 3.0
        assert len(df) == 200


def test_six_step_regression_harness_characterizes_end_to_end_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        loader, session_mgr = _test_loader_and_session(tmpdir)

        step0 = run_step0_lock_lectures(loader, _fixture_text("lecture_conflict.csv"))
        persist_upload_state(
            session_mgr,
            weekly_df=_weekly_df(_fixture_json("weekly_duplicate.json")),
            studio_df=_studio_df(_fixture_json("studio_upload.json")),
            weekly_file_name="weekly.xlsx",
            studio_file_name="studio.xlsx",
        )
        step2 = run_step2_rules_roundtrip(loader, _fixture_json("unsupported_rule_keys.json"))
        step3 = run_step3_optimize(
            loader,
            session_mgr,
            _weekly_df(_fixture_json("weekly_duplicate.json")),
            _studio_df(_fixture_json("studio_upload.json")),
            students=_students_fixture(),
            rooms=_rooms_fixture(),
            rules=step2["reloaded_rules"],
        )
        commit_current_round(loader, session_mgr, step3)
        exported = export_current_state(
            loader,
            restore_scheduler_state(session_mgr),
            students=_students_fixture(),
            valid_instructors=["Instructor 0001", "Instructor 0004"],
        )
        assert len(step0["lecture_candidates"]) == 1
        assert len(step3["duplicates"]) == 1
        assert step3["round_committed"] is True
        assert len(exported) >= 2

        start_round_two(step3, session_mgr)
        assert session_mgr.load_session() is None
