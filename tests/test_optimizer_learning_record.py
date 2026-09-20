from __future__ import annotations

import json

import pytest

from modules.scheduler.logic.optimizer_learning_record import (
    FILE_NAME,
    finalize_optimizer_run,
    get_optimizer_learning_view,
    repair_optimizer_learning_record,
    record_optimizer_intervention,
    record_optimizer_run,
    stage_optimizer_learning_recovery,
)
from modules.shared.data_loader import DataLoader


def _assignment():
    return {
        "id": "request-1",
        "source_request_id": "request-1",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "type": "weekly_lesson",
        "extendedProps": {
            "Instructor": "Instructor 0008",
            "Instrument": "Piano",
        },
    }


def _unresolved():
    return {
        "source_request_id": "request-2",
        "day": 1,
        "start": "10:00",
        "end": "11:00",
        "reason_code": "no_compatible_room",
        "reason": "No compatible room",
        "raw_row": {
            "Student Name": "Student 0001",
            "Instructor": "Instructor 0008",
            "Instrument": "Piano",
            "Day of Week": "Monday",
            "Class Time": "11:00-12:00",
        },
    }


def test_optimizer_learning_record_closes_the_run_without_raw_people_data(
    tmp_path,
):
    loader = DataLoader(base_dir=str(tmp_path))
    unresolved = _unresolved()
    state = {
        "scheduler_data_provenance": {
            "uploads": {
                "weekly": {
                    "filename": "Demo Student Names.xlsx",
                    "digest": "digest-1",
                    "uploaded_at": "2026-07-30T09:00:00+00:00",
                }
            }
        },
        "step4_edit_session": {
            "assignments": [_assignment()],
            "unassigned_lessons": [unresolved],
            "history": [],
            "optimizer_run_id": "run-1",
        },
    }
    rules = {
        "priorities": {"Piano": {"Piano": 10}},
        "constraints": {"room_stability_weight": 8},
        "room_types": {"R1": ["Piano"]},
        "instructor_priority": {"Instructor 0008": 8},
    }

    baseline = record_optimizer_run(
        loader,
        run_id="run-1",
        input_workspace_version="workspace-1",
        state=state,
        rules=rules,
        duplicate_count=1,
        started_at="2026-07-30T09:01:00+00:00",
        completed_at="2026-07-30T09:01:02+00:00",
        duration_ms=2000,
        dashboard_version="4.2.0",
    )

    assert baseline["baseline"] == {
        "assigned": 1,
        "unresolved": 1,
        "duplicates": 1,
        "preserved_pin_count": 0,
        "downgraded_pin_count": 0,
        "downgraded_pins": [],
        "allocation_rate": 0.5,
        "failure_counts": {"no_compatible_room": 1},
    }

    resolved = {
        **_assignment(),
        "id": "request-2",
        "source_request_id": "request-2",
        "resourceId": "R2",
        "startTime": "11:00:00",
        "endTime": "12:00:00",
    }
    state["step4_edit_session"].update(
        {
            "assignments": [_assignment(), resolved],
            "unassigned_lessons": [],
            "history": [
                {
                    "action": "assign",
                    "slot_id": "request-2",
                    "source_request_id": "request-2",
                    "prev_state": unresolved,
                    "new_state": resolved,
                    "decision_note": (
                        "Accepted a compatible room without increasing workload."
                    ),
                }
            ],
        }
    )

    finalized = finalize_optimizer_run(
        loader,
        state=state,
        finalized_at="2026-07-30T09:10:00+00:00",
    )

    assert finalized is not None
    assert finalized["status"] == "finalized"
    assert finalized["outcome"]["allocation_rate"] == 1.0
    assert finalized["outcome"]["allocation_rate_change"] == 0.5
    assert finalized["outcome"]["intervention_count"] == 1
    assert finalized["outcome"]["decision_note_count"] == 1
    assert get_optimizer_learning_view(loader)["latest"] == finalized

    saved = (tmp_path / FILE_NAME).read_text(encoding="utf-8")
    assert "Student 0001" not in saved
    assert "Instructor 0008" not in saved
    assert "Demo Student Names.xlsx" not in saved
    assert json.loads(saved)["runs"][0]["interventions"][0]["decision_note"]

def test_new_optimizer_run_supersedes_an_unfinalized_run(tmp_path):
    loader = DataLoader(base_dir=str(tmp_path))
    state = {
        "step4_edit_session": {
            "assignments": [],
            "unassigned_lessons": [],
        }
    }
    common = {
        "loader": loader,
        "input_workspace_version": "workspace",
        "state": state,
        "rules": {},
        "duplicate_count": 0,
        "started_at": "2026-07-30T09:00:00+00:00",
        "completed_at": "2026-07-30T09:00:01+00:00",
    }

    record_optimizer_run(run_id="run-1", **common)
    record_optimizer_run(run_id="run-2", **common)

    ledger = json.loads((tmp_path / FILE_NAME).read_text(encoding="utf-8"))
    assert ledger["runs"][0]["status"] == "superseded"
    assert ledger["runs"][0]["superseded_by"] == "run-2"
    assert ledger["runs"][1]["status"] == "open"


def test_intervention_ledger_survives_undo_history_cap_and_tracks_undo(tmp_path):
    loader = DataLoader(base_dir=str(tmp_path))
    state = {
        "step4_edit_session": {
            "assignments": [],
            "unassigned_lessons": [],
            "history": [],
            "optimizer_run_id": "run-many",
        }
    }
    record_optimizer_run(
        loader,
        run_id="run-many",
        input_workspace_version="workspace",
        state=state,
        rules={},
        duplicate_count=0,
        started_at="2026-07-30T09:00:00+00:00",
    )

    records = []
    for index in range(55):
        history_record = {
            "intervention_id": f"intervention-{index}",
            "action": "move",
            "slot_id": f"request-{index}",
            "prev_state": {
                **_assignment(),
                "id": f"request-{index}",
                "source_request_id": f"request-{index}",
            },
            "new_state": {
                **_assignment(),
                "id": f"request-{index}",
                "source_request_id": f"request-{index}",
                "resourceId": "R2",
            },
            "decision_note": f"Decision {index}",
        }
        records.append(history_record)
        record_optimizer_intervention(
            loader,
            state=state,
            history_record=history_record,
            active=True,
        )

    record_optimizer_intervention(
        loader,
        state=state,
        history_record=records[0],
        active=False,
    )
    state["step4_edit_session"]["history"] = records[-50:]
    finalized = finalize_optimizer_run(loader, state=state)

    assert finalized is not None
    assert finalized["outcome"]["intervention_count"] == 54
    assert finalized["outcome"]["decision_note_count"] == 54
    ledger = json.loads((tmp_path / FILE_NAME).read_text(encoding="utf-8"))
    events = ledger["runs"][0]["intervention_events"]
    assert len(events) == 55
    assert events[0]["active"] is False
