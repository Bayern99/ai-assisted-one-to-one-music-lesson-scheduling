from __future__ import annotations

from io import BytesIO
import json
import os
import time

import pandas as pd
import pytest

from modules.api.services.exports import ArtifactRegistry
from modules.shared.session_manager import SessionManager


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MIME = "application/zip"


def _assignment(event_id="wk-1", *, room="R103", instructor="Instructor 0008"):
    return {
        "id": event_id,
        "type": "weekly_lesson",
        "title": event_id,
        "resourceId": room,
        "source_request_id": event_id,
        "daysOfWeek": [1],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "pinned": True,
        "extendedProps": {
            "Instructor": instructor,
            "source_request_id": event_id,
            "Student Name": event_id,
            "Student No": event_id,
            "Course Code": "MUS101 (Piano)",
            "day_en": "Monday",
        },
    }


def _save_session(base_dir, assignments, *, history=None, dirty=True):
    return SessionManager(base_dir=str(base_dir)).save_session(
        {
            "step4_edit_session": {
                "assignments": assignments,
                "unassigned_lessons": [],
                "history": history or [],
                "redo_stack": [],
                "dirty": dirty,
                "last_save_outcome": None,
            }
        }
    )


@pytest.fixture
def auth_client(client, bootstrap_token):
    base_dir = client.app.state.config.base_dir
    (base_dir / "bookings.json").write_text("[]", encoding="utf-8")
    (base_dir / "rooms.json").write_text(
        json.dumps(
            [
                {"id": "R103", "type": ["Piano"], "types": ["Piano"]},
                {"id": "CC202", "type": ["Piano"], "types": ["Piano"]},
            ]
        ),
        encoding="utf-8",
    )
    (base_dir / "students.json").write_text(
        json.dumps([{"student_id": "wk-1", "name_en": "wk-1"}]),
        encoding="utf-8",
    )
    (base_dir / "instructors.json").write_text(
        json.dumps([{"name": "Instructor 0008"}]), encoding="utf-8"
    )
    (base_dir / "scheduling_rules.json").write_text("{}", encoding="utf-8")
    _save_session(base_dir, [_assignment()], history=[{"action": "move"}])
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def _version(client):
    return client.get("/api/workspace").json()["workspace_version"]


