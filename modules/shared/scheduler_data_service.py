import datetime
import io
import json
import re

import pandas as pd

from modules.shared.calendar_utils import generate_semester_dates
from modules.shared.field_schema import DAY_IDX_TO_EN, DAY_MAP_EN_SHORT, normalize_to_weekly_format, parse_studio_date
from modules.shared.models import LessonEvent
from modules.shared.time_parser import TimeParser
from modules.shared.source_requests import (
    stable_row_index,
    studio_source_request_id,
    studio_time_tokens,
    weekly_source_request_id,
)


def parse_lectures_from_csv(loader, file):
    try:
        if hasattr(file, "read"):
            file.seek(0)
            df = pd.read_csv(file)
        else:
            df = pd.read_csv(file)

        events = []
        sem_conf = loader.load_semester_config()
        sem_start = sem_conf.get("start_date", "2026-02-24")
        sem_end = sem_conf.get("end_date", "2026-06-30")
        df.columns = [c.strip() for c in df.columns]

        skipped_invalid_rows = 0
        for idx, row in df.iterrows():
            schedule = str(row.get("Class Schedule", "")).strip()
            if not schedule:
                skipped_invalid_rows += 1
                continue
            parts = schedule.split(" ")
            if len(parts) < 2:
                skipped_invalid_rows += 1
                continue
            day_str = parts[0]
            time_range = parts[1]
            normalized_range = TimeParser.normalize_hour_range(time_range)
            if not normalized_range:
                skipped_invalid_rows += 1
                continue
            start_str, end_str = normalized_range

            def normalize_dt(day_idx, t_str):
                base = datetime.datetime(2026, 1, 1)
                target = base + datetime.timedelta(days=7 if day_idx == 0 else day_idx - 1)
                minutes = TimeParser.to_minutes(t_str, default=None)
                if minutes is None:
                    raise ValueError("invalid normalized lecture time")
                if minutes == 24 * 60:
                    return target + datetime.timedelta(days=1)
                return target.replace(
                    hour=minutes // 60,
                    minute=minutes % 60,
                    second=0,
                )

            raw_room = str(row.get("Classroom", ""))
            room = re.sub(r"[^A-Z0-9]", "", raw_room)
            d_idx = DAY_MAP_EN_SHORT.get(day_str)
            if d_idx is None:
                skipped_invalid_rows += 1
                continue

            start_dt = normalize_dt(d_idx, start_str)
            end_dt = normalize_dt(d_idx, end_str)
            raw_dump = row.to_dict()
            evt = LessonEvent(
                source_id=LessonEvent.generate_source_id(idx, raw_dump),
                type="lecture",
                student_name="N/A",
                instructor_name=str(row.get("Teachers", "Unknown")),
                course_code=str(row.get("Course Code", "LOC")),
                start_dt=start_dt,
                end_dt=end_dt,
                preferred_rooms=[room] if room else [],
                raw_row_data=json.dumps(raw_dump, default=str),
                assigned_room=room,
            )

            evt_dict = evt.model_dump()
            evt_dict.pop("start_dt", None)
            evt_dict.pop("end_dt", None)
            evt_dict["id"] = f"lec_{evt.source_id[:8]}"
            evt_dict["resourceId"] = room
            evt_dict["locked"] = True
            evt_dict["title"] = f"🔒 {row.get('Course Title & Session')} (Reg)"
            evt_dict["daysOfWeek"] = [d_idx]
            evt_dict["startRecur"] = sem_start
            evt_dict["endRecur"] = sem_end
            evt_dict["startTime"] = start_dt.strftime("%H:%M:%S")
            evt_dict["endTime"] = end_dt.strftime("%H:%M:%S")
            evt_dict["backgroundColor"] = "#e74c3c"
            normalized = normalize_to_weekly_format(
                "lecture",
                raw_dump,
                {"day_en": DAY_IDX_TO_EN.get(d_idx, ""), "class_time": time_range},
            )
            normalized.update(
                {
                    "Note": str(row.get("Course Title & Session", "")),
                    "is_registry": True,
                    "auto_generated": True,
                    "source_id": evt.source_id,
                }
            )
            evt_dict["extendedProps"] = normalized
            events.append(evt_dict)

        if not events:
            if skipped_invalid_rows:
                return [], f"⚠️ No valid lecture events found. Skipped {skipped_invalid_rows} invalid lecture rows."
            return [], "⚠️ No valid lecture events found."
        if skipped_invalid_rows:
            return events, f"⚠️ Parsed {len(events)} lectures. Skipped {skipped_invalid_rows} invalid lecture rows."
        return events, None
    except Exception as exc:
        return [], f"❌ Parse Error: {exc}"


