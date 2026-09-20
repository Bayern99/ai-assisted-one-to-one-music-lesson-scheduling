"""Shared scheduler session-state helpers used by the product workflow."""

import copy

from modules.scheduler.logic.provenance import SCHEDULER_PROVENANCE_KEY
from modules.scheduler.logic.validation_authority import (
    UNSEALED_KEY,
    VALIDATION_AUTHORITY_KEY,
    ensure_validation_authority,
    seed_validation_authority,
)


STEP4_EDIT_SESSION_KEY = "step4_edit_session"
MAX_UNDO_HISTORY = 50
SNAPSHOT_DF_CACHE_KEY = "_scheduler_snapshot_df_cache"
SCHEDULER_SAVE_WARNING_KEY = "scheduler_save_warning"
SCHEDULER_DATA_SAVE_WARNING_KEY = "scheduler_data_save_warning"
SCHEDULER_SESSION_REVISION_KEY = "scheduler_session_revision"
LEGACY_STEP4_STATE_KEYS = (
    "generated_assignments",
    "unassigned_lessons",
    "override_history",
    "redo_stack",
)
SCHEDULER_WARNING_KEYS = (
    SCHEDULER_DATA_SAVE_WARNING_KEY,
    SCHEDULER_SAVE_WARNING_KEY,
)
SCHEDULER_UPLOAD_STATE_KEYS = (
    "wk_df",
    "stu_df",
    "weekly_file_name",
    "studio_file_name",
    SCHEDULER_PROVENANCE_KEY,
)

SCHEDULER_SESSION_KEYS = (
    *SCHEDULER_UPLOAD_STATE_KEYS,
    "opt_logs",
    "round_committed",
    "scheduler_rules_trace",
    STEP4_EDIT_SESSION_KEY,
)

ROUND2_CLEAR_KEYS = (
    *SCHEDULER_UPLOAD_STATE_KEYS,
    *LEGACY_STEP4_STATE_KEYS,
    "opt_logs",
    "round_committed",
    "scheduler_rules_trace",
    STEP4_EDIT_SESSION_KEY,
    SCHEDULER_SAVE_WARNING_KEY,
    SCHEDULER_DATA_SAVE_WARNING_KEY,
    SCHEDULER_SESSION_REVISION_KEY,
    "scheduler_session_mtime",
)
SCHEDULER_HARD_RESET_KEYS = ROUND2_CLEAR_KEYS + ("restored_flag",)
SCHEDULER_STEP_TABS = [
    "Step 0: Lock Lectures",
    "Step 1: Upload Data",
    "Step 2: Configuration",
    "Step 3: Run Optimizer",
    "Step 4: Interactive Editor",
    "Step 5: Master Export",
]
RESTORE_NOTICE_KEY = "scheduler_restore_notice"


def _has_visible_state(value):
    if value is None:
        return False
    if hasattr(value, "empty"):
        return not bool(value.empty)
    if isinstance(value, (list, tuple, set, dict, str)):
        return bool(value)
    return True


def _has_step4_draft_state(state):
    edit_session = state.get(STEP4_EDIT_SESSION_KEY)
    if not isinstance(edit_session, dict):
        return False
    return any(
        _has_visible_state(edit_session.get(key))
        for key in ("assignments", "unassigned_lessons", "history", "redo_stack")
    )


def infer_default_scheduler_tab(state):
    if has_pending_step4_draft(state):
        return SCHEDULER_STEP_TABS[4]
    if state.get("round_committed"):
        return SCHEDULER_STEP_TABS[5]
    if _has_step4_draft_state(state):
        return SCHEDULER_STEP_TABS[4]
    has_weekly = _has_visible_state(state.get("wk_df"))
    has_studio = _has_visible_state(state.get("stu_df"))
    if has_weekly and has_studio:
        return SCHEDULER_STEP_TABS[2]
    if has_weekly or has_studio:
        return SCHEDULER_STEP_TABS[1]
    return SCHEDULER_STEP_TABS[0]


def build_restore_notice(restored):
    if not isinstance(restored, dict):
        return None
    if has_pending_step4_draft(restored):
        return "Restored scheduler draft from local cache."
    if restored.get("round_committed"):
        return "Restored committed scheduler state from local cache."
    if _has_step4_draft_state(restored):
        return "Restored scheduler draft from local cache."
    if _has_visible_state(restored.get("wk_df")) or _has_visible_state(restored.get("stu_df")):
        return "Restored uploaded scheduler files from local cache."
    return None


