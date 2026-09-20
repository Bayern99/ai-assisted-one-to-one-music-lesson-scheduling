from __future__ import annotations

import io
import json
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def snapshot_tree(root: Path) -> dict:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        snapshot[relative_path] = (
            ("directory", None)
            if path.is_dir()
            else ("file", path.read_bytes())
        )
    return snapshot


def workbook_bytes(sheet_name: str, frame: pd.DataFrame) -> bytes:
    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return payload.getvalue()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
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


@pytest.fixture
def weekly_workbook() -> bytes:
    payload = io.BytesIO()
    weekly = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student No": "S1",
                "Student Name": "Student 0001",
                "Course Code": "MUS101",
                "Preferred Venue": "R103",
            }
        ]
    )
    rooms = pd.DataFrame(
        [
            {
                "Room Number": "R103",
                "Piano Specifications": "Yamaha upright piano",
            }
        ]
    )
    students = pd.DataFrame(
        [
            {
                "Student No": "S1",
                "English Name": "Student 0001",
                "Chinese Name": "学生三",
                "Study Year": 1,
                "Programme": "Music",
                "Instructor": "Instructor 0001",
                "Instrument": "Piano",
                "Course Code": "MUS101",
            }
        ]
    )
    with pd.ExcelWriter(payload) as writer:
        weekly.to_excel(writer, sheet_name="Weekly", index=False)
        rooms.to_excel(writer, sheet_name="Room", index=False)
        students.to_excel(writer, sheet_name="Student Info", index=False)
    return payload.getvalue()


@pytest.fixture
def six_sheet_workbook() -> bytes:
    weekly = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0001 {0:03d}".format(index + 1),
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student No": "S{0:03d}".format(index + 1),
                "Student Name": "Student {0:03d}".format(index + 1),
                "Course Code": "MUS101",
                "Preferred Venue": "R103",
            }
            for index in range(148)
        ]
    )
    studio = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher {0:02d}".format(index + 1),
                "Instruments": "Piano",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "13:00-14:00",
                "Preferred Venue": "R103",
            }
            for index in range(22)
        ]
    )
    students = pd.DataFrame(
        [
            {
                "Student No": "S001",
                "English Name": "Student 001",
                "Chinese Name": "学生一",
                "Study Year": 1,
                "Programme": "Music",
                "Instructor": "Instructor 0001",
                "Instrument": "Piano",
                "Course Code": "MUS101",
            }
        ]
    )
    instructors = pd.DataFrame(
        [{"Instructor": "Roster Teacher", "Instrument": "Piano"}]
    )
    rooms = pd.DataFrame(
        [
            {
                "Room Number": "R103",
                "Piano Specifications": "Yamaha upright piano",
            }
        ]
    )
    courses = pd.DataFrame(
        [{
            "Course Name": "MUS101 - Demo Instruction II (Piano) (1001)",
        }]
    )
    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        weekly.to_excel(writer, sheet_name="Weekly Schedule", index=False)
        studio.to_excel(
            writer,
            sheet_name="Studio Schedule ",
            index=False,
            startrow=1,
        )
        students.to_excel(writer, sheet_name="Student Info", index=False)
        instructors.to_excel(writer, sheet_name="Instructor", index=False)
        rooms.to_excel(writer, sheet_name="Room", index=False)
        courses.to_excel(writer, sheet_name="Course Code", index=False)
    return payload.getvalue()


def test_unified_preview_exposes_real_six_sheet_shape_without_writing(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
):
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )

    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["file_name"] == "scheduler.xlsx"
    assert preview["file_size"] == len(six_sheet_workbook)
    assert preview["fingerprint"] == hashlib.sha256(six_sheet_workbook).hexdigest()
    assert preview["warnings"] == []
    assert preview["blocking_errors"] == []
    assert preview["instructor_conflicts"] == []
    assert len(preview["preview_id"]) == 32
    assert [sheet["role"] for sheet in preview["sheets"]] == [
        "Weekly Schedule",
        "Studio Schedule",
        "Student Info",
        "Instructor",
        "Room",
        "Course Code",
    ]
    weekly, studio = preview["sheets"][:2]
    assert weekly["normalized_name"] == "Weekly Schedule"
    assert weekly["header_row"] == 1
    assert weekly["row_count"] == 148
    assert weekly["sample_rows"][0]["Preferred Venue"] == "R103"
    assert studio["sheet_name"] == "Studio Schedule "
    assert studio["normalized_name"] == "Studio Schedule"
    assert studio["header_row"] == 2
    assert studio["row_count"] == 22
    assert studio["columns"][:4] == [
        "Instructor",
        "Instruments",
        "Studio 1 Date",
        "Studio 1 Time",
    ]
    assert studio["sample_rows"][0]["Preferred Venue"] == "R103"
    assert snapshot_tree(data_dir) == before


