from __future__ import annotations

import json
import os

import pytest


STUDENTS = [
    {
        "student_id": "S2",
        "name_en": "Student 0002",
        "name_ch": "学生二",
        "display_name": "Student 0002 学生二",
        "year": 2,
        "instructor": "Instructor 0001",
        "instrument": "Piano",
        "type": "Piano",
        "course_code": "MUS200",
        "status": "active",
        "meta": {"source": "roster"},
    },
    {
        "student_id": "S1",
        "name_en": "Student 0001",
        "name_ch": "学生一",
        "display_name": "Student 0001 学生一",
        "year": 1,
        "instructor": "Instructor 0002",
        "instrument": "Violin",
        "type": "Instrumental",
        "course_code": "MUS100",
        "status": "active",
        "meta": {"source": "roster"},
    },
]

INVALID_ID_STUDENTS = [
    {"name_en": "Missing"},
    {"student_id": None, "name_en": "Null"},
    {"student_id": "", "name_en": "Empty"},
    {"student_id": "   ", "name_en": "Whitespace"},
    {"student_id": True, "name_en": "True"},
    {"student_id": False, "name_en": "False"},
]


@pytest.fixture
def data_dir(tmp_path):
    files = {
        "students.json": STUDENTS,
        "instructors.json": [{"name": "Instructor 0001"}],
        "rooms.json": [{"id": "R1"}],
        "bookings.json": [{"id": "B1", "type": "lecture"}],
        "workflow_state.json": {"current_phase": "scheduling"},
        "activity_cache.json": {
            "page_title": "Smart Scheduler",
            "timestamp": "malformed-but-safe",
        },
        "session_cache.json": {
            "round_committed": False,
            "step4_edit_session": {"dirty": True},
        },
        "semester_config.json": {
            "start_date": "2026-02-24",
            "last_day": "2026-05-29",
            "jury_start": "2026-05-31",
            "jury_end": "2026-06-01",
        },
    }
    for name, payload in files.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
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


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/dashboard"),
        ("get", "/api/students"),
        ("get", "/api/students/S1"),
        ("patch", "/api/students/S1"),
        ("delete", "/api/students/S1"),
        ("post", "/api/students/bulk-delete"),
        ("patch", "/api/dashboard/semester-config"),
    ],
)
def test_info_hub_routes_require_session(client, data_dir, method, path):
    del data_dir
    kwargs = {"json": {"expected_version": "version", "instructor": "Dr. New"}} if method in {"patch", "delete"} else {}
    if path.endswith("bulk-delete"):
        kwargs = {"json": {"expected_version": "version", "student_ids": ["S1"]}}

    response = client.request(method.upper(), path, **kwargs)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_dashboard_returns_real_summary_and_workspace_version(auth_client):
    response = auth_client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["workflow_state"] == {"current_phase": "scheduling"}
    assert payload["data"]["continue_action"] == {
        "page_title": "Smart Scheduler",
        "continue_path": "/schedule/resolve",
        "continue_label": "Continue schedule resolution",
        "timestamp": "malformed-but-safe",
        "page_icon": None,
    }
    assert payload["data"]["counts"] == {
        "students": 2,
        "instructors": 1,
        "rooms": 1,
        "bookings": 1,
    }
    assert payload["data"]["session"]["draft_dirty"] is True
    assert payload["data"]["health"]["status"] in {"ok", "warning", "error"}
    assert payload["data"]["semester_config"] == {
        "start_date": "2026-02-24",
        "last_day": "2026-05-29",
        "jury_start": "2026-05-31",
        "jury_end": "2026-06-01",
    }
    assert payload["workspace_version"]
    assert payload["error"] is None


def test_semester_configuration_is_versioned_validated_and_persisted(auth_client, data_dir):
    baseline = auth_client.get("/api/dashboard").json()["workspace_version"]
    payload = {
        "expected_version": baseline,
        "start_date": "2026-08-24",
        "last_day": "2026-12-04",
        "jury_start": "2026-12-07",
        "jury_end": "2026-12-08",
    }

    response = auth_client.patch("/api/dashboard/semester-config", json=payload)

    assert response.status_code == 200
    result = response.json()
    assert result["data"] == {key: value for key, value in payload.items() if key != "expected_version"}
    assert result["workspace_version"] != baseline
    persisted = json.loads((data_dir / "semester_config.json").read_text(encoding="utf-8"))
    assert persisted["end_date"] == "2026-12-04"
    assert persisted["jury_end"] == "2026-12-08"

    invalid = auth_client.patch("/api/dashboard/semester-config", json={
        **payload,
        "expected_version": result["workspace_version"],
        "jury_start": "2026-12-10",
        "jury_end": "2026-12-08",
    })
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_JURY_RANGE"


