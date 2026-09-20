from __future__ import annotations

import json
import os
import time

import pytest

from modules.scheduler.logic.optimizer_learning_record import (
    FILE_NAME as OPTIMIZER_LEARNING_FILE,
    record_optimizer_run,
)
from modules.shared.session_manager import SessionManager
from modules.shared.save_outcome import SaveOutcome


@pytest.fixture
def auth_client(client, bootstrap_token):
    base_dir = client.app.state.config.base_dir
    (base_dir / "bookings.json").write_text("[]", encoding="utf-8")
    (base_dir / "rooms.json").write_text(
        json.dumps([{"id": "R103"}, {"id": "CC202"}]),
        encoding="utf-8",
    )
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps({"room_types": {"R103": ["Piano"], "CC202": ["Piano"]}}),
        encoding="utf-8",
    )
    SessionManager(base_dir=str(base_dir)).save_session(
        {
            "step4_edit_session": {
                "assignments": [
                    {
                        "id": "wk-1",
                        "type": "weekly_lesson",
                        "title": "Piano lesson",
                        "resourceId": "R103",
                        "daysOfWeek": [1],
                        "startTime": "09:00:00",
                        "endTime": "10:00:00",
                        "pinned": True,
                        "extendedProps": {"Instructor": "Instructor 0008"},
                    }
                ],
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            }
        }
    )
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def _workspace_version(client) -> str:
    return client.get("/api/workspace").json()["workspace_version"]


def _install_unresolved_issue(client):
    manager = client.app.state.scheduler_context.session_manager
    manager.save_session(
        {
            "step4_edit_session": {
                "assignments": [],
                "unassigned_lessons": [
                    {
                        "id": "wk_reject_S100_source-row-7",
                        "student": "Student 0001",
                        "sid": "S100",
                        "inst": "Instructor 0002",
                        "day": 1,
                        "start": 9,
                        "end": 10,
                        "instrument": "Piano",
                        "prefs": ["R103", "CC202"],
                        "raw_row": {
                            "Student Name": "Student 0001",
                            "Student No": "S100",
                            "Instructor": "Instructor 0002",
                            "Course Code": "MUS101 Piano",
                            "Day of Week": "Monday",
                            "Class Time": "09:00-10:00",
                            "Preferred Venue": "R103, CC202",
                        },
                        "reason": "No feasible room",
                        "reason_code": "no_time_feasible_room",
                    }
                ],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            }
        }
    )


def _install_studio_issue(client):
    manager = client.app.state.scheduler_context.session_manager
    manager.save_session(
        {
            "step4_edit_session": {
                "assignments": [],
                "unassigned_lessons": [
                    {
                        "id": "stu-InstructorTwo-overnight-failed",
                        "type": "studio_class",
                        "student": "Studio",
                        "inst": "Instructor 0002",
                        "date": "2026-03-04",
                        "day": 5,
                        "start": "23:00",
                        "end": "01:00",
                        "instrument": "Piano",
                        "raw_row": {
                            "Instructor": "Instructor 0002",
                            "Course Code": "MUS101 Piano",
                            "Studio Date": "2026-03-04",
                            "Class Time": "23:00-01:00",
                        },
                        "reason": "No feasible room",
                        "reason_code": "no_time_feasible_room",
                    }
                ],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            }
        }
    )


def test_move_assignment_returns_fresh_scheduler_snapshot(auth_client):
    original_version = _workspace_version(auth_client)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": original_version,
            "teacher_confirmed": True,
            "teacher_confirmation_note": "Confirmed by Instructor 0008",
            "decision_note": "Preserves the preferred room sequence.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assignment = payload["data"]["assignments"][0]
    assert assignment["resourceId"] == "CC202"
    assert assignment["daysOfWeek"] == [2]
    assert assignment["startTime"] == "14:00:00"
    assert assignment["endTime"] == "15:00:00"
    assert payload["workspace_version"]
    assert payload["workspace_version"] != original_version
    assert payload["workspace_version"] == _workspace_version(auth_client)
    history = (
        auth_client.app.state.scheduler_context.session_manager.load_session()
        ["step4_edit_session"]["history"]
    )
    assert history[-1]["decision_note"] == (
        "Preserves the preferred room sequence."
    )


