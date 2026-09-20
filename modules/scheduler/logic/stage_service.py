"""Stage schedule command: atomically refresh the L1 validation authority."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from modules.scheduler.logic.session_state import (
    SCHEDULER_SESSION_REVISION_KEY,
    ensure_step4_edit_session,
    persist_scheduler_session,
    trim_undo_history,
)
from modules.scheduler.logic.validation_authority import (
    authority_snapshot,
    seed_validation_authority,
)


@dataclass
class StageResult:
    status: str
    message: str = ""
    warnings: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == "success"


def stage_schedule(context, state, *, expected_mtime=None) -> StageResult:
    edit_session = ensure_step4_edit_session(state)
    pre_l1 = authority_snapshot(edit_session)
    pre_l0 = {
        "assignments": copy.deepcopy(edit_session.get("assignments", []) or []),
        "unassigned_lessons": copy.deepcopy(
            edit_session.get("unassigned_lessons", []) or []
        ),
    }
    seed_validation_authority(edit_session)
    history = edit_session.setdefault("history", [])
    history.append(
        {
            "action": "stage",
            "intervention_id": uuid.uuid4().hex,
            "pre_l1": pre_l1,
            "pre_l0": pre_l0,
        }
    )
    edit_session["history"] = trim_undo_history(history)
    edit_session["redo_stack"] = []
    outcome = persist_scheduler_session(
        context.session_manager,
        state,
        expected_mtime=expected_mtime
        or state.get(SCHEDULER_SESSION_REVISION_KEY)
        or state.get("scheduler_session_mtime"),
    )
    if getattr(outcome, "status", "") == "conflict":
        return StageResult(
            status="conflict",
            message=getattr(outcome, "warning", "")
            or "Session changed before the schedule could be staged.",
        )
    warnings = []
    if getattr(outcome, "warning", ""):
        warnings.append(outcome.warning)
    return StageResult(status="success", message="Staged schedule.", warnings=warnings)


def revert_stage_record(edit_session: dict, record: dict) -> None:
    pre_l0 = record.get("pre_l0") or {}
    pre_l1 = record.get("pre_l1") or {}
    edit_session["assignments"] = copy.deepcopy(pre_l0.get("assignments", []) or [])
    edit_session["unassigned_lessons"] = copy.deepcopy(
        pre_l0.get("unassigned_lessons", []) or []
    )
    edit_session["validation_authority"] = copy.deepcopy(pre_l1)
    edit_session["unsealed"] = True


def replay_stage_record(edit_session: dict, record: dict) -> None:
    del record
    seed_validation_authority(edit_session)
