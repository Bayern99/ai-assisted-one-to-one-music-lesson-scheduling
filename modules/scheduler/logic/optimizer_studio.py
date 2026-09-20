"""Studio parsing helpers extracted from optimizer.py.

These helpers only normalize studio spreadsheet rows into assignment requests
and rejection descriptors. They do not perform scoring, placement, or
preemption.
"""

import pandas as pd

from modules.shared.field_schema import normalize_to_weekly_format, parse_studio_date
from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.source_requests import (
    is_missing,
    studio_source_request_id,
    studio_time_tokens,
)


INVALID_STUDIO_DATE_REASON = "Malformed Studio Date"
MALFORMED_CLASS_TIME_REASON = "Malformed Class Time"


def _infer_studio_instrument(inst_col):
    real_instrument = "Piano"
    if "Voice" in inst_col:
        return "Voice"
    if "Percussion" in inst_col:
        return "Percussion"
    if inst_col:
        return inst_col
    return real_instrument


def _sanitize_preferred_venues(row, room_types, normalize_instrument_type, real_instrument):
    venue_raw = str(row.get("Preferred Venue", "")).strip()
    if pd.isna(row.get("Preferred Venue")) or venue_raw.lower() in ["nan", "none", ""] or not venue_raw:
        return []

    raw_prefs = [value.strip() for value in venue_raw.replace("，", ",").split(",") if value.strip()]
    valid_prefs = []
    for pref in raw_prefs:
        if pref not in room_types:
            continue
        norm_inst = normalize_instrument_type(real_instrument)
        if norm_inst in room_types[pref]:
            valid_prefs.append(pref)
    return valid_prefs


def _build_invalid_date_rejection(
    row,
    idx,
    slot_idx,
    inst,
    date_str,
    col_time,
    source_request_id,
):
    normalized = normalize_to_weekly_format(
        "studio",
        row.to_dict(),
        {"day_en": "", "class_time": str(row.get(col_time, "") or "").strip()},
    )
    return {
        "payload": {
            "id": f"stu_reject_{idx}_{slot_idx}_date",
            "source_request_id": source_request_id,
            "student": "Studio",
            "inst": inst,
            "day": -1,
            "start": 0,
            "end": 0,
            "raw_row": normalized,
        },
        "reason": INVALID_STUDIO_DATE_REASON,
        "reason_code": "invalid_studio_date",
        "log_line": f"⚠️ Studio row skipped due to invalid studio date: {inst} | Studio {slot_idx} Date='{date_str}'",
    }


def _build_malformed_time_rejection(
    row,
    idx,
    slot_idx,
    slot_time_idx,
    inst,
    day_name,
    day_idx,
    iso_date,
    ts,
    source_request_id=None,
    reason=MALFORMED_CLASS_TIME_REASON,
):
    normalized = normalize_to_weekly_format(
        "studio",
        row.to_dict(),
        {"day_en": day_name, "class_time": ts.strip()},
    )
    payload = {
            "id": f"stu_reject_{idx}_{slot_idx}_{slot_time_idx}_time",
            "student": "Studio",
            "inst": inst,
            "day": day_idx,
            "date": iso_date,
            "start": 0,
            "end": 0,
            "raw_row": normalized,
        }
    if source_request_id:
        payload["source_request_id"] = source_request_id
    return {
        "payload": payload,
        "reason": reason,
        "reason_code": "invalid_course_time" if reason == MALFORMED_CLASS_TIME_REASON else "missing_studio_time",
        "log_line": f"⚠️ Studio row skipped due to malformed class time: {inst} | {ts.strip()}",
        "warning": {
            "message": "_process_studio: malformed class time, skipping slot: %s | %s",
            "args": (inst, ts.strip()),
        },
    }