def hard_reset_scheduler_state(state, session_mgr):
    for key in SCHEDULER_HARD_RESET_KEYS:
        if key in state:
            del state[key]
    session_mgr.clear_session()


def trim_undo_history(history):
    if len(history) <= MAX_UNDO_HISTORY:
        return history
    return history[-MAX_UNDO_HISTORY:]


def sync_optimizer_intervention_recovery(edit_session, history, redo_stack):
    recovery = edit_session.setdefault("optimizer_intervention_recovery", [])
    recovery = recovery if isinstance(recovery, list) else []
    by_id = {
        str(item.get("intervention_id")): item
        for item in recovery
        if isinstance(item, dict) and item.get("intervention_id")
    }
    # ponytail: semester-scale append-only evidence; archive with the run
    # before replacing this with a separate transactional store.
    for active, records in ((True, history), (False, redo_stack)):
        for record in records:
            intervention_id = str(record.get("intervention_id") or "").strip()
            if intervention_id:
                by_id[intervention_id] = {
                    "intervention_id": intervention_id,
                    "active": active,
                    "record": copy.deepcopy(record),
                }
    edit_session["optimizer_intervention_recovery"] = list(by_id.values())


def _dataframe_snapshot_records(df):
    if df is None:
        return None
    if hasattr(df, "empty") and df.empty:
        return []
    if hasattr(df, "to_dict"):
        return df.to_dict(orient="records")
    return df


def _snapshot_df_cache(state):
    cache = state.get(SNAPSHOT_DF_CACHE_KEY)
    if isinstance(cache, dict):
        return cache
    return {}


def _cache_upload_dataframes(state):
    cache = _snapshot_df_cache(state)
    for key in ("wk_df", "stu_df"):
        if key not in state:
            continue
        records = _dataframe_snapshot_records(state.get(key))
        cache[key] = records
    state[SNAPSHOT_DF_CACHE_KEY] = cache
    return cache


def _serialize_snapshot_value(key, value, state, df_cache):
    if key in ("wk_df", "stu_df"):
        if key in df_cache:
            return copy.deepcopy(df_cache[key])
    return copy.deepcopy(value)


def _legacy_step4_payload(state):
    return {
        "assignments": copy.deepcopy(state.get("generated_assignments", []) or []),
        "unassigned_lessons": copy.deepcopy(state.get("unassigned_lessons", []) or []),
        "history": copy.deepcopy(state.get("override_history", []) or []),
        "redo_stack": copy.deepcopy(state.get("redo_stack", []) or []),
        "resolution_waiting": {},
        "intervention_constraints": [],
        "reconciliation_plans": {},
        "optimizer_run_id": None,
        "source_workbook_version": None,
        "source_workbook_digests": {},
        "dirty": False,
        "last_save_outcome": None,
        UNSEALED_KEY: False,
        VALIDATION_AUTHORITY_KEY: {
            "assignments": copy.deepcopy(state.get("generated_assignments", []) or []),
            "unassigned_lessons": copy.deepcopy(state.get("unassigned_lessons", []) or []),
        },
    }


def _has_visible_legacy_step4_state(state):
    for key in LEGACY_STEP4_STATE_KEYS:
        value = state.get(key)
        if value:
            return True
    return False


def ensure_step4_edit_session(state):
    existing = state.get(STEP4_EDIT_SESSION_KEY)
    if isinstance(existing, dict):
        existing.setdefault("assignments", [])
        existing.setdefault("unassigned_lessons", [])
        existing.setdefault("history", [])
        existing.setdefault("redo_stack", [])
        existing.setdefault("resolution_waiting", {})
        existing.setdefault("intervention_constraints", [])
        if "reconciliation_plans" not in existing:
            existing["reconciliation_plans"] = existing.pop("reconciliation_investigations", {})
        existing.setdefault("optimizer_run_id", None)
        existing.setdefault("source_workbook_version", None)
        existing.setdefault("source_workbook_digests", {})
        existing.setdefault("optimizer_learning_recovery", None)
        existing.setdefault("optimizer_intervention_recovery", [])
        existing.setdefault("optimizer_finalized_at", None)
        existing.setdefault("optimizer_finalize_warnings", [])
        existing.setdefault("dirty", False)
        existing.setdefault("last_save_outcome", None)
        existing.setdefault(UNSEALED_KEY, False)
        ensure_validation_authority(existing)
        return existing

    edit_session = _legacy_step4_payload(state)
    state[STEP4_EDIT_SESSION_KEY] = edit_session
    return edit_session


