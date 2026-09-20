"""Data normalization helpers for scheduler slots."""

import copy
import logging

from modules.shared.time_parser import TimeParser

logger = logging.getLogger(__name__)


def enrich_unassigned_slot(slot):
    """Backfill raw_row metadata from extendedProps and slot fields."""
    props = slot.get("extendedProps", {})

    if "raw_row" not in slot:
        slot["raw_row"] = {}

    rr = slot["raw_row"]

    for k, v in props.items():
        if k not in ["auto_generated", "normalized_instrument"]:
            if k not in rr:
                rr[k] = v

    if "Student Name" not in rr:
        title_parts = slot.get("title", "").split("(")
        if len(title_parts) > 0:
            rr["Student Name"] = title_parts[0].replace("👤", "").strip()
        else:
            rr["Student Name"] = "Unknown"

    if "Instructor" not in rr:
        rr["Instructor"] = props.get("Instructor") or slot.get("instructor_name", "?")

    if "Class Time" not in rr and "Time" not in rr:
        if slot.get("startTime"):
            rr["Class Time"] = f"{slot['startTime'][:5]}-{slot['endTime'][:5]}"
        else:
            s_t, e_t = TimeParser.event_clock_pair(slot, default=(None, None))
            if s_t:
                rr["Class Time"] = f"{s_t}-{e_t}"

    if "Day of Week" not in rr:
        js_days = slot.get("daysOfWeek", [])
        if js_days:
            day_names = {
                0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
                4: "Thursday", 5: "Friday", 6: "Saturday",
            }
            rr["Day of Week"] = day_names.get(js_days[0], "")

    if "Instrument" not in rr:
        inst = props.get("normalized_instrument") or props.get("instrument")
        if not inst:
            cc = rr.get("Course Code")
            if cc:
                try:
                    from modules.shared.field_schema import extract_instrument_from_course_code
                    inst = extract_instrument_from_course_code(cc)
                except Exception:
                    logger.warning("enrich_unassigned_slot: failed to infer instrument from course code %r", cc, exc_info=True)
        if not inst:
            inst = "Studio/Unknown"
        rr["Instrument"] = inst

    return copy.deepcopy(slot)
