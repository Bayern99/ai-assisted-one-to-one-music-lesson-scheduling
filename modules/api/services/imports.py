from __future__ import annotations

import copy
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional, TypeVar
from uuid import uuid4

from modules.scheduler.logic.upload_workbook_service import (
    UPLOAD_PICKERS,
    ParsedSchedulerWorkbook,
    parse_scheduler_workbook,
    process_scheduler_upload,
)
from modules.scheduler.logic.instructor_time_integrity import audit_source_schedule


class InvalidWorkbookSchema(ValueError):
    pass


class ImportPreviewNotFound(LookupError):
    pass


class AtomicImportApplyFailed(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        conflicting_paths: Optional[list[str]] = None,
        rollback_complete: bool = True,
    ) -> None:
        super().__init__(message)
        self.conflicting_paths = list(conflicting_paths or [])
        self.rollback_complete = rollback_complete


ConsumeResult = TypeVar("ConsumeResult")


@dataclass(frozen=True)
class ImportPreview:
    id: str
    slot: str
    file_name: str
    file_bytes: bytes
    sheet_name: str
    row_count: int
    columns: list[str]
    parsed_workbook: ParsedSchedulerWorkbook
    instructor_conflicts: list[dict]


@dataclass(frozen=True)
class WorkbookImportPreview:
    id: str
    file_name: str
    file_bytes: bytes
    file_size: int
    fingerprint: str
    parsed_workbook: ParsedSchedulerWorkbook
    instructor_conflicts: list[dict]
    possible_instructor_duplicates: list[list[str]]


@dataclass(frozen=True)
class StoredImportPreview:
    preview: Any
    source_version: str


class ImportPreviewStore:
    MAX_ITEMS = 4

    def __init__(self) -> None:
        self._items: dict[str, StoredImportPreview] = {}
        self._lock = Lock()

    def put(self, preview, *, source_version: str) -> None:
        with self._lock:
            self._items[preview.id] = StoredImportPreview(
                preview=copy.deepcopy(preview),
                source_version=str(source_version),
            )
            while len(self._items) > self.MAX_ITEMS:
                self._items.pop(next(iter(self._items)))

    def get(self, preview_id: str):
        with self._lock:
            entry = self._items.get(preview_id)
            return copy.deepcopy(entry) if entry is not None else None

    def remove(self, preview_id: str) -> None:
        with self._lock:
            self._items.pop(preview_id, None)

    def consume(
        self,
        preview_id: str,
        callback: Callable[[StoredImportPreview], ConsumeResult],
    ) -> ConsumeResult:
        with self._lock:
            entry = self._items.get(preview_id)
            if entry is None:
                raise ImportPreviewNotFound(preview_id)
            result = callback(copy.deepcopy(entry))
            self._items.pop(preview_id, None)
            return result


def build_import_preview(
    slot: str,
    file_name: str,
    file_bytes: bytes,
    *,
    counterpart=None,
) -> ImportPreview:
    if slot not in UPLOAD_PICKERS:
        raise ValueError("Unsupported upload slot: {0}".format(slot))

    parsed = parse_scheduler_workbook(file_name, file_bytes)
    picked_sheet = parsed.sheet_for_slot(slot)
    if picked_sheet is None:
        raise ValueError(
            "Failed to parse {0} file. Verify workbook sheets.".format(slot)
        )
    sheet_name = picked_sheet.sheet_name
    picked_df = picked_sheet.frame

    columns = [str(column) for column in picked_df.columns]
    if slot == "weekly":
        required = {"Instructor", "Student No", "Day of Week", "Class Time"}
        missing = sorted(required - {column.strip() for column in columns})
        if missing:
            raise InvalidWorkbookSchema(
                "Weekly sheet is missing required columns: {0}".format(
                    ", ".join(missing)
                )
            )
    elif slot == "studio":
        column_set = set(columns)
        has_slot_pair = any(
            {
                "Studio {0} Date".format(slot_index),
                "Studio {0} Time".format(slot_index),
            }.issubset(column_set)
            for slot_index in range(1, 4)
        )
        if "Instructor" not in column_set or not has_slot_pair:
            raise InvalidWorkbookSchema(
                "Studio sheet requires Instructor and at least one matching "
                "Studio N Date/Studio N Time column pair"
            )

    conflicts = audit_source_schedule(
        picked_df if slot == "weekly" else counterpart,
        picked_df if slot == "studio" else counterpart,
    )
    return ImportPreview(
        id=uuid4().hex,
        slot=slot,
        file_name=file_name,
        file_bytes=file_bytes,
        sheet_name=str(sheet_name),
        row_count=len(picked_df),
        columns=columns,
        parsed_workbook=parsed,
        instructor_conflicts=conflicts,
    )


def build_workbook_import_preview(
    file_name: str,
    file_bytes: bytes,
) -> WorkbookImportPreview:
    parsed = parse_scheduler_workbook(file_name, file_bytes)
    weekly = parsed.sheet_for_slot("weekly")
    studio = parsed.sheet_for_slot("studio")
    conflicts = audit_source_schedule(
        weekly.frame if weekly and weekly.role == "Weekly Schedule" else None,
        studio.frame if studio and studio.role == "Studio Schedule" else None,
    )
    possible_duplicates = _possible_instructor_duplicates(parsed)
    return WorkbookImportPreview(
        id=uuid4().hex,
        file_name=file_name,
        file_bytes=file_bytes,
        file_size=len(file_bytes),
        fingerprint=hashlib.sha256(file_bytes).hexdigest(),
        parsed_workbook=parsed,
        instructor_conflicts=conflicts,
        possible_instructor_duplicates=possible_duplicates,
    )


