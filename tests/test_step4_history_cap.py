"""TDD: undo history capped at 50 entries."""
from modules.scheduler.logic.session_state import MAX_UNDO_HISTORY, trim_undo_history


def test_trim_undo_history_drops_oldest_beyond_cap():
    history = [{"action": "move", "slot_id": f"evt_{i}"} for i in range(55)]
    trimmed = trim_undo_history(history)
    assert len(trimmed) == MAX_UNDO_HISTORY
    assert trimmed[0]["slot_id"] == "evt_5"
    assert trimmed[-1]["slot_id"] == "evt_54"


def test_trim_undo_history_preserves_short_history():
    history = [{"action": "move"}]
    assert trim_undo_history(history) == history
