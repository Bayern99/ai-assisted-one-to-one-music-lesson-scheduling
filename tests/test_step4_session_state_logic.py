from modules.scheduler.logic.session_state import (
    ROUND2_CLEAR_KEYS,
    SCHEDULER_DATA_SAVE_WARNING_KEY,
    SCHEDULER_SAVE_WARNING_KEY,
    STEP4_EDIT_SESSION_KEY,
    build_scheduler_session_snapshot,
    can_start_round_two,
    collect_scheduler_warning_messages,
    ensure_step4_edit_session,
    clear_round_two_state,
    migrate_legacy_step4_state,
    persist_step4_draft,
    reset_step4_edit_session,
    persist_scheduler_session,
    has_pending_step4_draft,
    resolve_draft_save_status,
)
from modules.shared.save_outcome import SaveOutcome


class DummySessionManager:
    def __init__(self):
        self.cleared = False
        self.saved = None

    def clear_session(self):
        self.cleared = True

    def save_session(self, payload):
        self.saved = payload


def test_build_scheduler_session_snapshot_includes_edit_state():
    state = {
        "wk_df": [{"row": 1}],
        "stu_df": [{"row": 2}],
        "scheduler_data_provenance": {"uploads": {"weekly": {"filename": "a.xlsx"}}},
        "generated_assignments": [{"id": "evt_1"}],
        "unassigned_lessons": [{"id": "failed_1"}],
        "opt_logs": ["log"],
        "override_history": [{"action": "move"}],
        "redo_stack": [{"action": "undo"}],
        "round_committed": True,
        "edit_inst_sel": "Instructor 0008",
    }

    snapshot = build_scheduler_session_snapshot(state)

    assert "generated_assignments" not in snapshot
    assert "override_history" not in snapshot
    assert "redo_stack" not in snapshot
    assert snapshot["round_committed"] is True
    assert snapshot["scheduler_data_provenance"]["uploads"]["weekly"]["filename"] == "a.xlsx"
    assert snapshot[STEP4_EDIT_SESSION_KEY]["assignments"] == [{"id": "evt_1"}]
    assert snapshot[STEP4_EDIT_SESSION_KEY]["history"] == [{"action": "move"}]
    assert "edit_inst_sel" not in snapshot


def test_clear_round_two_state_clears_cache_and_round_keys():
    state = {key: f"value_for_{key}" for key in ROUND2_CLEAR_KEYS}
    state["restored_flag"] = True
    manager = DummySessionManager()

    clear_round_two_state(state, manager)

    assert manager.cleared is True
    assert "restored_flag" in state
    for key in ROUND2_CLEAR_KEYS:
        assert key not in state


def test_persist_scheduler_session_saves_deep_copy_snapshot():
    state = {
        "generated_assignments": [{"id": "evt_1", "extendedProps": {"Student Name": "Student 0001"}}],
        "unassigned_lessons": [{"id": "failed_1"}],
        "override_history": [{"action": "move"}],
    }
    manager = DummySessionManager()

    persist_scheduler_session(manager, state)
    state["generated_assignments"][0]["extendedProps"]["Student Name"] = "Student 0002"
    state["override_history"].append({"action": "undo"})

    assert manager.saved[STEP4_EDIT_SESSION_KEY]["assignments"][0]["extendedProps"]["Student Name"] == "Student 0001"
    assert manager.saved[STEP4_EDIT_SESSION_KEY]["history"] == [{"action": "move"}]


def test_ensure_step4_edit_session_bootstraps_from_scheduler_state():
    state = {
        "generated_assignments": [{"id": "evt_1"}],
        "unassigned_lessons": [{"id": "failed_1"}],
        "override_history": [{"action": "move"}],
        "redo_stack": [{"action": "redo"}],
    }

    edit_session = ensure_step4_edit_session(state)

    assert state[STEP4_EDIT_SESSION_KEY] is edit_session
    assert edit_session["assignments"] == [{"id": "evt_1"}]
    assert edit_session["unassigned_lessons"] == [{"id": "failed_1"}]
    assert edit_session["history"] == [{"action": "move"}]
    assert edit_session["redo_stack"] == [{"action": "redo"}]
    assert edit_session["dirty"] is False


