import json
import os
import ast
import tempfile
import time

from modules.shared.data_loader import DataLoader
from modules.shared.session_manager import SessionManager
from modules.scheduler.logic.optimizer import RoomAllocator


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def test_load_bookings_prefers_newer_shadow_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)

        primary_path = os.path.join(base_dir, "bookings.json")
        shadow_path = loader._shadow_paths("bookings.json")[0]

        _write_json(primary_path, [{"id": "primary_evt", "resourceId": "R1", "type": "weekly_lesson"}])
        _write_json(shadow_path, [{"id": "shadow_evt", "resourceId": "R2", "type": "weekly_lesson"}])

        now = time.time()
        os.utime(primary_path, (now - 60, now - 60))
        os.utime(shadow_path, (now, now))

        bookings = loader.load_bookings()
        assert [evt["id"] for evt in bookings] == ["shadow_evt"]
        metadata = loader.get_last_io_metadata("bookings.json")
        assert metadata["source"] == "shadow"
        assert metadata["selected_path"] == shadow_path
        assert metadata["warnings"]


def test_load_bookings_normalizes_legacy_committed_types():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)

        primary_path = os.path.join(base_dir, "bookings.json")
        _write_json(
            primary_path,
            [
                {"id": "w1", "resourceId": "R1", "type": "committed_weekly"},
                {"id": "s1", "resourceId": "R2", "type": "studio", "committed": True},
            ],
        )

        bookings = loader.load_bookings()
        assert bookings[0]["type"] == "weekly_lesson"
        assert bookings[0]["committed"] is True
        assert bookings[1]["type"] == "studio_class"


def test_save_data_records_shadow_fallback_metadata(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)
        primary_path = os.path.join(base_dir, "rules.json")
        shadow_path = loader._shadow_paths("rules.json")[0]

        calls = []

        def fake_atomic_save(path, data):
            calls.append(path)
            if path == primary_path:
                raise PermissionError("primary locked")

        monkeypatch.setattr(loader, "_atomic_save", fake_atomic_save)

        saved_path = loader.save_data("rules.json", {"ok": True})
        metadata = loader.get_last_io_metadata("rules.json")

        assert saved_path == shadow_path
        assert calls == [primary_path, shadow_path]
        assert metadata["source"] == "shadow"
        assert metadata["selected_path"] == shadow_path
        assert metadata["warnings"]


def test_save_data_shadow_fallback_is_immediately_readable(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)
        primary_path = os.path.join(base_dir, "rules.json")
        shadow_path = loader._shadow_paths("rules.json")[0]

        _write_json(primary_path, {"version": "primary"})
        original_atomic_save = loader._atomic_save

        def flaky_atomic_save(path, data):
            if path == primary_path:
                raise PermissionError("primary locked")
            return original_atomic_save(path, data)

        monkeypatch.setattr(loader, "_atomic_save", flaky_atomic_save)

        saved_path = loader.save_data("rules.json", {"version": "shadow"})
        reloaded = loader.get_data("rules.json")
        metadata = loader.get_last_io_metadata("rules.json")

        assert saved_path == shadow_path
        assert reloaded == {"version": "shadow"}
        assert metadata["source"] == "shadow"


def test_load_json_data_prefers_newer_shadow_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)

        primary_path = os.path.join(base_dir, "rules.json")
        shadow_path = loader._shadow_paths("rules.json")[0]

        _write_json(primary_path, {"version": "primary"})
        _write_json(shadow_path, {"version": "shadow"})

        now = time.time()
        os.utime(primary_path, (now - 60, now - 60))
        os.utime(shadow_path, (now, now))

        payload = loader.load_json_data("rules.json", default_value={})
        metadata = loader.get_last_io_metadata("rules.json")

        assert payload == {"version": "shadow"}
        assert metadata["source"] == "shadow"
        assert metadata["selected_path"] == shadow_path