def test_workbook_preview_flags_reordered_instructor_names_without_blocking(
    auth_client,
):
    weekly = pd.DataFrame(
        [{
            "Instructor": "Instructor 0004 Alt",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Student No": "S1",
        }]
    )
    studio = pd.DataFrame(
        [{
            "Instructor": "Instructor 0004",
            "Studio 1 Date": "2026-03-30",
            "Studio 1 Time": "13:00-14:00",
        }]
    )
    payload = io.BytesIO()
    with pd.ExcelWriter(payload) as writer:
        weekly.to_excel(writer, sheet_name="Weekly Schedule", index=False)
        studio.to_excel(
            writer,
            sheet_name="Studio Schedule",
            index=False,
            startrow=1,
        )

    response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", payload.getvalue(), XLSX_MIME)},
    )

    assert response.status_code == 200
    preview = response.json()["data"]
    assert preview["possible_instructor_duplicates"] == [
        ["Instructor 0004 Alt", "Instructor 0004"]
    ]
    assert preview["blocking_errors"] == []


def test_apply_openapi_documents_legacy_json_and_workbook_multipart(auth_client):
    request_body = auth_client.app.openapi()["paths"][
        "/api/scheduler/import/apply"
    ]["post"]["requestBody"]
    content = request_body["content"]

    assert request_body["required"] is True
    json_schema = content["application/json"]["schema"]
    assert json_schema["title"] == "SchedulerImportApplyRequest"
    assert json_schema["required"] == ["preview_id", "expected_version"]
    assert json_schema["properties"]["fingerprint"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    multipart_schema = content["multipart/form-data"]["schema"]
    assert multipart_schema["required"] == [
        "file",
        "preview_id",
        "fingerprint",
        "expected_version",
    ]
    assert multipart_schema["properties"]["file"] == {
        "type": "string",
        "format": "binary",
    }
    assert multipart_schema["properties"]["fingerprint"] == {
        "type": "string"
    }


def test_unified_apply_commits_both_writable_roles_and_master_data(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
):
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    preview = preview_response.json()["data"]

    response = auth_client.post(
        "/api/scheduler/import/apply",
        data={
            "preview_id": preview["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
            "fingerprint": preview["fingerprint"],
        },
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["state_keys"] == ["wk_df", "stu_df"]
    assert result["sheet_names"] == {
        "weekly": "Weekly Schedule",
        "studio": "Studio Schedule ",
    }
    assert result["row_counts"] == {"weekly": 148, "studio": 22}
    assert result["fingerprint"] == preview["fingerprint"]
    persisted = json.loads((data_dir / "session_cache.json").read_text())
    assert len(persisted["wk_df"]) == 148
    assert len(persisted["stu_df"]) == 22
    assert persisted["wk_df"][0]["Preferred Venue"] == "R103"
    assert persisted["stu_df"][0]["Preferred Venue"] == "R103"
    assert persisted["weekly_file_name"] == "scheduler.xlsx"
    assert persisted["studio_file_name"] == "scheduler.xlsx"
    assert json.loads((data_dir / "rooms.json").read_text())[0]["id"] == "R103"
    assert json.loads((data_dir / "students.json").read_text())[0]["student_id"] == "S001"
    assert json.loads((data_dir / "instructors.json").read_text()) == [
        {"name": "Roster Teacher", "status": "Active"}
    ]
    assert json.loads((data_dir / "courses.json").read_text()) == [
        {
            "code": "MUS101 - Demo Instruction II (Piano) (1001)",
            "title": "",
            "convener": "",
            "category": "Demo Instruction",
            "credits": 1,
        }
    ]
    assert result["sync_results"]["instructors"]["status"] == "synced"
    assert result["sync_results"]["courses"]["status"] == "synced"
    assert "Roster Teacher" in result["session"]["instructors"]


def test_unified_apply_rejects_changed_reuploaded_bytes_without_writing(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
):
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    preview = preview_response.json()["data"]
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/apply",
        data={
            "preview_id": preview["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
            "fingerprint": preview["fingerprint"],
        },
        files={"file": ("scheduler.xlsx", six_sheet_workbook + b"changed", XLSX_MIME)},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IMPORT_FILE_CHANGED"
    assert "preview the file again" in response.json()["error"]["message"]
    assert snapshot_tree(data_dir) == before

    fingerprint_response = auth_client.post(
        "/api/scheduler/import/apply",
        data={
            "preview_id": preview["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
            "fingerprint": "0" * 64,
        },
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    assert fingerprint_response.status_code == 409
    assert fingerprint_response.json()["error"]["code"] == "IMPORT_FILE_CHANGED"
    assert snapshot_tree(data_dir) == before


def test_unified_apply_rolls_back_the_complete_workspace_when_studio_fails(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
    monkeypatch,
):
    (data_dir / "session_cache.json").write_text(
        json.dumps({"wk_df": [{"Student No": "BEFORE"}], "marker": "before"})
    )
    (data_dir / "rooms.json").write_text('[{"id":"BEFORE_ROOM"}]')
    (data_dir / "students.json").write_text('[{"student_id":"BEFORE_STUDENT"}]')
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    before = snapshot_tree(data_dir)

    from modules.api.services import imports as import_service

    original_upload = import_service.process_scheduler_upload
    calls = {"count": 0}

    def fail_studio(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("studio apply failed")
        return original_upload(*args, **kwargs)

    monkeypatch.setattr(import_service, "process_scheduler_upload", fail_studio)
    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview_response.json()["data"]["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_APPLY_FAILED"
    assert calls["count"] == 2
    assert snapshot_tree(data_dir) == before


def test_failed_unified_apply_preserves_external_master_write_and_returns_conflict(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
    monkeypatch,
):
    (data_dir / "rooms.json").write_text('[{"id":"BEFORE_ROOM"}]')
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )

    from modules.api.services import imports as import_service

    original_upload = import_service.process_scheduler_upload
    calls = {"count": 0}

    def external_write_before_failure(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            (data_dir / "rooms.json").write_text('[{"id":"EXTERNAL_ROOM"}]')
            raise RuntimeError("studio apply failed after external write")
        return original_upload(*args, **kwargs)

    monkeypatch.setattr(
        import_service,
        "process_scheduler_upload",
        external_write_before_failure,
    )
    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview_response.json()["data"]["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert json.loads((data_dir / "rooms.json").read_text()) == [
        {"id": "EXTERNAL_ROOM"}
    ]


def test_session_cas_conflict_does_not_journal_or_restore_external_writer(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
    monkeypatch,
):
    session_path = data_dir / "session_cache.json"
    session_path.write_text('{"writer":"before"}')
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    session_manager = auth_client.app.state.scheduler_context.session_manager
    original_save = session_manager.save_session
    saves = {"count": 0}

    from modules.shared.save_outcome import SaveOutcome

    def conflict_after_external_write(payload, expected_mtime=None):
        saves["count"] += 1
        if saves["count"] == 2:
            session_path.write_text('{"writer":"external"}')
            _external_payload, external_revision = (
                session_manager.load_session_with_revision()
            )
            return SaveOutcome(
                status="conflict",
                path=str(session_path),
                warning="Session changed before save.",
                revision=external_revision,
            )
        return original_save(payload, expected_mtime=expected_mtime)

    monkeypatch.setattr(
        session_manager,
        "save_session",
        conflict_after_external_write,
    )
    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview_response.json()["data"]["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert json.loads(session_path.read_text()) == {"writer": "external"}


def test_partial_master_write_then_error_remains_compensatable(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
    monkeypatch,
):
    rooms_path = data_dir / "rooms.json"
    rooms_path.write_text('[{"id":"BEFORE_ROOM"}]')
    preview_response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("scheduler.xlsx", six_sheet_workbook, XLSX_MIME)},
    )
    loader = auth_client.app.state.scheduler_context.loader
    original_save = loader.save_data
    room_saves = {"count": 0}

    def fail_after_room_write(name, payload):
        saved_path = original_save(name, payload)
        if name == "rooms.json":
            room_saves["count"] += 1
            if room_saves["count"] == 2:
                raise RuntimeError("failed after committed room write")
        return saved_path

    monkeypatch.setattr(loader, "save_data", fail_after_room_write)
    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview_response.json()["data"]["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMPORT_APPLY_FAILED"
    assert json.loads(rooms_path.read_text()) == [{"id": "BEFORE_ROOM"}]


def test_unified_preview_reports_writable_role_blockers_without_writing(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/preview",
        files={"file": ("weekly-only.xlsx", weekly_workbook, XLSX_MIME)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["blocking_errors"] == [
        "Studio Schedule sheet is required."
    ]
    assert snapshot_tree(data_dir) == before


def test_unified_preview_eviction_and_source_version_conflict(
    auth_client,
    six_sheet_workbook: bytes,
    data_dir: Path,
):
    previews = [
        auth_client.post(
            "/api/scheduler/import/preview",
            files={
                "file": (
                    "scheduler-{0}.xlsx".format(index),
                    six_sheet_workbook,
                    XLSX_MIME,
                )
            },
        ).json()["data"]
        for index in range(5)
    ]
    version = auth_client.get("/api/workspace").json()["workspace_version"]

    evicted = auth_client.post(
        "/api/scheduler/import/apply",
        json={"preview_id": previews[0]["preview_id"], "expected_version": version},
    )
    assert evicted.status_code == 404
    assert evicted.json()["error"]["code"] == "IMPORT_PREVIEW_NOT_FOUND"

    (data_dir / "bookings.json").write_text('[{"id":"external-change"}]')
    current_version = auth_client.get("/api/workspace").json()["workspace_version"]
    conflict = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": previews[1]["preview_id"],
            "expected_version": current_version,
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert not (data_dir / "session_cache.json").exists()


def test_preview_does_not_write_master_data(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly_workbook, XLSX_MIME)},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "preview_id": response.json()["data"]["preview_id"],
        "slot": "weekly",
        "file_name": "weekly.xlsx",
        "sheet_name": "Weekly",
        "row_count": 1,
        "columns": [
            "Instructor",
            "Day of Week",
            "Class Time",
            "Student No",
            "Student Name",
            "Course Code",
            "Preferred Venue",
        ],
        "instructor_conflicts": [],
        "blocking_errors": [],
    }
    assert response.json()["workspace_version"] == auth_client.get(
        "/api/workspace"
    ).json()["workspace_version"]
    assert snapshot_tree(data_dir) == before


def test_weekly_preview_blocks_teacher_double_booking_before_apply(
    auth_client,
    data_dir: Path,
):
    workbook = workbook_bytes(
        "Weekly",
        pd.DataFrame(
            [
                {
                    "Instructor": "Dr. Conflict",
                    "Day of Week": "Monday",
                    "Class Time": "10:00-11:00",
                    "Student No": "S1",
                },
                {
                    "Instructor": "dr. conflict",
                    "Day of Week": "Monday",
                    "Class Time": "10:30-11:30",
                    "Student No": "S2",
                },
            ]
        ),
    )
    before = snapshot_tree(data_dir)

    preview_response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", workbook, XLSX_MIME)},
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()["data"]
    assert len(preview["instructor_conflicts"]) == 1
    assert "Instructor time conflict" in preview["blocking_errors"][0]
    apply_response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": preview_response.json()["workspace_version"],
        },
    )
    assert apply_response.status_code == 400
    assert snapshot_tree(data_dir) == before


def test_legacy_weekly_slot_preview_still_accepts_csv(auth_client):
    payload = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0001",
                "Student No": "S1",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Preferred Venue": "R103",
            }
        ]
    ).to_csv(index=False).encode("utf-8")

    response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.csv", payload, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["data"]["sheet_name"] == "Sheet1"
    assert response.json()["data"]["row_count"] == 1


def test_apply_uses_existing_upload_semantics_and_returns_fresh_session(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    preview = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly_workbook, XLSX_MIME)},
    ).json()["data"]
    version = auth_client.get("/api/workspace").json()["workspace_version"]

    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": version,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["state_key"] == "wk_df"
    assert payload["data"]["sheet_name"] == "Weekly"
    assert payload["data"]["row_count"] == 1
    fresh_session = auth_client.get("/api/scheduler/session").json()
    fresh_workspace = auth_client.get("/api/workspace").json()
    assert payload["data"]["session"] == fresh_session["data"]
    assert payload["warnings"] == fresh_session["warnings"]
    assert payload["workspace_version"] == fresh_workspace["workspace_version"]

    persisted = json.loads((data_dir / "session_cache.json").read_text())
    assert persisted["weekly_file_name"] == "weekly.xlsx"
    assert persisted["wk_df"][0]["Student Name"] == "Student 0001"
    assert json.loads((data_dir / "rooms.json").read_text())[0]["id"] == "R103"
    assert (
        json.loads((data_dir / "students.json").read_text())[0]["student_id"]
        == "S1"
    )

    repeated = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": fresh_workspace["workspace_version"],
        },
    )
    assert repeated.status_code == 404
    assert repeated.json()["error"]["code"] == "IMPORT_PREVIEW_NOT_FOUND"