def test_build_scheduler_session_snapshot_includes_step4_edit_session():
    state = {
        "generated_assignments": [{"id": "evt_1"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": {"status": "shadow"},
        },
    }

    snapshot = build_scheduler_session_snapshot(state)

    assert snapshot[STEP4_EDIT_SESSION_KEY]["assignments"][0]["id"] == "draft_evt"


def test_build_scheduler_session_snapshot_only_persists_canonical_edit_session_when_present():
    state = {
        "generated_assignments": [{"id": "committed_evt"}],
        "unassigned_lessons": [{"id": "committed_failed"}],
        "override_history": [{"action": "committed_move"}],
        "redo_stack": [{"action": "committed_redo"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "draft_move"}],
            "redo_stack": [{"action": "draft_redo"}],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    snapshot = build_scheduler_session_snapshot(state)

    assert "generated_assignments" not in snapshot
    assert "unassigned_lessons" not in snapshot
    assert "override_history" not in snapshot
    assert "redo_stack" not in snapshot
    assert snapshot[STEP4_EDIT_SESSION_KEY]["assignments"] == [{"id": "draft_evt"}]


def test_persist_scheduler_session_records_shadow_warning_and_last_save_outcome():
    state = {
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    class WarningSessionManager(DummySessionManager):
        def save_session(self, payload):
            self.saved = payload
            return SaveOutcome(
                status="shadow",
                path="/tmp/shadow/session_cache.json",
                warning="Primary session cache save failed; wrote fallback shadow copy.",
            )

    manager = WarningSessionManager()

    outcome = persist_scheduler_session(manager, state)

    assert outcome.status == "shadow"
    assert state[SCHEDULER_SAVE_WARNING_KEY]
    assert state[STEP4_EDIT_SESSION_KEY]["last_save_outcome"]["status"] == "shadow"


def test_persist_scheduler_session_omits_legacy_root_keys_when_edit_session_exists():
    state = {
        "generated_assignments": [{"id": "committed_evt"}],
        "unassigned_lessons": [{"id": "committed_failed"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "draft_move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }
    manager = DummySessionManager()

    persist_scheduler_session(manager, state)

    assert "generated_assignments" not in manager.saved
    assert "unassigned_lessons" not in manager.saved
    assert manager.saved[STEP4_EDIT_SESSION_KEY]["assignments"] == [{"id": "draft_evt"}]


def test_persist_step4_draft_marks_edit_session_dirty_before_persist():
    state = {
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
    }

    class DraftSessionManager(DummySessionManager):
        def save_session(self, payload):
            self.saved = payload
            return SaveOutcome(status="primary", path="/tmp/session_cache.json")

    manager = DraftSessionManager()

    persist_step4_draft(manager, state)

    assert state[STEP4_EDIT_SESSION_KEY]["dirty"] is True
    assert manager.saved[STEP4_EDIT_SESSION_KEY]["dirty"] is True
    assert resolve_draft_save_status(state[STEP4_EDIT_SESSION_KEY]) == "saved"


def test_resolve_draft_save_status_maps_persist_outcomes():
    assert resolve_draft_save_status({"last_save_outcome": {"status": "primary"}}) == "saved"
    assert resolve_draft_save_status({"last_save_outcome": {"status": "shadow"}}) == "degraded"
    assert resolve_draft_save_status({"last_save_outcome": {"status": "conflict"}}) == "failed"
    assert resolve_draft_save_status({"dirty": True}) == "saved"


def test_reset_step4_edit_session_replaces_stale_draft_and_clears_histories():
    state = {
        "generated_assignments": [{"id": "new_evt"}],
        "unassigned_lessons": [{"id": "new_failed"}],
        "override_history": [{"action": "old_move"}],
        "redo_stack": [{"action": "old_redo"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "stale_evt"}],
            "unassigned_lessons": [{"id": "stale_failed"}],
            "history": [{"action": "stale_move"}],
            "redo_stack": [{"action": "stale_redo"}],
            "dirty": True,
            "last_save_outcome": {"status": "shadow"},
        },
    }

    edit_session = reset_step4_edit_session(
        state,
        assignments=state["generated_assignments"],
        unassigned_lessons=state["unassigned_lessons"],
    )

    assert edit_session["assignments"] == [{"id": "new_evt"}]
    assert edit_session["unassigned_lessons"] == [{"id": "new_failed"}]
    assert edit_session["history"] == []
    assert edit_session["redo_stack"] == []
    assert edit_session["dirty"] is False
    assert edit_session["last_save_outcome"] is None
    # Legacy root state is left untouched; canonical draft now owns runtime mutations.
    assert state["override_history"] == [{"action": "old_move"}]
    assert state["redo_stack"] == [{"action": "old_redo"}]


def test_reset_step4_edit_session_without_explicit_payload_reuses_canonical_draft_only():
    state = {
        "generated_assignments": [{"id": "legacy_evt"}],
        "unassigned_lessons": [{"id": "legacy_failed"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [{"id": "draft_failed"}],
            "history": [{"action": "stale_move"}],
            "redo_stack": [{"action": "stale_redo"}],
            "dirty": True,
            "last_save_outcome": {"status": "shadow"},
        },
    }

    edit_session = reset_step4_edit_session(state)

    assert edit_session["assignments"] == [{"id": "draft_evt"}]
    assert edit_session["unassigned_lessons"] == [{"id": "draft_failed"}]
    assert edit_session["history"] == []
    assert edit_session["redo_stack"] == []
    assert edit_session["dirty"] is False


def test_migrate_legacy_step4_state_bootstraps_edit_session_once():
    restored = {
        "generated_assignments": [{"id": "evt_1"}],
        "unassigned_lessons": [{"id": "failed_1"}],
        "override_history": [{"action": "move"}],
        "redo_stack": [{"action": "redo"}],
    }

    edit_session = migrate_legacy_step4_state(restored)

    assert edit_session == restored[STEP4_EDIT_SESSION_KEY]
    assert edit_session["assignments"] == [{"id": "evt_1"}]
    assert edit_session["unassigned_lessons"] == [{"id": "failed_1"}]
    assert edit_session["history"] == [{"action": "move"}]
    assert edit_session["redo_stack"] == [{"action": "redo"}]


def test_can_start_round_two_requires_committed_round_without_pending_draft():
    assert can_start_round_two({"round_committed": False}) is False

    committed_state = {
        "round_committed": True,
        "generated_assignments": [{"id": "evt_1"}],
        "unassigned_lessons": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "evt_1"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
    }
    assert can_start_round_two(committed_state) is True


def test_collect_scheduler_warning_messages_returns_deduped_ordered_warnings():
    state = {
        SCHEDULER_DATA_SAVE_WARNING_KEY: "Bookings shadow save warning",
        SCHEDULER_SAVE_WARNING_KEY: "Session cache shadow save warning",
    }

    assert collect_scheduler_warning_messages(state) == [
        "Bookings shadow save warning",
        "Session cache shadow save warning",
    ]


def test_collect_scheduler_warning_messages_dedupes_duplicate_warning_text():
    state = {
        SCHEDULER_DATA_SAVE_WARNING_KEY: "Same warning",
        SCHEDULER_SAVE_WARNING_KEY: "Same warning",
    }

    assert collect_scheduler_warning_messages(state) == ["Same warning"]

    pending_draft_state = {
        "round_committed": True,
        "generated_assignments": [{"id": "evt_1"}],
        "unassigned_lessons": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }
    assert can_start_round_two(pending_draft_state) is False


def test_has_pending_step4_draft_ignores_root_key_drift_when_dirty_is_false():
    state = {
        "generated_assignments": [{"id": "old_evt"}],
        "unassigned_lessons": [],
        "override_history": [],
        "redo_stack": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "new_evt"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
    }
    # When dirty is False, root key drift should be ignored
    assert has_pending_step4_draft(state) is False


def test_has_pending_step4_draft_returns_true_when_dirty_is_true():
    state = {
        "generated_assignments": [{"id": "evt"}],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "evt"}],
            "dirty": True,
        },
    }
    assert has_pending_step4_draft(state) is True


def test_has_pending_step4_draft_returns_false_without_edit_session():
    state = {"generated_assignments": [{"id": "evt"}]}
    assert has_pending_step4_draft(state) is False
