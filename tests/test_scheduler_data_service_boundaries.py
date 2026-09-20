from pathlib import Path


def test_lecture_application_service_uses_extracted_lecture_service():
    source = Path("modules/api/services/scheduler_configuration.py").read_text(
        encoding="utf-8"
    )

    assert "from modules.shared.scheduler_data_service import parse_lectures_from_csv" in source
    assert "from modules.scheduler.logic import lecture_service" in source
    assert "loader.parse_lectures_from_csv(" not in source
    assert "loader.save_lectures(" not in source


def test_shared_scheduler_data_service_no_longer_owns_lecture_saves():
    source = Path("modules/shared/scheduler_data_service.py").read_text(
        encoding="utf-8"
    )

    assert "def save_lectures(" not in source


def test_data_loader_scheduler_façades_are_removed():
    source = Path("modules/shared/data_loader.py").read_text(encoding="utf-8")

    assert "parse_lectures_from_csv" not in source
    assert "save_lectures" not in source
    assert "import_schedule_from_excel" not in source
    assert "export_schedule_to_excel" not in source
    assert "detect_scheduler_conflicts" not in source


def test_step4_application_service_uses_runtime_draft_controller_boundary():
    source = Path("modules/api/services/scheduler.py").read_text(encoding="utf-8")

    assert "runtime.draft_controller" in source
    assert "controller.redo(" in source
    assert "runtime.overrider" not in source
    assert "apply_move_action" not in source
    assert "apply_undo_action" not in source
    assert "apply_unassign_action" not in source
    assert "apply_unlock_action" not in source
    assert "assign_failed_lesson" not in source
    assert "finalize_step4_round" not in source


def test_step4_runtime_does_not_expose_overrider_on_public_runtime():
    source = Path("modules/scheduler/logic/step4_service.py").read_text(encoding="utf-8")

    assert "overrider: ManualOverrider" not in source


def test_manual_override_module_is_now_only_a_legacy_shim():
    source = Path("modules/scheduler/logic/manual_override.py").read_text(encoding="utf-8")

    assert "from modules.scheduler.logic.manual_override_legacy import ManualOverrider" in source
    assert "def move_slot(" not in source
    assert "def unassign_slot(" not in source
    assert "def undo(" not in source
    assert "def redo(" not in source


def test_runtime_scheduler_paths_do_not_import_manual_override_legacy():
    runtime_source = "\n".join(
        Path(relpath).read_text(encoding="utf-8")
        for relpath in (
            "modules/api/services/scheduler.py",
            "modules/api/services/scheduler_resolution.py",
            "modules/scheduler/logic/step4_service.py",
            "modules/scheduler/logic/step4_resolution_actions.py",
        )
    )

    assert "manual_override_legacy" not in runtime_source


def test_runtime_scheduler_paths_do_not_import_manual_override_shim():
    runtime_source = "\n".join(
        Path(relpath).read_text(encoding="utf-8")
        for relpath in (
            "modules/api/services/scheduler.py",
            "modules/api/services/scheduler_resolution.py",
            "modules/scheduler/logic/step4_service.py",
            "modules/scheduler/logic/step4_resolution_actions.py",
        )
    )

    assert "from modules.scheduler.logic.manual_override import ManualOverrider" not in runtime_source


def test_data_loader_has_no_scheduler_adapter():
    source = Path("modules/shared/data_loader.py").read_text(encoding="utf-8")

    assert "_scheduler_adapter" not in source
    assert "data_loader_scheduler_adapter" not in source