def test_finalize_success_uses_canonical_controller_and_returns_fresh_snapshot(auth_client):
    before_version = _version(auth_client)

    response = auth_client.post(
        "/api/scheduler/finalize",
        json={"expected_version": before_version},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["active_stage"] == "export"
    assert payload["data"]["draft"]["dirty"] is False
    assert payload["data"]["assignments"][0]["id"] == "wk-1"
    assert payload["workspace_version"] != before_version
    assert payload["workspace_version"] == _version(auth_client)
    bookings = json.loads(
        (auth_client.app.state.config.base_dir / "bookings.json").read_text(
            encoding="utf-8"
        )
    )
    assert bookings[0]["committed"] is True


def test_finalize_domain_conflict_returns_structured_pair_and_preserves_draft(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    assignments = [
        _assignment("wk-a", instructor="Instructor 0008"),
        _assignment("wk-b", instructor="Instructor 0009"),
    ]
    _save_session(base_dir, assignments, history=[{"action": "move"}], dirty=True)
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/finalize",
        json={"expected_version": before["workspace_version"]},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "SCHEDULER_FINALIZE_CONFLICT"
    assert error["details"]["conflicts"] == [
        {"event": assignments[0], "conflict": assignments[1]}
    ]
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["data"]["draft"] == before["data"]["draft"]
    persisted = SessionManager(base_dir=str(base_dir)).load_session()
    assert persisted["step4_edit_session"]["history"] == [{"action": "move"}]


def test_finalize_session_cas_conflict_is_409_and_rolls_back_bookings(
    auth_client, monkeypatch
):
    context = auth_client.app.state.scheduler_context
    manager = context.session_manager
    original_save = manager.save_session
    before_session = manager.load_session()
    before_version = _version(auth_client)
    injected = False

    def conflict_save(payload, expected_mtime=None):
        nonlocal injected
        if expected_mtime is not None and not injected:
            injected = True
            original_save(before_session)
            future = time.time() + 2
            os.utime(manager._get_path(), (future, future))
        return original_save(payload, expected_mtime=expected_mtime)

    monkeypatch.setattr(manager, "save_session", conflict_save)

    response = auth_client.post(
        "/api/scheduler/finalize",
        json={"expected_version": before_version},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert context.loader.load_bookings() == []
    persisted = manager.load_session()["step4_edit_session"]
    assert persisted["assignments"][0]["id"] == "wk-1"
    assert persisted["dirty"] is True
    assert persisted["history"] == [{"action": "move"}]


def test_finalize_rejects_stale_workspace_version_before_domain_work(auth_client):
    stale = _version(auth_client)
    base_dir = auth_client.app.state.config.base_dir
    (base_dir / "scheduling_rules.json").write_text(
        '{"constraints":{"min_break_between_lessons":15}}', encoding="utf-8"
    )
    before = SessionManager(base_dir=str(base_dir)).load_session()

    response = auth_client.post(
        "/api/scheduler/finalize", json={"expected_version": stale}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert SessionManager(base_dir=str(base_dir)).load_session() == before
    assert json.loads((base_dir / "bookings.json").read_text(encoding="utf-8")) == []


def test_build_and_download_artifacts_return_exact_bytes_and_safe_headers(auth_client):
    finalized = auth_client.post(
        "/api/scheduler/finalize",
        json={"expected_version": _version(auth_client)},
    )
    assert finalized.status_code == 200

    built = auth_client.post("/api/scheduler/exports/build")

    assert built.status_code == 200
    payload = built.json()
    assert payload["workspace_version"] == _version(auth_client)
    assert len(payload["data"]["artifacts"]) == 3
    by_name = {item["filename"]: item for item in payload["data"]["artifacts"]}
    assert sorted(by_name) == [
        "Instructor_Schedules.zip",
        "Master_Schedule.xlsx",
        "Weekly_Schedule.xlsx",
    ]
    assert by_name["Master_Schedule.xlsx"]["mime_type"] == XLSX_MIME
    assert by_name["Weekly_Schedule.xlsx"]["mime_type"] == XLSX_MIME
    assert by_name["Instructor_Schedules.zip"]["mime_type"] == ZIP_MIME
    assert payload["data"]["failed_assignments"] == []
    assert all("/" not in item["artifact_id"] for item in by_name.values())

    master = by_name["Master_Schedule.xlsx"]
    stored = auth_client.app.state.artifact_registry.get(
        master["artifact_id"], scope="scheduler"
    )
    downloaded = auth_client.get(
        "/api/scheduler/exports/{0}".format(master["artifact_id"])
    )
    wrong_scope = auth_client.get(
        "/api/assessment/exports/{0}".format(master["artifact_id"])
    )
    assert downloaded.status_code == 200
    assert wrong_scope.status_code == 404
    assert downloaded.content == stored.content
    assert downloaded.content.startswith(b"PK")
    assert downloaded.headers["content-type"] == XLSX_MIME
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="Master_Schedule.xlsx"'
    )
    bundle = by_name["Instructor_Schedules.zip"]
    bundle_download = auth_client.get(
        "/api/scheduler/exports/{0}".format(bundle["artifact_id"])
    )
    assert bundle_download.status_code == 200
    assert bundle_download.headers["content-type"] == ZIP_MIME
    assert bundle_download.content.startswith(b"PK")


def test_export_build_envelope_stays_valid_with_missing_booking_values(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    booking = _assignment("wk-missing")
    booking["extendedProps"]["Student Name"] = float("nan")
    booking["extendedProps"]["Study Year"] = None
    (base_dir / "bookings.json").write_text(
        json.dumps([booking]), encoding="utf-8"
    )

    response = auth_client.post("/api/scheduler/exports/build")

    assert response.status_code == 200
    payload = response.json()
    json.dumps(payload, allow_nan=False)
    assert payload["data"]["artifacts"]


def test_export_build_reports_failed_assignments_without_hiding_them(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    manager = SessionManager(base_dir=str(base_dir))
    state = manager.load_session()
    state["step4_edit_session"]["unassigned_lessons"] = [{
        "stable_issue_id": "issue-1",
        "reason_code": "NO_ROOM",
        "reason": "No compatible room remained",
        "raw_row": {
            "Student Name": "Student 0001",
            "Instructor": "Instructor 0008",
            "Course Code": "MUS101",
            "Optional Value": float("nan"),
        },
    }]
    manager.save_session(state)

    response = auth_client.post("/api/scheduler/exports/build")

    assert response.status_code == 200
    failures = response.json()["data"]["failed_assignments"]
    assert failures == [{
        "stable_issue_id": "issue-1",
        "reason_code": "NO_ROOM",
        "reason": "No compatible room remained",
        "raw_row": {
            "Student Name": "Student 0001",
            "Instructor": "Instructor 0008",
            "Course Code": "MUS101",
            "Optional Value": None,
        },
    }]


def test_export_build_copies_snapshot_under_lock_then_builds_without_lock(
    auth_client, monkeypatch
):
    from modules.api.routers import scheduler_exports

    context = auth_client.app.state.scheduler_context
    observed = []
    original_build = scheduler_exports.build_download_artifacts

    def observed_build(*args, **kwargs):
        acquired = context.mutation_lock.acquire(blocking=False)
        observed.append(acquired)
        if acquired:
            context.mutation_lock.release()
        return original_build(*args, **kwargs)

    monkeypatch.setattr(scheduler_exports, "build_download_artifacts", observed_build)

    response = auth_client.post("/api/scheduler/exports/build")

    assert response.status_code == 200
    assert observed == [True]


def test_export_build_retries_when_bookings_change_mid_snapshot(
    auth_client, monkeypatch
):
    context = auth_client.app.state.scheduler_context
    base_dir = auth_client.app.state.config.base_dir
    old_booking = _assignment("wk-old", room="R103")
    new_booking = _assignment("wk-new", room="CC202")
    (base_dir / "bookings.json").write_text(
        json.dumps([old_booking]), encoding="utf-8"
    )
    original_get_data = context.loader.get_data
    calls = 0

    def change_bookings_during_first_read(name):
        nonlocal calls
        result = original_get_data(name)
        if name == "students.json" and calls == 0:
            calls += 1
            (base_dir / "bookings.json").write_text(
                json.dumps([new_booking]), encoding="utf-8"
            )
        return result

    monkeypatch.setattr(context.loader, "get_data", change_bookings_during_first_read)

    response = auth_client.post("/api/scheduler/exports/build")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_version"] == _version(auth_client)
    master_id = next(
        item["artifact_id"]
        for item in payload["data"]["artifacts"]
        if item["filename"] == "Master_Schedule.xlsx"
    )
    workbook = auth_client.get(
        "/api/scheduler/exports/{0}".format(master_id)
    )
    master = pd.read_excel(BytesIO(workbook.content))
    assert set(master["Room"]) == {"CC202"}
    assert set(master["Student ID"]) == {"wk-new"}


def test_export_build_rejects_continuous_snapshot_churn_without_artifacts(
    auth_client, monkeypatch
):
    context = auth_client.app.state.scheduler_context
    base_dir = auth_client.app.state.config.base_dir
    original_get_data = context.loader.get_data
    calls = 0

    def change_bookings_during_every_read(name):
        nonlocal calls
        result = original_get_data(name)
        if name == "students.json":
            calls += 1
            booking = _assignment("wk-{0}".format(calls))
            booking["external_revision"] = "x" * calls
            (base_dir / "bookings.json").write_text(
                json.dumps([booking]), encoding="utf-8"
            )
        return result

    monkeypatch.setattr(context.loader, "get_data", change_bookings_during_every_read)

    response = auth_client.post("/api/scheduler/exports/build")

    assert response.status_code == 409
    payload = response.json()
    assert payload["data"] is None
    assert payload["error"]["code"] == "WORKSPACE_CHANGED"
    assert len(context.loader.load_bookings()) == 1
    assert len(auth_client.app.state.artifact_registry._artifacts) == 0


def test_export_download_unknown_traversal_and_auth_are_rejected(auth_client, client):
    assert auth_client.get("/api/scheduler/exports/not-an-id").status_code == 404
    traversal = auth_client.get(
        "/api/scheduler/exports/..%2F..%2Fbookings.json"
    )
    assert traversal.status_code in (404, 422)
    client.cookies.clear()
    assert client.post(
        "/api/scheduler/finalize", json={"expected_version": "version"}
    ).status_code == 401
    assert client.post("/api/scheduler/exports/build").status_code == 401
    assert client.get("/api/scheduler/exports/not-an-id").status_code == 401


def test_registry_copies_mutable_bytes_and_returns_frozen_artifacts():
    registry = ArtifactRegistry()
    source = bytearray(b"original")

    artifact_id = registry.register(
        scope="scheduler",
        filename="Master_Schedule.xlsx",
        mime_type=XLSX_MIME,
        content=source,
    )
    source[:] = b"changed!"

    stored = registry.get(artifact_id, scope="scheduler")
    assert stored.scope == "scheduler"
    assert stored.content == b"original"
    with pytest.raises(Exception):
        stored.content = b"replacement"