def import_schedule_from_excel(loader, file):
    try:
        sem_conf = loader.load_semester_config()
        sem_start = sem_conf.get("start_date", "2026-02-24")
        sem_end = sem_conf.get("end_date", "2026-06-30")
        new_events = []
        weekly_skipped = 0
        studio_skipped = 0

        try:
            df_wk = pd.read_excel(file, sheet_name="Weekly Schedule")
            day_map = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 0}
            for idx, row in df_wk.iterrows():
                if pd.isna(row.get("Class Time")) or pd.isna(row.get("Day of Week")):
                    weekly_skipped += 1
                    continue
                time_raw = str(row["Class Time"]).strip()
                normalized_range = TimeParser.normalize_course_range(time_raw)
                d_idx = day_map.get(str(row.get("Day of Week")).strip())
                if d_idx is None or not normalized_range:
                    weekly_skipped += 1
                    continue
                start_str, end_str = normalized_range

                def to_dt(t_str, day_offset):
                    minutes = TimeParser.to_minutes(t_str, default=None)
                    if minutes is None:
                        raise ValueError("invalid course occupancy time")
                    base = datetime.datetime(2026, 1, 1)
                    if day_offset == 0:
                        day_offset = 7
                    target = base + datetime.timedelta(days=day_offset - 1)
                    if minutes == 24 * 60:
                        return target + datetime.timedelta(days=1)
                    return target.replace(
                        hour=minutes // 60,
                        minute=minutes % 60,
                        second=0,
                    )

                start_dt = to_dt(start_str, d_idx)
                end_dt = to_dt(end_str, d_idx)
                pref_raw = str(row.get("Preferred Venue", "")).strip()
                pref_list = [p.strip() for p in pref_raw.replace("，", ",").split(",") if p.strip()]
                inst_name = str(row.get("Instructor", "Unknown"))
                evt = LessonEvent(
                    source_id=LessonEvent.generate_source_id(idx, row.to_dict()),
                    type="weekly_lesson",
                    student_name=str(row.get("Student Name", "Unknown")),
                    instructor_name=inst_name,
                    course_code=str(row.get("Course Code", "MISSING")),
                    start_dt=start_dt,
                    end_dt=end_dt,
                    preferred_rooms=pref_list,
                    raw_row_data=json.dumps(row.to_dict(), default=str),
                )
                payload = evt.model_dump()
                payload.pop("start_dt", None)
                payload.pop("end_dt", None)
                payload["id"] = f"wk_{evt.source_id[:8]}"
                payload["title"] = f"👤 {evt.student_name} ({inst_name})"
                payload["daysOfWeek"] = [d_idx]
                payload["startRecur"] = sem_start
                payload["endRecur"] = sem_end
                payload["startTime"] = f"{start_str}:00"
                payload["endTime"] = f"{end_str}:00"
                payload["editable"] = True
                payload["backgroundColor"] = "#3788d8"
                payload["extendedProps"] = {
                    "instructor": inst_name,
                    "student_id": str(row.get("Student No")),
                    "course_code": evt.course_code,
                    "source_id": evt.source_id,
                    "preferred_rooms": pref_list,
                    "source_request_id": weekly_source_request_id(
                        row.to_dict(), idx
                    ),
                    "Class Time": f"{start_str}-{end_str}",
                }
                new_events.append(payload)
        except Exception as exc:
            return f"Weekly Import Error: {exc}"

        try:
            df_stu = pd.read_excel(file, sheet_name="Studio Schedule", header=1)
            if "Instructor" not in df_stu.columns:
                df_stu = pd.read_excel(file, sheet_name="Studio Schedule")
            for idx, row in df_stu.iterrows():
                inst = str(row.get("Instructor"))
                if pd.isna(row.get("Instructor")):
                    continue
                pref_raw = str(row.get("Preferred Venue", "")).strip()
                pref_list = [p.strip() for p in pref_raw.replace("，", ",").split(",") if p.strip()]
                for i in range(1, 4):
                    col_date = f"Studio {i} Date"
                    col_time = f"Studio {i} Time"
                    val_date = row.get(col_date)
                    date_str = str(val_date) if not pd.isna(val_date) else ""
                    if date_str.strip().lower() in {"", "nan", "none", "nat"}:
                        continue
                    if isinstance(val_date, datetime.datetime):
                        date_str = val_date.strftime("%Y年%m月%d日 星期X")
                    dt_obj, _day_idx, day_name = parse_studio_date(date_str)
                    if not dt_obj:
                        studio_skipped += 1
                        continue
                    iso_date = dt_obj.strftime("%Y-%m-%d")
                    raw_time = row.get(col_time)
                    if pd.isna(raw_time) or not str(raw_time).strip():
                        studio_skipped += 1
                        continue
                    row_dict = row.to_dict()
                    source_row_index = stable_row_index(row_dict, idx)
                    time_slots = studio_time_tokens(raw_time)
                    for sub_idx, ts in enumerate(time_slots):
                        normalized_range = TimeParser.normalize_course_range(ts)
                        if not normalized_range:
                            studio_skipped += 1
                            continue
                        start_clock, end_clock = normalized_range
                        dt_s = datetime.datetime.strptime(
                            f"{iso_date} {start_clock}", "%Y-%m-%d %H:%M"
                        )
                        duration = TimeParser.to_minutes(end_clock, default=0) - TimeParser.to_minutes(start_clock, default=0)
                        dt_e = dt_s + datetime.timedelta(minutes=duration)
                        row_dump = row.to_dict()
                        row_dump["slot_index"] = f"{i}_{sub_idx}"
                        evt = LessonEvent(
                            source_id=LessonEvent.generate_source_id(idx, row_dump),
                            type="studio",
                            student_name="Studio Group",
                            instructor_name=inst,
                            course_code="STU_CLASS",
                            start_dt=dt_s,
                            end_dt=dt_e,
                            preferred_rooms=pref_list,
                            raw_row_data=json.dumps(row.to_dict(), default=str),
                        )
                        payload = evt.model_dump()
                        payload.pop("start_dt", None)
                        payload.pop("end_dt", None)
                        payload["id"] = f"stu_{evt.source_id[:8]}"
                        payload["title"] = f"🎹 Studio: {inst}"
                        payload["start"] = dt_s.isoformat()
                        payload["end"] = dt_e.isoformat()
                        payload["editable"] = True
                        payload["backgroundColor"] = "#2c3e50"
                        normalized = normalize_to_weekly_format(
                            "studio",
                            row.to_dict(),
                            {"day_en": day_name, "class_time": ts.strip()},
                        )
                        normalized.update(
                            {
                                "is_studio": True,
                                "source_id": evt.source_id,
                                "preferred_rooms": pref_list,
                                "date": iso_date,
                                "source_request_id": studio_source_request_id(
                                    row_dict,
                                    source_row_index,
                                    i,
                                    sub_idx,
                                ),
                            }
                        )
                        payload["extendedProps"] = normalized
                        new_events.append(payload)
        except Exception as exc:
            return f"Studio Import Error: {exc}"

        all_events = loader.load_bookings()
        preserved = [e for e in all_events if e.get("type") not in ["weekly_lesson", "studio", "studio_class"]]
        outcome = loader.save_bookings(preserved + new_events)
        details = []
        if weekly_skipped:
            details.append(f"skipped {weekly_skipped} invalid weekly row(s)")
        if studio_skipped:
            details.append(f"skipped {studio_skipped} invalid studio slot(s)")
        if outcome and getattr(outcome, "warning", ""):
            details.append(outcome.warning)
        suffix = f" ({'; '.join(details)})" if details else ""
        return f"✅ Imported {len(new_events)} events (Integrity Checked, Course Codes Preserved){suffix}."
    except Exception as exc:
        return f"❌ Fatal Error: {exc}"


