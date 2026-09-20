"""Non-UI scheduler workflow helpers for Step 3/4 orchestration."""

import copy
import re

from modules.scheduler.logic.session_state import (
    SCHEDULER_DATA_SAVE_WARNING_KEY,
    SCHEDULER_SESSION_REVISION_KEY,
    STEP4_EDIT_SESSION_KEY,
    ensure_step4_edit_session,
    hard_reset_scheduler_state,
    persist_step4_draft,
    persist_scheduler_session,
)
from modules.shared.field_schema import extract_instrument_from_course_code
from modules.shared.time_parser import TimeParser


class SchedulerSessionConflict(RuntimeError):
    pass


DAY_NAME_BY_INDEX = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}


def _is_studio_artifact_payload(event):
    if not isinstance(event, dict):
        return False

    if str(event.get("type", "")).strip().lower() == "studio_class":
        return True

    event_id = str(event.get("id", "")).strip().lower()
    if event_id.startswith("stu_"):
        return True

    props = event.get("extendedProps", {})
    if not isinstance(props, dict):
        props = {}

    if props.get("is_studio") is True:
        return True

    event_type = str(props.get("Event Type", props.get("type", ""))).strip().lower()
    if event_type == "studio class":
        return True

    course_code = str(props.get("Course Code", "")).strip().upper()
    if course_code.startswith("STU"):
        return True

    student_name = str(props.get("Student Name", "")).strip().lower()
    if student_name == "studio" or "n/a (studio)" in student_name:
        return True

    title = str(event.get("title", "")).strip().lower()
    return title.startswith("🎹 studio:")


def build_locked_context(bookings):
    locked = []
    for booking in bookings:
        booking_type = booking.get("type")
        if booking.get("committed") or booking_type in (
            "committed_weekly",
            "committed_studio",
            "lecture",
            "academic_lecture",
        ):
            locked.append(booking)
            continue
        if booking_type not in ("weekly_lesson", "studio_class", "studio"):
            locked.append(booking)
    return locked


def reset_scheduling_workspace(loader, session_mgr, state):
    """Clear generated schedules and draft state while retaining lecture locks."""
    original = loader.load_bookings() or []
    preserved = [
        booking
        for booking in original
        if booking.get("type") in ("lecture", "academic_lecture")
    ]
    if len(preserved) == len(original):
        hard_reset_scheduler_state(state, session_mgr)
        return preserved

    outcome = loader.save_bookings(preserved)
    if getattr(outcome, "status", "primary") != "primary":
        loader.save_bookings(original)
        raise RuntimeError(
            getattr(outcome, "warning", "")
            or "Scheduling workspace reset could not update bookings.json."
        )
    try:
        hard_reset_scheduler_state(state, session_mgr)
    except Exception:
        rollback = loader.save_bookings(original)
        if getattr(rollback, "status", "primary") != "primary":
            raise RuntimeError(
                "Scheduling workspace reset failed and bookings rollback "
                "did not reach the primary path."
            )
        raise
    return preserved


def _normalize_manual_time_range(requested_time):
    time_match = re.findall(r"(\d{1,2}:\d{2})", str(requested_time))
    if len(time_match) >= 2:
        normalized = TimeParser.normalize_course_range(
            f"{time_match[0]}-{time_match[1]}"
        )
        if normalized:
            return normalized
    return None


def _is_studio_failed_row(raw):
    student_name = str(raw.get("Student Name", raw.get("title", ""))).lower()
    course_code = str(raw.get("Course Code", "")).lower()
    event_type = str(raw.get("Event Type", raw.get("type", ""))).lower()
    return any(token in value for token in ("studio", "stu_class", "stu class") for value in (student_name, course_code, event_type))


def _manual_event_id(name, detected_day, room, start_clock):
    safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_") or "item"
    safe_room = re.sub(r"[^A-Za-z0-9_]+", "_", str(room)).strip("_") or "room"
    safe_time = str(start_clock).replace(":", "")
    return f"manual_{safe_name}_{detected_day}_{safe_time}_{safe_room}"


def build_manual_assignment_from_failed(raw, requested_time, room, detected_day):
    source_request_id = str(
        raw.get("source_request_id") or raw.get("_source_request_id") or ""
    ).strip()
    if not source_request_id:
        raise ValueError("missing_source_request_id")
    name = raw.get("Student Name", raw.get("title", "?"))
    instrument = raw.get("Instrument", "?")
    normalized_range = _normalize_manual_time_range(requested_time)
    if normalized_range is None:
        raise ValueError("invalid_course_time")
    start_clock, end_clock = normalized_range
    event_type = "studio_class" if _is_studio_failed_row(raw) else "weekly_lesson"

    return {
        "id": _manual_event_id(name, detected_day, room, start_clock),
        "source_request_id": source_request_id,
        "resourceId": room,
        "title": f"👤 {name} ({instrument})",
        "startTime": f"{start_clock}:00" if len(start_clock) == 5 else start_clock,
        "endTime": f"{end_clock}:00" if len(end_clock) == 5 else end_clock,
        "daysOfWeek": [detected_day],
        "type": event_type,
        "extendedProps": {
            "Instructor": raw.get("Instructor", "?"),
            "Student Name": name,
            "Student No": raw.get("Student No", raw.get("Student ID", "")),
            "Instrument": instrument,
            "Study Year": raw.get("Study Year", raw.get("Year", "")),
            "Course Code": raw.get("Course Code", ""),
            "source_request_id": source_request_id,
            "day_en": DAY_NAME_BY_INDEX.get(detected_day, ""),
        },
    }