def test_auto_schedule_is_explicitly_marked_legacy_experimental():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        loader = DataLoader(base_dir=base_dir)
        loader.save_data(
            "students.json",
            [{"student_id": "S1", "name_en": "Student 0001", "instructor": "Instructor 0001", "type": "Piano"}],
        )
        loader.save_data("rooms.json", [{"id": "R1", "type": "General"}])
        loader.save_data("bookings.json", [])

        result = loader.auto_schedule({}, clear_existing=False)

        assert result["mode"] == "legacy_csp"
        assert result["is_legacy"] is True
        assert result["is_experimental"] is True
        assert result["warnings"]


def test_clear_session_removes_shadow_cache_too():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = os.path.join(tmpdir, "data")
        manager = SessionManager(base_dir=base_dir)

        primary_path = os.path.join(base_dir, manager.FILE_NAME)
        shadow_path = manager._get_shadow_paths()[0]

        _write_json(primary_path, {"source": "primary"})
        _write_json(shadow_path, {"source": "shadow"})

        manager.clear_session()

        assert not os.path.exists(primary_path)
        assert not os.path.exists(shadow_path)


def test_optimizer_logs_actual_rules_source(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "shadow_rules.json")
        _write_json(rules_path, {"priorities": {}})

        allocator = RoomAllocator([], [], [], {}, rules_source_path=rules_path)
        _, _, logs = allocator.optimize(None, None)

    assert "Rules Source:" in logs[0]
    assert rules_path in logs[0]


