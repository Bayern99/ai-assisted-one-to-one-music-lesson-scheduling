"""Rejection/unassigned helpers extracted from optimizer.py.

These helpers preserve the current unassigned payload shapes and reason-code
contract without changing optimizer policy or orchestration.
"""

from modules.shared.field_schema import DAY_MAP_EN, extract_instrument_from_course_code
from modules.shared.time_parser import TimeParser


def append_unassigned_entry(unassigned_sink, payload, reason, reason_code):
    entry = dict(payload)
    entry["reason"] = reason
    entry["reason_code"] = reason_code
    unassigned_sink.append(entry)
    return entry


def _missing(value):
    return str(value).strip().lower() in {"", "nan", "none", "null", "nat"}


def _normalize_weekly_rejection_base(raw_row, normalized=None):
    base = dict(normalized or {})
    if base:
        return base
    return {
        "Student Name": str(raw_row.get("Student Name", "")).strip(),
        "Student No": str(raw_row.get("Student No", "")).strip(),
        "Instructor": str(raw_row.get("Instructor", "")).strip(),
        "Study Year": str(raw_row.get("Study Year", "")).strip(),
        "Course Code": str(raw_row.get("Course Code", "")).strip(),
        "Day of Week": str(raw_row.get("Day of Week", "")).strip(),
        "Class Time": str(raw_row.get("Class Time", "")).strip(),
        "Preferred Venue": str(raw_row.get("Preferred Venue", "")).strip(),
    }


def _parse_weekly_rejection_range(class_time, warning_logger=None):
    start_h, end_h = 0, 0
    if isinstance(class_time, str) and "-" in class_time:
        try:
            start_str, end_str = TimeParser.parse_time_range(class_time)
            start_h = TimeParser.extract_start_hour(start_str, default=0)
            end_h = TimeParser.extract_end_hour(end_str, default=0)
        except Exception:
            if warning_logger is not None:
                warning_logger("_record_weekly_rejection: time parse failed, using 0,0")
            start_h, end_h = 0, 0
    return start_h, end_h


def build_weekly_rejection_entry(
    raw_row,
    reason,
    normalized=None,
    row_idx=None,
    reason_code=None,
    existing_unassigned_count=0,
    warning_logger=None,
):
    base = _normalize_weekly_rejection_base(raw_row, normalized=normalized)
    start_h, end_h = _parse_weekly_rejection_range(
        base.get("Class Time", ""),
        warning_logger=warning_logger,
    )
    day_idx = DAY_MAP_EN.get(base.get("Day of Week"))
    sid = "" if _missing(base.get("Student No")) else str(base.get("Student No")).strip()
    pref_rooms = str(base.get("Preferred Venue", "")).replace("，", ",").split(",")
    pref_rooms = [room_id.strip() for room_id in pref_rooms if room_id.strip()]
    suffix = row_idx if row_idx is not None else existing_unassigned_count
    source_request_id = (
        base.get("source_request_id")
        or raw_row.get("_source_request_id")
        or f"weekly:{suffix}"
    )

    return {
        "id": f"wk_reject_{sid or 'row'}_{suffix}",
        "source_request_id": source_request_id,
        "student": base.get("Student Name") or "Unknown",
        "sid": sid,
        "inst": base.get("Instructor", ""),
        "day": day_idx if day_idx is not None else -1,
        "start": start_h,
        "end": end_h,
        "instrument": extract_instrument_from_course_code(base.get("Course Code", "")),
        "prefs": pref_rooms,
        "raw_row": base,
        "reason": reason,
        "reason_code": reason_code or "rule_constraint_rejection",
    }


def build_studio_failed_unassigned(req, reason, reason_code):
    entry = {
        "id": f"stu_{req['inst']}_{req['id_suffix']}_failed",
        "student": "Studio",
        "inst": req["inst"],
        "start": req["start"],
        "end": req["end"],
        "day": req["day"],
        "date": req["date"],
        "raw_row": req["raw_row"],
        "reason": reason,
        "reason_code": reason_code,
    }
    if req.get("source_request_id"):
        entry["source_request_id"] = req["source_request_id"]
    if req.get("source_row_index") is not None:
        entry["source_row_index"] = req["source_row_index"]
    return entry
