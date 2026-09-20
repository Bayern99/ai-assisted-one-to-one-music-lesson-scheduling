from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig
from modules.scheduler.context import build_scheduler_context
from modules.scheduler.logic.session_state import (
    SCHEDULER_SESSION_REVISION_KEY,
    STEP4_EDIT_SESSION_KEY,
)
from modules.shared.session_manager import SessionManager


PROHIBITED_PRESENTATION_KEYS = (
    "backgroundColor",
    "borderColor",
    "textColor",
    "color",
    "className",
    "classNames",
    "display",
)


def test_scheduler_api_does_not_import_retired_page_package():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import modules.api.app; "
                "assert not any(name.startswith('modules.scheduler.pages') for name in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.fixture
def seeded_scheduler(tmp_path: Path) -> dict:
    rooms_path = tmp_path / "rooms.json"
    bookings_path = tmp_path / "bookings.json"
    rules_path = tmp_path / "scheduling_rules.json"
    instructors_path = tmp_path / "instructors.json"
    rooms_path.write_text(
        json.dumps(
            [
                {
                    "id": "R104",
                    "capacity": 24,
                    "backgroundColor": "#ff0000",
                    "color": "#000000",
                    "classNames": ["legacy-room-style"],
                    "legacyZone": "north",
                },
                {"id": "R107B", "capacity": 16},
            ]
        ),
        encoding="utf-8",
    )
    bookings_path.write_text("[]", encoding="utf-8")
    rules_path.write_text("{}", encoding="utf-8")
    instructors_path.write_text(
        json.dumps([{"name": "Teacher C", "status": "Active"}]),
        encoding="utf-8",
    )

    session_manager = SessionManager(base_dir=str(tmp_path))
    session_manager.save_session(
        {
            "wk_df": [{"Instructor": "Instructor 0008"}],
            "stu_df": [{"Instructor": "Instructor 0009"}],
            STEP4_EDIT_SESSION_KEY: {
                "assignments": [
                    {
                        "id": "a-1",
                        "title": "Cello lesson",
                        "resourceId": "R104",
                        "daysOfWeek": [1],
                        "startTime": "10:00",
                        "endTime": "11:00",
                        "extendedProps": {"Instructor": "Instructor 0008"},
                        "backgroundColor": "#ff0000",
                        "borderColor": "#00ff00",
                        "textColor": "#ffffff",
                        "color": "#000000",
                        "className": "legacy-assignment-style",
                        "classNames": ["legacy-assignment-style"],
                        "display": "block",
                        "legacyBusinessField": {"source": "optimizer"},
                    }
                ],
                "unassigned_lessons": [
                    {
                        "id": "issue-1",
                        "assignment_id": "a-2",
                        "reason_code": "no_compatible_room",
                        "reason": "No compatible room",
                        "backgroundColor": "#ff0000",
                        "raw_row": {
                            "borderColor": "#00ff00",
                            "Student Name": "Student 0001",
                            "legacyPriority": 2,
                        },
                    },
                    {
                        "id": "issue-2",
                        "assignment_id": "a-3",
                        "reason_code": "no_compatible_room",
                        "reason": "No compatible room",
                    },
                    {
                        "id": "issue-3",
                        "reason_code": "missing_source_data",
                        "reason": "Missing source data",
                    },
                ],
                "history": [{"action": "move"}],
                "redo_stack": [{"action": "move"}],
                "dirty": True,
                "last_save_outcome": None,
            },
            "scheduler_data_save_warning": "Recovered workbook metadata",
            "scheduler_save_warning": "Recovered scheduler draft",
        }
    )
    session_path = tmp_path / SessionManager.FILE_NAME
    tracked_paths = (
        rooms_path,
        bookings_path,
        rules_path,
        instructors_path,
        session_path,
    )
    return {
        "base_dir": tmp_path,
        "session_mtime": session_path.stat().st_mtime_ns,
        "snapshots": {path: path.read_bytes() for path in tracked_paths},
    }


@pytest.fixture
def auth_client(client, bootstrap_token, seeded_scheduler):
    del seeded_scheduler
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def test_scheduler_session_returns_canonical_read_model(
    auth_client,
    seeded_scheduler,
):
    response = auth_client.get("/api/scheduler/session")

    assert response.status_code == 200
    payload = response.json()
    data = payload["data"]
    assert data["active_stage"] == "resolve"
    assert data["draft"] == {
        "dirty": True,
        "can_undo": True,
        "can_redo": True,
        "validation_state": "staged",
        "unsealed": False,
        "authority_stale": False,
        "save_status": "saved",
    }
    assert data["metrics"] == {
        "assigned": 1,
        "unresolved": 3,
        "source_gaps": 1,
    }
    assert data["assignments"][0]["id"] == "a-1"
    assert data["assignments"][0]["legacyBusinessField"] == {
        "source": "optimizer"
    }
    assert data["issues"][0]["reason_code"] == "no_compatible_room"
    assert data["issues"][0]["count"] == 2
    assert data["issues"][0]["items"][0]["assignment_id"] == "a-2"
    assert data["issues"][0]["items"][0]["payload"]["raw_row"] == {
        "Student Name": "Student 0001",
        "legacyPriority": 2,
    }
    assert data["rooms"][0]["id"] == "R104"
    assert data["rooms"][0]["legacyZone"] == "north"
    assert data["instructors"] == ["Instructor 0008", "Instructor 0009", "Teacher C"]
    assert data["warnings"] == [
        "Recovered workbook metadata",
        "Recovered scheduler draft",
    ]
    assert payload["warnings"] == data["warnings"]
    assert payload["workspace_version"]
    serialized = json.dumps(data)
    for presentation_key in PROHIBITED_PRESENTATION_KEYS:
        assert '"{0}"'.format(presentation_key) not in serialized

    session_path = seeded_scheduler["base_dir"] / SessionManager.FILE_NAME
    assert session_path.stat().st_mtime_ns == seeded_scheduler["session_mtime"]
    for path, expected in seeded_scheduler["snapshots"].items():
        assert path.read_bytes() == expected