def test_optimizer_module_has_no_direct_dataloader_import():
    path = os.path.join("modules", "scheduler", "logic", "optimizer.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "modules.shared.data_loader":
            for alias in node.names:
                imported_names.add(alias.name)

    assert "DataLoader" not in imported_names


def test_optimizer_module_has_no_local_datetime_imports():
    path = os.path.join("modules", "scheduler", "logic", "optimizer.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    local_datetime_imports = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "datetime"
    ]

    assert local_datetime_imports == []


def test_optimizer_module_has_no_legacy_top_level_calendar_or_json_imports():
    path = os.path.join("modules", "scheduler", "logic", "optimizer.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    top_level_imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_imports.add(alias.name)

    assert "calendar" not in top_level_imports
    assert "json" not in top_level_imports


def test_data_loader_module_has_no_direct_scheduler_imports():
    path = os.path.join("modules", "shared", "data_loader.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    scheduler_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("modules.scheduler"):
            scheduler_imports.add(node.module)

    assert scheduler_imports == set()


def test_data_loader_and_session_manager_delegate_atomic_writes_to_shared_helper():
    data_loader_source = open(
        os.path.join("modules", "shared", "data_loader.py"),
        "r",
        encoding="utf-8",
    ).read()
    session_manager_source = open(
        os.path.join("modules", "shared", "session_manager.py"),
        "r",
        encoding="utf-8",
    ).read()

    assert "from modules.shared.atomic_json_io import atomic_write_json" in data_loader_source
    assert "from modules.shared.atomic_json_io import atomic_write_json" in session_manager_source


def test_runtime_scheduler_paths_do_not_call_private_loader_read_helpers():
    for relpath in (
        os.path.join("modules", "scheduler", "context.py"),
        os.path.join("modules", "scheduler", "logic", "preflight.py"),
        os.path.join("modules", "scheduler", "logic", "synthetic_blockage_audit.py"),
        os.path.join("modules", "scheduler", "logic", "step4_service.py"),
    ):
        source = open(relpath, "r", encoding="utf-8").read()
        assert "_preferred_path_for_read(" not in source
        assert "_safe_load(" not in source


def test_runtime_scheduler_paths_do_not_import_legacy_scheduler_modules():
    runtime_source = "\n".join(
        open(relpath, "r", encoding="utf-8").read()
        for relpath in (
            os.path.join("modules", "api", "app.py"),
            os.path.join("modules", "scheduler", "context.py"),
            os.path.join("modules", "scheduler", "logic", "preflight.py"),
            os.path.join("modules", "scheduler", "logic", "synthetic_blockage_audit.py"),
            os.path.join("modules", "scheduler", "logic", "step4_service.py"),
        )
    )

    assert "gap_analysis" not in runtime_source
    assert "legacy_csp_adapter" not in runtime_source
    assert "logic.validation" not in runtime_source.replace("validation_authority", "")
    assert "modules.scheduler.logic.csp" not in runtime_source


def test_optimizer_logs_unavailable_rules_source_when_none():
    allocator = RoomAllocator([], [], [], {}, rules_source_path=None)
    _, _, logs = allocator.optimize(None, None)

    assert "Rules Source:" in logs[0]
    assert "Unavailable" in logs[0]


def test_test_path_optimizer_does_not_redefine_solver():
    path = os.path.join("tests", "test_path_optimizer.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)

    local_defs = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_solve_fragmented_block_min_switches" not in local_defs


def test_step4_commit_logic_test_file_removed():
    assert not os.path.exists(os.path.join("tests", "test_step4_commit_logic.py"))


def test_optimizer_finalize_studio_merge_helper_removed():
    assert not hasattr(RoomAllocator, "_finalize_studio_merge")


def test_optimizer_try_relocate_conflict_helper_removed():
    assert not hasattr(RoomAllocator, "_try_relocate_conflict")


# ── Semester config compatibility matrix (Report 7.5-5) ────────────────────

_SEMESTER_KEYS_MATRIX = [
    # (label, payload, expected_start, expected_end, expected_last_day)
    ("new-format start_date/end_date", {"start_date": "2026-02-24", "end_date": "2026-06-30"}, "2026-02-24", "2026-06-30", "2026-06-30"),
    ("new-format start_date/last_day", {"start_date": "2026-02-24", "last_day": "2026-06-30"}, "2026-02-24", "2026-06-30", "2026-06-30"),
    ("new-format start_date/end_date+last_day", {"start_date": "2026-02-24", "end_date": "2026-06-30", "last_day": "2026-06-30"}, "2026-02-24", "2026-06-30", "2026-06-30"),
    ("legacy-format start/end", {"start": "2026-02-24", "end": "2026-06-30"}, "2026-02-24", "2026-06-30", "2026-06-30"),
    ("mixed start/end_date+last_day_differs", {"start": "2026-02-24", "end_date": "2026-06-30", "last_day": "2026-06-25"}, "2026-02-24", "2026-06-30", "2026-06-25"),
    ("empty dict", {}, None, None, None),
]


def _make_semester_config_test(payload):
    import os, tempfile
    base_dir = tempfile.mkdtemp()
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "semester_config.json")
    if payload is not None:
        _write_json(path, payload)
    loader = DataLoader(base_dir=data_dir)
    return loader.load_semester_config()


def test_semester_config_returns_start_date_and_end_date_for_each_format():
    for label, payload, exp_start, exp_end, exp_last in _SEMESTER_KEYS_MATRIX:
        result = _make_semester_config_test(payload if payload is not None else {})
        if exp_start is None:
            assert result.get("start_date") is None, f"{label}: expected no start_date, got {result.get('start_date')}"
            assert result.get("end_date") is None, f"{label}: expected no end_date, got {result.get('end_date')}"
            assert result.get("last_day") is None, f"{label}: expected no last_day, got {result.get('last_day')}"
        else:
            assert result.get("start_date") == exp_start, f"{label}: start_date mismatch"
            assert result.get("end_date") == exp_end, f"{label}: end_date mismatch"
            assert result.get("last_day") == exp_last, f"{label}: last_day mismatch"


def test_semester_config_normalizes_legacy_start_key_to_start_date():
    result = _make_semester_config_test({"start": "2026-03-01", "end": "2026-07-15"})
    assert result.get("start_date") == "2026-03-01"
    assert result.get("end_date") == "2026-07-15"


def test_semester_config_normalizes_legacy_end_key_to_end_date_and_last_day():
    result = _make_semester_config_test({"start_date": "2026-03-01", "end": "2026-07-15"})
    assert result.get("end_date") == "2026-07-15"
    assert result.get("last_day") == "2026-07-15"


def test_semester_config_start_only_preserves_existing():
    result = _make_semester_config_test({"start": "2026-03-01"})
    assert result.get("start_date") == "2026-03-01"
    assert result.get("end_date") is None


def test_semester_config_end_only_preserves_existing():
    result = _make_semester_config_test({"end": "2026-07-15"})
    assert result.get("end_date") == "2026-07-15"
    assert result.get("last_day") == "2026-07-15"