def migrate_legacy_step4_state(state):
    existing = state.get(STEP4_EDIT_SESSION_KEY)
    if isinstance(existing, dict):
        return ensure_step4_edit_session(state)
    if not _has_visible_legacy_step4_state(state):
        return None
    return ensure_step4_edit_session(state)


def get_step4_assignments(state):
    return ensure_step4_edit_session(state)["assignments"]


def get_step4_unassigned_lessons(state):
    return ensure_step4_edit_session(state)["unassigned_lessons"]


def has_pending_step4_draft(state):
    edit_session = state.get(STEP4_EDIT_SESSION_KEY)
    if not isinstance(edit_session, dict):
        return False
    return bool(edit_session.get("dirty"))


def resolve_draft_save_status(edit_session):
    """Map last persist outcome. ``dirty`` still means unpublished, not unsaved."""
    if not isinstance(edit_session, dict):
        return "saved"
    outcome = edit_session.get("last_save_outcome")
    if not isinstance(outcome, dict):
        return "saved"
    status = str(outcome.get("status") or "").strip()
    if status == "conflict":
        return "failed"
    if status == "shadow":
        return "degraded"
    return "saved"


def can_start_round_two(state):
    edit_session = state.get(STEP4_EDIT_SESSION_KEY)
    if not isinstance(edit_session, dict):
        return False
    from modules.scheduler.logic.validation_authority import (
        authority_stale,
        is_validation_unsealed,
    )

    return (
        bool(state.get("round_committed"))
        and not has_pending_step4_draft(state)
        and not is_validation_unsealed(edit_session)
        and not authority_stale(edit_session)
    )


def collect_scheduler_warning_messages(state):
    warnings = []
    for key in SCHEDULER_WARNING_KEYS:
        message = state.get(key)
        if message and message not in warnings:
            warnings.append(message)
    provenance = state.get(SCHEDULER_PROVENANCE_KEY, {})
    syncs = provenance.get("master_data_sync", {}) if isinstance(provenance, dict) else {}
    for item in syncs.values():
        if not isinstance(item, dict):
            continue
        for message in item.get("warnings", []):
            if message and message not in warnings:
                warnings.append(message)
    return warnings


def _build_normalized_edit_session_snapshot(state):
    edit_session = ensure_step4_edit_session(state)
    return {
        "assignments": copy.deepcopy(edit_session.get("assignments", []) or []),
        "unassigned_lessons": copy.deepcopy(edit_session.get("unassigned_lessons", []) or []),
        "history": copy.deepcopy(trim_undo_history(edit_session.get("history", []) or [])),
        "redo_stack": copy.deepcopy(edit_session.get("redo_stack", []) or []),
        "resolution_waiting": copy.deepcopy(edit_session.get("resolution_waiting", {}) or {}),
        "intervention_constraints": copy.deepcopy(edit_session.get("intervention_constraints", []) or []),
        "reconciliation_plans": copy.deepcopy(edit_session.get("reconciliation_plans", {}) or {}),
        "optimizer_run_id": edit_session.get("optimizer_run_id"),
        "source_workbook_version": edit_session.get("source_workbook_version"),
        "source_workbook_digests": copy.deepcopy(
            edit_session.get("source_workbook_digests", {}) or {}
        ),
        "optimizer_learning_recovery": copy.deepcopy(
            edit_session.get("optimizer_learning_recovery")
        ),
        "optimizer_intervention_recovery": copy.deepcopy(
            edit_session.get("optimizer_intervention_recovery", []) or []
        ),
        "optimizer_finalized_at": edit_session.get("optimizer_finalized_at"),
        "optimizer_finalize_warnings": copy.deepcopy(
            edit_session.get("optimizer_finalize_warnings", []) or []
        ),
        "dirty": bool(edit_session.get("dirty")),
        "last_save_outcome": copy.deepcopy(edit_session.get("last_save_outcome")),
        UNSEALED_KEY: bool(edit_session.get(UNSEALED_KEY)),
        VALIDATION_AUTHORITY_KEY: copy.deepcopy(
            ensure_validation_authority(edit_session)
        ),
    }


