"""
TDD tests for:
- P1-6: SessionManager activity tracking (Continue Where You Left Off)
- MEDIUM: session_manager _atomic_write temp_name fix
"""
import json
import os
import time
import pytest

from modules.shared.session_manager import SessionManager


class TestActivitySaveLoad:
    """Activity cache: save and load independently of session cache."""

    @pytest.fixture
    def mgr(self, tmp_path):
        return SessionManager(base_dir=str(tmp_path))

    def test_01_save_and_load_activity(self, mgr):
        """Save activity and load it back with all fields intact."""
        activity = {
            "page_title": "Smart Scheduler",
            "page_icon": "📅",
            "timestamp": "2026-03-15T14:30:00",
            "action": None,
            "has_data": True,
        }
        mgr.save_activity(activity)
        loaded = mgr.load_activity()
        assert loaded is not None
        assert loaded["page_title"] == "Smart Scheduler"

    def test_02_load_activity_no_file_returns_none(self, mgr):
        """When activity_cache.json does not exist, return None."""
        assert mgr.load_activity() is None

    def test_03_activity_ttl_not_expired(self, mgr):
        """Activity within 90-day TTL is loadable."""
        mgr.save_activity({
            "page_title": "Smart Scheduler",
            "page_icon": "📅",
            "timestamp": "2026-03-15T14:30:00",
            "action": None,
            "has_data": False,
        })
        # Backdate to 89 days ago (within 90-day TTL)
        path = os.path.join(mgr.base_dir, "activity_cache.json")
        past = time.time() - (89 * 86400)
        os.utime(path, (past, past))
        assert mgr.load_activity() is not None

    def test_04_activity_ttl_expired(self, mgr):
        """Activity beyond 90-day TTL returns None."""
        mgr.save_activity({
            "page_title": "Old Page",
            "page_icon": "📄",
            "timestamp": "2026-01-01T00:00:00",
            "action": None,
            "has_data": False,
        })
        path = os.path.join(mgr.base_dir, "activity_cache.json")
        past = time.time() - (91 * 86400)
        os.utime(path, (past, past))
        assert mgr.load_activity() is None

    def test_05_activity_independent_of_session(self, mgr):
        """Save session does not affect activity; save activity does not affect session."""
        mgr.save_session({"step": 3, "data": "hello"})
        mgr.save_activity({"page_title": "Smart Scheduler", "page_icon": "📅",
                           "timestamp": "2026-01-01T00:00:00", "action": None, "has_data": True})

        # Activity should be loadable
        activity = mgr.load_activity()
        assert activity is not None
        assert activity["page_title"] == "Smart Scheduler"

        # Session should still be loadable
        session = mgr.load_session()
        assert session is not None
        assert session["step"] == 3

    def test_06_clear_session_does_not_clear_activity(self, mgr):
        """clear_session removes session_cache.json but not activity_cache.json."""
        mgr.save_session({"step": 1})
        mgr.save_activity({"page_title": "PI Info Hub", "page_icon": "📚",
                           "timestamp": "2026-01-01T00:00:00", "action": None, "has_data": True})

        mgr.clear_session()

        # Session should be gone
        assert mgr.load_session() is None
        # Activity should survive
        assert mgr.load_activity() is not None

    def test_07_activity_corrupted_file(self, mgr):
        """Corrupted activity_cache.json returns None gracefully."""
        path = os.path.join(mgr.base_dir, "activity_cache.json")
        with open(path, 'w') as f:
            f.write("this is not valid json{{{")
        assert mgr.load_activity() is None

    def test_08_activity_timestamp_preserved(self, mgr):
        """ISO timestamp round-trips correctly."""
        activity = {
            "page_title": "Smart Scheduler",
            "page_icon": "🎓",
            "timestamp": "2026-05-17T09:45:00",
            "action": "Step 4: Interactive Editor",
            "has_data": True,
        }
        mgr.save_activity(activity)
        loaded = mgr.load_activity()
        assert loaded["timestamp"] == "2026-05-17T09:45:00"
        assert loaded["action"] == "Step 4: Interactive Editor"


class TestAtomicWriteFix:
    """SessionManager._atomic_write should not leak temp files."""

    @pytest.fixture
    def mgr(self, tmp_path):
        return SessionManager(base_dir=str(tmp_path))

    def test_temp_name_initialized_before_dump(self, mgr, tmp_path):
        """When json.dump throws, the temp file must be cleaned up."""
        target = os.path.join(str(tmp_path), SessionManager.FILE_NAME)
        before = set(os.listdir(tmp_path))

        import modules.shared.session_manager as sm
        with patch.object(sm.json, 'dump', side_effect=RuntimeError("simulated crash")):
            with pytest.raises(RuntimeError):
                mgr._atomic_write(target, {"key": "value"})

        after = set(os.listdir(tmp_path))
        leaked = after - before
        assert not leaked, f"Temp file leaked in session_manager._atomic_write: {leaked}"

    def test_atomic_write_preserves_data(self, mgr, tmp_path):
        """Normal atomic write produces correct data."""
        target = os.path.join(str(tmp_path), SessionManager.FILE_NAME)
        data = {"a": 1, "b": [2, 3]}

        mgr._atomic_write(target, data)

        assert os.path.exists(target)
        with open(target) as f:
            result = json.load(f)
        assert result == data


# patch helper (avoid name clash with unittest.mock.patch)
from unittest.mock import patch
