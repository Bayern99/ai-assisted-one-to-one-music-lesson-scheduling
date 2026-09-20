from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig
from modules.shared.session_manager import SessionManager


class _SuccessfulOptimizer:
    def __init__(
        self,
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.entered = entered
        self.release = release
        self.unassigned = [
            {
                "id": "unassigned-1",
                "source_request_id": "weekly:1",
                "reason_code": "no_compatible_room",
                "reason": "No compatible room",
            }
        ]

    def optimize(self, weekly, studio):
        assert list(weekly["Student No"]) == ["S1", "S2"]
        assert studio is None
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        return (
            [
                {
                    "id": "assignment-1",
                    "resourceId": "R1",
                    "source_request_id": "weekly:0",
                    "daysOfWeek": [1],
                    "startTime": "10:00:00",
                    "endTime": "11:00:00",
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "Instructor": "Instructor 0008",
                        "Instrument": "Piano",
                        "Student No": "S1",
                    },
                }
            ],
            [{"id": "S1", "name": "Duplicate Student"}],
            ["optimizer success"],
        )


def _poll_operation(
    client: TestClient,
    operation_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    timeout: float = 5,
) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/operations/{operation_id}")
        assert response.status_code == 200
        last = response.json()["data"]
        if (status is None or last["status"] == status) and (
            phase is None or last["phase"] == phase
        ):
            return last
        time.sleep(0.01)
    pytest.fail(f"operation did not reach status={status} phase={phase}: {last}")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "students.json").write_text(
        json.dumps(
            [
                {
                    "student_id": "S1",
                    "name": "Student 0001",
                    "instrument": "Piano",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "rooms.json").write_text(
        json.dumps([{"id": "R1", "types": ["Piano"], "capacity": 10}]),
        encoding="utf-8",
    )
    (tmp_path / "bookings.json").write_text("[]", encoding="utf-8")
    (tmp_path / "scheduling_rules.json").write_text(
        json.dumps({"room_types": {"R1": ["Piano"]}}),
        encoding="utf-8",
    )
    (tmp_path / "semester_config.json").write_text(
        json.dumps({"start_date": "2026-03-01", "end_date": "2026-06-15"}),
        encoding="utf-8",
    )
    SessionManager(base_dir=str(tmp_path)).save_session(
        {
            "wk_df": [
                {
                    "Student No": "S1",
                    "Student Name": "Student 0001",
                    "Instructor": "Instructor 0008",
                    "Day of Week": "Monday",
                    "Class Time": "10:00-11:00",
                    "Course Code": "MUS100",
                },
                {
                    "Student No": "S2",
                    "Student Name": "Student 0002",
                    "Instructor": "Instructor 0009",
                    "Day of Week": "Tuesday",
                    "Class Time": "11:00-12:00",
                    "Course Code": "MUS101",
                },
            ],
            "stu_df": None,
            "opt_logs": [],
        }
    )
    return tmp_path


@pytest.fixture
def auth_client(
    data_dir: Path,
    bootstrap_token: str,
) -> Iterator[TestClient]:
    config = AppConfig(
        base_dir=data_dir,
        bootstrap_token=bootstrap_token,
        frontend_dir=None,
        allow_test_host=True,
    )
    with TestClient(create_app(config)) as active_client:
        response = active_client.post(
            "/api/auth/exchange",
            headers={"X-PI-Bootstrap-Token": bootstrap_token},
        )
        assert response.status_code == 200
        yield active_client


def _workspace_version(client: TestClient) -> str:
    value = client.get("/api/workspace").json()["workspace_version"]
    assert value
    return value


def test_optimizer_preflight_reports_current_authoritative_health(auth_client):
    response = auth_client.get("/api/scheduler/optimize/preflight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["is_blocked"] is False
    assert payload["data"]["issues"] == []
    assert payload["data"]["room_health"]["rooms_corrupted_or_degenerated"] is False
    assert payload["workspace_version"] == _workspace_version(auth_client)


def test_optimize_requires_explicit_rerun_mode_for_dirty_step4_draft(
    auth_client,
    data_dir,
):
    manager = SessionManager(base_dir=str(data_dir))
    state = manager.load_session()
    state["step4_edit_session"] = {
        "assignments": [],
        "unassigned_lessons": [],
        "history": [{"action": "move"}],
        "dirty": True,
    }
    manager.save_session(state)

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OPTIMIZER_RERUN_MODE_REQUIRED"


def test_optimize_returns_202_tracks_phases_and_preserves_run_evidence(
    auth_client,
    monkeypatch,
):
    entered = threading.Event()
    release = threading.Event()
    persisting_entered = threading.Event()
    release_persist = threading.Event()
    context = auth_client.app.state.scheduler_context
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda *args, **kwargs: _SuccessfulOptimizer(
            entered=entered,
            release=release,
        ),
    )
    save_calls = 0
    original_save = context.session_manager.save_session

    def counting_save(*args, **kwargs):
        nonlocal save_calls
        save_calls += 1
        persisting_entered.set()
        assert release_persist.wait(timeout=5)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(context.session_manager, "save_session", counting_save)
    version = _workspace_version(auth_client)

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": version},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "data": {
            "operation_id": payload["data"]["operation_id"],
            "status": "queued",
        },
        "workspace_version": version,
        "warnings": [],
        "error": None,
    }
    operation_id = payload["data"]["operation_id"]
    assert entered.wait(timeout=5)
    running = _poll_operation(
        auth_client,
        operation_id,
        status="running",
        phase="optimizing",
    )
    assert running["result"] is None

    release.set()
    assert persisting_entered.wait(timeout=5)
    persisting = _poll_operation(
        auth_client,
        operation_id,
        status="running",
        phase="persisting",
    )
    assert persisting["result"] is None
    release_persist.set()
    completed = _poll_operation(
        auth_client,
        operation_id,
        status="completed",
        phase="completed",
    )
    assert completed["result"] == {
        "assignment_count": 1,
        "unassigned_count": 1,
        "duplicate_count": 1,
        "duplicates": [{"id": "S1", "name": "Duplicate Student"}],
            "logs": ["optimizer success"],
            "rerun_mode": "fresh",
            "preserved_pin_count": 0,
            "downgraded_pin_count": 0,
            "downgraded_pins": [],
        }
    assert save_calls == 1
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["metrics"]["assigned"] == 1
    assert session["metrics"]["unresolved"] == 1
    records = auth_client.get("/api/scheduler/optimize/records")
    assert records.status_code == 200
    latest = records.json()["data"]["latest"]
    assert latest["run_id"] == operation_id
    assert latest["status"] == "open"
    assert latest["baseline"] == {
        "assigned": 1,
        "unresolved": 1,
        "duplicates": 1,
        "allocation_rate": 0.5,
        "failure_counts": {"no_compatible_room": 1},
        "expected_requests": 0,
        "accounted_requests": 0,
        "reconciliation_anomaly_count": 0,
            "rerun_mode": "fresh",
            "preserved_pin_count": 0,
            "downgraded_pin_count": 0,
            "downgraded_pins": [],
        }


def test_optimizer_surfaces_and_repairs_a_learning_projection_failure(
    auth_client,
    monkeypatch,
):
    from modules.api.services import scheduler as scheduler_service

    context = auth_client.app.state.scheduler_context
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda *args, **kwargs: _SuccessfulOptimizer(),
    )
    original_record = scheduler_service.record_optimizer_run
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("learning ledger unavailable")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(scheduler_service, "record_optimizer_run", fail_once)
    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": _workspace_version(auth_client)},
    )
    operation_id = response.json()["data"]["operation_id"]

    completed = _poll_operation(
        auth_client,
        operation_id,
        status="completed",
        phase="completed",
    )

    assert completed["result"]["learning_record_warning"] == (
        "Optimizer completed, but its learning record needs repair: "
        "learning ledger unavailable"
    )
    records = auth_client.get("/api/scheduler/optimize/records")
    assert records.status_code == 200
    assert records.json()["data"]["latest"]["run_id"] == operation_id