def test_stale_apply_keeps_preview_but_requires_a_fresh_preview_after_churn(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    preview = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly_workbook, XLSX_MIME)},
    ).json()["data"]
    stale_version = auth_client.get("/api/workspace").json()["workspace_version"]
    (data_dir / "bookings.json").write_text('[{"id":"changed"}]')

    conflict = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": stale_version,
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert not (data_dir / "session_cache.json").exists()

    current_version = auth_client.get("/api/workspace").json()["workspace_version"]
    retry = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": current_version,
        },
    )
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert not (data_dir / "session_cache.json").exists()


def test_apply_rejects_preview_created_from_an_older_workspace_without_consuming_it(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    preview_response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly_workbook, XLSX_MIME)},
    )
    preview = preview_response.json()["data"]
    source_version = preview_response.json()["workspace_version"]
    before = snapshot_tree(data_dir)

    (data_dir / "bookings.json").write_text('[{"id":"external-v2"}]')
    current_version = auth_client.get("/api/workspace").json()["workspace_version"]
    assert current_version != source_version

    first = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": current_version,
        },
    )
    second = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": current_version,
        },
    )

    assert first.status_code == 409
    assert first.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "WORKSPACE_CHANGED"
    assert not (data_dir / "session_cache.json").exists()
    assert snapshot_tree(data_dir) == {
        **before,
        "bookings.json": ("file", b'[{"id":"external-v2"}]'),
    }


