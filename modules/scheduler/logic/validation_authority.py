"""L1 validation-authority snapshot helpers for Step 4 Stage/Finalize."""

from __future__ import annotations

import copy
from typing import Any, Optional

from modules.shared.time_parser import TimeParser

VALIDATION_AUTHORITY_KEY = "validation_authority"
UNSEALED_KEY = "unsealed"


def _source_request_id(event: dict) -> str:
    props = event.get("extendedProps") or {}
    props = props if isinstance(props, dict) else {}
    return str(
        event.get("source_request_id")
        or props.get("source_request_id")
        or ""
    ).strip()


def _pi_placement_signature(event: dict) -> tuple[str, str, Any, Any, Any, str]:
    props = event.get("extendedProps") or {}
    props = props if isinstance(props, dict) else {}
    instructor = str(props.get("Instructor") or event.get("instructor") or "").strip()
    room = str(event.get("resourceId") or event.get("room_id") or "").strip()
    specific_date = TimeParser.event_specific_date(event) or ""
    days = tuple(event.get("daysOfWeek") or [])
    start_clock, end_clock = TimeParser.event_clock_pair(event, default=(None, None))
    return (
        _source_request_id(event),
        instructor,
        room,
        days,
        (start_clock, end_clock),
        specific_date,
    )


def authority_snapshot(edit_session: dict) -> dict:
    authority = edit_session.get(VALIDATION_AUTHORITY_KEY)
    if not isinstance(authority, dict):
        return {"assignments": [], "unassigned_lessons": []}
    return {
        "assignments": copy.deepcopy(authority.get("assignments", []) or []),
        "unassigned_lessons": copy.deepcopy(
            authority.get("unassigned_lessons", []) or []
        ),
    }


def authority_assignments(edit_session: dict) -> list[dict]:
    return authority_snapshot(edit_session)["assignments"]


def seed_validation_authority(edit_session: dict) -> dict:
    """Replace L1 with the current L0 draft and mark the session staged."""
    snapshot = {
        "assignments": copy.deepcopy(edit_session.get("assignments", []) or []),
        "unassigned_lessons": copy.deepcopy(
            edit_session.get("unassigned_lessons", []) or []
        ),
    }
    edit_session[VALIDATION_AUTHORITY_KEY] = snapshot
    edit_session[UNSEALED_KEY] = False
    return snapshot


def ensure_validation_authority(edit_session: dict) -> dict:
    authority = edit_session.get(VALIDATION_AUTHORITY_KEY)
    if isinstance(authority, dict):
        authority.setdefault("assignments", [])
        authority.setdefault("unassigned_lessons", [])
        edit_session.setdefault(UNSEALED_KEY, False)
        return authority
    return seed_validation_authority(edit_session)


def mark_validation_unsealed(edit_session: dict) -> None:
    edit_session[UNSEALED_KEY] = True


def is_validation_unsealed(edit_session: dict) -> bool:
    return bool(edit_session.get(UNSEALED_KEY))


def authority_stale(edit_session: dict) -> bool:
    l0_assignments = edit_session.get("assignments", []) or []
    l1_assignments = authority_assignments(edit_session)
    l0_by_source = {
        _source_request_id(event): _pi_placement_signature(event)
        for event in l0_assignments
        if isinstance(event, dict) and _source_request_id(event)
    }
    l1_by_source = {
        _source_request_id(event): _pi_placement_signature(event)
        for event in l1_assignments
        if isinstance(event, dict) and _source_request_id(event)
    }
    if set(l0_by_source) != set(l1_by_source):
        return True
    return any(l0_by_source[sid] != l1_by_source[sid] for sid in l0_by_source)


def resolve_validation_tri_state(state: dict, edit_session: dict) -> str:
    if state.get("round_committed"):
        return "finalized"
    if is_validation_unsealed(edit_session) or authority_stale(edit_session):
        return "editing"
    return "staged"


def is_finalize_ready(state: dict, edit_session: dict) -> bool:
    if state.get("round_committed"):
        return False
    return not is_validation_unsealed(edit_session) and not authority_stale(edit_session)


_EXPLICIT_LOCK_TYPES = frozenset({"committed_weekly", "committed_studio"})


def is_explicit_occupancy_lock(event: dict) -> bool:
    """True when occupancy is a real lock, not a previous L1 snapshot."""
    if not isinstance(event, dict):
        return False
    if event.get("committed") is True:
        return True
    return str(event.get("type") or "").strip() in _EXPLICIT_LOCK_TYPES


def merge_committed_bookings_into_l1(
    l1_assignments: list[dict],
    l0_assignments: list[dict],
    bookings: list[dict],
) -> list[dict]:
    """Attach committed PI that is not already present in L0 or L1."""
    from modules.scheduler.logic.workflow_service import build_locked_context

    l0_sources = {
        _source_request_id(event)
        for event in l0_assignments or []
        if isinstance(event, dict) and _source_request_id(event)
    }
    l1_sources = {
        _source_request_id(event)
        for event in l1_assignments or []
        if isinstance(event, dict) and _source_request_id(event)
    }
    extras = []
    for event in build_locked_context(bookings or []):
        if not isinstance(event, dict):
            continue
        if event.get("type") in ("lecture", "academic_lecture"):
            continue
        source_id = _source_request_id(event)
        if source_id and source_id in l0_sources:
            continue
        if source_id and source_id in l1_sources:
            continue
        extras.append(event)
    return copy.deepcopy(list(l1_assignments or []) + extras)


def build_occupancy_assignments(
    l1_assignments: list[dict],
    l0_assignments: list[dict],
    *,
    exclude_source_request_id: Optional[str] = None,
) -> list[dict]:
    """Current occupancy is L0 PI plus explicit locks, not a stale L1 snapshot."""
    l0_source_ids = {
        _source_request_id(event)
        for event in l0_assignments or []
        if isinstance(event, dict) and _source_request_id(event)
    }
    held_locks = []
    for event in l1_assignments or []:
        if not isinstance(event, dict) or not is_explicit_occupancy_lock(event):
            continue
        source_id = _source_request_id(event)
        if source_id and source_id in l0_source_ids:
            if exclude_source_request_id and source_id == exclude_source_request_id:
                continue
            continue
        if exclude_source_request_id and source_id == exclude_source_request_id:
            continue
        held_locks.append(event)
    return copy.deepcopy(held_locks) + copy.deepcopy(l0_assignments or [])
