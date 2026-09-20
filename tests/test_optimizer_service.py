from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from modules.scheduler.context import build_scheduler_context
from modules.scheduler.logic.optimizer_service import (
    OptimizerInputError,
    OptimizerPersistenceError,
    run_optimizer,
)
from modules.scheduler.logic.provenance import (
    active_workbook_provenance,
    record_uploaded_workbook,
)
from modules.shared.save_outcome import SaveOutcome


class _FakeOptimizer:
    def __init__(self) -> None:
        self.unassigned = [
            {
                "id": "unassigned-1",
                "source_request_id": "weekly:1",
                "reason_code": "no_compatible_room",
                "reason": "No compatible room",
            }
        ]

    def optimize(self, weekly, studio):
        assert list(weekly["Student No"]) == ["S1", "S2"]
        assert studio is None
        return (
            [
                {
                    "id": "assignment-1",
                    "resourceId": "R1",
                    "source_request_id": "weekly:0",
                    "daysOfWeek": [1],
                    "startTime": "10:00:00",
                    "endTime": "11:00:00",
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "Instructor": "Instructor 0008",
                        "Instrument": "Piano",
                        "Student No": "S1",
                    },
                }
            ],
            [
                {
                    "id": "S1",
                    "name": "Student 0001",
                    "course": "MUS100",
                    "day": "Monday",
                    "time": "10:00",
                }
            ],
            ["optimizer started", "optimizer success"],
        )


class _PinAwareOptimizer:
    def __init__(self) -> None:
        self.unassigned = []
        self.received_pins = None

    def optimize(self, weekly, studio, *, pinned_assignments=None):
        self.received_pins = pinned_assignments
        return list(pinned_assignments or []), [], ["optimizer preserved pins"]


@pytest.fixture
def context(tmp_path, monkeypatch):
    context = build_scheduler_context(base_dir=str(tmp_path))
    context.loader.save_data(
        "students.json",
        [{"student_id": "S1", "name": "Student 0001", "instrument": "Piano"}],
    )
    context.loader.save_data(
        "rooms.json",
        [{"id": "R1", "types": ["Piano"], "capacity": 10}],
    )
    context.loader.save_data("bookings.json", [])
    context.loader.save_data(
        "scheduling_rules.json",
        {"room_types": {"R1": ["Piano"]}},
    )
    context.loader.save_data(
        "semester_config.json",
        {"start_date": "2026-03-01", "end_date": "2026-06-15"},
    )
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda students, rooms, locked, rules=None: _FakeOptimizer(),
    )
    return context


@pytest.fixture
def scheduler_state():
    return {
        "wk_df": pd.DataFrame(
            [
                {
                    "Student No": "S1",
                    "Student Name": "Student 0001",
                    "Instructor": "Instructor 0008",
                    "Day of Week": "Monday",
                    "Class Time": "10:00-11:00",
                    "Course Code": "MUS100",
                },
                {
                    "Student No": "S2",
                    "Student Name": "Student 0002",
                    "Instructor": "Instructor 0009",
                    "Day of Week": "Tuesday",
                    "Class Time": "11:00-12:00",
                    "Course Code": "MUS101",
                },
            ]
        ),
        "stu_df": None,
    }


def test_optimizer_service_builds_step4_draft(context, scheduler_state):
    result = run_optimizer(context, scheduler_state)

    edit_session = scheduler_state["step4_edit_session"]
    assert result.assignment_count == len(edit_session["assignments"])
    assert result.unassigned_count == len(edit_session["unassigned_lessons"])
    assert result.duplicate_count == 1
    assert result.duplicates[0]["id"] == "S1"
    assert scheduler_state["scheduler_rules_trace"] == result.rules_trace
    assert result.rules_snapshot["room_types"] == {"R1": ["Piano"]}
    assert edit_session["assignments"][0]["startRecur"] == "2026-03-01"
    assert edit_session["assignments"][0]["endRecur"] == "2026-06-15"
    assert scheduler_state["opt_logs"] == [
        "optimizer started",
        "optimizer success",
    ]

    persisted = json.loads(
        Path(context.session_manager._get_path()).read_text(encoding="utf-8")
    )
    assert persisted["step4_edit_session"]["assignments"][0]["id"] == (
        "assignment-1"
    )


def test_optimizer_service_rejects_missing_weekly_workbook(context):
    with pytest.raises(OptimizerInputError, match="Weekly workbook is required"):
        run_optimizer(context, {})


def test_optimizer_service_rejects_blocked_preflight_without_persisting(
    context,
    scheduler_state,
):
    context.loader.save_data("rooms.json", [{"id": "R1", "types": []}])
    context.loader.save_data("scheduling_rules.json", {})
    session_path = context.session_manager._get_path()

    with pytest.raises(OptimizerInputError, match="Room inventory"):
        run_optimizer(context, scheduler_state)

    assert not Path(session_path).exists()


def test_optimizer_service_reports_session_conflict_instead_of_false_success(
    context,
    scheduler_state,
    monkeypatch,
):
    monkeypatch.setattr(
        context.session_manager,
        "save_session",
        lambda *args, **kwargs: SaveOutcome(
            status="conflict",
            path=context.session_manager._get_path(),
            warning="Session cache changed while optimizer was running.",
        ),
    )

    with pytest.raises(
        OptimizerPersistenceError,
        match="Session cache changed",
    ):
        run_optimizer(context, scheduler_state)


def test_optimizer_service_preserve_pinned_passes_valid_step4_pins_to_optimizer(
    context,
    monkeypatch,
):
    optimizer = _PinAwareOptimizer()
    monkeypatch.setattr(
        context,
        "make_optimizer",
        lambda students, rooms, locked, rules=None: optimizer,
    )
    state = {
        "wk_df": pd.DataFrame(
            [
                {
                    "Student No": "S1",
                    "Instructor": "Instructor 0008",
                    "Day of Week": "Monday",
                    "Class Time": "10:00-11:00",
                    "Course Code": "MUS100",
                }
            ]
        ),
        "stu_df": None,
        "scheduler_data_provenance": {},
        "step4_edit_session": {
            "assignments": [
                {
                    "id": "assignment-1",
                    "source_request_id": "weekly:0",
                    "resourceId": "R1",
                    "daysOfWeek": [1],
                    "startTime": "10:00:00",
                    "endTime": "11:00:00",
                    "pinned": True,
                    "extendedProps": {"Instructor": "Instructor 0008", "Instrument": "Piano"},
                }
            ],
            "unassigned_lessons": [],
            "history": [],
            "dirty": True,
        },
    }
    state["scheduler_data_provenance"] = record_uploaded_workbook(
        state["scheduler_data_provenance"],
        "weekly",
        "weekly.xlsx",
        b"weekly-fixture",
    )
    version, digests = active_workbook_provenance(state["scheduler_data_provenance"])
    state["step4_edit_session"]["source_workbook_version"] = version
    state["step4_edit_session"]["source_workbook_digests"] = digests

    result = run_optimizer(context, state, rerun_mode="preserve_pinned")

    assert [item["source_request_id"] for item in optimizer.received_pins] == [
        "weekly:0"
    ]
    assert result.rerun_mode == "preserve_pinned"
    assert result.preserved_pin_count == 1
    assert state["optimizer_run_summary"] == {
        "rerun_mode": "preserve_pinned",
        "preserved_pin_count": 1,
        "downgraded_pin_count": 0,
        "downgraded_pins": [],
        "assigned_count": 1,
        "unresolved_count": 0,
    }
