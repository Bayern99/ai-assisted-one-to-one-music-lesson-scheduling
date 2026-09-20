import os
import json
import logging
import time
import tempfile
import hashlib
import fcntl
from contextlib import contextmanager

import pandas as pd
from modules.shared.atomic_json_io import atomic_write_json
from modules.shared.save_outcome import SaveOutcome, SessionRevision

logger = logging.getLogger(__name__)

class SessionEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        if isinstance(obj, (pd.Timestamp, pd.Period)):
            return str(obj)
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return super().default(obj)

class SessionManager:
    """Persist the scheduler work session and a separate activity pointer.

    Work drafts in ``session_cache.json`` are durable until explicitly cleared.
    Pass ``ttl_seconds`` only for tests that need expiry. Activity still uses
    ``ACTIVITY_TTL_SECONDS``.
    """
    FILE_NAME = "session_cache.json"
    ACTIVITY_FILE_NAME = "activity_cache.json"
    ACTIVITY_TTL_SECONDS = 90 * 86400  # 90 days

    def __init__(self, base_dir="data", ttl_seconds=None):
        self.base_dir = os.path.abspath(base_dir)
        self._canonical_base_dir = os.path.realpath(self.base_dir)
        lock_key = hashlib.sha256(
            os.path.join(self._canonical_base_dir, self.FILE_NAME).encode("utf-8")
        ).hexdigest()[:24]
        lock_dir = os.path.join(tempfile.gettempdir(), "music_lesson_scheduler_session_locks")
        os.makedirs(lock_dir, exist_ok=True)
        self._lock_path = os.path.join(lock_dir, f"{lock_key}.lock")
        shadow_key = hashlib.sha1(self._canonical_base_dir.encode("utf-8")).hexdigest()[:16]
        project_shadow = os.path.join(os.path.dirname(self._canonical_base_dir), ".runtime_shadow_data", shadow_key)
        temp_shadow = os.path.join(tempfile.gettempdir(), "music_lesson_scheduler_shadow", shadow_key)
        self.shadow_dirs = []
        for candidate in [project_shadow, temp_shadow]:
            try:
                os.makedirs(candidate, exist_ok=True)
                self.shadow_dirs.append(candidate)
            except Exception:
                logger.warning("Failed to create session shadow dir: %s", candidate, exc_info=True)
        self.ttl_seconds = ttl_seconds
        self._ensure_dir()
        try:
            open(self._get_lock_path(), "a").close()
        except Exception:
            logger.warning("Failed to create session lock file", exc_info=True)

    def _ensure_dir(self):
        if not os.path.exists(self.base_dir):
            try:
                os.makedirs(self.base_dir)
            except Exception:
                logger.warning("Failed to create session base dir: %s", self.base_dir, exc_info=True)
        for shadow_dir in self.shadow_dirs:
            try:
                os.makedirs(shadow_dir, exist_ok=True)
            except Exception:
                pass

    def _get_path(self):
        return os.path.join(self.base_dir, self.FILE_NAME)

    def _get_lock_path(self):
        return self._lock_path

    @contextmanager
    def _session_lock(self, operation):
        lock_file = open(self._get_lock_path(), "a+")
        try:
            fcntl.flock(lock_file.fileno(), operation)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _get_shadow_path(self):
        return self._get_shadow_paths()[0] if self._get_shadow_paths() else os.path.join(tempfile.gettempdir(), self.FILE_NAME)

    def _get_shadow_paths(self):
        return [os.path.join(d, self.FILE_NAME) for d in self.shadow_dirs]

    def _atomic_write(self, path: str, session_data: dict, preserve_existing=True):
        atomic_write_json(
            path,
            session_data,
            preserve_existing=preserve_existing,
            encoder_cls=SessionEncoder,
        )

    def get_session_mtime(self):
        path = self._get_path()
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    def _get_session_revision_unlocked(self):
        _payload, _path, revision = self._load_preferred_session()
        return revision

    def get_session_revision(self):
        with self._session_lock(fcntl.LOCK_SH):
            return self._get_session_revision_unlocked()

    @staticmethod
    def _revision_matches(expected, current):
        if isinstance(expected, SessionRevision):
            return expected == current
        if current.mtime is None:
            return True
        return float(expected) == float(current.mtime)

    def save_session(self, session_data: dict, expected_mtime=None):
        """
        Save session data atomically to disk.
        """
        path = self._get_path()
        with self._session_lock(fcntl.LOCK_EX):
            current_revision = self._get_session_revision_unlocked()
            if (
                expected_mtime is not None
                and not self._revision_matches(expected_mtime, current_revision)
            ):
                return SaveOutcome(
                    status="conflict",
                    path=path,
                    warning="Session cache was modified by another browser tab or session. Reload before saving.",
                    revision=current_revision,
                )
            try:
                self._atomic_write(path, session_data, preserve_existing=True)
                revision = self._get_session_revision_unlocked()
                return SaveOutcome(
                    status="primary",
                    path=path,
                    mtime=revision.mtime,
                    revision=revision,
                )
            except Exception as primary_err:
                for shadow in self._get_shadow_paths():
                    try:
                        self._atomic_write(shadow, session_data, preserve_existing=False)
                        revision = self._get_session_revision_unlocked()
                        return SaveOutcome(
                            status="shadow",
                            path=shadow,
                            warning="Primary session cache save failed; wrote fallback shadow copy.",
                            mtime=revision.mtime,
                            revision=revision,
                        )
                    except Exception:
                        continue
                raise primary_err

    def _preferred_path_for_read(self):
        primary = self._get_path()
        candidates = []
        if os.path.exists(primary):
            candidates.append(primary)
        for shadow in self._get_shadow_paths():
            if os.path.exists(shadow):
                candidates.append(shadow)
        if not candidates:
            return primary
        def _mtime(path):
            try:
                return os.path.getmtime(path)
            except Exception:
                return 0
        return max(candidates, key=_mtime)

    def _all_candidates_by_mtime(self):
        """Return every readable path (primary + shadows) sorted newest-first."""
        candidates = []
        primary = self._get_path()
        if os.path.exists(primary):
            candidates.append(primary)
        for shadow in self._get_shadow_paths():
            if os.path.exists(shadow):
                candidates.append(shadow)

        def _mtime(p):
            try:
                return os.path.getmtime(p)
            except Exception:
                return 0

        candidates.sort(key=_mtime, reverse=True)
        return candidates

    def _load_preferred_session(self):
        """Return the same logical session payload and source used by reads."""
        for path in self._all_candidates_by_mtime():
            if not os.path.exists(path):
                continue

            mtime = os.path.getmtime(path)
            if self.ttl_seconds is not None and time.time() - mtime > self.ttl_seconds:
                continue

            try:
                with open(path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                    stat = os.fstat(f.fileno())
                return payload, path, SessionRevision(
                    source=os.path.realpath(path),
                    mtime_ns=stat.st_mtime_ns,
                )
            except Exception:
                logger.warning("SessionManager: skipping corrupted candidate %s", path)
                continue

        return None, None, SessionRevision(source=None, mtime_ns=None)

    def preferred_session_path(self):
        """Return the readable, non-expired source that ``load_session`` selects."""
        with self._session_lock(fcntl.LOCK_SH):
            _payload, path, _revision = self._load_preferred_session()
            return path

    def load_session_with_revision(self):
        """Load the logical session and the exact source revision read."""
        with self._session_lock(fcntl.LOCK_SH):
            payload, _path, revision = self._load_preferred_session()
            return payload, revision

    def load_session(self):
        """
        Load session data if it exists.
        Iterates candidates by mtime so that a corrupted newest file
        falls back to an older shadow copy automatically.
        Returns None if all candidates are missing, expired (when a TTL is
        configured), or corrupted.
        """
        payload, _revision = self.load_session_with_revision()
        return payload

    def clear_session(self):
        """Manually clear the session cache"""
        with self._session_lock(fcntl.LOCK_EX):
            for path in [self._get_path()] + self._get_shadow_paths():
                if os.path.exists(path):
                    os.remove(path)

    # ============================================================
    # Activity tracking (Continue Where You Left Off)
    # Independent of session cache — uses separate file + 90-day TTL
    # ============================================================

    def _get_activity_path(self):
        return os.path.join(self.base_dir, self.ACTIVITY_FILE_NAME)

    def save_activity(self, activity: dict):
        """Save activity metadata for cross-session resume."""
        path = self._get_activity_path()
        try:
            self._atomic_write(path, activity)
        except Exception:
            logger.warning("Failed to save activity cache", exc_info=True)

    def load_activity(self):
        """Load activity metadata. Returns None if missing, expired, or corrupted."""
        path = self._get_activity_path()
        if not os.path.exists(path):
            return None

        mtime = os.path.getmtime(path)
        if time.time() - mtime > self.ACTIVITY_TTL_SECONDS:
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