def test_move_and_undo_update_optimizer_intervention_ledger(auth_client):
    context = auth_client.app.state.scheduler_context
    state = context.session_manager.load_session()
    state["step4_edit_session"]["optimizer_run_id"] = "run-1"
    context.session_manager.save_session(state)
    record_optimizer_run(
        context.loader,
        run_id="run-1",
        input_workspace_version=_workspace_version(auth_client),
        state=state,
        rules={},
        duplicate_count=0,
        started_at="2026-07-30T09:00:00+00:00",
    )

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": _workspace_version(auth_client),
            "teacher_confirmed": True,
            "decision_note": "A research-relevant human choice.",
        },
    )
    assert response.status_code == 200
    ledger = context.loader.get_data(OPTIMIZER_LEARNING_FILE)
    event = ledger["runs"][0]["intervention_events"][0]
    assert event["active"] is True
    assert event["decision_note"] == "A research-relevant human choice."

    undo = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": response.json()["workspace_version"]},
    )
    assert undo.status_code == 200
    ledger = context.loader.get_data(OPTIMIZER_LEARNING_FILE)
    assert ledger["runs"][0]["intervention_events"][0]["active"] is False


def test_saved_draft_keeps_learning_projection_failure_visible(
    auth_client,
    monkeypatch,
):
    from modules.scheduler.logic import optimizer_learning_record

    context = auth_client.app.state.scheduler_context
    state = context.session_manager.load_session()
    state["step4_edit_session"]["optimizer_run_id"] = "run-1"
    record_optimizer_run(
        context.loader,
        run_id="run-1",
        input_workspace_version=_workspace_version(auth_client),
        state=state,
        rules={},
        duplicate_count=0,
        started_at="2026-07-30T09:00:00+00:00",
    )
    context.session_manager.save_session(state)
    def fail_save(*args, **kwargs):
        del args, kwargs
        raise OSError("learning ledger unavailable")

    monkeypatch.setattr(optimizer_learning_record, "_save_ledger", fail_save)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": _workspace_version(auth_client),
            "teacher_confirmed": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["assignments"][0]["resourceId"] == "CC202"
    assert "learning ledger unavailable" in " ".join(payload["warnings"])
    assert "needs repair" in " ".join(payload["data"]["warnings"])
    refreshed = auth_client.get("/api/scheduler/session").json()["data"]
    assert "needs repair" in " ".join(refreshed["warnings"])


def test_time_changed_move_requires_teacher_confirmation_without_mutation(auth_client):
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00",
            "end": "15:00",
            "expected_version": before["workspace_version"],
        },
    )

    assert response.status_code == 400
    assert "Teacher confirmation is required" in response.json()["error"]["message"]
    assert auth_client.get("/api/scheduler/session").json() == before


