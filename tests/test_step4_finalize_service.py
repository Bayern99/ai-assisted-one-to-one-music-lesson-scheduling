from types import SimpleNamespace

from modules.scheduler.logic.session_state import (
    SCHEDULER_DATA_SAVE_WARNING_KEY,
    SCHEDULER_SAVE_WARNING_KEY,
)
from modules.scheduler.logic import step4_service
from modules.scheduler.logic.validation_authority import seed_validation_authority


def _runtime_stub():
    controller = step4_service.Step4DraftController(
        session_mgr=object(),
        validator=object(),
        overrider=object(),
        edit_session={"assignments": [{"id": "draft_evt"}]},
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    return SimpleNamespace(
        loader=object(),
        session_mgr=object(),
        edit_session={"assignments": [{"id": "draft_evt"}]},
        draft_controller=controller,
    )


def test_finalize_step4_round_blocks_commit_when_conflicts_exist(monkeypatch):
    runtime = _runtime_stub()
    state = {}
    conflicts = [({"id": "a"}, {"id": "b"})]

    monkeypatch.setattr(
        step4_service,
        "collect_finalize_conflicts",
        lambda runtime, generated_assignments: (conflicts, ["warn-before-save"]),
    )

    def _unexpected_commit(*args, **kwargs):
        raise AssertionError("commit_current_round should not run when conflicts exist")

    monkeypatch.setattr(step4_service, "commit_current_round", _unexpected_commit)

    result = runtime.draft_controller.finalize(state)

    assert result.status == "blocked"
    assert result.conflicts == conflicts
    assert result.warnings == ["warn-before-save"]
    assert result.save_warnings == []
    assert result.final is None


def test_finalize_blocks_same_instructor_in_two_rooms():
    assignments = [
        {
            "id": "a",
            "source_request_id": "weekly:0",
            "resourceId": "R1",
            "daysOfWeek": [1],
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001", "Instrument": "Piano"},
        },
        {
            "id": "b",
            "source_request_id": "weekly:1",
            "resourceId": "R2",
            "daysOfWeek": [1],
            "startTime": "10:00:00",
            "endTime": "12:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001", "Instrument": "Piano"},
        },
    ]
    edit_session = {"assignments": assignments}
    seed_validation_authority(edit_session)
    controller = step4_service.Step4DraftController(
        session_mgr=object(),
        validator=step4_service.ConflictValidator(
            {"assignments": assignments, "lectures": [], "rules": {}}
        ),
        edit_session=edit_session,
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )
    controller.rooms_cache = [
        {"id": "R1", "types": ["Piano"]},
        {"id": "R2", "types": ["Piano"]},
    ]

    result = controller.finalize({})

    assert result.status == "blocked"
    assert len(result.conflicts) == 1
    assert any({item["id"] for item in pair if "id" in item} == {"a", "b"} for pair in result.conflicts)


def test_finalize_step4_round_returns_save_warnings_after_successful_commit(monkeypatch):
    runtime = _runtime_stub()
    state = {}
    saved_final = [{"id": "draft_evt"}]

    monkeypatch.setattr(
        step4_service,
        "collect_finalize_conflicts",
        lambda runtime, generated_assignments: ([], ["warn-before-save"]),
    )

    def _commit(loader, session_mgr, current_state):
        current_state[SCHEDULER_DATA_SAVE_WARNING_KEY] = "Bookings shadow save warning"
        current_state[SCHEDULER_SAVE_WARNING_KEY] = "Session cache shadow save warning"
        return saved_final

    monkeypatch.setattr(step4_service, "commit_current_round", _commit)

    result = runtime.draft_controller.finalize(state)

    assert result.status == "committed"
    assert result.conflicts == []
    assert result.warnings == ["warn-before-save"]
    assert result.save_warnings == [
        "Bookings shadow save warning",
        "Session cache shadow save warning",
    ]
    assert result.final == saved_final
    assert result.error is None


def test_finalize_step4_round_reports_commit_failure_without_swallowing_message(monkeypatch):
    runtime = _runtime_stub()
    state = {}

    monkeypatch.setattr(
        step4_service,
        "collect_finalize_conflicts",
        lambda runtime, generated_assignments: ([], ["warn-before-save"]),
    )

    def _commit(loader, session_mgr, current_state):
        raise OSError("disk full")

    monkeypatch.setattr(step4_service, "commit_current_round", _commit)

    result = runtime.draft_controller.finalize(state)

    assert result.status == "failed"
    assert result.warnings == ["warn-before-save"]
    assert result.save_warnings == []
    assert result.final is None
    assert result.error == "disk full"