def test_optimize_blocked_preflight_fails_without_changing_session(
    auth_client,
    data_dir,
):
    (data_dir / "rooms.json").write_text(
        json.dumps([{"id": "R1", "types": []}]),
        encoding="utf-8",
    )
    (data_dir / "scheduling_rules.json").write_text("{}", encoding="utf-8")
    session_path = data_dir / SessionManager.FILE_NAME
    before = session_path.read_bytes()

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 202
    failed = _poll_operation(
        auth_client,
        response.json()["data"]["operation_id"],
        status="failed",
    )
    assert "Room inventory" in failed["error"]
    assert session_path.read_bytes() == before


def test_optimize_failure_does_not_persist_partial_state(
    auth_client,
    data_dir,
    monkeypatch,
):
    class _FailingOptimizer:
        unassigned = []

        def optimize(self, weekly, studio):
            raise RuntimeError("optimizer exploded")

    context = auth_client.app.state.scheduler_context
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda *args, **kwargs: _FailingOptimizer(),
    )
    session_path = data_dir / SessionManager.FILE_NAME
    before = session_path.read_bytes()

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": _workspace_version(auth_client)},
    )

    failed = _poll_operation(
        auth_client,
        response.json()["data"]["operation_id"],
        status="failed",
    )
    assert failed["error"] == "optimizer exploded"
    assert session_path.read_bytes() == before


