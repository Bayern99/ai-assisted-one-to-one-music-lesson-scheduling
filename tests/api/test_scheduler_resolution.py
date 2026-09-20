import json

import pytest

from modules.scheduler.logic.optimizer_learning_record import (
    record_optimizer_run,
)
from modules.scheduler.logic.validation_authority import seed_validation_authority
from modules.shared.session_manager import SessionManager


@pytest.fixture
def auth_client(client, bootstrap_token):
    base_dir = client.app.state.config.base_dir
    (base_dir / "bookings.json").write_text("[]", encoding="utf-8")
    (base_dir / "rooms.json").write_text(
        json.dumps([{"id": "R103", "type": "Piano"}]),
        encoding="utf-8",
    )
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps({"room_types": {"R103": ["Piano"]}}),
        encoding="utf-8",
    )
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def _version(client):
    return client.get("/api/workspace").json()["workspace_version"]


def _install_issue(client):
    base_dir = client.app.state.config.base_dir
    SessionManager(base_dir=str(base_dir)).save_session(
        {
            "step4_edit_session": {
                "assignments": [],
                "unassigned_lessons": [
                    {
                        "id": "issue-one",
                        "type": "weekly_lesson",
                        "instructor": "Instructor 0008",
                        "instrument": "Piano",
                        "day": 1,
                        "start": "10:00",
                        "end": "11:00",
                        "preferred_venues": ["R103"],
                    }
                ],
                "history": [],
                "redo_stack": [],
                "dirty": False,
            }
        }
    )


def _install_optimizer_case(client):
    base_dir = client.app.state.config.base_dir
    state = {
        "step4_edit_session": {
            "optimizer_run_id": "run-1",
            "assignments": [],
            "unassigned_lessons": [
                {
                    "id": "issue-one",
                    "source_request_id": "private-source-id",
                    "type": "weekly_lesson",
                    "student": "Student Secret",
                    "instructor": "Instructor Secret",
                    "instrument": "Piano",
                    "day": 1,
                    "start": "10:00",
                    "end": "11:00",
                    "preferred_venues": ["R103"],
                }
            ],
            "history": [],
            "redo_stack": [],
            "dirty": False,
        }
    }
    SessionManager(base_dir=str(base_dir)).save_session(state)
    record_optimizer_run(
        client.app.state.scheduler_context.loader,
        run_id="run-1",
        input_workspace_version=_version(client),
        state=state,
        rules={},
        duplicate_count=0,
        started_at="2026-07-30T10:00:00+00:00",
    )


def test_resolution_advice_is_read_only_and_groups_cases(auth_client):
    _install_issue(auth_client)
    before = _version(auth_client)

    response = auth_client.get("/api/scheduler/resolution/advice")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_version"] == before
    assert payload["data"]["summary"]["total"] == 1
    assert payload["data"]["summary"]["cases"] == 1


def test_review_draft_reports_ready_state(auth_client):
    _install_optimizer_case(auth_client)
    version = _version(auth_client)

    response = auth_client.post(
        "/api/scheduler/resolution/review-draft",
        json={"expected_version": version},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] in {"ready", "blocked", "integrity_blocked"}
    assert set(payload) >= {"status", "summary", "conflicts", "warnings", "integrity"}
    assert "assignments" in payload["summary"]


def test_pi_stays_unavailable_without_a_persisted_optimizer_baseline(auth_client):
    _install_issue(auth_client)
    state = auth_client.app.state.scheduler_context.session_manager.load_session()
    state["step4_edit_session"]["optimizer_run_id"] = "missing-run"
    auth_client.app.state.scheduler_context.session_manager.save_session(state)

    response = auth_client.get("/api/scheduler/resolution/advice")

    assert response.status_code == 200
    assert response.json()["data"]["pi_available"] is False


