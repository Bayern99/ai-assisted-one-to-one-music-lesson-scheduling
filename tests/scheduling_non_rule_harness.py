import copy
import io
import time

import pandas as pd

from modules.scheduler.logic.export_generator import build_export_dataframe
from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.rules_schema import (
    DEFAULT_RULES,
    canonicalize_rules_for_save,
    get_rules_trace,
    normalize_rules,
)
from modules.scheduler.logic.workflow_service import (
    build_locked_context,
    commit_current_round,
)
from modules.scheduler.logic.session_state import (
    clear_round_two_state,
    get_step4_unassigned_lessons,
    migrate_legacy_step4_state,
    persist_scheduler_session,
    reset_step4_edit_session,
)
from modules.scheduler.logic.lecture_service import save_lectures
from modules.shared.scheduler_data_service import parse_lectures_from_csv


def run_step0_lock_lectures(loader, lecture_csv_text):
    lecture_file = io.StringIO(lecture_csv_text)
    events, err = parse_lectures_from_csv(loader, lecture_file)
    if err and not events:
        raise AssertionError(err)

    ok, msg = save_lectures(loader, events)
    if not ok:
        raise AssertionError(msg)

    return {
        "lecture_candidates": events,
        "bookings": loader.load_bookings(),
        "message": msg,
        "parse_warning": err,
    }


def persist_upload_state(session_mgr, weekly_df=None, studio_df=None, weekly_file_name=None, studio_file_name=None):
    snapshot = session_mgr.load_session() or {}
    updates = {
        "wk_df": weekly_df,
        "stu_df": studio_df,
        "weekly_file_name": weekly_file_name,
        "studio_file_name": studio_file_name,
    }
    for key, value in updates.items():
        if value is not None:
            snapshot[key] = value
    session_mgr.save_session(snapshot)
    return snapshot


def run_step2_rules_roundtrip(loader, raw_rules, default_rules=None):
    rules_source_path = loader._preferred_path_for_read("scheduling_rules.json")
    normalized = normalize_rules(raw_rules, default_rules or DEFAULT_RULES, source_path=rules_source_path)
    saved_rules = canonicalize_rules_for_save(
        normalized,
        default_rules=default_rules or DEFAULT_RULES,
        source_path=rules_source_path,
    )
    saved_path = loader.save_data("scheduling_rules.json", saved_rules)
    reloaded_source = loader._preferred_path_for_read("scheduling_rules.json")
    reloaded = normalize_rules(loader.load_rules(), default_rules or DEFAULT_RULES, source_path=reloaded_source)
    return {
        "normalized_rules": normalized,
        "saved_rules": saved_rules,
        "reloaded_rules": reloaded,
        "saved_path": saved_path,
        "trace": get_rules_trace(normalized),
    }


def run_step3_optimize(loader, session_mgr, weekly_df, studio_df, students, rooms, rules=None):
    run_rules = copy.deepcopy(rules if rules is not None else loader.load_rules())
    if rules is not None:
        loader.save_data("scheduling_rules.json", run_rules)

    locked = build_locked_context(loader.load_bookings())
    optimizer = RoomAllocator(
        students,
        rooms,
        locked,
        run_rules,
        rules_source_path=loader._preferred_path_for_read("scheduling_rules.json"),
    )
    assignments, duplicates, logs = optimizer.optimize(weekly_df, studio_df)

    sem_conf = loader.load_semester_config()
    for assignment in assignments:
        assignment["startRecur"] = sem_conf.get("start_date", "2026-02-24")
        assignment["endRecur"] = sem_conf.get("end_date", sem_conf.get("last_day", "2026-06-30"))

    state = {
        "wk_df": weekly_df,
        "stu_df": studio_df,
        "generated_assignments": assignments,
        "assignments": assignments,
        "unassigned_lessons": optimizer.unassigned,
        "opt_logs": logs,
        "override_history": [],
        "redo_stack": [],
        "round_committed": False,
        "duplicates": duplicates,
        "locked_context": locked,
    }
    reset_step4_edit_session(
        state,
        assignments=assignments,
        unassigned_lessons=optimizer.unassigned,
    )
    persist_scheduler_session(session_mgr, state)

    return state


def run_step3_optimize_perf_smoke(loader, session_mgr, weekly_df, studio_df, students, rooms, rules=None):
    started = time.perf_counter()
    state = run_step3_optimize(loader, session_mgr, weekly_df, studio_df, students, rooms, rules)
    return state, time.perf_counter() - started


def persist_editor_state(session_mgr, state):
    migrate_legacy_step4_state(state)
    persist_scheduler_session(session_mgr, state)
    return state


def start_round_two(state, session_mgr):
    clear_round_two_state(state, session_mgr)
    return state


def restore_scheduler_state(session_mgr):
    restored = session_mgr.load_session()
    if not restored:
        return None

    for key in ("wk_df", "stu_df"):
        if key in restored and isinstance(restored[key], list):
            restored[key] = pd.DataFrame(restored[key]) if restored[key] else None

    migrate_legacy_step4_state(restored)
    restored["restored_flag"] = True
    return restored


def export_current_state(loader, state, students, valid_instructors):
    bookings = loader.load_bookings()
    student_map = {}
    for student in students:
        student_id = student.get("student_id") or student.get("Student No")
        if student_id is not None:
            student_map[str(student_id)] = student

    return build_export_dataframe(
        bookings,
        get_step4_unassigned_lessons(state),
        student_map,
        valid_instructors,
        uploaded_studio_df=state.get("stu_df"),
    )


def summarize_optimizer_state(state):
    assignments = state.get("assignments", []) or []
    duplicates = state.get("duplicates", []) or []
    unassigned = state.get("unassigned_lessons", []) or []
    logs = state.get("opt_logs", []) or []

    rooms = {}
    for assignment in assignments:
        room_id = assignment.get("resourceId", "")
        rooms[room_id] = rooms.get(room_id, 0) + 1

    event_types = {}
    for assignment in assignments:
        event_type = assignment.get("type", "")
        event_types[event_type] = event_types.get(event_type, 0) + 1

    reason_codes = {}
    for lesson in unassigned:
        reason_code = lesson.get("reason_code", "")
        reason_codes[reason_code] = reason_codes.get(reason_code, 0) + 1

    return {
        "assignments": len(assignments),
        "duplicates": len(duplicates),
        "rooms": dict(sorted(rooms.items())),
        "types": dict(sorted(event_types.items())),
        "reasons": dict(sorted(reason_codes.items())),
        "studio_summary": logs[-1] if logs else "",
    }


def summarize_export_dataframe(df):
    if df is None or df.empty:
        return {
            "rows": 0,
            "rooms": [],
            "event_types": {},
            "students": [],
            "unassigned_students": [],
        }

    return {
        "rows": len(df),
        "rooms": sorted(df["Room"].dropna().unique().tolist()),
        "event_types": dict(sorted(df["Event Type"].value_counts().to_dict().items())),
        "students": sorted(df["Student Name (EN)"].dropna().tolist()),
        "unassigned_students": sorted(df[df["Room"] == "Unassigned"]["Student Name (EN)"].dropna().tolist()),
    }


def run_step5_export_perf_smoke(loader, state, students, valid_instructors):
    started = time.perf_counter()
    df = export_current_state(loader, state, students, valid_instructors)
    return df, time.perf_counter() - started
