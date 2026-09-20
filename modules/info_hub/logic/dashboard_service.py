from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Optional

from modules.scheduler.logic.session_state import infer_default_scheduler_tab


@dataclass(frozen=True)
class ContinueAction:
    page_title: str
    continue_path: str
    continue_label: str
    timestamp: Optional[str] = None
    page_icon: Optional[str] = None


@dataclass(frozen=True)
class DashboardCounts:
    students: int
    instructors: int
    rooms: int
    bookings: int


@dataclass(frozen=True)
class DashboardSessionSummary:
    active_step: Optional[str]
    round_committed: bool
    draft_dirty: bool


@dataclass(frozen=True)
class DashboardSummary:
    workflow_state: dict[str, Any]
    continue_action: Optional[ContinueAction]
    counts: DashboardCounts
    session: DashboardSessionSummary
    health: dict[str, Any]


# These titles are the persisted values written by app.py. Keep this explicit;
# it is a migration seam, not a general navigation framework.
ACTIVITY_DESTINATIONS = {
    "PI Info Hub": ("/students", "Continue student records"),
    "Smart Scheduler": (
        "/schedule/resolve",
        "Continue schedule resolution",
    ),
    "Rules (Advanced)": ("/schedule/rules", "Continue scheduling rules"),
}

WORKFLOW_PAGE_TITLES = {
    "scheduling": "Smart Scheduler",
}


def _continue_action(activity: Any, workflow_state: dict[str, Any]) -> Optional[ContinueAction]:
    if activity is None or activity == {}:
        current_phase = workflow_state.get("current_phase")
        page_title = (
            WORKFLOW_PAGE_TITLES.get(current_phase)
            if isinstance(current_phase, str)
            else None
        )
        activity_record = {}
    elif isinstance(activity, dict):
        activity_record = activity
        page_title = activity_record.get("page_title")
    else:
        return None
    if not isinstance(page_title, str) or page_title not in ACTIVITY_DESTINATIONS:
        return None

    continue_path, continue_label = ACTIVITY_DESTINATIONS[page_title]
    timestamp = activity_record.get("timestamp")
    page_icon = activity_record.get("page_icon")
    return ContinueAction(
        page_title=page_title,
        continue_path=continue_path,
        continue_label=continue_label,
        timestamp=timestamp if isinstance(timestamp, str) else None,
        page_icon=page_icon if isinstance(page_icon, str) else None,
    )


def _record_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for item in value if isinstance(item, dict))


def _session_summary(session: Any) -> DashboardSessionSummary:
    if not isinstance(session, dict) or not session:
        return DashboardSessionSummary(
            active_step=None,
            round_committed=False,
            draft_dirty=False,
        )
    edit_session = session.get("step4_edit_session")
    if not isinstance(edit_session, dict):
        edit_session = {}
    return DashboardSessionSummary(
        active_step=infer_default_scheduler_tab(session),
        round_committed=bool(session.get("round_committed")),
        draft_dirty=bool(edit_session.get("dirty")),
    )


def build_dashboard_summary(loader, session_manager, health: Any) -> DashboardSummary:
    workflow_state = loader.load_workflow_state()
    if not isinstance(workflow_state, dict):
        workflow_state = {}
    activity = session_manager.load_activity()
    session = session_manager.load_session()
    students = loader.get_data("students.json")
    instructors = loader.get_data("instructors.json")
    rooms = loader.get_data("rooms.json")
    bookings = loader.load_bookings()

    return DashboardSummary(
        workflow_state=copy.deepcopy(workflow_state),
        continue_action=_continue_action(activity, workflow_state),
        counts=DashboardCounts(
            students=_record_count(students),
            instructors=_record_count(instructors),
            rooms=_record_count(rooms),
            bookings=_record_count(bookings),
        ),
        session=_session_summary(session),
        health=copy.deepcopy(health if isinstance(health, dict) else {}),
    )