def test_preview_store_evicts_oldest_item_after_four_entries(
    auth_client,
    weekly_workbook: bytes,
):
    previews = [
        auth_client.post(
            "/api/scheduler/import/preview?slot=weekly",
            files={"file": ("weekly-{0}.xlsx".format(index), weekly_workbook, XLSX_MIME)},
        ).json()["data"]
        for index in range(5)
    ]
    version = auth_client.get("/api/workspace").json()["workspace_version"]

    response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": previews[0]["preview_id"],
            "expected_version": version,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IMPORT_PREVIEW_NOT_FOUND"


def test_import_routes_require_authentication(client, weekly_workbook: bytes):
    preview = client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly_workbook, XLSX_MIME)},
    )
    apply = client.post(
        "/api/scheduler/import/apply",
        json={"preview_id": "missing", "expected_version": "version"},
    )

    assert preview.status_code == 401
    assert preview.json()["error"]["code"] == "AUTH_REQUIRED"
    assert apply.status_code == 401
    assert apply.json()["error"]["code"] == "AUTH_REQUIRED"


def test_invalid_workbook_returns_standard_error_envelope(auth_client):
    response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("broken.xlsx", b"not-an-xlsx", XLSX_MIME)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_WORKBOOK"


def test_weekly_preview_rejects_unschedulable_sheet_without_writing(
    auth_client,
    weekly_workbook: bytes,
    data_dir: Path,
):
    valid_previews = [
        auth_client.post(
            "/api/scheduler/import/preview?slot=weekly",
            files={
                "file": (
                    "valid-{0}.xlsx".format(index),
                    weekly_workbook,
                    XLSX_MIME,
                )
            },
        ).json()["data"]
        for index in range(4)
    ]
    malformed = workbook_bytes(
        "Weekly",
        pd.DataFrame([{"Name": "Student 0001", "When": "Monday morning"}]),
    )
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("malformed-weekly.xlsx", malformed, XLSX_MIME)},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WORKBOOK_SCHEMA"
    assert snapshot_tree(data_dir) == before

    version = auth_client.get("/api/workspace").json()["workspace_version"]
    oldest = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": valid_previews[0]["preview_id"],
            "expected_version": version,
        },
    )
    assert oldest.status_code == 200


