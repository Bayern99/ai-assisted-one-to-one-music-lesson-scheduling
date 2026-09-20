"""Normalization helpers extracted from optimizer.py.

Prepare weekly lesson rows and splice them into instructor-day placement groups.
"""

# Same-teacher same-day lessons with a gap of at most 60 minutes share a room
# search. Overlaps (negative gaps) stay separate. Not a user-facing setting.
WEEKLY_GROUP_MAX_GAP_MINUTES = 60
WEEKLY_GROUP_MAX_GAP_HOURS = WEEKLY_GROUP_MAX_GAP_MINUTES / 60.0

from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.source_requests import weekly_source_request_id


def prepare_weekly_lessons(weekly_df, duplicate_sink, reject_weekly):
    from modules.shared.field_schema import (
        DAY_MAP_EN,
        extract_instrument_from_course_code,
        normalize_to_weekly_format,
    )

    raw_lessons = []
    weekly_df.columns = [c.strip() for c in weekly_df.columns]

    def _missing(value):
        return str(value).strip().lower() in {"", "nan", "none", "null", "nat"}

    seen_students = set()

    for row_idx, row in weekly_df.iterrows():
        raw_dict = row.to_dict()
        source_request_id = weekly_source_request_id(raw_dict, row_idx)
        raw_dict["_source_request_id"] = source_request_id
        try:
            normalized = normalize_to_weekly_format("weekly", raw_dict)
        except Exception:
            reject_weekly(
                raw_dict,
                "Normalization failed",
                row_idx=row_idx,
                reason_code="normalization_failed",
            )
            continue

        normalized = {
            "Student Name": "",
            "Student No": "",
            "Instructor": "",
            "Study Year": "",
            "Course Code": "",
            "Day of Week": "",
            "Class Time": "",
            "Preferred Venue": "",
            **normalized,
        }
        normalized["source_request_id"] = source_request_id

        sid = normalized.get("Student No")
        if _missing(sid):
            reject_weekly(
                raw_dict,
                "Missing Student No",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="missing_student_no",
            )
            continue
        sid = str(sid).strip()

        if sid in seen_students:
            duplicate_sink.append(
                {
                    "name": normalized.get("Student Name", "Unknown"),
                    "id": sid,
                    "course": normalized.get("Course Code", "Unknown"),
                    "day": normalized.get("Day of Week", "Unknown"),
                    "time": normalized.get("Class Time", "Unknown"),
                }
            )
            reject_weekly(
                raw_dict,
                f"Duplicate Student Entry: {sid}",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="duplicate_student",
            )
            continue
        seen_students.add(sid)

        if _missing(normalized.get("Class Time")) or _missing(normalized.get("Day of Week")):
            reject_weekly(
                raw_dict,
                "Missing Day of Week or Class Time",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="missing_day_or_time",
            )
            continue

        day_idx = DAY_MAP_EN.get(normalized["Day of Week"])
        if day_idx is None:
            reject_weekly(
                raw_dict,
                f"Unsupported weekday: {normalized.get('Day of Week', '')}",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="unsupported_weekday",
            )
            continue

        time_raw = normalized["Class Time"]
        if "-" not in time_raw:
            reject_weekly(
                raw_dict,
                f"Malformed Class Time: {time_raw}",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="invalid_course_time",
            )
            continue

        try:
            normalized_range = TimeParser.normalize_course_range(time_raw)
            if not normalized_range:
                raise ValueError(f"unparseable class time: {time_raw}")
            start_clock, end_clock = normalized_range
            start_minute = TimeParser.to_minutes(start_clock, default=0)
            end_minute = TimeParser.to_minutes(end_clock, default=0)
            start_h = start_minute // 60 if start_minute % 60 == 0 else start_minute / 60
            end_h = end_minute // 60 if end_minute % 60 == 0 else end_minute / 60
            start_hour = start_minute // 60
            normalized["Class Time"] = f"{start_clock}-{end_clock}"
        except Exception:
            reject_weekly(
                raw_dict,
                f"Malformed Class Time: {time_raw}",
                normalized=normalized,
                row_idx=row_idx,
                reason_code="invalid_course_time",
            )
            continue

        course_code = normalized["Course Code"]
        instrument = extract_instrument_from_course_code(course_code)
        pref_rooms = normalized["Preferred Venue"].replace("，", ",").split(",")
        pref_rooms = [room_id.strip() for room_id in pref_rooms if room_id.strip()]

        raw_lessons.append(
            {
                "id": f"wk_{normalized['Student No']}{day_idx}{start_hour:02d}",
                "source_request_id": source_request_id,
                "student": normalized["Student Name"],
                "sid": normalized["Student No"],
                "inst": normalized["Instructor"],
                "day": day_idx,
                "start": start_h,
                "end": end_h,
                "start_minute": start_minute,
                "end_minute": end_minute,
                "instrument": instrument,
                "prefs": pref_rooms,
                "raw_row": normalized,
            }
        )

    return raw_lessons


def build_block(lessons):
    return {
        "inst": lessons[0]["inst"],
        "day": lessons[0]["day"],
        "start": lessons[0]["start"],
        "end": lessons[-1]["end"],
        "duration": sum(lesson["end"] - lesson["start"] for lesson in lessons),
        "lessons": lessons,
        "size": len(lessons),
    }


def group_lessons_into_blocks(raw_lessons, rules):
    grouped = {}
    for lesson in raw_lessons:
        key = (lesson["inst"], lesson["day"])
        grouped.setdefault(key, []).append(lesson)

    blocks = []
    constraints = rules.get("constraints", {})
    enforce_blocks = constraints.get("enforce_instructor_blocks", True)
    gap_tolerance = WEEKLY_GROUP_MAX_GAP_HOURS if enforce_blocks else -1.0

    for (_inst, _day), lessons in grouped.items():
        lessons.sort(key=lambda item: item["start"])
        current_block = [lessons[0]]
        for idx in range(1, len(lessons)):
            prev = current_block[-1]
            curr = lessons[idx]
            gap = curr["start"] - prev["end"]
            if 0 <= gap <= gap_tolerance:
                current_block.append(curr)
            else:
                blocks.append(build_block(current_block))
                current_block = [curr]
        blocks.append(build_block(current_block))

    return blocks