def prepare_studio_requests(studio_df, room_types, normalize_instrument_type):
    studio_events_buffer = []
    rejections = []

    for source_row_index, (idx, row) in enumerate(studio_df.iterrows()):
        row_dict = row.to_dict()
        inst = str(row.get("Instructor", "")).strip()

        inst_col = str(row.get("Instruments", "")).strip()
        real_instrument = _infer_studio_instrument(inst_col)
        pref_venues = _sanitize_preferred_venues(
            row,
            room_types=room_types,
            normalize_instrument_type=normalize_instrument_type,
            real_instrument=real_instrument,
        )

        for slot_idx in range(1, 4):
            col_date = f"Studio {slot_idx} Date"
            col_time = f"Studio {slot_idx} Time"
            date_str = str(row.get(col_date, "") or "")
            time_value = row.get(col_time, "")
            time_str = "" if is_missing(time_value) else str(time_value).strip()
            date_missing = is_missing(date_str)
            time_missing = is_missing(time_str)

            if date_missing and time_missing:
                continue

            row_level_source_id = studio_source_request_id(
                row_dict,
                source_row_index,
                slot_idx,
                0,
            )
            if not inst:
                rejections.append(
                    _build_malformed_time_rejection(
                        row,
                        idx,
                        slot_idx,
                        0,
                        inst,
                        "",
                        -1,
                        None,
                        time_str or "",
                        row_level_source_id,
                        reason="Missing Instructor",
                    )
                )
                rejections[-1]["reason_code"] = "missing_instructor"
                rejections[-1]["log_line"] = (
                    f"⚠️ Studio row skipped because Instructor is missing: row {source_row_index}"
                )
                continue

            if not studio_time_tokens(time_str):
                rejections.append(
                    _build_malformed_time_rejection(
                        row,
                        idx,
                        slot_idx,
                        0,
                        inst,
                        "",
                        -1,
                        None,
                        time_str,
                        None,
                        reason="Missing Studio Time",
                    )
                )
                rejections[-1]["reason_code"] = "missing_studio_time"
                continue

            if date_missing:
                rejections.append(
                    _build_malformed_time_rejection(
                        row,
                        idx,
                        slot_idx,
                        0,
                        inst,
                        "",
                        -1,
                        None,
                        time_str,
                        row_level_source_id,
                        reason="Missing Studio Date",
                    )
                )
                rejections[-1]["reason_code"] = "missing_studio_date"
                continue

            if time_missing:
                rejections.append(
                    _build_malformed_time_rejection(
                        row,
                        idx,
                        slot_idx,
                        0,
                        inst,
                        "",
                        -1,
                        None,
                        "",
                        None,
                        reason="Missing Studio Time",
                    )
                )
                rejections[-1]["reason_code"] = "missing_studio_time"
                continue

            dt_obj, day_idx, day_name = parse_studio_date(date_str)
            if not dt_obj:
                rejections.append(
                    _build_invalid_date_rejection(
                        row,
                        idx,
                        slot_idx,
                        inst,
                        date_str,
                        col_time,
                        row_level_source_id,
                    )
                )
                continue

            iso_date = dt_obj.strftime("%Y-%m-%d")
            time_slots = studio_time_tokens(time_str)

            for slot_time_idx, ts in enumerate(time_slots):
                source_request_id = studio_source_request_id(
                    row_dict,
                    source_row_index,
                    slot_idx,
                    slot_time_idx,
                )
                if "-" not in ts:
                    rejections.append(
                        _build_malformed_time_rejection(
                            row,
                            idx,
                            slot_idx,
                            slot_time_idx,
                            inst,
                            day_name,
                            day_idx,
                            iso_date,
                            ts,
                            source_request_id,
                        )
                    )
                    continue
                try:
                    normalized_range = TimeParser.normalize_course_range(ts)
                    if not normalized_range:
                        raise ValueError("invalid hour interval")
                    start_token, end_token = normalized_range
                    start_minute = TimeParser.to_minutes(start_token, default=0)
                    end_minute = TimeParser.to_minutes(end_token, default=0)
                    start_h = start_minute // 60 if start_minute % 60 == 0 else start_minute / 60
                    end_h = end_minute // 60 if end_minute % 60 == 0 else end_minute / 60
                except Exception:
                    rejections.append(
                        _build_malformed_time_rejection(
                            row,
                            idx,
                            slot_idx,
                            slot_time_idx,
                            inst,
                            day_name,
                            day_idx,
                            iso_date,
                            ts,
                            source_request_id,
                        )
                    )
                    continue

                normalized = normalize_to_weekly_format(
                    "studio",
                    row.to_dict(),
                    {
                        "day_en": day_name,
                        "class_time": f"{start_token}-{end_token}",
                    },
                )
                normalized["_source_row_index"] = source_row_index
                normalized["source_request_id"] = source_request_id
                studio_events_buffer.append(
                    {
                        "source_request_id": source_request_id,
                        "inst": inst,
                        "day": day_idx,
                        "start": start_h,
                        "end": end_h,
                        "start_minute": start_minute,
                        "end_minute": end_minute,
                        "date": iso_date,
                        "prefs": pref_venues,
                        "instrument": real_instrument,
                        "raw_row": normalized,
                        "source_row_index": source_row_index,
                        "id_suffix": f"{source_row_index}_{slot_idx}_{slot_time_idx}",
                    }
                )

    return studio_events_buffer, rejections
