from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from modules.api.operations import OperationRegistry


@pytest.fixture
def auth_client(client, bootstrap_token):
    with client as active_client:
        response = active_client.post(
            "/api/auth/exchange",
            headers={"X-PI-Bootstrap-Token": bootstrap_token},
        )
        assert response.status_code == 200
        yield active_client


def test_operation_lifecycle():
    registry = OperationRegistry()
    operation = registry.create("optimizer")
    registry.start(operation.id, phase="loading")
    registry.complete(operation.id, result={"assignments": 12})

    snapshot = registry.get(operation.id)

    assert snapshot.status == "completed"
    assert snapshot.result == {"assignments": 12}


def test_created_operation_cannot_mutate_stored_status():
    registry = OperationRegistry()
    operation = registry.create("optimizer")

    with pytest.raises(FrozenInstanceError):
        operation.status = "completed"

    assert registry.get(operation.id).status == "queued"


def test_complete_copies_the_input_result():
    registry = OperationRegistry()
    operation = registry.create("optimizer")
    result = {"assignments": [{"lesson_id": "lesson-1"}]}

    registry.complete(operation.id, result=result)
    result["assignments"][0]["lesson_id"] = "changed"

    assert registry.get(operation.id).result == {
        "assignments": [{"lesson_id": "lesson-1"}]
    }


def test_get_returns_a_deep_copy_of_the_result():
    registry = OperationRegistry()
    operation = registry.create("optimizer")
    registry.complete(
        operation.id,
        result={"assignments": [{"lesson_id": "lesson-1"}]},
    )

    snapshot = registry.get(operation.id)
    snapshot.result["assignments"][0]["lesson_id"] = "changed"

    assert registry.get(operation.id).result == {
        "assignments": [{"lesson_id": "lesson-1"}]
    }


def test_operation_failed_lifecycle():
    registry = OperationRegistry()
    operation = registry.create("optimizer")

    registry.start(operation.id, phase="optimizing")
    registry.fail(operation.id, error="No valid assignment")

    snapshot = registry.get(operation.id)
    assert snapshot.status == "failed"
    assert snapshot.phase == "failed"
    assert snapshot.error == "No valid assignment"


def test_operation_endpoint_requires_session(client):
    response = client.get("/api/operations/missing")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_operation_endpoint_returns_operation_envelope(auth_client):
    operation = auth_client.app.state.operation_registry.create("optimizer")
    auth_client.app.state.operation_registry.start(operation.id, phase="loading")

    response = auth_client.get("/api/operations/{0}".format(operation.id))

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_version"] is None
    assert payload["warnings"] == []
    assert payload["error"] is None
    data = payload["data"]
    assert data["id"] == operation.id
    assert data["kind"] == "optimizer"
    assert data["status"] == "running"
    assert data["phase"] == "loading"
    assert data["result"] is None
    assert data["error"] is None
    assert data["events"] == []
    assert data["started_at"]
    assert data["last_activity_at"]


def test_operation_events_are_bounded_and_timestamped():
    registry = OperationRegistry(max_events=5)
    operation = registry.create("optimizer")

    for index in range(8):
        registry.emit(
            operation.id,
            type="tick",
            source="python",
            label="tick {0}".format(index),
            detail={"index": index},
        )

    snapshot = registry.get(operation.id)
    assert [event.seq for event in snapshot.events] == [4, 5, 6, 7, 8]
    assert snapshot.events[-1].detail == {"index": 7}
    assert snapshot.events[-1].at
    assert snapshot.events[-1].elapsed_ms >= 0
    assert snapshot.last_activity_at == snapshot.events[-1].at


def test_operation_event_details_are_truncated():
    registry = OperationRegistry()
    operation = registry.create("optimizer")

    registry.emit(
        operation.id,
        type="note",
        source="python",
        label="note",
        detail={"reason": "x" * 1000},
    )

    event = registry.get(operation.id).events[0]
    assert len(event.detail["reason"]) == 300


def test_terminal_operations_are_evicted_beyond_the_retention_limit():
    registry = OperationRegistry(max_records=3)
    completed = []
    for _ in range(3):
        operation = registry.create("optimizer")
        registry.complete(operation.id, result={})
        completed.append(operation.id)

    running = registry.create("optimizer")
    registry.start(running.id, phase="working")

    assert len(completed) == 3
    with pytest.raises(KeyError):
        registry.get(completed[0])
    assert registry.get(completed[1]).status == "completed"
    assert registry.get(running.id).status == "running"


def test_get_returns_a_deep_copy_of_events():
    registry = OperationRegistry()
    operation = registry.create("optimizer")
    registry.emit(operation.id, type="tick", source="python", label="tick", detail={"index": 1})

    snapshot = registry.get(operation.id)
    snapshot.events[0].detail["index"] = 99

    assert registry.get(operation.id).events[0].detail == {"index": 1}


def test_unknown_operation_is_404(auth_client):
    response = auth_client.get("/api/operations/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OPERATION_NOT_FOUND"