def test_scheduler_session_restores_draft_older_than_one_day(
    auth_client,
    seeded_scheduler,
):
    import os
    import time

    session_path = seeded_scheduler["base_dir"] / SessionManager.FILE_NAME
    past = time.time() - (3 * 86400)
    os.utime(session_path, (past, past))

    response = auth_client.get("/api/scheduler/session")
    assert response.status_code == 200
    assert response.json()["data"]["assignments"][0]["id"] == "a-1"


def test_scheduler_session_requires_authentication(client, seeded_scheduler):
    del seeded_scheduler

    response = client.get("/api/scheduler/session")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def _snapshot_tree(root: Path) -> dict:
    if not root.exists():
        return {}
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative_path = str(path.relative_to(root))
        snapshot[relative_path] = (
            ("directory", None)
            if path.is_dir()
            else ("file", path.read_bytes())
        )
    return snapshot


def test_scheduler_session_get_does_not_write_files_or_directories(tmp_path: Path):
    runtime_root = tmp_path / "runtime"
    base_dir = runtime_root / "data"
    app = create_app(
        AppConfig(
            base_dir=base_dir,
            bootstrap_token="startup-token",
            frontend_dir=None,
            allow_test_host=True,
        )
    )

    with TestClient(app) as active_client:
        exchange = active_client.post(
            "/api/auth/exchange",
            headers={"X-PI-Bootstrap-Token": "startup-token"},
        )
        assert exchange.status_code == 200
        before = _snapshot_tree(runtime_root)

        response = active_client.get("/api/scheduler/session")

        after = _snapshot_tree(runtime_root)

    assert response.status_code == 200
    assert after == before


def test_scheduler_session_corrupt_read_returns_error_without_writing(
    tmp_path: Path,
):
    runtime_root = tmp_path / "runtime"
    base_dir = runtime_root / "data"
    app = create_app(
        AppConfig(
            base_dir=base_dir,
            bootstrap_token="startup-token",
            frontend_dir=None,
            allow_test_host=True,
        )
    )

    with TestClient(app, raise_server_exceptions=False) as active_client:
        exchange = active_client.post(
            "/api/auth/exchange",
            headers={"X-PI-Bootstrap-Token": "startup-token"},
        )
        assert exchange.status_code == 200
        (base_dir / "rooms.json").write_text("{ malformed", encoding="utf-8")
        before = _snapshot_tree(runtime_root)

        response = active_client.get("/api/scheduler/session")

        after = _snapshot_tree(runtime_root)

    assert response.status_code == 500
    assert response.json() == {
        "data": None,
        "workspace_version": None,
        "warnings": [],
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "details": None,
            "operation_id": None,
        },
    }
    assert after == before


def test_restore_scheduler_state_rehydrates_legacy_state_without_persisting(
    tmp_path: Path,
):
    manager = SessionManager(base_dir=str(tmp_path))
    manager.save_session(
        {
            "wk_df": [{"Instructor": "Instructor 0008"}],
            "stu_df": [],
            "generated_assignments": [{"id": "legacy-a-1"}],
            "unassigned_lessons": [
                {
                    "id": "legacy-issue-1",
                    "reason_code": "no_compatible_room",
                }
            ],
            "override_history": [{"action": "move"}],
            "redo_stack": [],
        }
    )
    context = build_scheduler_context(
        base_dir=str(tmp_path),
        session_manager=manager,
    )
    session_path = tmp_path / SessionManager.FILE_NAME
    before = session_path.read_bytes()
    before_mtime = session_path.stat().st_mtime_ns

    try:
        from modules.api.services.scheduler import restore_scheduler_state
    except ImportError:
        pytest.fail("scheduler session service is not implemented")

    restored = restore_scheduler_state(context)

    assert isinstance(restored["wk_df"], pd.DataFrame)
    assert restored["stu_df"] is None
    assert restored[STEP4_EDIT_SESSION_KEY]["assignments"] == [
        {"id": "legacy-a-1"}
    ]
    assert restored[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"][0]["reason_code"] == (
        "no_compatible_room"
    )
    assert restored["scheduler_session_mtime"] == manager.get_session_mtime()
    assert restored[SCHEDULER_SESSION_REVISION_KEY] == manager.get_session_revision()
    assert session_path.stat().st_mtime_ns == before_mtime
    assert session_path.read_bytes() == before
