from modules.scheduler.logic.session_state import (
    SCHEDULER_HARD_RESET_KEYS,
    hard_reset_scheduler_state,
)


HARD_RESET_KEYS = SCHEDULER_HARD_RESET_KEYS


class DummySessionManager:
    def __init__(self):
        self.cleared = False

    def clear_session(self):
        self.cleared = True


def test_hard_reset_scheduler_state_clears_edit_and_upload_flow_state():
    state = {key: f"value_for_{key}" for key in HARD_RESET_KEYS}
    state["scheduler_data_provenance"] = {"uploads": {"weekly": {"filename": "a.xlsx"}}}
    state["restored_flag"] = True
    state["reset_key"] = 123
    manager = DummySessionManager()

    hard_reset_scheduler_state(state, manager)

    assert manager.cleared is True
    for key in HARD_RESET_KEYS:
        assert key not in state
    assert "scheduler_data_provenance" not in state
    assert "restored_flag" not in state
    assert state["reset_key"] == 123


def test_hard_reset_keys_track_canonical_session_state_contract():
    assert HARD_RESET_KEYS == SCHEDULER_HARD_RESET_KEYS
    assert "scheduler_rules_trace" in HARD_RESET_KEYS