def test_optimize_rejects_stale_version_before_enqueue(auth_client, data_dir):
    stale_version = _workspace_version(auth_client)
    (data_dir / "bookings.json").write_text('[{"id":"changed"}]', encoding="utf-8")

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": stale_version},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"


def test_queued_optimize_rechecks_version_before_optimizer_or_persistence(
    auth_client,
    data_dir,
    monkeypatch,
):
    blocker_entered = threading.Event()
    release_blocker = threading.Event()

    def block_worker():
        blocker_entered.set()
        assert release_blocker.wait(timeout=5)

    auth_client.app.state.operation_executor.submit(block_worker)
    assert blocker_entered.wait(timeout=5)

    optimizer_calls = 0
    context = auth_client.app.state.scheduler_context

    def make_optimizer(*args, **kwargs):
        nonlocal optimizer_calls
        optimizer_calls += 1
        return _SuccessfulOptimizer()

    monkeypatch.setattr(context, "make_optimizer", make_optimizer)
    session_path = data_dir / SessionManager.FILE_NAME
    before = session_path.read_bytes()
    version = _workspace_version(auth_client)

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": version},
    )
    assert response.status_code == 202
    operation_id = response.json()["data"]["operation_id"]
    (data_dir / "bookings.json").write_text(
        '[{"id":"changed-while-queued"}]',
        encoding="utf-8",
    )
    release_blocker.set()

    failed = _poll_operation(
        auth_client,
        operation_id,
        status="failed",
    )
    assert "Workspace changed" in failed["error"]
    assert optimizer_calls == 0
    assert session_path.read_bytes() == before


def test_optimize_rechecks_version_again_immediately_before_persistence(
    auth_client,
    data_dir,
    monkeypatch,
):
    entered = threading.Event()
    release = threading.Event()
    context = auth_client.app.state.scheduler_context
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda *args, **kwargs: _SuccessfulOptimizer(
            entered=entered,
            release=release,
        ),
    )
    session_path = data_dir / SessionManager.FILE_NAME
    before = session_path.read_bytes()

    response = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": _workspace_version(auth_client)},
    )
    operation_id = response.json()["data"]["operation_id"]
    assert entered.wait(timeout=5)
    (data_dir / "bookings.json").write_text(
        '[{"id":"changed-during-optimization"}]',
        encoding="utf-8",
    )
    release.set()

    failed = _poll_operation(auth_client, operation_id, status="failed")
    assert "Workspace changed" in failed["error"]
    assert session_path.read_bytes() == before


def test_optimizer_compare_and_commit_serializes_concurrent_bookings_writer(
    auth_client,
    data_dir,
    monkeypatch,
):
    context = auth_client.app.state.scheduler_context
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda *args, **kwargs: _SuccessfulOptimizer(),
    )

    from modules.api.services import workspace as workspace_service

    original_require = workspace_service.require_current_version
    final_guard_entered = threading.Event()
    release_final_guard = threading.Event()
    guard_count = 0
    count_lock = threading.Lock()

    def barrier_require(*args, **kwargs):
        nonlocal guard_count
        result = original_require(*args, **kwargs)
        with count_lock:
            guard_count += 1
            current_count = guard_count
        if current_count == 3:
            final_guard_entered.set()
            assert release_final_guard.wait(timeout=5)
        return result

    monkeypatch.setattr(
        workspace_service,
        "require_current_version",
        barrier_require,
    )
    initial_version = _workspace_version(auth_client)

    optimize = auth_client.post(
        "/api/scheduler/optimize",
        json={"expected_version": initial_version},
    )
    operation_id = optimize.json()["data"]["operation_id"]
    assert final_guard_entered.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        bookings_write = executor.submit(
            auth_client.put,
            "/api/scheduler/lectures",
            json={
                "lectures": [],
                "expected_version": initial_version,
            },
        )
        time.sleep(0.1)
        assert not bookings_write.done()
        release_final_guard.set()
        write_response = bookings_write.result(timeout=5)

    completed = _poll_operation(auth_client, operation_id, status="completed")
    assert completed["result"]["assignment_count"] == 1
    assert write_response.status_code == 409
    assert write_response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert json.loads((data_dir / "bookings.json").read_text(encoding="utf-8")) == []
