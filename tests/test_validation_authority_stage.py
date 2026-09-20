from __future__ import annotations

import copy

import pytest

from modules.scheduler.logic.session_state import (
    STEP4_EDIT_SESSION_KEY,
    ensure_step4_edit_session,
    reset_step4_edit_session,
)
from modules.scheduler.logic.validation_authority import (
    authority_assignments,
    authority_stale,
    build_occupancy_assignments,
    is_finalize_ready,
    seed_validation_authority,
)
from modules.shared.session_manager import SessionManager


def _assignment(event_id="wk-1", *, room="R103", instructor="Instructor 0008"):
    return {
        "id": event_id,
        "type": "weekly_lesson",
        "title": event_id,
        "resourceId": room,
        "source_request_id": event_id,
        "daysOfWeek": [1],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "extendedProps": {
            "Instructor": instructor,
            "source_request_id": event_id,
        },
    }


def test_optimizer_reset_reseeds_l1():
    state = {
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [_assignment("old")],
            "unassigned_lessons": [],
            "validation_authority": {
                "assignments": [_assignment("stale")],
                "unassigned_lessons": [],
            },
            "unsealed": True,
        }
    }
    reset_step4_edit_session(
        state,
        assignments=[_assignment("fresh")],
        unassigned_lessons=[],
        optimizer_run_id="run-1",
    )
    edit_session = state[STEP4_EDIT_SESSION_KEY]
    assert authority_assignments(edit_session)[0]["id"] == "fresh"
    assert edit_session["unsealed"] is False
    assert authority_stale(edit_session) is False


def test_migrate_missing_l1_on_load():
    state = {
        STEP4_EDIT_SESSION_KEY: {
            "assignments": [_assignment("wk-1")],
            "unassigned_lessons": [{"id": "issue-1"}],
        }
    }
    edit_session = ensure_step4_edit_session(state)
    assert authority_assignments(edit_session)[0]["id"] == "wk-1"
    assert edit_session["unsealed"] is False


def test_occupancy_excludes_moved_source_request_from_l1():
    l1 = [_assignment("wk-1", room="R103")]
    l0 = [copy.deepcopy(l1[0])]
    l0[0]["resourceId"] = "CC202"
    occupancy = build_occupancy_assignments(l1, l0)
    rooms = {item["resourceId"] for item in occupancy}
    assert rooms == {"CC202"}


def test_occupancy_releases_unassigned_l1_snapshot():
    l1 = [_assignment("wk-1", room="R103")]
    occupancy = build_occupancy_assignments(l1, [])
    assert occupancy == []
    from modules.scheduler.logic.conflict_validator import ConflictValidator

    validator = ConflictValidator(
        {
            "assignments": occupancy,
            "lectures": [],
            "rooms": [{"id": "R103"}],
            "rules": {},
        }
    )
    assert not validator.check_conflict("R103", 1, 540, 600)


def test_occupancy_keeps_committed_lock_after_unassign():
    locked = _assignment("wk-1", room="R103")
    locked["committed"] = True
    occupancy = build_occupancy_assignments([locked], [])
    assert occupancy[0]["resourceId"] == "R103"
    from modules.scheduler.logic.conflict_validator import ConflictValidator

    validator = ConflictValidator(
        {
            "assignments": occupancy,
            "lectures": [],
            "rooms": [{"id": "R103"}],
            "rules": {},
        }
    )
    assert validator.check_conflict("R103", 1, 540, 600)


def test_finalize_not_ready_when_unsealed():
    state = {"step4_edit_session": {"assignments": [], "unsealed": True}}
    edit_session = ensure_step4_edit_session(state)
    seed_validation_authority(edit_session)
    edit_session["unsealed"] = True
    assert is_finalize_ready(state, edit_session) is False
