from __future__ import annotations

import copy
import json

import pytest

from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY
from modules.scheduler.logic.validation_authority import authority_assignments
from modules.shared.session_manager import SessionManager


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
        "extendedProps": {
            "Instructor": instructor,
            "source_request_id": event_id,
        },
    }


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
    (base_dir / "students.json").write_text("[]", encoding="utf-8")
    (base_dir / "instructors.json").write_text(
        json.dumps([{"name": "Instructor 0008"}]), encoding="utf-8"
    )
    (base_dir / "scheduling_rules.json").write_text("{}", encoding="utf-8")
    SessionManager(base_dir=str(base_dir)).save_session(
        {
            STEP4_EDIT_SESSION_KEY: {
                "assignments": [_assignment()],
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "validation_authority": {
                    "assignments": [_assignment()],
                    "unassigned_lessons": [],
                },
                "unsealed": False,
            }
        }
    )
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def _version(client):
    return client.get("/api/workspace").json()["workspace_version"]


def test_finalize_requires_stage_when_editing(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    session = SessionManager(base_dir=str(base_dir)).load_session()
    session[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] = "CC202"
    session[STEP4_EDIT_SESSION_KEY]["unsealed"] = True
    SessionManager(base_dir=str(base_dir)).save_session(session)

    response = auth_client.post(
        "/api/scheduler/finalize",
        json={"expected_version": _version(auth_client)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SCHEDULER_FINALIZE_REQUIRES_STAGE"


def test_stage_endpoint_copies_l0_to_l1(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    session = SessionManager(base_dir=str(base_dir)).load_session()
    moved = copy.deepcopy(session[STEP4_EDIT_SESSION_KEY]["assignments"][0])
    moved["resourceId"] = "CC202"
    session[STEP4_EDIT_SESSION_KEY]["assignments"] = [moved]
    session[STEP4_EDIT_SESSION_KEY]["unsealed"] = True
    session[STEP4_EDIT_SESSION_KEY]["dirty"] = True
    SessionManager(base_dir=str(base_dir)).save_session(session)
    version = _version(auth_client)

    response = auth_client.post(
        "/api/scheduler/stage",
        json={"expected_version": version},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["draft"]["validation_state"] == "staged"
    assert payload["draft"]["unsealed"] is False
    assert payload["assignments"][0]["resourceId"] == "CC202"
    persisted = SessionManager(base_dir=str(base_dir)).load_session()
    assert persisted[STEP4_EDIT_SESSION_KEY]["dirty"] is True
    assert authority_assignments(persisted[STEP4_EDIT_SESSION_KEY])[0]["resourceId"] == "CC202"
    assert persisted.get("round_committed") is None


def test_stage_undo_redo_pairs_l0_and_l1(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    session = SessionManager(base_dir=str(base_dir)).load_session()
    moved = copy.deepcopy(session[STEP4_EDIT_SESSION_KEY]["assignments"][0])
    moved["resourceId"] = "CC202"
    session[STEP4_EDIT_SESSION_KEY]["assignments"] = [moved]
    session[STEP4_EDIT_SESSION_KEY]["unsealed"] = True
    SessionManager(base_dir=str(base_dir)).save_session(session)
    version = _version(auth_client)
    assert auth_client.post("/api/scheduler/stage", json={"expected_version": version}).status_code == 200
    version = _version(auth_client)

    undo = auth_client.post("/api/scheduler/draft/undo", json={"expected_version": version})
    assert undo.status_code == 200
    undo_payload = undo.json()["data"]
    assert undo_payload["draft"]["validation_state"] == "editing"
    assert undo_payload["assignments"][0]["resourceId"] == "CC202"
    assert undo_payload["draft"]["authority_stale"] is True
    assert undo_payload["draft"]["unsealed"] is True

    version = _version(auth_client)
    redo = auth_client.post("/api/scheduler/draft/redo", json={"expected_version": version})
    assert redo.status_code == 200
    redo_payload = redo.json()["data"]
    assert redo_payload["draft"]["validation_state"] == "staged"
    assert redo_payload["assignments"][0]["resourceId"] == "CC202"


def test_session_payload_exposes_validation_state_and_labels(auth_client):
    response = auth_client.get("/api/scheduler/session")
    assert response.status_code == 200
    draft = response.json()["data"]["draft"]
    assert draft["validation_state"] in {"editing", "staged", "finalized"}
    assert "unsealed" in draft
    assert "authority_stale" in draft
    assert draft["save_status"] in {"saved", "degraded", "failed"}
    assert "reservation_classifications" in response.json()["data"]