def build_scheduler_session_snapshot(state):
    snapshot = {}
    edit_session_snapshot = None
    if STEP4_EDIT_SESSION_KEY in state or _has_visible_legacy_step4_state(state):
        edit_session_snapshot = _build_normalized_edit_session_snapshot(state)

    df_cache = _cache_upload_dataframes(state)
    for key in SCHEDULER_SESSION_KEYS:
        if key in state:
            if key == STEP4_EDIT_SESSION_KEY and edit_session_snapshot is not None:
                snapshot[key] = edit_session_snapshot
            else:
                snapshot[key] = _serialize_snapshot_value(key, state[key], state, df_cache)
    return snapshot


def persist_scheduler_session(session_mgr, state, expected_mtime=None):
    snapshot = build_scheduler_session_snapshot(state)
    if expected_mtime is not None:
        outcome = session_mgr.save_session(snapshot, expected_mtime=expected_mtime)
    else:
        outcome = session_mgr.save_session(snapshot)

    edit_session = state.get(STEP4_EDIT_SESSION_KEY)
    if edit_session is not None:
        edit_session["last_save_outcome"] = outcome.to_dict() if hasattr(outcome, "to_dict") else None

    if outcome and getattr(outcome, "status", "") == "conflict":
        state[SCHEDULER_SAVE_WARNING_KEY] = outcome.warning
    elif outcome and getattr(outcome, "warning", ""):
        state[SCHEDULER_SAVE_WARNING_KEY] = outcome.warning
    else:
        state.pop(SCHEDULER_SAVE_WARNING_KEY, None)

    if outcome and getattr(outcome, "status", "") != "conflict":
        if getattr(outcome, "revision", None) is not None:
            state[SCHEDULER_SESSION_REVISION_KEY] = outcome.revision
        if getattr(outcome, "mtime", None) is not None:
            state["scheduler_session_mtime"] = outcome.mtime
    return outcome


def persist_step4_draft(session_mgr, state):
    edit_session = ensure_step4_edit_session(state)
    edit_session["dirty"] = True
    expected_revision = state.get(SCHEDULER_SESSION_REVISION_KEY)
    if expected_revision is None:
        expected_revision = state.get("scheduler_session_mtime")
    return persist_scheduler_session(
        session_mgr,
        state,
        expected_mtime=expected_revision,
    )


def reset_step4_edit_session(
    state,
    assignments=None,
    unassigned_lessons=None,
    optimizer_run_id=None,
    source_workbook_version=None,
    source_workbook_digests=None,
):
    current_edit_session = state.get(STEP4_EDIT_SESSION_KEY)
    if not isinstance(current_edit_session, dict):
        current_edit_session = {}
    edit_session = {
        "assignments": copy.deepcopy(
            assignments if assignments is not None else (current_edit_session.get("assignments", []) or [])
        ),
        "unassigned_lessons": copy.deepcopy(
            unassigned_lessons
            if unassigned_lessons is not None
            else (current_edit_session.get("unassigned_lessons", []) or [])
        ),
        "history": [],
        "redo_stack": [],
        "resolution_waiting": {},
        "reconciliation_plans": {},
        "optimizer_run_id": (
            optimizer_run_id
            if optimizer_run_id is not None
            else current_edit_session.get("optimizer_run_id")
        ),
        "source_workbook_version": (
            source_workbook_version
            if source_workbook_version is not None
            else current_edit_session.get("source_workbook_version")
        ),
        "source_workbook_digests": copy.deepcopy(
            source_workbook_digests
            if source_workbook_digests is not None
            else (current_edit_session.get("source_workbook_digests", {}) or {})
        ),
        "optimizer_learning_recovery": None,
        "optimizer_intervention_recovery": [],
        "optimizer_finalized_at": None,
        "optimizer_finalize_warnings": [],
        "dirty": False,
        "last_save_outcome": None,
        UNSEALED_KEY: False,
        VALIDATION_AUTHORITY_KEY: {
            "assignments": copy.deepcopy(
                assignments if assignments is not None else (current_edit_session.get("assignments", []) or [])
            ),
            "unassigned_lessons": copy.deepcopy(
                unassigned_lessons
                if unassigned_lessons is not None
                else (current_edit_session.get("unassigned_lessons", []) or [])
            ),
        },
    }
    seed_validation_authority(edit_session)
    state[STEP4_EDIT_SESSION_KEY] = edit_session
    return edit_session


def clear_round_two_state(state, session_mgr):
    for key in ROUND2_CLEAR_KEYS:
        if key in state:
            del state[key]
    session_mgr.clear_session()