_INSTRUCTOR_COLUMNS = frozenset({"instructor", "teacher", "teachers"})
_NAME_TITLES = frozenset({"dr", "mr", "mrs", "ms", "miss", "prof", "professor"})


def _possible_instructor_duplicates(
    parsed: ParsedSchedulerWorkbook,
) -> list[list[str]]:
    groups: dict[tuple[str, ...], dict[tuple[str, ...], str]] = {}
    for sheet in parsed.sheets:
        for column in sheet.frame.columns:
            if str(column).strip().casefold() not in _INSTRUCTOR_COLUMNS:
                continue
            for value in sheet.frame[column].dropna():
                for display in re.split(r"\s*[&;/]\s*", str(value).strip()):
                    tokens = tuple(
                        token
                        for token in re.findall(r"[^\W\d_]+", display.casefold())
                        if token not in _NAME_TITLES
                    )
                    if len(tokens) < 2:
                        continue
                    groups.setdefault(tuple(sorted(tokens)), {}).setdefault(
                        tokens,
                        display,
                    )
    return [
        list(variants.values())
        for variants in groups.values()
        if len(variants) > 1
    ]


@dataclass(frozen=True)
class _PathSnapshot:
    payload: bytes
    mode: int
    mtime_ns: int


@dataclass(frozen=True)
class _MutationRecord:
    path: Path
    before: Optional[_PathSnapshot]
    after: Optional[_PathSnapshot]


def _capture_path(path: Path) -> Optional[_PathSnapshot]:
    if not path.exists():
        return None
    path_stat = path.stat()
    return _PathSnapshot(
        payload=path.read_bytes(),
        mode=path_stat.st_mode,
        mtime_ns=path_stat.st_mtime_ns,
    )


def _restore_path(path: Path, snapshot: Optional[_PathSnapshot]) -> None:
    if snapshot is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(snapshot.payload)
    os.chmod(path, snapshot.mode)
    os.utime(path, ns=(snapshot.mtime_ns, snapshot.mtime_ns))


class _WorkspaceMutationJournal:
    """Compensate only writes still owned by this import transaction."""

    def __init__(self) -> None:
        self._records: list[_MutationRecord] = []

    def run(
        self,
        paths,
        operation: Callable[[], ConsumeResult],
        owns_path=None,
    ) -> ConsumeResult:
        candidates = list(dict.fromkeys(Path(path).resolve() for path in paths))
        before = {path: _capture_path(path) for path in candidates}
        result = None
        operation_error = None
        operation_succeeded = False
        try:
            result = operation()
            operation_succeeded = True
            return result
        except Exception as exc:
            operation_error = exc
            raise
        finally:
            for path in candidates:
                after = _capture_path(path)
                owned = (
                    owns_path(
                        path,
                        after,
                        result,
                        operation_error,
                    )
                    if owns_path is not None
                    else operation_succeeded
                )
                if before[path] != after and owned:
                    self._records.append(
                        _MutationRecord(
                            path=path,
                            before=before[path],
                            after=after,
                        )
                    )

    def rollback(self) -> list[str]:
        conflicting_paths = set()
        for record in reversed(self._records):
            path_key = str(record.path)
            if path_key in conflicting_paths:
                continue
            if _capture_path(record.path) != record.after:
                conflicting_paths.add(path_key)
                continue
            _restore_path(record.path, record.before)
        return sorted(conflicting_paths)


def apply_preview(context, state: dict, preview) -> dict:
    if preview.instructor_conflicts:
        raise InvalidWorkbookSchema(
            "Instructor time conflicts must be corrected before import."
        )
    if isinstance(preview, ImportPreview):
        result = process_scheduler_upload(
            context.loader,
            context.session_manager,
            state,
            preview.slot,
            preview.file_name,
            preview.file_bytes,
            parsed_workbook=preview.parsed_workbook,
        )
        return {
            "state_key": UPLOAD_PICKERS[preview.slot][2],
            **result,
        }

    if not isinstance(preview, WorkbookImportPreview):
        raise TypeError("Unsupported scheduler import preview")
    if preview.parsed_workbook.blocking_errors:
        raise InvalidWorkbookSchema("; ".join(preview.parsed_workbook.blocking_errors))

    mutation_journal = _WorkspaceMutationJournal()
    results = {}
    try:
        for slot in ("weekly", "studio"):
            results[slot] = process_scheduler_upload(
                context.loader,
                context.session_manager,
                state,
                slot,
                preview.file_name,
                preview.file_bytes,
                parsed_workbook=preview.parsed_workbook,
                require_atomic_success=True,
                mutation_journal=mutation_journal,
            )
    except Exception as exc:
        try:
            conflicting_paths = mutation_journal.rollback()
        except Exception as rollback_exc:
            raise AtomicImportApplyFailed(
                "Scheduler workbook apply failed and rollback also failed: {0}".format(
                    rollback_exc
                ),
                rollback_complete=False,
            ) from exc
        raise AtomicImportApplyFailed(
            str(exc),
            conflicting_paths=conflicting_paths,
        ) from exc

    return {
        "state_keys": ["wk_df", "stu_df"],
        "sheet_names": {
            slot: results[slot]["sheet_name"]
            for slot in ("weekly", "studio")
        },
        "row_counts": {
            slot: results[slot]["row_count"]
            for slot in ("weekly", "studio")
        },
        "fingerprint": preview.fingerprint,
        "sync_results": results["studio"]["sync_results"],
    }
