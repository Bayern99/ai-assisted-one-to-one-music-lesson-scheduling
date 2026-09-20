import json
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from modules.shared.session_manager import SessionManager


class TestSessionShadowFallback:
    """Verify that load_session() falls back to shadow copies when the
    most-recent file (by mtime) is corrupted."""

    @staticmethod
    def _write_json(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    @staticmethod
    def _corrupt(path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('not valid json {{{')

    def test_load_session_reads_newer_shadow_when_primary_corrupted(self):
        """When primary is corrupted AND has the newest mtime, load_session
        must fall back to an older but valid shadow copy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir, ttl_seconds=99999)
            primary = mgr._get_path()
            shadows = mgr._get_shadow_paths()

            # Write valid shadow first (old mtime)
            self._write_json(shadows[0], {"step": 4, "recovered": True})
            shadow_mtime = os.path.getmtime(shadows[0])

            # Corrupt primary after shadow (newer mtime)
            time.sleep(0.01)  # ensure primary mtime > shadow mtime
            self._corrupt(primary)

            assert os.path.getmtime(primary) > shadow_mtime, \
                "Primary must be newer than shadow for fallback test"

            result = mgr.load_session()
            assert result == {"step": 4, "recovered": True}, \
                "Should fall back to valid shadow when newest file is corrupted"

    def test_load_session_tries_all_shadows_before_giving_up(self):
        """When primary and first shadow are both corrupted, load_session
        must try the second shadow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir, ttl_seconds=99999)
            primary = mgr._get_path()
            shadows = mgr._get_shadow_paths()

            # Write valid second shadow (oldest)
            self._write_json(shadows[1], {"step": 5, "last_resort": True})
            # Corrupt first shadow (middle)
            time.sleep(0.01)
            self._corrupt(shadows[0])
            # Corrupt primary (newest)
            time.sleep(0.01)
            self._corrupt(primary)

            result = mgr.load_session()
            assert result == {"step": 5, "last_resort": True}, \
                "Should try all candidates before giving up"

    def test_load_session_skips_corrupted_newer_shadow_and_uses_valid_primary(self):
        """A newer corrupted shadow must not mask an older valid primary snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir, ttl_seconds=99999)
            primary = mgr._get_path()
            shadow = mgr._get_shadow_paths()[0]

            self._write_json(primary, {"step": 2, "source": "primary"})
            time.sleep(0.01)
            self._corrupt(shadow)

            result = mgr.load_session()

            assert result == {"step": 2, "source": "primary"}

    def test_load_session_returns_none_when_all_copies_corrupted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir, ttl_seconds=99999)
            primary = mgr._get_path()
            for shadow in mgr._get_shadow_paths():
                self._corrupt(shadow)
            self._corrupt(primary)

            result = mgr.load_session()
            assert result is None


class TestAtomicWriteSafety:
    """The PermissionError fallback path must not delete the original file
    before confirming the replacement write succeeds."""

    def test_atomic_write_writes_and_reads_back_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir)
            path = os.path.join(tmpdir, "target.json")
            original = {"original": True}
            mgr._atomic_write(path, original)

            with open(path, 'r', encoding='utf-8') as f:
                assert json.load(f) == original

            updated = {"updated": True}
            mgr._atomic_write(path, updated)
            with open(path, 'r', encoding='utf-8') as f:
                assert json.load(f) == updated

    def test_save_session_returns_shadow_outcome_and_preserves_primary_when_replace_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir)
            primary = mgr._get_path()
            shadow = mgr._get_shadow_paths()[0]

            mgr._atomic_write(primary, {"original": True})

            with patch("os.replace", side_effect=OSError("replace blocked")):
                outcome = mgr.save_session({"updated": True})

            assert outcome.status == "shadow"
            assert outcome.path == shadow
            assert outcome.warning
            with open(primary, "r", encoding="utf-8") as f:
                assert json.load(f) == {"original": True}

            with open(shadow, "r", encoding="utf-8") as f:
                assert json.load(f) == {"updated": True}

    def test_unwritable_primary_lock_location_still_allows_shadow_cas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_writer = SessionManager(base_dir=tmpdir)
            external_writer = SessionManager(base_dir=tmpdir)
            expected_revision = stale_writer.get_session_revision()
            primary = external_writer._get_path()
            original_write = external_writer._atomic_write
            real_open = open

            assert stale_writer._get_lock_path() == external_writer._get_lock_path()
            assert os.path.dirname(stale_writer._get_lock_path()) != os.path.abspath(tmpdir)
            assert os.path.abspath(tmpdir) not in os.path.basename(
                stale_writer._get_lock_path()
            )

            def deny_primary_append(path, mode="r", *args, **kwargs):
                if (
                    os.path.dirname(os.path.abspath(os.fspath(path)))
                    == os.path.abspath(tmpdir)
                    and "a" in mode
                ):
                    raise PermissionError("primary data dir is read-only")
                return real_open(path, mode, *args, **kwargs)

            def shadow_only(path, payload, preserve_existing=True):
                if path == primary:
                    raise PermissionError("primary session is read-only")
                return original_write(
                    path,
                    payload,
                    preserve_existing=preserve_existing,
                )

            with patch("builtins.open", side_effect=deny_primary_append):
                with patch.object(
                    external_writer,
                    "_atomic_write",
                    side_effect=shadow_only,
                ):
                    outcome = external_writer.save_session({"writer": "external"})

            assert outcome.status == "shadow"
            stale = stale_writer.save_session(
                {"writer": "stale"},
                expected_mtime=expected_revision,
            )
            assert stale.status == "conflict"
            assert stale_writer.load_session() == {"writer": "external"}

    def test_save_session_raises_when_primary_and_all_shadow_writes_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SessionManager(base_dir=tmpdir)
            primary = mgr._get_path()
            mgr._atomic_write(primary, {"original": True})

            with patch.object(mgr, "_atomic_write", side_effect=OSError("all writes failed")):
                with pytest.raises(OSError, match="all writes failed"):
                    mgr.save_session({"updated": True})

            with open(primary, "r", encoding="utf-8") as f:
                assert json.load(f) == {"original": True}

            unlocked = SessionManager(base_dir=tmpdir).save_session({"after": True})
            assert unlocked.status == "primary"