def test_move_preview_blocks_same_teacher_overlap_across_rooms(auth_client):
    manager = auth_client.app.state.scheduler_context.session_manager
    manager.save_session(
        {
            "step4_edit_session": {
                "assignments": [
                    {
                        "id": "a",
                        "resourceId": "R103",
                        "daysOfWeek": [1],
                        "startTime": "10:00:00",
                        "endTime": "11:00:00",
                        "extendedProps": {"Instructor": "Dr. Same"},
                    },
                    {
                        "id": "b",
                        "resourceId": "CC202",
                        "daysOfWeek": [1],
                        "startTime": "12:00:00",
                        "endTime": "13:00:00",
                        "extendedProps": {"Instructor": "dr. same"},
                    },
                ],
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
            }
        }
    )

    response = auth_client.post(
        "/api/scheduler/assignments/b/validate-move",
        json={"room": "CC202", "day": 1, "start": "10:00", "end": "11:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["success"] is False
    assert "Instructor time conflict" in response.json()["data"]["message"]


def test_invalid_move_returns_400_without_changing_assignments(auth_client):
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "15:00:00",
            "end": "14:00:00",
            "expected_version": before["workspace_version"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SCHEDULER_COMMAND_REJECTED"
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["workspace_version"] == before["workspace_version"]


def test_unknown_room_move_returns_400_without_changing_draft(auth_client):
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC999",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": before["workspace_version"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SCHEDULER_COMMAND_REJECTED"
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["data"]["draft"] == before["data"]["draft"]
    assert after["workspace_version"] == before["workspace_version"]


def test_validate_move_rejects_same_unknown_room_without_writing(auth_client):
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/validate-move",
        json={
            "room": "CC999",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["success"] is False
    assert response.json()["data"]["message"] == "Unknown room: CC999"
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["data"]["draft"] == before["data"]["draft"]
    assert after["workspace_version"] == before["workspace_version"]


@pytest.mark.parametrize("day", [-1, 7])
@pytest.mark.parametrize(
    ("path", "include_version"),
    [
        ("/api/scheduler/assignments/wk-1/validate-move", False),
        ("/api/scheduler/assignments/wk-1/move", True),
    ],
)
def test_move_day_outside_week_is_422_without_changes(
    auth_client,
    path,
    include_version,
    day,
):
    before = auth_client.get("/api/scheduler/session").json()
    payload = {
        "room": "CC202",
        "day": day,
        "start": "14:00:00",
        "end": "15:00:00",
    }
    if include_version:
        payload["expected_version"] = before["workspace_version"]

    response = auth_client.post(path, json=payload)

    assert response.status_code == 422
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["data"]["draft"] == before["data"]["draft"]
    assert after["workspace_version"] == before["workspace_version"]


@pytest.mark.parametrize(
    ("path", "include_version"),
    [
        ("/api/scheduler/assignments/wk-1/validate-move", False),
        ("/api/scheduler/assignments/wk-1/move", True),
    ],
)
def test_blank_move_room_is_422_without_changes(
    auth_client,
    path,
    include_version,
):
    before = auth_client.get("/api/scheduler/session").json()
    payload = {
        "room": "   ",
        "day": 2,
        "start": "14:00:00",
        "end": "15:00:00",
    }
    if include_version:
        payload["expected_version"] = before["workspace_version"]

    response = auth_client.post(path, json=payload)

    assert response.status_code == 422
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert after["data"]["draft"] == before["data"]["draft"]
    assert after["workspace_version"] == before["workspace_version"]


def test_validate_move_is_read_only_and_returns_structured_warnings(auth_client):
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/validate-move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == {
        "success": True,
        "message": None,
        "proposal_start": "14:00",
        "proposal_end": "15:00",
        "start_norm": "14:00",
        "end_norm": "15:00",
        "specific_date": None,
        "warnings": [],
        "requires_teacher_confirmation": True,
        "teacher_confirmation_message": (
            "Teacher confirmation is required before changing Instructor 0008's "
            "scheduled day or time."
        ),
    }
    after = auth_client.get("/api/scheduler/session").json()
    assert after["data"]["assignments"] == before["data"]["assignments"]
    assert payload["workspace_version"] == before["workspace_version"]
    assert after["workspace_version"] == before["workspace_version"]


def test_unresolved_issue_view_has_stable_source_identity_and_full_context(auth_client):
    _install_unresolved_issue(auth_client)

    response = auth_client.get("/api/scheduler/session")

    assert response.status_code == 200
    issue = response.json()["data"]["issues"][0]["items"][0]
    assert issue["id"] == "wk_reject_S100_source-row-7"
    assert issue["source_request_id"] == "wk_reject_S100_source-row-7"
    assert issue["instructor"] == "Instructor 0002"
    assert issue["course_code"] == "MUS101 Piano"
    assert issue["student_name"] == "Student 0001"
    assert issue["student_id"] == "S100"
    assert issue["type"] == "weekly_lesson"
    assert issue["instrument"] == "Piano"
    assert issue["duration_minutes"] == 60
    assert issue["original_day"] == 1
    assert issue["original_time"] == "09:00-10:00"
    assert issue["preferred_venues"] == ["R103", "CC202"]
    assert issue["room_types"] == ["Piano"]


def test_validate_unresolved_assignment_is_read_only_and_blocks_room_mismatch(auth_client):
    _install_unresolved_issue(auth_client)
    base_dir = auth_client.app.state.config.base_dir
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps({"room_types": {"R103": ["Piano"], "CC202": ["Voice"]}}),
        encoding="utf-8",
    )
    before = auth_client.get("/api/scheduler/session").json()

    response = auth_client.post(
        "/api/scheduler/issues/wk_reject_S100_source-row-7/validate-assignment",
        json={"room": "CC202", "day": 3, "start": "14:00", "end": "15:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "success": False,
        "message": "Room Type Mismatch. CC202 allows ['Voice'], but instrument is Piano.",
        "proposal_start": None,
        "proposal_end": None,
        "start_norm": None,
        "end_norm": None,
        "specific_date": None,
        "warnings": [],
        "requires_teacher_confirmation": False,
        "teacher_confirmation_message": None,
    }
    after = auth_client.get("/api/scheduler/session").json()
    assert after == before


def test_assign_unresolved_issue_returns_canonical_snapshot_and_round_trips_history(auth_client):
    _install_unresolved_issue(auth_client)
    before = auth_client.get("/api/scheduler/session").json()

    assigned = auth_client.post(
        "/api/scheduler/issues/wk_reject_S100_source-row-7/assign",
        json={
            "room": "R103",
            "day": 3,
            "start": "14:00",
            "end": "15:00",
            "expected_version": before["workspace_version"],
            "teacher_confirmed": True,
            "teacher_confirmation_note": "Instructor 0002 agreed by email",
        },
    )

    assert assigned.status_code == 200
    assigned_payload = assigned.json()
    assert assigned_payload["data"]["issues"] == []
    assert assigned_payload["data"]["metrics"]["assigned"] == 1
    assert assigned_payload["data"]["metrics"]["unresolved"] == 0
    assignment = assigned_payload["data"]["assignments"][0]
    assert assignment["source_request_id"] == "wk_reject_S100_source-row-7"
    assert assignment["raw_row"]["Preferred Venue"] == "R103, CC202"
    assert assignment["extendedProps"]["Preferred Venue"] == "R103, CC202"
    confirmation = assignment["extendedProps"]["teacher_time_change_confirmation"]
    assert confirmation["confirmed"] is True
    assert confirmation["instructor"] == "Instructor 0002"
    assert confirmation["note"] == "Instructor 0002 agreed by email"
    assert confirmation["confirmed_at"].endswith("+00:00")
    assert assigned_payload["data"]["draft"]["can_undo"] is True

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": assigned_payload["workspace_version"]},
    )
    assert undone.status_code == 200
    assert undone.json()["data"]["assignments"] == []
    assert undone.json()["data"]["issues"][0]["items"][0]["id"] == "wk_reject_S100_source-row-7"

    redone = auth_client.post(
        "/api/scheduler/draft/redo",
        json={"expected_version": undone.json()["workspace_version"]},
    )
    assert redone.status_code == 200
    assert redone.json()["data"]["issues"] == []
    assert redone.json()["data"]["assignments"][0]["resourceId"] == "R103"


def test_studio_validate_and_commit_reject_day_that_differs_from_original_date(auth_client):
    _install_studio_issue(auth_client)
    before = auth_client.get("/api/scheduler/session").json()
    assert before["data"]["issues"][0]["items"][0]["original_day"] == 3
    payload = {"room": "R103", "day": 4, "start": "23:00", "end": "01:00"}

    validation = auth_client.post(
        "/api/scheduler/issues/stu-InstructorTwo-overnight-failed/validate-assignment",
        json=payload,
    )
    committed = auth_client.post(
        "/api/scheduler/issues/stu-InstructorTwo-overnight-failed/assign",
        json={**payload, "expected_version": before["workspace_version"]},
    )

    expected_message = "Studio date 2026-03-04 is Wednesday; day must remain 3."
    assert validation.status_code == 200
    assert validation.json()["data"] == {
        "success": False,
        "message": expected_message,
        "proposal_start": None,
        "proposal_end": None,
        "start_norm": None,
        "end_norm": None,
        "specific_date": None,
        "warnings": [],
        "requires_teacher_confirmation": False,
        "teacher_confirmation_message": None,
    }
    assert committed.status_code == 400
    assert committed.json()["error"]["message"] == expected_message
    after = auth_client.get("/api/scheduler/session").json()
    assert after == before


def test_assign_unresolved_issue_rejects_stale_version_before_mutation(auth_client):
    _install_unresolved_issue(auth_client)
    stale_version = _workspace_version(auth_client)
    base_dir = auth_client.app.state.config.base_dir
    (base_dir / "scheduling_rules.json").write_text(
        '{"constraints":{"min_break_between_lessons":15}}',
        encoding="utf-8",
    )

    response = auth_client.post(
        "/api/scheduler/issues/wk_reject_S100_source-row-7/assign",
        json={
            "room": "R103",
            "day": 3,
            "start": "14:00",
            "end": "15:00",
            "expected_version": stale_version,
        },
    )

    assert response.status_code == 409
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["assignments"] == []
    assert session["issues"][0]["items"][0]["id"] == "wk_reject_S100_source-row-7"


def test_unassign_moves_assignment_into_issue_queue(auth_client):
    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/unassign",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["assignments"] == []
    issue_ids = [
        item["id"]
        for group in payload["data"]["issues"]
        for item in group["items"]
    ]
    assert issue_ids == ["wk-1"]
    assert payload["data"]["draft"]["can_undo"] is True
    assert payload["workspace_version"] == _workspace_version(auth_client)


def test_unassign_block_moves_contiguous_assignments_in_one_undo(auth_client):
    manager = auth_client.app.state.scheduler_context.session_manager
    manager.save_session(
        {
            "step4_edit_session": {
                "assignments": [
                    {
                        "id": "wk-1",
                        "type": "weekly_lesson",
                        "title": "Piano 1",
                        "resourceId": "R103",
                        "daysOfWeek": [1],
                        "startTime": "09:00:00",
                        "endTime": "10:00:00",
                        "pinned": True,
                        "extendedProps": {"Instructor": "Instructor 0008", "Student": "Ada"},
                    },
                    {
                        "id": "wk-2",
                        "type": "weekly_lesson",
                        "title": "Piano 2",
                        "resourceId": "R103",
                        "daysOfWeek": [1],
                        "startTime": "10:00:00",
                        "endTime": "11:00:00",
                        "pinned": True,
                        "extendedProps": {"Instructor": "Instructor 0008", "Student": "Ben"},
                    },
                    {
                        "id": "wk-3",
                        "type": "weekly_lesson",
                        "title": "Other room",
                        "resourceId": "CC202",
                        "daysOfWeek": [1],
                        "startTime": "11:00:00",
                        "endTime": "12:00:00",
                        "pinned": True,
                        "extendedProps": {"Instructor": "Instructor 0008", "Student": "Cara"},
                    },
                ],
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            }
        }
    )

    response = auth_client.post(
        "/api/scheduler/assignments/unassign-block",
        json={
            "assignment_ids": ["wk-1", "wk-2", "wk-1"],
            "expected_version": _workspace_version(auth_client),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    remaining = [item["id"] for item in payload["data"]["assignments"]]
    assert remaining == ["wk-3"]
    issue_ids = [
        item["id"]
        for group in payload["data"]["issues"]
        for item in group["items"]
    ]
    assert issue_ids == ["wk-1", "wk-2"]
    assert payload["data"]["draft"]["can_undo"] is True

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": payload["workspace_version"]},
    )
    assert undone.status_code == 200
    restored = [item["id"] for item in undone.json()["data"]["assignments"]]
    assert restored == ["wk-3", "wk-2", "wk-1"]
    assert undone.json()["data"]["issues"] == []


def test_unassign_block_rejects_locked_lectures(auth_client):
    manager = auth_client.app.state.scheduler_context.session_manager
    manager.save_session(
        {
            "step4_edit_session": {
                "assignments": [
                    {
                        "id": "lec-1",
                        "type": "lecture",
                        "title": "Theory",
                        "resourceId": "R103",
                        "daysOfWeek": [1],
                        "startTime": "09:00:00",
                        "endTime": "10:00:00",
                        "locked": True,
                    }
                ],
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            }
        }
    )
    response = auth_client.post(
        "/api/scheduler/assignments/unassign-block",
        json={
            "assignment_ids": ["lec-1"],
            "expected_version": _workspace_version(auth_client),
        },
    )
    assert response.status_code == 400
    assert auth_client.get("/api/scheduler/session").json()["data"]["assignments"][0]["id"] == "lec-1"


def test_unlock_clears_assignment_pin(auth_client):
    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/unlock",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["assignments"][0]["pinned"] is False
    assert payload["workspace_version"] == _workspace_version(auth_client)


def test_undo_and_redo_round_trip_last_draft_command(auth_client):
    moved = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": _workspace_version(auth_client),
            "teacher_confirmed": True,
        },
    )
    assert moved.status_code == 200

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": moved.json()["workspace_version"]},
    )

    assert undone.status_code == 200
    undone_assignment = undone.json()["data"]["assignments"][0]
    assert undone_assignment["resourceId"] == "R103"
    assert undone.json()["data"]["draft"]["can_redo"] is True

    redone = auth_client.post(
        "/api/scheduler/draft/redo",
        json={"expected_version": undone.json()["workspace_version"]},
    )

    assert redone.status_code == 200
    redone_assignment = redone.json()["data"]["assignments"][0]
    assert redone_assignment["resourceId"] == "CC202"
    assert redone.json()["data"]["draft"]["can_undo"] is True
    assert redone.json()["workspace_version"] == _workspace_version(auth_client)


def test_reset_uses_canonical_hard_reset_and_returns_empty_snapshot(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    session_path = base_dir / SessionManager.FILE_NAME
    assert session_path.exists()

    response = auth_client.post(
        "/api/scheduler/reset",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["assignments"] == []
    assert payload["data"]["issues"] == []
    assert payload["data"]["draft"] == {
        "dirty": False,
        "can_undo": False,
        "can_redo": False,
        "validation_state": "staged",
        "unsealed": False,
        "authority_stale": False,
        "save_status": "saved",
    }
    assert not session_path.exists()
    assert payload["workspace_version"] == _workspace_version(auth_client)


def test_reset_removes_committed_schedule_before_same_request_is_rerun(auth_client):
    base_dir = auth_client.app.state.config.base_dir
    issue_id = "wk_reject_S100_source-row-7"
    lecture = {
        "id": "lecture-keep",
        "type": "lecture",
        "title": "Theory",
        "resourceId": "CC202",
        "daysOfWeek": [2],
        "startTime": "15:00:00",
        "endTime": "16:00:00",
    }
    committed_copy = {
        "id": issue_id,
        "type": "weekly_lesson",
        "title": "Student 0001",
        "resourceId": "R103",
        "daysOfWeek": [1],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "committed": True,
        "extendedProps": {"Instructor": "Instructor 0002"},
    }
    (base_dir / "bookings.json").write_text(
        json.dumps([lecture, committed_copy]),
        encoding="utf-8",
    )
    _install_unresolved_issue(auth_client)

    before = auth_client.get("/api/scheduler/resolution/advice").json()
    assert before["data"]["cases"][0]["issues"][0]["reason"] == (
        "Teacher is occupied at the original time; same-day alternatives exist."
    )

    reset = auth_client.post(
        "/api/scheduler/reset",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert reset.status_code == 200
    assert json.loads((base_dir / "bookings.json").read_text(encoding="utf-8")) == [
        lecture
    ]

    _install_unresolved_issue(auth_client)
    after = auth_client.get("/api/scheduler/resolution/advice").json()
    assert after["data"]["cases"][0]["issues"][0]["reason"] == (
        "Original time is available in a compatible room."
    )


def test_start_round_two_returns_committed_bookings_as_locked_assignments(
    auth_client,
):
    base_dir = auth_client.app.state.config.base_dir
    committed = [
        {
            "id": "wk-committed",
            "type": "weekly_lesson",
            "title": "Committed lesson",
            "resourceId": "R103",
            "daysOfWeek": [1],
            "startTime": "09:00:00",
            "endTime": "10:00:00",
            "committed": True,
        }
    ]
    (base_dir / "bookings.json").write_text(
        json.dumps(committed),
        encoding="utf-8",
    )
    SessionManager(base_dir=str(base_dir)).save_session(
        {
            "round_committed": True,
            "step4_edit_session": {
                "assignments": committed,
                "unassigned_lessons": [],
                "history": [],
                "redo_stack": [],
                "dirty": False,
                "last_save_outcome": None,
            },
        }
    )

    response = auth_client.post(
        "/api/scheduler/rounds/start",
        json={"expected_version": _workspace_version(auth_client)},
    )

    assert response.status_code == 200
    locked = response.json()["data"]["locked_assignments"]
    assert [item["id"] for item in locked] == ["wk-committed"]
    assert all(item["committed"] is True for item in locked)
    assert response.json()["workspace_version"] == _workspace_version(auth_client)
    assert not (base_dir / SessionManager.FILE_NAME).exists()


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/scheduler/assignments/wk-1/move",
            {
                "room": "CC202",
                "day": 2,
                "start": "14:00:00",
                "end": "15:00:00",
            },
        ),
        ("/api/scheduler/assignments/wk-1/unassign", {}),
        ("/api/scheduler/assignments/wk-1/unlock", {}),
        ("/api/scheduler/draft/undo", {}),
        ("/api/scheduler/draft/redo", {}),
        ("/api/scheduler/reset", {}),
        ("/api/scheduler/rounds/start", {}),
    ],
)
def test_stale_mutations_return_workspace_changed_before_domain_work(
    auth_client,
    path,
    payload,
):
    stale_version = _workspace_version(auth_client)
    before = auth_client.get("/api/scheduler/session").json()["data"][
        "assignments"
    ]
    base_dir = auth_client.app.state.config.base_dir
    (base_dir / "scheduling_rules.json").write_text(
        '{"constraints":{"min_break_between_lessons":15}}',
        encoding="utf-8",
    )

    response = auth_client.post(
        path,
        json={**payload, "expected_version": stale_version},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    after = auth_client.get("/api/scheduler/session").json()["data"][
        "assignments"
    ]
    assert after == before


def test_session_cas_conflict_after_version_check_returns_409_without_move(
    auth_client,
    monkeypatch,
):
    context = auth_client.app.state.scheduler_context
    manager = context.session_manager
    original_save = manager.save_session
    original_version = _workspace_version(auth_client)
    injected = False

    def conflict_save(payload, expected_mtime=None):
        nonlocal injected
        if not injected:
            injected = True
            external_state = manager.load_session()
            original_save(external_state)
            future = time.time() + 2
            os.utime(manager._get_path(), (future, future))
        return original_save(payload, expected_mtime=expected_mtime)

    monkeypatch.setattr(manager, "save_session", conflict_save)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": original_version,
            "teacher_confirmed": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert response.json()["data"] is None
    persisted = auth_client.get("/api/scheduler/session").json()["data"]
    assert persisted["assignments"][0]["resourceId"] == "R103"
    assert persisted["draft"]["can_undo"] is False


def test_shadow_draft_save_returns_canonical_snapshot_with_warning(
    auth_client,
    monkeypatch,
):
    context = auth_client.app.state.scheduler_context
    manager = context.session_manager
    calls = 0
    warning = "Primary session save failed; wrote fallback shadow copy."

    def shadow_save(payload, expected_mtime=None):
        nonlocal calls
        del expected_mtime
        calls += 1
        shadow_path = manager._get_shadow_paths()[0]
        manager._atomic_write(shadow_path, payload, preserve_existing=False)
        future = time.time() + 2
        os.utime(shadow_path, (future, future))
        return SaveOutcome(
            status="shadow",
            path=shadow_path,
            warning=warning,
        )

    monkeypatch.setattr(manager, "save_session", shadow_save)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
            "expected_version": _workspace_version(auth_client),
            "teacher_confirmed": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["assignments"][0]["resourceId"] == "CC202"
    assert payload["warnings"] == [warning]
    assert calls == 1


def test_draft_mutation_holds_lock_through_persistence_and_version(
    auth_client,
    monkeypatch,
):
    from modules.api.routers import scheduler_draft as router_module

    context = auth_client.app.state.scheduler_context
    version = _workspace_version(auth_client)
    lock_observations = []
    original_execute = router_module.execute_draft_command
    original_compute = router_module.compute_workspace_version

    def lock_is_held():
        acquired = context.mutation_lock.acquire(blocking=False)
        if acquired:
            context.mutation_lock.release()
        return not acquired

    def observed_execute(*args, **kwargs):
        lock_observations.append(("execute", lock_is_held()))
        return original_execute(*args, **kwargs)

    def observed_compute(*args, **kwargs):
        lock_observations.append(("version", lock_is_held()))
        return original_compute(*args, **kwargs)

    monkeypatch.setattr(router_module, "execute_draft_command", observed_execute)
    monkeypatch.setattr(router_module, "compute_workspace_version", observed_compute)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/unlock",
        json={"expected_version": version},
    )

    assert response.status_code == 200
    assert lock_observations == [("execute", True), ("version", True)]


def test_validate_move_reads_under_snapshot_lock(auth_client, monkeypatch):
    from modules.api.routers import scheduler_draft as router_module

    context = auth_client.app.state.scheduler_context
    observed = []
    original_validate = router_module.validate_draft_move

    def observed_validate(*args, **kwargs):
        acquired = context.mutation_lock.acquire(blocking=False)
        observed.append(not acquired)
        if acquired:
            context.mutation_lock.release()
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(router_module, "validate_draft_move", observed_validate)

    response = auth_client.post(
        "/api/scheduler/assignments/wk-1/validate-move",
        json={
            "room": "CC202",
            "day": 2,
            "start": "14:00:00",
            "end": "15:00:00",
        },
    )

    assert response.status_code == 200
    assert observed == [True]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/scheduler/assignments/wk-1/validate-move",
            {"room": "CC202", "day": 2, "start": "14:00", "end": "15:00"},
        ),
        (
            "/api/scheduler/issues/issue-1/validate-assignment",
            {"room": "CC202", "day": 2, "start": "14:00", "end": "15:00"},
        ),
        (
            "/api/scheduler/issues/issue-1/assign",
            {
                "room": "CC202",
                "day": 2,
                "start": "14:00",
                "end": "15:00",
                "expected_version": "version",
            },
        ),
        (
            "/api/scheduler/assignments/wk-1/move",
            {
                "room": "CC202",
                "day": 2,
                "start": "14:00",
                "end": "15:00",
                "expected_version": "version",
            },
        ),
        (
            "/api/scheduler/assignments/wk-1/unassign",
            {"expected_version": "version"},
        ),
        (
            "/api/scheduler/assignments/wk-1/unlock",
            {"expected_version": "version"},
        ),
        ("/api/scheduler/draft/undo", {"expected_version": "version"}),
        ("/api/scheduler/draft/redo", {"expected_version": "version"}),
        ("/api/scheduler/reset", {"expected_version": "version"}),
        ("/api/scheduler/rounds/start", {"expected_version": "version"}),
    ],
)
def test_draft_routes_require_authentication(client, path, payload):
    response = client.post(path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