def test_resolution_case_can_enter_and_leave_waiting(auth_client):
    _install_issue(auth_client)
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    case_id = advice["data"]["cases"][0]["id"]

    waiting = auth_client.post(
        f"/api/scheduler/resolution/cases/{case_id}/waiting",
        json={
            "expected_version": advice["workspace_version"],
            "waiting": True,
            "note": "Ask teacher about 11:00",
        },
    )

    assert waiting.status_code == 200
    assert waiting.json()["data"]["cases"][0]["waiting"] is True
    persisted = SessionManager(
        base_dir=str(auth_client.app.state.config.base_dir)
    ).load_session()
    assert persisted["step4_edit_session"]["resolution_waiting"][case_id]["note"]

    resumed = auth_client.post(
        f"/api/scheduler/resolution/cases/{case_id}/waiting",
        json={
            "expected_version": waiting.json()["workspace_version"],
            "waiting": False,
            "note": "",
        },
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["cases"][0]["waiting"] is False


def test_waiting_requires_an_operator_note(auth_client):
    _install_issue(auth_client)
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    case_id = advice["data"]["cases"][0]["id"]

    response = auth_client.post(
        f"/api/scheduler/resolution/cases/{case_id}/waiting",
        json={
            "expected_version": advice["workspace_version"],
            "waiting": True,
            "note": "  ",
        },
    )

    assert response.status_code == 400
    assert "Waiting note" in response.json()["error"]["message"]


def test_piano_leverage_applies_atomically_and_undoes_as_one_action(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    (base_dir / "rooms.json").write_text(
        json.dumps([{"id": "R101"}, {"id": "R106"}]),
        encoding="utf-8",
    )
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps(
            {
                "room_types": {"R101": ["Piano"], "R106": ["Piano"]},
                "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
            }
        ),
        encoding="utf-8",
    )
    assignments = [
        {
            "id": "inst5-10",
            "source_request_id": "inst5-10",
            "type": "weekly_lesson",
            "resourceId": "R101",
            "daysOfWeek": [3],
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "extendedProps": {"Instructor": "Instructor 0005", "Instrument": "Piano"},
        },
        {
            "id": "inst5-11",
            "source_request_id": "inst5-11",
            "type": "weekly_lesson",
            "resourceId": "R106",
            "daysOfWeek": [3],
            "startTime": "11:00:00",
            "endTime": "12:00:00",
            "extendedProps": {"Instructor": "Instructor 0005", "Instrument": "Piano"},
        },
    ]
    unresolved = [
        {
            "id": "open-10",
            "source_request_id": "open-10",
            "type": "weekly_lesson",
            "instructor": "Instructor 0009",
            "instrument": "Piano",
            "day": 3,
            "start": "10:00",
            "end": "11:00",
            "preferred_venues": ["R101"],
        }
    ]
    edit_session = {
        "assignments": assignments,
        "unassigned_lessons": unresolved,
        "history": [],
        "redo_stack": [],
        "dirty": False,
    }
    seed_validation_authority(edit_session)
    SessionManager(base_dir=str(base_dir)).save_session(
        {"step4_edit_session": edit_session}
    )
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    proposal = advice["data"]["piano_leverage"][0]

    rejected = auth_client.post(
        f"/api/scheduler/resolution/piano-leverage/{proposal['id']}/apply",
        json={"expected_version": advice["workspace_version"]},
    )
    assert rejected.status_code == 400
    assert "Teacher confirmation" in rejected.json()["error"]["message"]

    applied = auth_client.post(
        f"/api/scheduler/resolution/piano-leverage/{proposal['id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "teacher_confirmed": True,
            "confirmation_note": "Instructor 0005 approved Friday R101",
        },
    )

    assert applied.status_code == 200
    assert applied.json()["data"]["metrics"]["unresolved"] == 0
    moved = [
        item for item in applied.json()["data"]["assignments"]
        if item["id"].startswith("inst5-")
    ]
    assert {tuple(item["daysOfWeek"]) for item in moved} == {(4,)}
    assert all(
        item["extendedProps"]["teacher_time_change_confirmation"]["confirmed"]
        for item in moved
    )
    persisted = SessionManager(base_dir=str(base_dir)).load_session()
    assert persisted["step4_edit_session"]["history"][-1]["action"] == "compound"

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": applied.json()["workspace_version"]},
    )
    assert undone.status_code == 200
    assert undone.json()["data"]["metrics"]["unresolved"] == 1
    restored = [
        item for item in undone.json()["data"]["assignments"]
        if item["id"].startswith("inst5-")
    ]
    assert {tuple(item["daysOfWeek"]) for item in restored} == {(3,)}