def test_dashboard_snapshot_tracks_primary_activity_despite_newer_loader_shadow(
    auth_client,
    data_dir,
    monkeypatch,
):
    from modules.api.services.workspace import compute_workspace_version

    context = auth_client.app.state.scheduler_context
    shadow_dir = data_dir / "loader-shadow"
    shadow_dir.mkdir()
    context.loader.shadow_dirs = [str(shadow_dir)]
    shadow_path = shadow_dir / "activity_cache.json"
    shadow_path.write_text(
        json.dumps({"page_title": "Smart Scheduler"}),
        encoding="utf-8",
    )
    primary_path = data_dir / "activity_cache.json"
    future_mtime = primary_path.stat().st_mtime_ns + 60_000_000_000
    os.utime(shadow_path, ns=(future_mtime, future_mtime))
    old_version = compute_workspace_version(data_dir, context=context)
    original_load = context.session_manager.load_activity
    activity_reads = 0

    def load_then_external_write():
        nonlocal activity_reads
        activity = original_load()
        activity_reads += 1
        if activity_reads == 1:
            primary_path.write_text(
                json.dumps({"page_title": "PI Info Hub"}),
                encoding="utf-8",
            )
        return activity

    monkeypatch.setattr(
        context.session_manager,
        "load_activity",
        load_then_external_write,
    )

    response = auth_client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert activity_reads == 2
    assert payload["data"]["continue_action"]["page_title"] == "PI Info Hub"
    assert payload["data"]["continue_action"]["continue_path"] == "/students"
    assert payload["workspace_version"] != old_version

    shadow_path.write_text(
        json.dumps({"page_title": "Rules (Advanced)"}),
        encoding="utf-8",
    )
    os.utime(shadow_path, ns=(future_mtime + 1, future_mtime + 1))
    assert (
        compute_workspace_version(data_dir, context=context)
        == payload["workspace_version"]
    )