def test_studio_preview_rejects_sheet_without_a_date_time_pair(
    auth_client,
    data_dir: Path,
):
    malformed = workbook_bytes(
        "Studio",
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Studio 1 Date": "2026年3月30日 星期一",
                }
            ]
        ),
    )
    before = snapshot_tree(data_dir)

    response = auth_client.post(
        "/api/scheduler/import/preview?slot=studio",
        files={"file": ("malformed-studio.xlsx", malformed, XLSX_MIME)},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WORKBOOK_SCHEMA"
    assert snapshot_tree(data_dir) == before


def test_studio_preview_and_apply_preserve_existing_slot_semantics(
    auth_client,
    data_dir: Path,
):
    studio = workbook_bytes(
        "Studio",
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Instruments": "Piano",
                    "Studio 1 Date": "2026年3月30日 星期一",
                    "Studio 1 Time": "13:00-14:00",
                    "Preferred Venue": "R103",
                }
            ]
        ),
    )
    before = snapshot_tree(data_dir)

    preview_response = auth_client.post(
        "/api/scheduler/import/preview?slot=studio",
        files={"file": ("studio.xlsx", studio, XLSX_MIME)},
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()["data"]
    assert preview["sheet_name"] == "Studio"
    assert preview["row_count"] == 1
    assert preview["columns"] == [
        "Instructor",
        "Instruments",
        "Studio 1 Date",
        "Studio 1 Time",
        "Preferred Venue",
    ]
    assert snapshot_tree(data_dir) == before

    version = auth_client.get("/api/workspace").json()["workspace_version"]
    apply_response = auth_client.post(
        "/api/scheduler/import/apply",
        json={
            "preview_id": preview["preview_id"],
            "expected_version": version,
        },
    )

    assert apply_response.status_code == 200
    assert apply_response.json()["data"]["state_key"] == "stu_df"
    persisted = json.loads((data_dir / "session_cache.json").read_text())
    assert persisted["studio_file_name"] == "studio.xlsx"
    assert persisted["stu_df"][0]["Instructor"] == "Studio Teacher"
    assert apply_response.json()["data"]["session"] == auth_client.get(
        "/api/scheduler/session"
    ).json()["data"]


def test_concurrent_apply_consumes_preview_once(
    auth_client,
    monkeypatch,
):
    weekly = workbook_bytes(
        "Weekly",
        pd.DataFrame(
            [
                {
                    "Instructor": "Instructor 0001",
                    "Student No": "S1",
                    "Day of Week": "Monday",
                    "Class Time": "09:00-10:00",
                }
            ]
        ),
    )
    preview = auth_client.post(
        "/api/scheduler/import/preview?slot=weekly",
        files={"file": ("weekly.xlsx", weekly, XLSX_MIME)},
    ).json()["data"]
    version = auth_client.get("/api/workspace").json()["workspace_version"]

    from modules.api.services import imports as import_service

    original_upload = import_service.process_scheduler_upload
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_upload = threading.Event()
    count_lock = threading.Lock()
    upload_calls = {"count": 0}

    def blocking_upload(*args, **kwargs):
        with count_lock:
            upload_calls["count"] += 1
            call_number = upload_calls["count"]
        if call_number == 1:
            first_entered.set()
        else:
            second_entered.set()
        assert release_upload.wait(timeout=5)
        return original_upload(*args, **kwargs)

    monkeypatch.setattr(import_service, "process_scheduler_upload", blocking_upload)
    command = {
        "preview_id": preview["preview_id"],
        "expected_version": version,
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            auth_client.post,
            "/api/scheduler/import/apply",
            json=command,
        )
        assert first_entered.wait(timeout=2)
        second = executor.submit(
            auth_client.post,
            "/api/scheduler/import/apply",
            json=command,
        )
        second_entered.wait(timeout=0.25)
        release_upload.set()
        responses = [first.result(timeout=5), second.result(timeout=5)]

    assert upload_calls["count"] == 1
    assert sorted(response.status_code for response in responses) == [200, 404]
    not_found = next(response for response in responses if response.status_code == 404)
    assert not_found.json()["error"]["code"] == "IMPORT_PREVIEW_NOT_FOUND"
