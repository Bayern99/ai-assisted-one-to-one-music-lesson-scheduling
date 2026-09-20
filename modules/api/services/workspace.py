from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, TypeVar

from modules.api.errors import ApiProblem
from modules.shared.data_loader import DataLoader
from modules.shared.session_manager import SessionManager

TRACKED_FILES = (
    "activity_cache.json",
    "bookings.json",
    "scheduling_rules.json",
    "session_cache.json",
    "workflow_state.json",
    "students.json",
    "instructors.json",
    "rooms.json",
    "semester_config.json",
    "jury_sessions.json",
    "conveners.json",
    "assessments.json",
    "jury_scores.json",
    "score_templates.json",
    "optimizer_learning_records.json",
)

SnapshotData = TypeVar("SnapshotData")
WORKSPACE_SNAPSHOT_ATTEMPTS = 3


class WorkspaceChanged(ApiProblem):
    def __init__(self, expected: str, current: str) -> None:
        self.expected = expected
        self.current = current
        super().__init__(
            status_code=409,
            code="WORKSPACE_CHANGED",
            message="Workspace changed; reload before saving",
            details={"expected": expected, "current": current},
        )


def compute_workspace_version(
    base_dir: Path,
    *,
    context: Optional[Any] = None,
) -> str:
    base_dir = Path(base_dir)
    loader = context.loader if context is not None else DataLoader(
        base_dir=str(base_dir),
        backup_corrupt_reads=False,
    )
    session_manager = (
        context.session_manager
        if context is not None
        else SessionManager(base_dir=str(base_dir))
    )
    facts = {}
    for name in TRACKED_FILES:
        if name == SessionManager.FILE_NAME:
            selected_path = session_manager.preferred_session_path()
            path = Path(selected_path) if selected_path is not None else None
        elif name == SessionManager.ACTIVITY_FILE_NAME:
            path = Path(session_manager.base_dir) / name
        else:
            path = Path(loader.preferred_data_path(name))
        stat = path.stat() if path is not None and path.exists() else None
        facts[name] = (
            None
            if stat is None
            else [str(path.resolve()), stat.st_mtime_ns, stat.st_size]
        )
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def read_workspace_snapshot(
    base_dir: Path,
    context: Any,
    reader: Callable[[], SnapshotData],
) -> Tuple[SnapshotData, str]:
    """Return a reader result bounded by two matching workspace versions."""
    with context.mutation_lock:
        for _attempt in range(WORKSPACE_SNAPSHOT_ATTEMPTS):
            before = compute_workspace_version(base_dir, context=context)
            data = reader()
            after = compute_workspace_version(base_dir, context=context)
            if before == after:
                return data, after
    raise WorkspaceChanged(expected=before, current=after)


def require_current_version(
    base_dir: Path,
    expected: str,
    *,
    context: Optional[Any] = None,
) -> str:
    current = compute_workspace_version(base_dir, context=context)
    if expected != current:
        raise WorkspaceChanged(expected=expected, current=current)
    return current
