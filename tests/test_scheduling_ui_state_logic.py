from modules.scheduler.logic.session_state import (
    RESTORE_NOTICE_KEY,
    SCHEDULER_STEP_TABS,
    build_restore_notice,
    infer_default_scheduler_tab,
)
from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY


class FrameStub:
    def __init__(self, *, empty):
        self.empty = empty


def test_infer_default_scheduler_tab_defaults_to_step0_without_progress():
    assert infer_default_scheduler_tab({}) == SCHEDULER_STEP_TABS[0]


def test_infer_default_scheduler_tab_returns_step1_for_partial_upload():
    state = {"wk_df": FrameStub(empty=False), "stu_df": None}

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[1]


def test_infer_default_scheduler_tab_returns_step2_after_both_uploads():
    state = {"wk_df": FrameStub(empty=False), "stu_df": FrameStub(empty=False)}

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[2]


def test_infer_default_scheduler_tab_returns_step4_for_draft_schedule_state():
    state = {
        "wk_df": FrameStub(empty=False),
        "stu_df": FrameStub(empty=False),
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "evt_1"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": False,
            "last_save_outcome": None,
        },
    }

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[4]


def test_infer_default_scheduler_tab_returns_step5_for_committed_round():
    state = {
        "wk_df": FrameStub(empty=False),
        "stu_df": FrameStub(empty=False),
        "round_committed": True,
    }

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[5]


def test_build_restore_notice_prefers_draft_restore_message():
    restored = {
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "evt_1"}],
            "unassigned_lessons": [],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    assert build_restore_notice(restored) == "Restored scheduler draft from local cache."


def test_build_restore_notice_returns_upload_message_for_files_only():
    restored = {"wk_df": FrameStub(empty=False), "stu_df": FrameStub(empty=False)}

    assert build_restore_notice(restored) == "Restored uploaded scheduler files from local cache."


def test_build_restore_notice_returns_committed_message_for_committed_only_state():
    restored = {"round_committed": True}

    assert build_restore_notice(restored) == "Restored committed scheduler state from local cache."


def test_build_restore_notice_returns_none_for_empty_restore_payload():
    restored = {
        "wk_df": FrameStub(empty=True),
        "stu_df": FrameStub(empty=True),
        RESTORE_NOTICE_KEY: "ignored",
    }

    assert build_restore_notice(restored) is None


def test_infer_default_scheduler_tab_uses_step4_edit_session_when_root_state_is_empty():
    state = {
        "wk_df": FrameStub(empty=False),
        "stu_df": FrameStub(empty=False),
        "generated_assignments": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[4]


def test_build_restore_notice_prefers_step4_edit_session_when_root_state_is_empty():
    restored = {
        "generated_assignments": [],
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    assert build_restore_notice(restored) == "Restored scheduler draft from local cache."


def test_infer_default_scheduler_tab_prefers_step4_when_dirty_draft_exists_after_commit():
    state = {
        "wk_df": FrameStub(empty=False),
        "stu_df": FrameStub(empty=False),
        "generated_assignments": [{"id": "committed_evt"}],
        "round_committed": True,
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    assert infer_default_scheduler_tab(state) == SCHEDULER_STEP_TABS[4]


def test_build_restore_notice_prefers_draft_message_over_committed_when_dirty_draft_exists():
    restored = {
        "generated_assignments": [{"id": "committed_evt"}],
        "round_committed": True,
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [{"id": "draft_evt"}],
            "unassigned_lessons": [],
            "history": [{"action": "move"}],
            "redo_stack": [],
            "dirty": True,
            "last_save_outcome": None,
        },
    }

    assert build_restore_notice(restored) == "Restored scheduler draft from local cache."
