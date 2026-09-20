from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "workflow_state.json").write_text(
        json.dumps({"semester": "2026", "current_phase": "scheduling"}),
        encoding="utf-8",
    )
    (tmp_path / "activity_cache.json").write_text(
        json.dumps(
            {
                "page_title": "Smart Scheduler",
                "timestamp": "2026-07-11T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "rooms.json").write_text("[]", encoding="utf-8")
    return tmp_path


@pytest.fixture
def auth_client(client, bootstrap_token, data_dir):
    del data_dir
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def test_workspace_requires_session(client, data_dir):
    del data_dir

    response = client.get("/api/workspace")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_workspace_returns_persisted_state_activity_and_health(auth_client, data_dir):
    response = auth_client.get("/api/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["workflow_state"] == {
        "semester": "2026",
        "current_phase": "scheduling",
    }
    assert payload["data"]["activity"] == {
        "page_title": "Smart Scheduler",
        "timestamp": "2026-07-11T10:00:00",
    }
    assert payload["data"]["health"]["status"] in {"ok", "warning", "error"}
    assert payload["data"]["health"]["checks"]
    assert payload["workspace_version"]
    assert payload["warnings"] == []
    assert payload["error"] is None


def test_workspace_version_changes_when_bookings_change(auth_client, data_dir):
    before = auth_client.get("/api/workspace").json()["workspace_version"]
    (data_dir / "bookings.json").write_text('[{"id":"new"}]', encoding="utf-8")

    after = auth_client.get("/api/workspace").json()["workspace_version"]

    assert after != before


def test_workspace_version_changes_when_semester_config_changes(
    auth_client,
    data_dir,
):
    config_path = data_dir / "semester_config.json"
    config_path.write_text(
        json.dumps({"start_date": "2026-02-24", "end_date": "2026-06-30"}),
        encoding="utf-8",
    )
    before = auth_client.get("/api/workspace").json()["workspace_version"]

    config_path.write_text(
        json.dumps({"start_date": "2026-03-01", "end_date": "2026-07-15"}),
        encoding="utf-8",
    )
    after = auth_client.get("/api/workspace").json()["workspace_version"]

    assert after != before


def test_workspace_version_tracks_newer_logical_shadow_session(
    auth_client,
    data_dir,
):
    manager = auth_client.app.state.scheduler_context.session_manager
    primary_path = Path(manager._get_path())
    shadow_path = Path(manager._get_shadow_path())
    primary_path.write_text(json.dumps({"source": "primary"}), encoding="utf-8")
    now = time.time()
    os.utime(primary_path, (now - 2, now - 2))
    shadow_path.write_text(json.dumps({"source": "shadow-v1"}), encoding="utf-8")
    os.utime(shadow_path, (now - 1, now - 1))

    assert manager.load_session() == {"source": "shadow-v1"}
    before = auth_client.get("/api/workspace").json()["workspace_version"]

    shadow_path.write_text(
        json.dumps({"source": "shadow-v2", "changed": True}),
        encoding="utf-8",
    )
    os.utime(shadow_path, (now, now))
    assert manager.load_session() == {"source": "shadow-v2", "changed": True}
    after = auth_client.get("/api/workspace").json()["workspace_version"]

    assert after != before


def test_scheduler_context_is_initialized_at_startup_and_reused(
    auth_client,
    data_dir,
):
    del data_dir
    first_context = auth_client.app.state.scheduler_context
    first_response = auth_client.get("/api/workspace")
    second_response = auth_client.get("/api/workspace")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert auth_client.app.state.scheduler_context is first_context


def test_require_current_version_rejects_stale_token(data_dir):
    from modules.api.services.workspace import (
        WorkspaceChanged,
        compute_workspace_version,
        require_current_version,
    )

    with pytest.raises(WorkspaceChanged) as error:
        require_current_version(data_dir, "stale")

    assert error.value.status_code == 409
    assert error.value.code == "WORKSPACE_CHANGED"
    assert error.value.expected == "stale"
    assert error.value.current == compute_workspace_version(data_dir)


def test_require_current_version_accepts_current_token(data_dir):
    from modules.api.services.workspace import (
        compute_workspace_version,
        require_current_version,
    )

    expected = compute_workspace_version(data_dir)

    assert require_current_version(data_dir, expected) == expected


def test_read_workspace_snapshot_retries_an_external_write(
    data_dir,
    monkeypatch,
):
    from modules.api.services import workspace as workspace_service
    from modules.scheduler.context import build_scheduler_context

    context = build_scheduler_context(base_dir=str(data_dir))
    original_compute = workspace_service.compute_workspace_version
    version_reads = 0
    reader_calls = 0

    def compute_with_external_write(base_dir, *, context=None):
        nonlocal version_reads
        version = original_compute(base_dir, context=context)
        version_reads += 1
        if version_reads == 1:
            (data_dir / "rooms.json").write_text(
                '[{"id":"external"}]',
                encoding="utf-8",
            )
        return version

    def reader():
        nonlocal reader_calls
        reader_calls += 1
        return context.loader.load_workflow_state()

    monkeypatch.setattr(
        workspace_service,
        "compute_workspace_version",
        compute_with_external_write,
    )

    data, version = workspace_service.read_workspace_snapshot(
        data_dir,
        context,
        reader,
    )

    assert data == {"semester": "2026", "current_phase": "scheduling"}
    assert reader_calls == 2
    assert version == original_compute(data_dir, context=context)
