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
    assert response.json() == {
        "data": {
            "id": operation.id,
            "kind": "optimizer",
            "status": "running",
            "phase": "loading",
            "result": None,
            "error": None,
        },
        "workspace_version": None,
        "warnings": [],
        "error": None,
    }


def test_unknown_operation_is_404(auth_client):
    response = auth_client.get("/api/operations/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "OPERATION_NOT_FOUND"
