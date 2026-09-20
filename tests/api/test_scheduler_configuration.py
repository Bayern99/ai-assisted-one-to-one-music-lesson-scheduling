from __future__ import annotations

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig
from modules.shared.scheduler_data_service import parse_lectures_from_csv


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "bookings.json").write_text(
        json.dumps(
            [
                {
                    "id": "weekly-existing",
                    "type": "weekly_lesson",
                    "title": "Piano lesson",
                    "resourceId": "R103",
                    "daysOfWeek": [1],
                    "startTime": "09:30:00",
                    "endTime": "11:00:00",
                },
                {
                    "id": "lecture-existing",
                    "type": "lecture",
                    "title": "Old lecture",
                    "resourceId": "CC102",
                    "daysOfWeek": [2],
                    "startTime": "12:00:00",
                    "endTime": "13:00:00",
                    "locked": True,
                },
                {
                    "id": "academic-existing",
                    "type": "academic_lecture",
                    "title": "External academic event",
                    "resourceId": "CC103",
                    "daysOfWeek": [3],
                    "startTime": "14:00:00",
                    "endTime": "15:00:00",
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "scheduling_rules.json").write_text("{}", encoding="utf-8")
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


@pytest.fixture
def lecture_payload() -> dict:
    return {
        "lectures": [
            {
                "id": "lecture-new",
                "title": "Theory lecture",
                "resourceId": "R103",
                "daysOfWeek": [1],
                "startTime": "9:00:00",
                "endTime": "10:30:00",
                "extendedProps": {"course_code": "MUS100"},
                "legacyRegistryField": {"source": "registry"},
            }
        ]
    }


def workspace_version(client: TestClient) -> str:
    version = client.get("/api/workspace").json()["workspace_version"]
    assert version
    return version


def snapshot_bookings(data_dir: Path) -> bytes:
    return (data_dir / "bookings.json").read_bytes()


LECTURE_CSV = """Course Code,Course Title & Session,Teachers,Class Schedule,Hours,Classroom
MUS101,Theory A,Instructor 0008,Mon 10:00-11:00,1,CC-105
MUS102,Theory B,Instructor 0009,Tue 13:10-14:50,2,CC-106
"""


def test_get_rules_returns_canonical_rules_source_and_trace(auth_client):
    response = auth_client.get("/api/scheduler/rules")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["rules"]["constraints"]["time_range"] == {
        "start": "08:00",
        "end": "23:00",
    }
    assert payload["data"]["source_path"].endswith("scheduling_rules.json")
    assert payload["data"]["trace"]["schema_version"] == 1
    assert payload["workspace_version"] == workspace_version(auth_client)


def test_rules_reconciliation_reports_matches_missing_and_phantoms(
    auth_client,
    data_dir: Path,
):
    (data_dir / "session_cache.json").write_text(
        json.dumps(
            {
                "wk_df": [
                    {
                        "Instructor": "Instructor 0008",
                        "Student No": "1001",
                        "Student Name": "Student 0001",
                        "Day of Week": "Monday",
                        "Class Time": "09:00-10:00",
                    },
                    {
                        "Instructor": "Instructor 0009",
                        "Student No": "1002",
                        "Student Name": "Student 0002",
                        "Day of Week": "Tuesday",
                        "Class Time": "11:00-12:00",
                    },
                ],
                "stu_df": [],
                "step4_edit_session": {
                    "assignments": [
                        {
                            "id": "match-1",
                            "startTime": "09:00:00",
                            "extendedProps": {
                                "Instructor": "Instructor 0008",
                                "Student No": "1001",
                                "Day of Week": "Monday",
                            },
                        },
                        {
                            "id": "phantom-1",
                            "startTime": "13:00:00",
                            "extendedProps": {
                                "Instructor": "Teacher C",
                                "Student No": "1003",
                                "Day of Week": "Wednesday",
                            },
                        },
                    ],
                    "unassigned_lessons": [],
                    "dirty": False,
                },
            }
        ),
        encoding="utf-8",
    )

    response = auth_client.get("/api/scheduler/rules/reconciliation")

    assert response.status_code == 200
    report = response.json()["data"]
    assert report["source_row_count"] == 2
    assert report["assignment_count"] == 2
    assert [item["assignment_id"] for item in report["matches"]] == ["match-1"]
    assert [item["assignment_id"] for item in report["phantom"]] == ["phantom-1"]
    assert [item["Student"] for item in report["missing"]] == ["Student 0002"]


def test_put_rules_round_trips_through_scheduler_context(auth_client):
    version = workspace_version(auth_client)
    rules = {
        "constraints": {"time_range": {"start": "09:00", "end": "22:00"}}
    }

    response = auth_client.put(
        "/api/scheduler/rules",
        json={"rules": rules, "expected_version": version},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["rules"]["constraints"]["time_range"] == rules[
        "constraints"
    ]["time_range"]
    assert payload["data"]["source_path"].endswith("scheduling_rules.json")
    assert payload["data"]["trace"]["schema_version"] == 1
    assert payload["data"]["trace"]["source_path"] == payload["data"][
        "source_path"
    ]
    assert payload["workspace_version"] == workspace_version(auth_client)
    saved = auth_client.get("/api/scheduler/rules").json()["data"]
    assert saved["rules"]["constraints"]["time_range"] == rules["constraints"][
        "time_range"
    ]
    assert saved["trace"]["source_path"] == saved["source_path"]


def test_rules_get_cannot_return_old_data_with_concurrent_writer_version(
    auth_client,
    monkeypatch,
):
    from modules.api.routers import scheduler_configuration as router_module
    from modules.api.services import scheduler_configuration as service_module

    initial_version = workspace_version(auth_client)
    read_completed = threading.Event()
    release_read = threading.Event()
    writer_crossed_version_check = threading.Event()
    original_load = service_module.load_rules
    original_require = router_module.require_current_version

    def blocking_load(context):
        result = original_load(context)
        read_completed.set()
        assert release_read.wait(timeout=5)
        return result

    def observed_require(*args, **kwargs):
        writer_crossed_version_check.set()
        return original_require(*args, **kwargs)

    monkeypatch.setattr(service_module, "load_rules", blocking_load)
    monkeypatch.setattr(router_module, "require_current_version", observed_require)
    new_rules = {
        "constraints": {"min_break_between_lessons": 15},
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(auth_client.get, "/api/scheduler/rules")
        assert read_completed.wait(timeout=5)
        write_future = executor.submit(
            auth_client.put,
            "/api/scheduler/rules",
            json={
                "rules": new_rules,
                "expected_version": initial_version,
            },
        )
        writer_crossed_before_read_finished = writer_crossed_version_check.wait(
            timeout=0.2
        )
        release_read.set()
        read_response = read_future.result(timeout=5)
        write_response = write_future.result(timeout=5)

    assert not writer_crossed_before_read_finished
    assert read_response.status_code == 200
    assert write_response.status_code == 200

    stale_replay = auth_client.put(
        "/api/scheduler/rules",
        json={
            "rules": read_response.json()["data"]["rules"],
            "expected_version": read_response.json()["workspace_version"],
        },
    )

    assert stale_replay.status_code == 409
    assert stale_replay.json()["error"]["code"] == "WORKSPACE_CHANGED"
    current_rules = auth_client.get("/api/scheduler/rules").json()["data"][
        "rules"
    ]
    assert current_rules["constraints"]["min_break_between_lessons"] == 0


@pytest.mark.parametrize(
    ("method", "path", "reader_kind"),
    [
        ("get", "/api/scheduler/rules", "rules"),
        ("get", "/api/scheduler/lectures", "lectures"),
        ("post", "/api/scheduler/lectures/validate", "validation"),
        ("get", "/api/scheduler/session", "session"),
        ("get", "/api/workspace", "workspace"),
    ],
)
def test_versioned_editable_reads_hold_workspace_snapshot_lock(
    auth_client,
    monkeypatch,
    method,
    path,
    reader_kind,
):
    from modules.api.routers import scheduler_session as session_router
    from modules.api.services import scheduler_configuration as service_module

    context = auth_client.app.state.scheduler_context
    observed_lock_state = []

    if reader_kind == "rules":
        target, attribute = service_module, "load_rules"
    elif reader_kind == "lectures":
        target, attribute = service_module, "load_lectures"
    elif reader_kind == "validation":
        target, attribute = service_module, "validate_lectures"
    elif reader_kind == "session":
        target, attribute = session_router, "build_scheduler_view"
    else:
        target, attribute = context.loader, "load_workflow_state"

    original_reader = getattr(target, attribute)

    def observe_lock(*args, **kwargs):
        acquired = context.mutation_lock.acquire(blocking=False)
        observed_lock_state.append(not acquired)
        if acquired:
            context.mutation_lock.release()
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(target, attribute, observe_lock)
    if method == "post":
        response = auth_client.post(path, json={"lectures": []})
    else:
        response = auth_client.get(path)

    assert response.status_code == 200
    assert observed_lock_state == [True]


def test_stale_rules_put_does_not_write(auth_client, data_dir: Path):
    stale_version = workspace_version(auth_client)
    rules_before = (data_dir / "scheduling_rules.json").read_bytes()
    (data_dir / "bookings.json").write_text('[{"id":"changed"}]', encoding="utf-8")

    response = auth_client.put(
        "/api/scheduler/rules",
        json={"rules": {}, "expected_version": stale_version},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert (data_dir / "scheduling_rules.json").read_bytes() == rules_before


def test_get_lectures_returns_only_canonical_lecture_events(auth_client):
    response = auth_client.get("/api/scheduler/lectures")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["data"]["lectures"]] == [
        "lecture-existing"
    ]
    assert payload["data"]["lectures"][0]["locked"] is True
    assert payload["workspace_version"] == workspace_version(auth_client)


def test_lecture_csv_preview_matches_legacy_parser_and_does_not_write(
    auth_client,
    data_dir: Path,
):
    before = snapshot_bookings(data_dir)
    legacy_file = io.StringIO(LECTURE_CSV)
    legacy_file.name = "registry.csv"
    expected, warning = parse_lectures_from_csv(
        auth_client.app.state.scheduler_context.loader,
        legacy_file,
    )
    assert warning is None

    response = auth_client.post(
        "/api/scheduler/lectures/preview",
        files={"file": ("registry.csv", LECTURE_CSV, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == {
        "file_name": "registry.csv",
        "lectures": expected,
        "source_row_count": 2,
        "skipped_rows": [],
        "duplicate_rows": [],
        "warnings": [],
    }
    assert payload["workspace_version"] == workspace_version(auth_client)
    assert snapshot_bookings(data_dir) == before


@pytest.mark.parametrize(
    ("file_name", "contents", "expected_status", "expected_code"),
    [
        ("empty.csv", b"", 422, "LECTURE_CSV_UNREADABLE"),
        (
            "missing.csv",
            b"Teachers,Classroom\nInstructor 0008,CC-105\n",
            400,
            "LECTURE_CSV_MISSING_COLUMNS",
        ),
        (
            "headers.csv",
            (
                b"Course Code,Course Title & Session,Teachers,Class Schedule,"
                b"Hours,Classroom\n"
            ),
            422,
            "LECTURE_CSV_EMPTY_RESULT",
        ),
    ],
)
def test_lecture_csv_preview_distinguishes_blocking_errors_without_writing(
    auth_client,
    data_dir: Path,
    file_name,
    contents,
    expected_status,
    expected_code,
):
    before = snapshot_bookings(data_dir)

    response = auth_client.post(
        "/api/scheduler/lectures/preview",
        files={"file": (file_name, contents, "text/csv")},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert snapshot_bookings(data_dir) == before


def test_lecture_csv_preview_reports_partial_invalid_rows_and_duplicates(
    auth_client,
    data_dir: Path,
):
    csv_text = """Course Code,Course Title & Session,Teachers,Class Schedule,Hours,Classroom
MUS101,Theory A,Instructor 0008,Mon 10:00-11:00,1,CC-105
MUS102,Theory B,Instructor 0009,Wed TBD,1,CC-106
MUS103,Theory C,Teacher C,Funday 12:00-13:00,1,CC-107
MUS101,Theory A,Instructor 0008,Mon 10:00-11:00,1,CC-105
"""
    before = snapshot_bookings(data_dir)

    response = auth_client.post(
        "/api/scheduler/lectures/preview",
        files={"file": ("partial.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_row_count"] == 4
    assert len(data["lectures"]) == 2
    assert data["skipped_rows"] == [
        {
            "row_number": 3,
            "code": "invalid_time",
            "message": "Class Schedule contains an invalid time range",
            "raw_value": "Wed TBD",
        },
        {
            "row_number": 4,
            "code": "invalid_day",
            "message": "Class Schedule contains an unsupported weekday",
            "raw_value": "Funday 12:00-13:00",
        },
    ]
    assert data["duplicate_rows"] == [
        {"row_number": 5, "duplicate_of_row": 2}
    ]
    assert any("Skipped 2 invalid lecture rows" in item for item in data["warnings"])
    assert any("duplicate" in item.lower() for item in data["warnings"])
    assert snapshot_bookings(data_dir) == before


def test_lecture_csv_preview_draft_validates_and_saves_through_existing_routes(
    auth_client,
    data_dir: Path,
):
    preview = auth_client.post(
        "/api/scheduler/lectures/preview",
        files={"file": ("registry.csv", LECTURE_CSV, "text/csv")},
    ).json()
    lectures = preview["data"]["lectures"]
    lectures[0]["title"] = "Edited after preview"

    validation = auth_client.post(
        "/api/scheduler/lectures/validate",
        json={"lectures": lectures},
    )
    assert validation.status_code == 200
    assert validation.json()["data"]["conflicts"] == []

    saved = auth_client.put(
        "/api/scheduler/lectures",
        json={
            "lectures": validation.json()["data"]["lectures"],
            "expected_version": preview["workspace_version"],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["data"]["lectures"][0]["title"] == "Edited after preview"
    persisted = json.loads((data_dir / "bookings.json").read_text(encoding="utf-8"))
    assert [item["title"] for item in persisted if item.get("type") == "lecture"] == [
        "Edited after preview",
        "🔒 Theory B (Reg)",
    ]


def test_lecture_csv_preview_version_governs_existing_save_route(
    auth_client,
    data_dir: Path,
):
    preview = auth_client.post(
        "/api/scheduler/lectures/preview",
        files={"file": ("registry.csv", LECTURE_CSV, "text/csv")},
    ).json()
    (data_dir / "scheduling_rules.json").write_text(
        '{"constraints":{"min_break_between_lessons":15}}',
        encoding="utf-8",
    )
    before = snapshot_bookings(data_dir)

    response = auth_client.put(
        "/api/scheduler/lectures",
        json={
            "lectures": preview["data"]["lectures"],
            "expected_version": preview["workspace_version"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert snapshot_bookings(data_dir) == before


def test_session_bootstrap_summarizes_source_preferences_without_changing_rules(
    auth_client,
    data_dir: Path,
):
    (data_dir / "rooms.json").write_text(
        json.dumps([{"id": "R1"}, {"id": "R2"}]),
        encoding="utf-8",
    )
    (data_dir / "scheduling_rules.json").write_text(
        json.dumps(
            {"instructor_preferred_rooms": {"Instructor 0008": ["R1", "LegacyRoom"]}}
        ),
        encoding="utf-8",
    )
    (data_dir / "session_cache.json").write_text(
        json.dumps(
            {
                "wk_df": [
                    {"Instructor": "Instructor 0008", "Preferred Venue": "R1"},
                    {"Instructor": "Instructor 0008", "Preferred Venue": "R2, UnknownSource"},
                    {"Preferred Venue": "R1"},
                ],
                "stu_df": [
                    {"Instructor": "Instructor 0008", "Preferred Venue": "R2，UnknownSource"},
                    {"Instructor": "Instructor 0009", "Preferred Venue": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    response = auth_client.get("/api/scheduler/session")

    assert response.status_code == 200
    assert response.json()["data"]["source_preferences"] == [
        {
            "instructor": "Instructor 0008",
            "request_count": 2,
            "room_variants": [["R1"], ["R2", "UnknownSource"]],
            "unknown_rooms": ["UnknownSource"],
        },
        {
            "instructor": "Instructor 0009",
            "request_count": 0,
            "room_variants": [],
            "unknown_rooms": [],
        },
    ]
    rules = auth_client.get("/api/scheduler/rules").json()["data"]["rules"]
    assert rules["instructor_preferred_rooms"]["Instructor 0008"] == [
        "R1",
        "LegacyRoom",
    ]
    assert "R2" not in rules["instructor_preferred_rooms"]["Instructor 0008"]


def test_lecture_validation_normalizes_candidates_without_writing(
    auth_client,
    data_dir: Path,
):
    before = snapshot_bookings(data_dir)
    response = auth_client.post(
        "/api/scheduler/lectures/validate",
        json={
            "lectures": [
                {
                    "id": "lecture-safe",
                    "title": "Safe lecture",
                    "resourceId": "R107",
                    "daysOfWeek": [4],
                    "startTime": "15:00:00",
                    "endTime": "16:00:00",
                    "legacyRegistryField": {"source": "registry"},
                }
            ]
        },
    )

    assert response.status_code == 200
    lecture = response.json()["data"]["lectures"][0]
    assert lecture["type"] == "lecture"
    assert lecture["locked"] is True
    assert lecture["legacyRegistryField"] == {"source": "registry"}
    assert response.json()["data"]["conflicts"] == []
    assert snapshot_bookings(data_dir) == before


def test_lecture_lock_rejects_overlap_without_writing(
    auth_client,
    lecture_payload: dict,
    data_dir: Path,
):
    before = snapshot_bookings(data_dir)

    response = auth_client.post(
        "/api/scheduler/lectures/validate",
        json=lecture_payload,
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "LECTURE_CONFLICT"
    conflict = payload["error"]["details"]["conflicts"][0]
    assert conflict["room_id"] == "R103"
    assert conflict["lecture_id"] == "lecture-new"
    assert conflict["existing_booking_id"] == "weekly-existing"
    assert conflict["days_of_week"] == [1]
    assert payload["error"]["details"]["lectures"][0]["type"] == "lecture"
    assert snapshot_bookings(data_dir) == before


def test_put_lectures_replaces_only_type_lecture_and_returns_fresh_version(
    auth_client,
    data_dir: Path,
):
    version = workspace_version(auth_client)
    new_lecture = {
        "id": "lecture-safe",
        "title": "Safe lecture",
        "resourceId": "R107",
        "daysOfWeek": [4],
        "startTime": "15:00:00",
        "endTime": "16:00:00",
        "legacyRegistryField": {"source": "registry"},
    }

    response = auth_client.put(
        "/api/scheduler/lectures",
        json={"lectures": [new_lecture], "expected_version": version},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["lectures"][0]["id"] == "lecture-safe"
    assert payload["data"]["lectures"][0]["type"] == "lecture"
    assert payload["data"]["lectures"][0]["locked"] is True
    assert payload["data"]["lectures"][0]["legacyRegistryField"] == {
        "source": "registry"
    }
    assert payload["workspace_version"] == workspace_version(auth_client)
    assert payload["workspace_version"] != version

    persisted = json.loads((data_dir / "bookings.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in persisted] == [
        "weekly-existing",
        "academic-existing",
        "lecture-safe",
    ]


def test_put_lectures_revalidates_and_keeps_bookings_on_conflict(
    auth_client,
    lecture_payload: dict,
    data_dir: Path,
):
    before = snapshot_bookings(data_dir)

    response = auth_client.put(
        "/api/scheduler/lectures",
        json={
            **lecture_payload,
            "expected_version": workspace_version(auth_client),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LECTURE_CONFLICT"
    assert snapshot_bookings(data_dir) == before


def test_stale_lecture_put_does_not_write(auth_client, data_dir: Path):
    stale_version = workspace_version(auth_client)
    (data_dir / "scheduling_rules.json").write_text(
        '{"constraints":{"min_break_between_lessons":15}}',
        encoding="utf-8",
    )
    before = snapshot_bookings(data_dir)

    response = auth_client.put(
        "/api/scheduler/lectures",
        json={"lectures": [], "expected_version": stale_version},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert snapshot_bookings(data_dir) == before


def test_configuration_routes_require_authentication(client):
    responses = [
        client.get("/api/scheduler/rules"),
        client.put(
            "/api/scheduler/rules",
            json={"rules": {}, "expected_version": "version"},
        ),
        client.get("/api/scheduler/lectures"),
        client.post(
            "/api/scheduler/lectures/preview",
            files={"file": ("registry.csv", LECTURE_CSV, "text/csv")},
        ),
        client.post("/api/scheduler/lectures/validate", json={"lectures": []}),
        client.put(
            "/api/scheduler/lectures",
            json={"lectures": [], "expected_version": "version"},
        ),
    ]

    assert [response.status_code for response in responses] == [401] * 6
    assert all(
        response.json()["error"]["code"] == "AUTH_REQUIRED"
        for response in responses
    )
