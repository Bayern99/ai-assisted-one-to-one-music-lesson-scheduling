from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import pandas as pd

from modules.info_hub.logic import dashboard_service, student_service
from modules.info_hub.logic.convener_manager import ConvenerManager
from modules.shared.health_check import run_health_check
from modules.shared.import_service import infer_room_records, infer_student_records


SourceDataset = Literal["students", "instructors", "rooms", "courses", "conveners"]
ImportDataset = Literal["students", "rooms", "conveners"]
SOURCE_FILES: dict[SourceDataset, str] = {
    "students": "students.json",
    "instructors": "instructors.json",
    "rooms": "rooms.json",
    "courses": "courses.json",
    "conveners": "conveners.json",
}
DEFAULT_SEMESTER_CONFIG = {
    "start_date": "2026-02-24",
    "last_day": "2026-05-29",
    "jury_start": "2026-05-31",
    "jury_end": "2026-06-01",
}


class InvalidSourceImport(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSourceImport:
    id: str
    dataset: ImportDataset
    file_name: str
    columns: tuple[str, ...]
    records: tuple[dict[str, Any], ...]


def load_dashboard(context, base_dir):
    return dashboard_service.build_dashboard_summary(
        context.loader,
        context.session_manager,
        run_health_check(base_dir=str(base_dir)),
    )


def load_semester_config(context) -> dict[str, str]:
    stored = context.loader.load_semester_config()
    if not isinstance(stored, dict):
        stored = {}
    last_day = stored.get("last_day") or stored.get("end_date")
    return {
        "start_date": str(stored.get("start_date") or DEFAULT_SEMESTER_CONFIG["start_date"]),
        "last_day": str(last_day or DEFAULT_SEMESTER_CONFIG["last_day"]),
        "jury_start": str(stored.get("jury_start") or DEFAULT_SEMESTER_CONFIG["jury_start"]),
        "jury_end": str(stored.get("jury_end") or DEFAULT_SEMESTER_CONFIG["jury_end"]),
    }


def save_semester_config(context, config: dict[str, str]) -> None:
    payload = dict(config)
    payload["end_date"] = payload["last_day"]
    context.loader.save_semester_config(payload)


def load_students(context, query: str = "", instrument: str = ""):
    return student_service.list_students(
        context.loader,
        query=query,
        instrument=instrument,
    )


def load_student(context, student_id: str):
    return student_service.get_student(context.loader, student_id)


def save_student(context, student_id: str, changes: dict):
    return student_service.update_student(context.loader, student_id, changes)


def delete_student(context, student_id: str) -> str:
    return student_service.delete_student(context.loader, student_id)


def delete_students(context, student_ids: list[str]) -> list[str]:
    return student_service.delete_students(context.loader, student_ids)


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and all(isinstance(item, dict) for item in value.values()):
        return [dict(item) for item in value.values()]
    return []


def load_source_dataset(context, dataset: SourceDataset) -> list[dict[str, Any]]:
    records = _records(context.loader.get_data(SOURCE_FILES[dataset]))
    if dataset == "instructors" and not records:
        names = sorted({
            str(student.get("instructor", "")).strip()
            for student in _records(context.loader.get_data("students.json"))
            if str(student.get("instructor", "")).strip()
        })
        return [{"name": name, "status": "Active"} for name in names]
    return records


def _read_tabular(file_name: str, file_bytes: bytes, *, student_sheet: bool = False) -> pd.DataFrame:
    if not file_bytes:
        raise InvalidSourceImport("The selected source file is empty")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise InvalidSourceImport("Source data uploads are limited to 10 MB")
    suffix = os.path.splitext(file_name)[1].lower()
    if suffix not in {".csv", ".xlsx"}:
        raise InvalidSourceImport("Source data must be a CSV or XLSX file")
    try:
        if suffix == ".csv":
            frame = pd.read_csv(io.BytesIO(file_bytes))
        else:
            if student_sheet:
                workbook = pd.ExcelFile(io.BytesIO(file_bytes))
                sheet = "Student Info" if "Student Info" in workbook.sheet_names else workbook.sheet_names[0]
                frame = pd.read_excel(workbook, sheet_name=sheet)
            else:
                frame = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:
        raise InvalidSourceImport("The selected source file could not be parsed") from exc
    if frame.empty:
        raise InvalidSourceImport("The selected source file contains no rows")
    frame = frame.copy(deep=True)
    frame.columns = [str(column).strip() for column in frame.columns]
    if len(set(frame.columns)) != len(frame.columns):
        raise InvalidSourceImport("The selected source file contains duplicate columns")
    return frame


def _parse_conveners(frame: pd.DataFrame) -> list[dict[str, Any]]:
    def column(*candidates: str) -> str | None:
        for source in frame.columns:
            normalized = source.strip().lower()
            if any(candidate.lower() in normalized for candidate in candidates):
                return source
        return None

    code_column = column("Course Code", "Subject Code", "Code")
    if code_column is None:
        raise InvalidSourceImport("Course convener data requires a Course Code column")
    title_column = column("Course (Session) Title", "Course Title", "Title")
    teacher_column = column("Teacher", "Instructor")
    convener_column = column("Course Convener", "Convener")
    manager = ConvenerManager.__new__(ConvenerManager)
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        code = str(row.get(code_column, "")).strip()
        if not code or code.lower() == "nan":
            continue
        title = str(row.get(title_column, "")).strip() if title_column else ""
        convener = str(row.get(convener_column, "")).strip() if convener_column else ""
        teachers_raw = str(row.get(teacher_column, "")).strip() if teacher_column else ""
        instrument, year = manager.extract_instrument_and_year(code, title)
        records.append({
            "course_code": code,
            "course_title": "" if title.lower() == "nan" else title,
            "convener_name": "" if convener.lower() == "nan" else convener,
            "teachers": [value.strip() for value in teachers_raw.split("&") if value.strip() and value.strip().lower() != "nan"],
            "instrument_family": instrument,
            "year_level": year,
        })
    if not records:
        raise InvalidSourceImport("No valid course convener records were found")
    return records


def build_source_import_preview(
    dataset: ImportDataset,
    file_name: str,
    file_bytes: bytes,
) -> ParsedSourceImport:
    frame = _read_tabular(file_name, file_bytes, student_sheet=dataset == "students")
    try:
        if dataset == "students":
            records = infer_student_records(frame)
        elif dataset == "rooms":
            records = infer_room_records(frame)
        else:
            records = _parse_conveners(frame)
    except InvalidSourceImport:
        raise
    except (TypeError, ValueError) as exc:
        raise InvalidSourceImport(str(exc)) from exc
    records = _records(records)
    if not records:
        raise InvalidSourceImport(f"No valid {dataset} records were found")
    return ParsedSourceImport(
        id=uuid4().hex,
        dataset=dataset,
        file_name=file_name,
        columns=tuple(str(column) for column in frame.columns),
        records=tuple(records),
    )


def apply_source_import(context, preview: ParsedSourceImport) -> int:
    context.loader.save_data(SOURCE_FILES[preview.dataset], list(preview.records))
    return len(preview.records)


def _excel_safe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for record in records:
        result.append({
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for key, value in record.items()
        })
    return result


def build_source_backup(context) -> bytes:
    output = io.BytesIO()
    datasets = ["students", "instructors", "rooms", "courses", "conveners"]
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for dataset in datasets:
            records = _excel_safe(load_source_dataset(context, dataset))
            pd.DataFrame(records).to_excel(
                writer,
                sheet_name=dataset.title()[:31],
                index=False,
            )
    return output.getvalue()


def build_student_register(context) -> bytes:
    output = io.BytesIO()
    records = _excel_safe(load_source_dataset(context, "students"))
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(records).to_excel(writer, sheet_name="Students", index=False)
    return output.getvalue()