def export_schedule_to_excel(loader):
    bookings = loader.load_bookings()
    output = io.BytesIO()
    rows = []

    day_names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 0: "Sunday"}

    for booking in bookings:
        if booking.get("type") not in ("weekly_lesson", "studio", "studio_class"):
            continue
        props = booking.get("extendedProps", {})
        days = booking.get("daysOfWeek", [])
        day_str = day_names.get(days[0], "") if days else ""
        start_minutes, end_minutes = TimeParser.event_to_minute_range(booking, default=None)
        time_str = ""
        if start_minutes is not None and end_minutes is not None and end_minutes > start_minutes:
            start_t = f"{start_minutes // 60:02d}:{start_minutes % 60:02d}"
            end_t = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            time_str = f"{start_t}-{end_t}"

        rows.append(
            {
                "Student Name": props.get("Student Name", ""),
                "Student No": props.get("Student No", props.get("student_id", "")),
                "Instructor": props.get("Instructor", props.get("instructor", "")),
                "Study Year": props.get("Study Year", ""),
                "Course Code": props.get("Course Code", props.get("course_code", "")),
                "Day of Week": props.get("Day of Week", day_str),
                "Class Time": props.get("Class Time", time_str),
                "Preferred Venue": props.get("Preferred Venue", ""),
                "Room": booking.get("resourceId", booking.get("room_id", "")),
            }
        )

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Master Schedule")
    return output.getvalue()


