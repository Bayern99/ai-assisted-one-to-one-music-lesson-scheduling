"""
TDD tests for P1-4: data_loader.py _atomic_save temp file leak fix.

Strategy: verify temp file cleanup on crash, atomicity preservation.
"""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from modules.shared.data_loader import DataLoader


class TestAtomicSaveCleanup:
    """Verify _atomic_save temp file cleanup behavior."""

    @pytest.fixture
    def loader(self, tmp_path):
        """DataLoader pointed at temp directory."""
        dl = DataLoader(base_dir=str(tmp_path))
        return dl

    def test_tempfile_cleaned_after_json_dump_failure(self, loader, tmp_path):
        """When json.dump throws mid-write, the temp file must be cleaned up."""
        target = os.path.join(str(tmp_path), "test_cleanup.json")
        data = {"key": "value"}

        before = set(os.listdir(tmp_path))

        with patch('json.dump', side_effect=RuntimeError("simulated crash")):
            with pytest.raises(RuntimeError):
                loader._atomic_save(target, data)

        after = set(os.listdir(tmp_path))
        leaked = after - before
        assert not leaked, f"Temp file leaked: {leaked}"

    def test_tempfile_cleaned_after_replace_permission_error(self, loader, tmp_path):
        """When os.replace throws PermissionError, fallback cleanup must work."""
        target = os.path.join(str(tmp_path), "test_perm.json")
        data = {"key": "value"}

        before = set(os.listdir(tmp_path))

        # Simulate PermissionError for first two os.replace calls, then allow
        # the final fallback to call the real os.replace.
        call_count = [0]
        real_replace = os.replace

        def _failing_then_real(src, dst, _cnt=call_count, _real=real_replace):
            _cnt[0] += 1
            if _cnt[0] <= 2:
                raise PermissionError("simulated permission error")
            return _real(src, dst)

        with patch('os.replace', side_effect=_failing_then_real):
            loader._atomic_save(target, data)

        after = set(os.listdir(tmp_path))
        assert "test_perm.json" in after
        leaked = [f for f in after - before if f.startswith('tmp')]
        assert not leaked, f"Temp file leaked after fallback: {leaked}"

    def test_atomic_write_preserves_data(self, loader, tmp_path):
        """Normal atomic write path produces correct data."""
        target = os.path.join(str(tmp_path), "test_atomic.json")
        data = {"a": 1, "b": [2, 3], "c": "hello"}

        loader._atomic_save(target, data)

        assert os.path.exists(target)
        with open(target) as f:
            result = json.load(f)
        assert result == data

    def test_save_data_with_outcome_returns_shadow_and_preserves_primary_when_replace_stays_blocked(self, loader, tmp_path):
        target_name = "rules.json"
        primary = os.path.join(str(tmp_path), target_name)
        shadow = loader._shadow_paths(target_name)[0]
        loader._atomic_save(primary, {"original": True})

        with patch("os.replace", side_effect=OSError("replace blocked")):
            outcome = loader._save_data_with_outcome(target_name, {"updated": True})

        assert outcome.status == "shadow"
        assert outcome.path == shadow
        assert outcome.warning
        with open(primary, "r", encoding="utf-8") as f:
            assert json.load(f) == {"original": True}
        with open(shadow, "r", encoding="utf-8") as f:
            assert json.load(f) == {"updated": True}

    def test_save_data_with_outcome_raises_when_primary_and_shadow_writes_all_fail(self, loader, tmp_path):
        target_name = "rules.json"
        primary = os.path.join(str(tmp_path), target_name)
        loader._atomic_save(primary, {"original": True})

        with patch.object(loader, "_atomic_save", side_effect=OSError("all writes failed")):
            with pytest.raises(OSError, match="all writes failed"):
                loader._save_data_with_outcome(target_name, {"updated": True})

        with open(primary, "r", encoding="utf-8") as f:
            assert json.load(f) == {"original": True}