def test_students_list_query_filter_sort_and_envelope(auth_client):
    response = auth_client.get(
        "/api/students",
        params={"query": "  student 0001 ", "instrument": "Violin"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [student["student_id"] for student in payload["data"]] == ["S1"]
    assert payload["workspace_version"]
    assert payload["warnings"] == []
    assert payload["error"] is None


def test_student_get_and_stable_not_found(auth_client):
    response = auth_client.get("/api/students/S2")
    missing = auth_client.get("/api/students/missing")

    assert response.status_code == 200
    assert response.json()["data"]["name_en"] == "Student 0002"
    assert response.json()["workspace_version"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "STUDENT_NOT_FOUND"


def test_student_delete_is_versioned_and_removes_only_selected_record(auth_client, data_dir):
    baseline = auth_client.get("/api/students").json()["workspace_version"]

    response = auth_client.request(
        "DELETE",
        "/api/students/S1",
        json={"expected_version": baseline},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"deleted_student_id": "S1"}
    assert response.json()["workspace_version"] != baseline
    persisted = json.loads((data_dir / "students.json").read_text(encoding="utf-8"))
    assert [student["student_id"] for student in persisted] == ["S2"]
    assert auth_client.get("/api/students/S1").status_code == 404


def test_student_bulk_delete_is_atomic_and_returns_deleted_ids(auth_client, data_dir):
    baseline = auth_client.get("/api/students").json()["workspace_version"]

    response = auth_client.post(
        "/api/students/bulk-delete",
        json={"expected_version": baseline, "student_ids": ["S1", "S2", "S1"]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"deleted_student_ids": ["S1", "S2"]}
    assert response.json()["workspace_version"] != baseline
    assert json.loads((data_dir / "students.json").read_text(encoding="utf-8")) == []


def test_student_bulk_delete_does_not_write_when_any_id_is_missing(auth_client, data_dir):
    before = (data_dir / "students.json").read_bytes()
    baseline = auth_client.get("/api/students").json()["workspace_version"]

    response = auth_client.post(
        "/api/students/bulk-delete",
        json={"expected_version": baseline, "student_ids": ["S1", "missing"]},
    )

    assert response.status_code == 404
    assert (data_dir / "students.json").read_bytes() == before


def test_numeric_student_id_list_get_and_patch_return_string(
    auth_client,
    data_dir,
):
    numeric_student = {**STUDENTS[1], "student_id": 1001}
    (data_dir / "students.json").write_text(
        json.dumps([*INVALID_ID_STUDENTS, numeric_student]),
        encoding="utf-8",
    )

    listed = auth_client.get("/api/students")
    detail = auth_client.get("/api/students/1001")
    patched = auth_client.patch(
        "/api/students/1001",
        json={
            "expected_version": listed.json()["workspace_version"],
            "instructor": "Dr. New",
        },
    )

    assert listed.status_code == 200
    assert listed.json()["data"][0]["student_id"] == "1001"
    assert detail.status_code == 200
    assert detail.json()["data"]["student_id"] == "1001"
    assert patched.status_code == 200
    assert patched.json()["data"]["student_id"] == "1001"
    assert patched.json()["data"]["meta"] == {"source": "roster"}
    persisted = json.loads((data_dir / "students.json").read_text(encoding="utf-8"))
    assert persisted[:-1] == INVALID_ID_STUDENTS
    assert persisted[-1]["student_id"] == "1001"


def test_invalid_student_ids_are_hidden_and_not_routable(
    auth_client,
    data_dir,
):
    records = [*INVALID_ID_STUDENTS, STUDENTS[1]]
    (data_dir / "students.json").write_text(
        json.dumps(records),
        encoding="utf-8",
    )
    listed = auth_client.get("/api/students")
    version = listed.json()["workspace_version"]

    assert listed.status_code == 200
    assert [student["student_id"] for student in listed.json()["data"]] == ["S1"]
    for student_id in ("None", "True", "False"):
        detail = auth_client.get("/api/students/{0}".format(student_id))
        patched = auth_client.patch(
            "/api/students/{0}".format(student_id),
            json={"expected_version": version, "instructor": "Dr. New"},
        )
        assert detail.status_code == 404
        assert patched.status_code == 404
        assert patched.json()["error"]["code"] == "STUDENT_NOT_FOUND"

    assert json.loads((data_dir / "students.json").read_text(encoding="utf-8")) == records
    assert auth_client.get("/api/students").json()["workspace_version"] == version


def test_duplicate_student_ids_get_and_patch_conflict_without_write(
    auth_client,
    data_dir,
):
    duplicates = [
        {**STUDENTS[1], "student_id": 7},
        {**STUDENTS[0], "student_id": "7"},
    ]
    (data_dir / "students.json").write_text(
        json.dumps(duplicates),
        encoding="utf-8",
    )
    listed = auth_client.get("/api/students")
    version = listed.json()["workspace_version"]

    detail = auth_client.get("/api/students/7")
    patched = auth_client.patch(
        "/api/students/7",
        json={"expected_version": version, "instructor": "Dr. New"},
    )

    assert listed.status_code == 200
    assert [student["student_id"] for student in listed.json()["data"]] == ["7", "7"]
    assert detail.status_code == 409
    assert detail.json()["error"]["code"] == "DUPLICATE_STUDENT_ID"
    assert patched.status_code == 409
    assert patched.json()["error"]["code"] == "DUPLICATE_STUDENT_ID"
    assert json.loads((data_dir / "students.json").read_text(encoding="utf-8")) == duplicates
    assert auth_client.get("/api/students").json()["workspace_version"] == version


def test_health_probe_oserror_keeps_dashboard_and_workspace_available(
    auth_client,
    monkeypatch,
):
    from modules.shared import health_check

    def fail_probe(_path):
        raise OSError("probe unavailable")

    monkeypatch.setattr(health_check.os, "listdir", fail_probe)

    dashboard = auth_client.get("/api/dashboard")
    workspace = auth_client.get("/api/workspace")

    assert dashboard.status_code == 200
    assert dashboard.json()["data"]["health"]["status"] == "error"
    assert dashboard.json()["data"]["counts"]["students"] == 2
    assert dashboard.json()["data"]["workflow_state"] == {"current_phase": "scheduling"}
    assert dashboard.json()["data"]["continue_action"]["page_title"] == "Smart Scheduler"
    assert workspace.status_code == 200
    assert workspace.json()["data"]["health"]["status"] == "error"


def test_student_patch_preserves_unmentioned_and_returns_fresh_version(
    auth_client,
    data_dir,
):
    before = auth_client.get("/api/students/S1").json()

    response = auth_client.patch(
        "/api/students/S1",
        json={
            "expected_version": before["workspace_version"],
            "instructor": "Dr. New",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == {**STUDENTS[1], "instructor": "Dr. New"}
    assert payload["data"]["student_id"] == "S1"
    assert payload["workspace_version"] != before["workspace_version"]
    persisted = json.loads((data_dir / "students.json").read_text(encoding="utf-8"))
    assert persisted == [STUDENTS[0], {**STUDENTS[1], "instructor": "Dr. New"}]


def test_student_patch_rejects_stale_version_without_writing(auth_client, data_dir):
    stale = auth_client.get("/api/students/S1").json()["workspace_version"]
    (data_dir / "rooms.json").write_text('[{"id":"R2"}]', encoding="utf-8")

    response = auth_client.patch(
        "/api/students/S1",
        json={"expected_version": stale, "instructor": "Dr. Stale"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    persisted = json.loads((data_dir / "students.json").read_text(encoding="utf-8"))
    assert persisted == STUDENTS


def test_student_patch_not_found_and_schema_protects_id_and_internal_fields(auth_client):
    version = auth_client.get("/api/students").json()["workspace_version"]

    missing = auth_client.patch(
        "/api/students/missing",
        json={"expected_version": version, "instructor": "Dr. New"},
    )
    id_injection = auth_client.patch(
        "/api/students/S1",
        json={
            "expected_version": version,
            "student_id": "S9",
            "instructor": "Dr. New",
        },
    )
    internal_injection = auth_client.patch(
        "/api/students/S1",
        json={
            "expected_version": version,
            "meta": {"injected": True},
            "instructor": "Dr. New",
        },
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "STUDENT_NOT_FOUND"
    assert id_injection.status_code == 422
    assert id_injection.json()["error"]["code"] == "VALIDATION_ERROR"
    assert internal_injection.status_code == 422
    assert internal_injection.json()["error"]["code"] == "VALIDATION_ERROR"


def test_student_patch_requires_a_change(auth_client):
    version = auth_client.get("/api/students/S1").json()["workspace_version"]

    response = auth_client.patch(
        "/api/students/S1",
        json={"expected_version": version},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_student_patch_rejects_null_without_writing(auth_client, data_dir):
    version = auth_client.get("/api/students/S1").json()["workspace_version"]

    response = auth_client.patch(
        "/api/students/S1",
        json={"expected_version": version, "instructor": None},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    persisted = json.loads((data_dir / "students.json").read_text(encoding="utf-8"))
    assert persisted == STUDENTS


def test_student_patch_maps_persistence_failure_to_stable_error(
    auth_client,
    monkeypatch,
):
    version = auth_client.get("/api/students/S1").json()["workspace_version"]

    def fail_save(_name, _data):
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        auth_client.app.state.scheduler_context.loader,
        "save_data",
        fail_save,
    )
    response = auth_client.patch(
        "/api/students/S1",
        json={"expected_version": version, "instructor": "Dr. New"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "STUDENT_SAVE_FAILED"


def test_source_data_browses_all_canonical_datasets(auth_client, data_dir):
    (data_dir / "courses.json").write_text(
        json.dumps([{"course_code": "MUS100", "course_title": "Demo Instruction"}]),
        encoding="utf-8",
    )
    (data_dir / "conveners.json").write_text(
        json.dumps([{"course_code": "MUS100", "convener_name": "Instructor 0001"}]),
        encoding="utf-8",
    )

    for dataset in ("students", "instructors", "rooms", "courses", "conveners"):
        response = auth_client.get(f"/api/source-data/{dataset}")
        assert response.status_code == 200
        assert response.json()["data"]["dataset"] == dataset
        assert response.json()["workspace_version"]


def test_source_data_room_preview_then_version_safe_apply(auth_client, data_dir):
    preview = auth_client.post(
        "/api/source-data/rooms/preview",
        files={"file": ("rooms.csv", b"Room Number,Piano Specifications\nR107B,Steinway piano\n", "text/csv")},
    )

    assert preview.status_code == 200
    payload = preview.json()
    assert payload["data"]["row_count"] == 1
    assert payload["data"]["sample"][0]["id"] == "R107B"
    applied = auth_client.post(
        "/api/source-data/import/apply",
        json={
            "preview_id": payload["data"]["preview_id"],
            "expected_version": payload["workspace_version"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["data"] == {"dataset": "rooms", "records_written": 1}
    assert json.loads((data_dir / "rooms.json").read_text(encoding="utf-8"))[0]["type"] == "Piano"


def test_source_data_import_rejects_stale_workspace(auth_client, data_dir):
    preview = auth_client.post(
        "/api/source-data/conveners/preview",
        files={"file": ("conveners.csv", b"Course Code,Course Title,Course Convener\nMUS100,Demo Course I (Piano),Instructor 0001\n", "text/csv")},
    ).json()
    (data_dir / "rooms.json").write_text('[{"id":"external"}]', encoding="utf-8")

    response = auth_client.post(
        "/api/source-data/import/apply",
        json={
            "preview_id": preview["data"]["preview_id"],
            "expected_version": preview["workspace_version"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert not (data_dir / "conveners.json").exists()


def test_source_data_backup_is_real_downloadable_workbook(auth_client):
    built = auth_client.post("/api/source-data/exports/build")
    assert built.status_code == 200
    artifacts = built.json()["data"]["artifacts"]
    assert [artifact["filename"] for artifact in artifacts] == [
        "Source_Data_Backup.xlsx",
        "Student_Register.xlsx",
    ]
    artifact = artifacts[0]
    assert artifact["filename"] == "Source_Data_Backup.xlsx"

    downloaded = auth_client.get(f"/api/source-data/exports/{artifact['artifact_id']}")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")
    assert downloaded.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    student_register = auth_client.get(
        f"/api/source-data/exports/{artifacts[1]['artifact_id']}"
    )
    assert student_register.status_code == 200
    assert student_register.content.startswith(b"PK")