def detect_scheduler_conflicts(loader):
    bookings = loader.load_bookings()
    conflicts = []

    room_map = {}
    inst_map = {}

    sem_conf = loader.load_semester_config()
    sem_start = sem_conf.get("start_date", "2026-02-24")
    sem_end = sem_conf.get("end_date", "2026-06-30")

    def expand_event(evt, start_mins, end_mins):
        instances = []
        if evt.get("daysOfWeek"):
            for dow in evt["daysOfWeek"]:
                py_dow = (dow - 1) % 7
                for date_str in generate_semester_dates(sem_start, sem_end, py_dow):
                    instances.append((date_str, start_mins, end_mins))
        else:
            date_str = TimeParser.event_specific_date(evt)
            if date_str:
                instances.append((date_str, start_mins, end_mins))
        return instances

    for event in bookings:
        eid = event.get("id")
        rid = event.get("resourceId") or event.get("room_id")
        title = event.get("title", "")
        inst = event.get("extendedProps", {}).get("instructor")
        if not inst and "(" in title:
            inst = title.split("(")[-1].strip(")")
        normalized = TimeParser.board_event_occupancy(event)
        start_mins, end_mins = normalized or (None, None)
        if start_mins is None or end_mins is None:
            conflicts.append(
                f"⚠️ MALFORMED TIME [{eid or 'unknown'}]: '{title}' has invalid time fields and was skipped from conflict detection."
            )
            continue
        for date_str, start, end in expand_event(event, start_mins, end_mins):
            room_map.setdefault(rid, []).append((date_str, start, end, eid, title))
            if inst:
                inst_map.setdefault(inst, []).append((date_str, start, end, eid, title))

    def add_overlaps(entries, label):
        entries.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        for i in range(len(entries) - 1):
            d1, s1, e1, id1, title1 = entries[i]
            d2, s2, e2, id2, title2 = entries[i + 1]
            if id1 == id2:
                continue
            if d1 == d2 and s1 < e2 and e1 > s2:
                conflicts.append(
                    f"⚠️ {label} CONFLICT [{d1}] {title1} ({id1}) overlaps with {title2} ({id2})"
                )

    for rid, entries in room_map.items():
        add_overlaps(entries, f"ROOM {rid}")
    for inst, entries in inst_map.items():
        add_overlaps(entries, f"INSTRUCTOR {inst}")

    return conflicts if conflicts else ["✅ No scheduling conflicts detected."]
