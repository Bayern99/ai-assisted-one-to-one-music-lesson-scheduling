"""Workbook upload parsing + master-data sync for scheduler Step 1."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from modules.scheduler.logic.provenance import (
    SCHEDULER_PROVENANCE_KEY,
    build_workbook_digest,
    ensure_scheduler_provenance,
    record_master_data_sync,
    record_uploaded_workbook,
)
from modules.scheduler.logic.session_state import (
    SCHEDULER_SAVE_WARNING_KEY,
    SCHEDULER_SESSION_REVISION_KEY,
)
from modules.shared.import_service import (
    NamedBytesIO,
    infer_course_records,
    infer_instructor_records,
    infer_room_records,
    infer_student_records,
)
from modules.shared.session_manager import SessionEncoder
from modules.scheduler.logic.source_requests import frame_with_source_row_indexes


UPLOAD_PICKERS = {
    "weekly": (["Weekly", "Weekly Schedule"], ["weekly"], "wk_df", "weekly_file_name"),
    "studio": (["Studio", "Studio Schedule"], ["studio"], "stu_df", "studio_file_name"),
}

SCHEDULER_SHEET_ROLES = (
    "Weekly Schedule",
    "Studio Schedule",
    "Student Info",
    "Instructor",
    "Room",
    "Course Code",
)

ROLE_EXACT_NAMES = {
    "Weekly Schedule": ("Weekly Schedule", "Weekly"),
    "Studio Schedule": ("Studio Schedule", "Studio"),
    "Student Info": ("Student Info",),
    "Instructor": ("Instructor",),
    "Room": ("Room",),
    "Course Code": ("Course Code",),
}

ROLE_KEYWORDS = {
    "Weekly Schedule": ("weekly",),
    "Studio Schedule": ("studio",),
    "Student Info": ("student",),
    "Instructor": ("instructor",),
    "Room": ("room",),
    "Course Code": ("course code", "course"),
}

WEEKLY_REQUIRED_COLUMNS = frozenset(
    {"Instructor", "Student No", "Day of Week", "Class Time"}
)


@dataclass
class ParsedSchedulerSheet:
    sheet_name: str
    normalized_name: str
    role: str
    header_row: int
    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)


@dataclass
class ParsedSchedulerWorkbook:
    file_name: str
    file_bytes: bytes
    sheets: list[ParsedSchedulerSheet]
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)

    def sheet_for_role(self, role: str) -> Optional[ParsedSchedulerSheet]:
        return next((sheet for sheet in self.sheets if sheet.role == role), None)

    def sheet_for_slot(self, slot: str) -> Optional[ParsedSchedulerSheet]:
        role = "Weekly Schedule" if slot == "weekly" else "Studio Schedule"
        selected = self.sheet_for_role(role)
        if selected is not None:
            return selected
        if not self.sheets:
            return None
        return self.sheets[0]

    def role_frames(self) -> dict[str, pd.DataFrame]:
        return {
            sheet.role: sheet.frame
            for sheet in self.sheets
            if sheet.role in SCHEDULER_SHEET_ROLES
        }


def _normalized_sheet_name(name) -> str:
    return str(name).strip()


def _match_sheet_role(name) -> str:
    normalized = _normalized_sheet_name(name)
    for role, exact_names in ROLE_EXACT_NAMES.items():
        if normalized in exact_names:
            return role

    lowered = normalized.lower()
    for role, keywords in ROLE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return role
    return "Unknown"


def _column_set(frame: pd.DataFrame) -> set[str]:
    return {str(column).strip() for column in frame.columns}


def _studio_shape_is_valid(frame: pd.DataFrame) -> bool:
    columns = _column_set(frame)
    has_slot_pair = any(
        {
            "Studio {0} Date".format(slot_index),
            "Studio {0} Time".format(slot_index),
        }.issubset(columns)
        for slot_index in range(1, 4)
    )
    return "Instructor" in columns and has_slot_pair


def _schema_blockers(role: str, frame: pd.DataFrame) -> list[str]:
    if role == "Weekly Schedule":
        missing = sorted(WEEKLY_REQUIRED_COLUMNS - _column_set(frame))
        if missing:
            return [
                "Weekly sheet is missing required columns: {0}".format(
                    ", ".join(missing)
                )
            ]
    if role == "Studio Schedule" and not _studio_shape_is_valid(frame):
        return [
            "Studio sheet requires Instructor and at least one matching "
            "Studio N Date/Studio N Time column pair"
        ]
    return []


def parse_scheduler_workbook(
    file_name: str,
    file_bytes: bytes,
) -> ParsedSchedulerWorkbook:
    if file_name.lower().endswith(".csv"):
        try:
            frame = pd.read_csv(NamedBytesIO(file_bytes, file_name))
        except Exception as exc:
            raise ValueError("Failed to parse workbook. Verify the CSV file.") from exc
        warning = "Sheet 'Sheet1' is not a recognized scheduler role."
        return ParsedSchedulerWorkbook(
            file_name=file_name,
            file_bytes=file_bytes,
            sheets=[
                ParsedSchedulerSheet(
                    sheet_name="Sheet1",
                    normalized_name="Sheet1",
                    role="Unknown",
                    header_row=1,
                    frame=frame,
                    warnings=[warning],
                )
            ],
            warnings=[warning],
            blocking_errors=[
                "Weekly Schedule sheet is required.",
                "Studio Schedule sheet is required.",
            ],
        )

    try:
        workbook = pd.ExcelFile(NamedBytesIO(file_bytes, file_name))
    except Exception as exc:
        raise ValueError("Failed to parse workbook. Verify the Excel file.") from exc

    parsed_sheets: list[ParsedSchedulerSheet] = []
    role_counts: dict[str, int] = {}
    for raw_name in workbook.sheet_names:
        sheet_name = str(raw_name)
        normalized_name = _normalized_sheet_name(raw_name)
        role = _match_sheet_role(raw_name)
        header_row = 1
        if role == "Studio Schedule":
            first_row_frame = pd.read_excel(
                workbook,
                sheet_name=raw_name,
                header=0,
            )
            if _studio_shape_is_valid(first_row_frame):
                frame = first_row_frame
            else:
                frame = pd.read_excel(
                    workbook,
                    sheet_name=raw_name,
                    header=1,
                )
                header_row = 2
        else:
            frame = pd.read_excel(
                workbook,
                sheet_name=raw_name,
                header=0,
            )

        blockers = _schema_blockers(role, frame)
        warnings = []
        if role == "Unknown":
            warnings.append(
                "Sheet '{0}' is not a recognized scheduler role.".format(
                    normalized_name or sheet_name
                )
            )
        else:
            role_counts[role] = role_counts.get(role, 0) + 1
        parsed_sheets.append(
            ParsedSchedulerSheet(
                sheet_name=sheet_name,
                normalized_name=normalized_name,
                role=role,
                header_row=header_row,
                frame=frame,
                warnings=warnings,
                blocking_errors=blockers,
            )
        )

    workbook_warnings = [
        warning
        for sheet in parsed_sheets
        for warning in sheet.warnings
    ]
    workbook_blockers = [
        blocker
        for sheet in parsed_sheets
        for blocker in sheet.blocking_errors
    ]
    for writable_role in ("Weekly Schedule", "Studio Schedule"):
        count = role_counts.get(writable_role, 0)
        if count == 0:
            workbook_blockers.append(
                "{0} sheet is required.".format(writable_role)
            )
        elif count > 1:
            workbook_blockers.append(
                "Workbook contains multiple {0} sheets.".format(writable_role)
            )

    return ParsedSchedulerWorkbook(
        file_name=file_name,
        file_bytes=file_bytes,
        sheets=parsed_sheets,
        warnings=workbook_warnings,
        blocking_errors=workbook_blockers,
    )


def _pick_sheet(dfs, exact_names, keyword_hints):
    if not dfs:
        return None, None

    for name in exact_names:
        for sheet_name, df in dfs.items():
            if _normalized_sheet_name(sheet_name) == name:
                return sheet_name, df

    for sheet_name, df in dfs.items():
        lowered = str(sheet_name).strip().lower()
        if any(keyword in lowered for keyword in keyword_hints):
            return sheet_name, df

    first_name = next(iter(dfs.keys()))
    return first_name, dfs[first_name]


def _tracked_write(mutation_journal, paths, operation, owns_path=None):
    if mutation_journal is None:
        return operation()
    return mutation_journal.run(paths, operation, owns_path=owns_path)


def _json_write_ownership(payload, *, encoder_cls=None, rejected_result=None):
    expected = json.dumps(
        payload,
        cls=encoder_cls,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")

    def owns_path(_path, after, result, operation_error):
        if (
            operation_error is None
            and rejected_result is not None
            and rejected_result(result)
        ):
            return False
        if after is None:
            return False
        return after.payload == expected

    return owns_path


def _loader_write_paths(loader, name):
    return [
        os.path.join(loader.base_dir, name),
        *(os.path.join(directory, name) for directory in loader.shadow_dirs),
    ]


def _session_write_paths(session_mgr):
    return [
        os.path.join(session_mgr.base_dir, session_mgr.FILE_NAME),
        *(
            os.path.join(directory, session_mgr.FILE_NAME)
            for directory in session_mgr.shadow_dirs
        ),
    ]


def _sync_master_data(
    loader,
    sheets,
    *,
    role,
    target_file,
    label,
    infer_records,
    file_name,
    workbook_digest,
    synced_at,
    mutation_journal=None,
):
    if role not in sheets:
        return {
            "status": "not_present",
            "workbook_filename": file_name,
            "workbook_digest": workbook_digest,
            "synced_at": synced_at,
            "message": f"{role} sheet not present in workbook.",
        }

    try:
        payload = infer_records(sheets[role])
        saved_path = _tracked_write(
            mutation_journal,
            _loader_write_paths(loader, target_file),
            lambda: loader.save_data(target_file, payload),
            owns_path=_json_write_ownership(payload),
        )
        save_meta = loader.get_last_io_metadata(target_file)
        reloaded = loader.get_data(target_file)
        read_meta = loader.get_last_io_metadata(target_file)
        verified = reloaded == payload
        warnings = list(save_meta.get("warnings", []))
        warnings.extend(
            item
            for item in read_meta.get("warnings", [])
            if item not in warnings
        )
        return {
            "status": "synced" if verified else "failed",
            "count": len(payload),
            "workbook_filename": file_name,
            "workbook_digest": workbook_digest,
            "synced_at": synced_at,
            "message": (
                f"Synced {len(payload)} {label}."
                if verified
                else f"{role} sync verification failed: canonical read-back "
                "did not match the workbook."
            ),
            "save_target_path": saved_path,
            "save_source": save_meta.get("source"),
            "selected_path": read_meta.get("selected_path"),
            "selected_source": read_meta.get("source"),
            "verified": verified,
            "warnings": warnings,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "workbook_filename": file_name,
            "workbook_digest": workbook_digest,
            "synced_at": synced_at,
            "message": str(exc),
        }


def process_scheduler_upload(
    loader,
    session_mgr,
    state,
    upload_slot,
    file_name,
    file_bytes,
    synced_at=None,
    parsed_workbook=None,
    require_atomic_success=False,
    mutation_journal=None,
):
    if upload_slot not in UPLOAD_PICKERS:
        raise ValueError(f"Unsupported upload slot: {upload_slot}")

    _exact_names, _keyword_hints, df_key, name_key = UPLOAD_PICKERS[upload_slot]
    workbook_digest = build_workbook_digest(file_bytes)
    parsed = parsed_workbook or parse_scheduler_workbook(file_name, file_bytes)
    picked_sheet = parsed.sheet_for_slot(upload_slot)
    if picked_sheet is None:
        raise ValueError(f"Failed to parse {upload_slot} file. Verify workbook sheets.")
    sheet_name = picked_sheet.sheet_name
    picked_df = frame_with_source_row_indexes(picked_sheet.frame)
    blockers = _schema_blockers(
        "Weekly Schedule" if upload_slot == "weekly" else "Studio Schedule",
        picked_df,
    )
    if blockers:
        raise ValueError(blockers[0])

    state[df_key] = picked_df
    state[name_key] = file_name

    provenance = record_uploaded_workbook(
        state.get(SCHEDULER_PROVENANCE_KEY),
        upload_slot,
        file_name,
        file_bytes,
        uploaded_at=synced_at,
    )

    role_frames = parsed.role_frames()
    rooms_sync = _sync_master_data(
        loader,
        role_frames,
        role="Room",
        target_file="rooms.json",
        label="rooms",
        infer_records=infer_room_records,
        file_name=file_name,
        workbook_digest=workbook_digest,
        synced_at=synced_at,
        mutation_journal=mutation_journal,
    )
    students_sync = _sync_master_data(
        loader,
        role_frames,
        role="Student Info",
        target_file="students.json",
        label="students",
        infer_records=infer_student_records,
        file_name=file_name,
        workbook_digest=workbook_digest,
        synced_at=synced_at,
        mutation_journal=mutation_journal,
    )
    instructors_sync = _sync_master_data(
        loader,
        role_frames,
        role="Instructor",
        target_file="instructors.json",
        label="instructors",
        infer_records=infer_instructor_records,
        file_name=file_name,
        workbook_digest=workbook_digest,
        synced_at=synced_at,
        mutation_journal=mutation_journal,
    )
    courses_sync = _sync_master_data(
        loader,
        role_frames,
        role="Course Code",
        target_file="courses.json",
        label="courses",
        infer_records=infer_course_records,
        file_name=file_name,
        workbook_digest=workbook_digest,
        synced_at=synced_at,
        mutation_journal=mutation_journal,
    )
    failed_syncs = [
        target
        for target, sync_result in (
            ("rooms", rooms_sync),
            ("students", students_sync),
            ("instructors", instructors_sync),
            ("courses", courses_sync),
        )
        if sync_result.get("status") == "failed"
    ]
    if require_atomic_success and failed_syncs:
        raise RuntimeError(
            "Master-data sync failed for: {0}".format(", ".join(failed_syncs))
        )
    provenance = record_master_data_sync(provenance, "rooms", rooms_sync)
    provenance = record_master_data_sync(provenance, "students", students_sync)
    provenance = record_master_data_sync(
        provenance,
        "instructors",
        instructors_sync,
    )
    provenance = record_master_data_sync(provenance, "courses", courses_sync)

    state[SCHEDULER_PROVENANCE_KEY] = ensure_scheduler_provenance(provenance)
    loaded, revision = session_mgr.load_session_with_revision()
    snapshot = loaded or {}
    snapshot.update(
        {
            df_key: copy.deepcopy(picked_df),
            name_key: file_name,
            SCHEDULER_PROVENANCE_KEY: copy.deepcopy(state[SCHEDULER_PROVENANCE_KEY]),
        }
    )
    session_outcome = _tracked_write(
        mutation_journal,
        _session_write_paths(session_mgr),
        lambda: session_mgr.save_session(snapshot, expected_mtime=revision),
        owns_path=_json_write_ownership(
            snapshot,
            encoder_cls=SessionEncoder,
            rejected_result=lambda outcome: (
                outcome is not None
                and getattr(outcome, "status", "") == "conflict"
            ),
        ),
    )
    if (
        require_atomic_success
        and session_outcome
        and getattr(session_outcome, "status", "") == "conflict"
    ):
        raise RuntimeError("Scheduler session changed during workbook apply")
    if session_outcome and getattr(session_outcome, "warning", ""):
        state[SCHEDULER_SAVE_WARNING_KEY] = session_outcome.warning
    else:
        state.pop(SCHEDULER_SAVE_WARNING_KEY, None)
    if session_outcome and getattr(session_outcome, "status", "") != "conflict":
        if getattr(session_outcome, "revision", None) is not None:
            state[SCHEDULER_SESSION_REVISION_KEY] = session_outcome.revision
        if getattr(session_outcome, "mtime", None) is not None:
            state["scheduler_session_mtime"] = session_outcome.mtime

    return {
        "sheet_name": sheet_name,
        "row_count": len(picked_df),
        "workbook_digest": workbook_digest,
        "sync_results": {
            "rooms": rooms_sync,
            "students": students_sync,
            "instructors": instructors_sync,
            "courses": courses_sync,
        },
    }