def promote_failed_assignment(session_mgr, state, failed_index, new_event):
    had_edit_session = STEP4_EDIT_SESSION_KEY in state
    edit_session = ensure_step4_edit_session(state)
    generated = copy.deepcopy(edit_session.get("assignments", []) or [])
    unassigned = copy.deepcopy(edit_session.get("unassigned_lessons", []) or [])

    if failed_index < 0 or failed_index >= len(unassigned):
        raise IndexError("failed_index out of range")

    generated.append(copy.deepcopy(new_event))
    unassigned.pop(failed_index)

    edit_session["assignments"] = generated
    edit_session["unassigned_lessons"] = unassigned
    persist_step4_draft(session_mgr, state)

    return {
        "generated_assignments": generated,
        "unassigned_lessons": unassigned,
    }


def repair_unassigned_metadata(session_mgr, state):
    had_edit_session = STEP4_EDIT_SESSION_KEY in state
    edit_session = ensure_step4_edit_session(state)
    original_unassigned = edit_session.get("unassigned_lessons", []) or []
    repaired_unassigned = copy.deepcopy(original_unassigned)
    did_repair = False
    did_mutate = False

    for lesson in repaired_unassigned:
        if "raw_row" not in lesson:
            lesson["raw_row"] = {}
            did_mutate = True
        raw_row = lesson["raw_row"]
        current_instrument = raw_row.get("Instrument", "?")
        if current_instrument not in ["?", "Studio/Unknown", "Instrumental"]:
            continue

        props = lesson.get("extendedProps", {})
        repaired_instrument = props.get("normalized_instrument") or props.get("instrument")

        if not repaired_instrument:
            course_code = raw_row.get("Course Code") or props.get("Course Code")
            if course_code:
                repaired_instrument = extract_instrument_from_course_code(course_code)

        if repaired_instrument and repaired_instrument not in ["Instrumental", "Studio/Unknown"]:
            raw_row["Instrument"] = repaired_instrument
            did_repair = True
            did_mutate = True

    if did_mutate:
        edit_session["unassigned_lessons"] = repaired_unassigned
        persist_step4_draft(session_mgr, state)
    elif repaired_unassigned is not original_unassigned:
        edit_session["unassigned_lessons"] = repaired_unassigned

    return {
        "unassigned_lessons": edit_session.get("unassigned_lessons", repaired_unassigned),
        "repaired": did_repair,
    }


def commit_current_round(loader, session_mgr, state):
    all_bookings = loader.load_bookings()
    edit_session = ensure_step4_edit_session(state)
    state_snapshot = copy.deepcopy(state)
    generated = copy.deepcopy(edit_session.get("assignments", []) or [])
    unassigned = copy.deepcopy(edit_session.get("unassigned_lessons", []) or [])
    generated_ids = {evt.get("id") for evt in generated}

    preserved = [
        booking
        for booking in all_bookings
        if (
            ((booking.get("type") not in ["weekly_lesson", "studio_class", "studio"]) or booking.get("committed"))
            and booking.get("id") not in generated_ids
        )
    ]
    final = copy.deepcopy(preserved) + copy.deepcopy(generated)

    for evt in final:
        if _is_studio_artifact_payload(evt):
            evt["type"] = "studio_class"

    for evt in final:
        if evt.get("id") in generated_ids and evt.get("type") in ("weekly_lesson", "studio_class"):
            evt["committed"] = True

    bookings_written = False
    try:
        bookings_save_outcome = loader.save_bookings(final)
        bookings_written = True
        bookings_status = (
            getattr(bookings_save_outcome, "status", "primary")
            if bookings_save_outcome is not None
            else "primary"
        )
        if bookings_status != "primary":
            warning = getattr(
                bookings_save_outcome,
                "warning",
                "Bookings save degraded to a shadow path; scheduler round was not committed.",
            )
            raise RuntimeError(warning)
        state["round_committed"] = True
        edit_session["assignments"] = copy.deepcopy(generated)
        edit_session["unassigned_lessons"] = copy.deepcopy(unassigned)
        edit_session["dirty"] = False
        if bookings_save_outcome and getattr(bookings_save_outcome, "warning", ""):
            state[SCHEDULER_DATA_SAVE_WARNING_KEY] = bookings_save_outcome.warning
        else:
            state.pop(SCHEDULER_DATA_SAVE_WARNING_KEY, None)

        expected_revision = state.get(SCHEDULER_SESSION_REVISION_KEY)
        if expected_revision is None:
            expected_revision = state.get("scheduler_session_mtime")
        persistence_outcome = persist_scheduler_session(
            session_mgr,
            state,
            expected_mtime=expected_revision,
        )
        if getattr(persistence_outcome, "status", "") == "conflict":
            raise SchedulerSessionConflict(
                getattr(persistence_outcome, "warning", "")
                or "Session changed before the schedule could be finalized."
            )
        return final
    except Exception as exc:
        rollback_error = None
        if bookings_written:
            try:
                rollback = loader.save_bookings(all_bookings)
                if getattr(rollback, "status", "primary") != "primary":
                    rollback_error = "bookings rollback did not reach the primary path"
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
        state.clear()
        state.update(state_snapshot)
        if rollback_error:
            raise RuntimeError(
                "{0} Finalize rollback failed: {1}.".format(exc, rollback_error)
            ) from exc
        raise
