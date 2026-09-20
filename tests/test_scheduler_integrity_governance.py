import copy
import io
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

from modules.scheduler.logic import step4_service
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.validation_authority import seed_validation_authority
from modules.scheduler.logic.finalize_validation import collect_finalize_conflicts
from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.optimizer_service import _validate_pinned_assignments
from modules.scheduler.logic.optimizer_studio import prepare_studio_requests
from modules.scheduler.logic.reconciliation_checker import (
    build_source_requests,
    reconcile_assignments,
    verify_candidate_state,
)
from modules.scheduler.logic.step4_service import Step4DraftController
from modules.scheduler.logic.source_requests import source_request_ids
from modules.shared.time_parser import TimeParser


def _weekly_source():
    return pd.DataFrame(
        [
            {
                "Student Name": "Student 0001",
                "Student No": "S1",
                "Instructor": "Instructor 0008",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Course Code": "Piano",
            },
            {
                "Student Name": "Student 0002",
                "Student No": "S2",
                "Instructor": "Instructor 0009",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
                "Course Code": "Piano",
            },
        ]
    )


def _assignment(source_id, *, event_id=None, room="R1", instructor="Instructor 0008", start="09:00", end="10:00"):
    return {
        "id": event_id or source_id,
        "source_request_id": source_id,
        "resourceId": room,
        "daysOfWeek": [1],
        "startTime": f"{start}:00",
        "endTime": f"{end}:00",
        "type": "weekly_lesson",
        "extendedProps": {
            "Instructor": instructor,
            "Instrument": "Piano",
        },
    }


def _unresolved(source_id):
    return {
        "id": f"issue-{source_id}",
        "source_request_id": source_id,
        "type": "weekly_lesson",
        "instructor": "Instructor 0009",
        "instrument": "Piano",
        "day": 1,
        "start": "10:00",
        "end": "11:00",
        "reason_code": "no_time_feasible_room",
    }


def test_course_time_contract_is_strict_and_has_no_default_fallback():
    assert TimeParser.normalize_course_range("09:00-10:00") == ("09:00", "10:00")
    assert TimeParser.normalize_course_range("09:30-10:30") == ("09:00", "11:00")
    assert TimeParser.normalize_course_range("21:30-22:30") == ("21:00", "23:00")
    assert TimeParser.normalize_course_range("22:00-23:00") == ("22:00", "23:00")
    assert TimeParser.normalize_course_range("22:30-23:30") == ("22:00", "24:00")
    assert TimeParser.event_to_minute_range(
        {"startTime": "22:00:00", "endTime": "24:00:00"},
        default=None,
    ) == (1320, 1440)

    for value in (
        "09:00-09:15",
        "09:00-09:30",
        "09:00-09:45",
        "09:00-10:30",
        "09:00-11:00",
        "09:15-10:15",
        "09:30-09:45",
        "09:45-10:45",
        "not a time",
    ):
        assert TimeParser.normalize_course_range(value) is None
    assert TimeParser.canonical_course_occupancy(None, None) is None


def test_outside_window_course_becomes_unresolved_without_time_relocation():
    allocator = RoomAllocator(
        [],
        [{"id": "R1", "types": ["Piano"]}],
        [],
        {
            "room_types": {"R1": ["Piano"]},
            "priorities": {"Piano": {"Piano": 10}},
            "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
            "instructor_priority": {"Instructor 0008": 1},
        },
    )

    assignments, _duplicates, _logs = allocator.optimize(
        pd.DataFrame(
            [
                {
                    "Student Name": "Student 0001",
                    "Student No": "S1",
                    "Instructor": "Instructor 0008",
                    "Course Code": "Piano",
                    "Day of Week": "Monday",
                    "Class Time": "22:30-23:30",
                }
            ]
        )
    )

    assert assignments == []
    assert allocator.unassigned[0]["reason_code"] == "outside_scheduling_window"
    assert allocator.unassigned[0]["start"] == 22
    assert allocator.unassigned[0]["end"] == 24


def test_studio_tokenization_is_shared_and_filters_empty_tokens():
    studio = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher",
                "Instruments": "Piano",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": " 09:00-10:00,，09:30-10:30,, ",
            }
        ]
    )
    expected = {"studio:0:1:0", "studio:0:1:1"}

    assert source_request_ids(None, studio) == expected
    assert {
        item["source_request_id"]
        for item in build_source_requests(None, studio)
    } == expected
    requests, rejections = prepare_studio_requests(
        studio,
        room_types={"R1": ["Piano"]},
        normalize_instrument_type=lambda value: "Piano",
    )
    assert {item["source_request_id"] for item in requests} == expected
    assert rejections == []


def test_empty_studio_time_cell_is_a_blocking_rejection_without_a_fake_request():
    requests, rejections = prepare_studio_requests(
        pd.DataFrame(
            [
                {
                    "Instructor": "Studio Teacher",
                    "Instruments": "Piano",
                    "Studio 1 Date": "2026年3月30日 星期一",
                    "Studio 1 Time": ",，",
                }
            ]
        ),
        room_types={"R1": ["Piano"]},
        normalize_instrument_type=lambda value: "Piano",
    )

    assert requests == []
    assert rejections[0]["reason_code"] == "missing_studio_time"
    assert "source_request_id" not in rejections[0]["payload"]


def test_strict_reconciliation_enforces_assigned_xor_unresolved_and_counts():
    source = _weekly_source()
    assigned = [_assignment("weekly:0")]
    unresolved = [_unresolved("weekly:1")]
    valid = reconcile_assignments(source, assigned, unresolved=unresolved)
    assert valid["is_valid"] is True
    assert valid["blocking_reason_codes"] == []

    missing = reconcile_assignments(source, assigned)
    assert missing["missing_source_request_ids"] == ["weekly:1"]
    assert missing["missing_count"] == 1
    assert missing["blocking_reason_codes"] == ["missing_source"]

    phantom = reconcile_assignments(
        source,
        assigned,
        unresolved=[_unresolved("weekly:1"), _unresolved("phantom")],
    )
    assert phantom["phantom_source_request_ids"] == ["phantom"]
    assert phantom["phantom_count"] == 1
    assert "phantom_result" in phantom["blocking_reason_codes"]

    duplicate_assigned = reconcile_assignments(
        source,
        [
            _assignment("weekly:0", event_id="a"),
            _assignment("weekly:0", event_id="b"),
        ],
        unresolved=unresolved,
    )
    assert duplicate_assigned["duplicate_assigned_source_request_ids"] == ["weekly:0"]
    assert duplicate_assigned["duplicates"]
    assert "assigned_and_unresolved" not in duplicate_assigned["blocking_reason_codes"]

    duplicate_unresolved = reconcile_assignments(
        source,
        assigned,
        unresolved=[_unresolved("weekly:1"), _unresolved("weekly:1")],
    )
    assert duplicate_unresolved["duplicate_unresolved_source_request_ids"] == ["weekly:1"]
    assert duplicate_unresolved["duplicate_unresolved_count"] == 1

    dual = reconcile_assignments(
        source,
        [_assignment("weekly:0"), _assignment("weekly:1")],
        unresolved=[_unresolved("weekly:0")],
    )
    assert dual["dual_state_source_request_ids"] == ["weekly:0"]
    assert dual["duplicates"] == []
    assert dual["blocking_reason_codes"] == ["assigned_and_unresolved"]

    missing_id = reconcile_assignments(
        source,
        [{"id": "missing-id"}],
        unresolved=unresolved,
    )
    assert missing_id["missing_source_id_locations"] == [
        {"collection": "assigned", "index": 0, "item_id": "missing-id"}
    ]
    assert "missing_source_request_id" in missing_id["blocking_reason_codes"]


def test_reconciliation_report_is_stable_when_multiple_integrity_errors_coexist():
    source = _weekly_source()
    report = reconcile_assignments(
        source,
        [
            {"id": "missing-id"},
            _assignment("weekly:0", event_id="a"),
            _assignment("weekly:0", event_id="b"),
            _assignment("phantom", event_id="phantom"),
        ],
        unresolved=[
            _unresolved("weekly:0"),
            _unresolved("weekly:1"),
            _unresolved("weekly:1"),
            _unresolved("phantom-unresolved"),
            {"id": "unresolved-missing-id"},
        ],
    )

    assert report["is_valid"] is False
    assert report["blocking_reason_codes"] == [
        "phantom_result",
        "duplicate_assigned",
        "duplicate_unresolved",
        "assigned_and_unresolved",
        "missing_source_request_id",
    ]
    assert report["phantom_count"] == 2
    assert report["duplicate_assigned_count"] == 1
    assert report["duplicate_unresolved_count"] == 1
    assert report["dual_state_count"] == 1
    assert report["missing_source_id_count"] == 2
    assert report["duplicates"] == [
        {
            "source_request_id": "weekly:0",
            "assignment_ids": ["a", "b"],
        },
        {
            "source_request_id": "weekly:1",
            "state": "unresolved",
            "item_indexes": [1, 2],
        },
    ]


def test_candidate_verifier_accepts_a_complete_final_state_and_rejects_duplicate_state():
    source = _weekly_source()
    rooms = [{"id": "R1", "types": ["Piano"]}]
    rules = {
        "room_types": {"R1": ["Piano"]},
        "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
    }
    result = verify_candidate_state(
        source,
        [_assignment("weekly:0")],
        unresolved=[_unresolved("weekly:1")],
        rooms=rooms,
        rules=rules,
    )
    assert result["is_valid"] is True

    duplicate = verify_candidate_state(
        source,
        [_assignment("weekly:0"), copy.deepcopy(_assignment("weekly:0", event_id="dup"))],
        unresolved=[_unresolved("weekly:1")],
        rooms=rooms,
        rules=rules,
    )
    assert duplicate["is_valid"] is False
    assert "duplicate_assigned" in duplicate["blocking_reason_codes"]


def test_pins_downgrade_individually_and_pin_conflicts_downgrade_the_whole_set():
    source = _weekly_source()
    rules = {
        "room_types": {"R1": ["Piano"], "R2": ["Voice"]},
        "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
    }
    state = {
        "wk_df": source,
        "stu_df": None,
        "step4_edit_session": {
            "assignments": [
                {**_assignment("weekly:0", event_id="pin-room-missing", room="MISSING"), "pinned": True},
                {**_assignment("weekly:1", event_id="pin-type-mismatch", room="R2", instructor="Instructor 0009"), "pinned": True},
            ],
        },
    }
    valid, downgraded = _validate_pinned_assignments(
        state,
        rules,
        [{"id": "R1", "types": ["Piano"]}, {"id": "R2", "types": ["Voice"]}],
    )
    assert valid == []
    assert downgraded == [
        {"source_request_id": "weekly:0", "reason_codes": ["room_missing"]},
        {"source_request_id": "weekly:1", "reason_codes": ["room_type_mismatch"]},
    ]

    conflict_state = {
        "wk_df": source,
        "stu_df": None,
        "step4_edit_session": {
            "assignments": [
                {**_assignment("weekly:0", event_id="pin-a"), "pinned": True},
                {**_assignment("weekly:1", event_id="pin-b", instructor="Instructor 0009"), "pinned": True},
            ],
        },
    }
    valid, downgraded = _validate_pinned_assignments(
        conflict_state,
        rules,
        [{"id": "R1", "types": ["Piano"]}],
    )
    assert valid == []
    assert downgraded == [
        {"source_request_id": "weekly:0", "reason_codes": ["room_conflict"]},
        {"source_request_id": "weekly:1", "reason_codes": ["room_conflict"]},
    ]


def _step4_controller(source, assignments, unresolved):
    rooms = [
        {"id": "R1", "types": ["Piano"]},
        {"id": "R2", "types": ["Piano"]},
    ]
    rules = {
        "room_types": {"R1": ["Piano"], "R2": ["Piano"]},
        "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
    }
    edit_session = {
        "assignments": copy.deepcopy(assignments),
        "unassigned_lessons": copy.deepcopy(unresolved),
        "history": [],
        "redo_stack": [],
        "dirty": False,
    }
    seed_validation_authority(edit_session)
    validator = ConflictValidator(
        {
            "assignments": copy.deepcopy(assignments),
            "lectures": [],
            "rooms": rooms,
            "rules": rules,
        }
    )
    return Step4DraftController(
        session_mgr=SimpleNamespace(),
        validator=validator,
        edit_session=edit_session,
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules=rules,
        weekly_df=source,
        studio_df=None,
    )


def test_step4_candidate_hard_gate_rolls_back_invalid_mutation():
    source = _weekly_source()
    controller = _step4_controller(
        source,
        [_assignment("weekly:0")],
        [_unresolved("weekly:1")],
    )
    state = {"step4_edit_session": controller.edit_session}
    before = copy.deepcopy(controller.edit_session)
    apply_move = controller._apply_move

    def produce_noncanonical_occupancy(slot, *args, **kwargs):
        result = apply_move(slot, *args, **kwargs)
        slot["endTime"] = "10:30:00"
        result["endTime"] = "10:30:00"
        return result

    controller._apply_move = produce_noncanonical_occupancy
    result = controller.move(
        state,
        "weekly:0",
        "R2",
        1,
        "09:00",
        "10:00",
    )

    assert result.status == "failed"
    assert "noncanonical_occupancy" in result.message
    assert controller.edit_session == before
    assert state["step4_edit_session"] == before


def test_finalize_accepts_a_legal_unresolved_source_without_persisting_it_as_assigned(
    monkeypatch,
):
    source = _weekly_source()
    controller = _step4_controller(
        source,
        [_assignment("weekly:0")],
        [_unresolved("weekly:1")],
    )
    monkeypatch.setattr(
        step4_service,
        "commit_current_round",
        lambda loader, session_mgr, state: [{"id": "final-assignment"}],
    )

    result = controller.finalize({"step4_edit_session": controller.edit_session})

    assert result.status == "committed"
    assert result.final == [{"id": "final-assignment"}]


def test_finalize_blocks_a_studio_event_with_an_unparseable_date():
    runtime = SimpleNamespace(
        locked_context_assignments=[],
        booked_lectures=[],
        rooms_cache=[{"id": "R1", "types": ["Piano"]}],
        normalized_rules={
            "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
        },
    )
    conflicts, warnings = collect_finalize_conflicts(
        runtime,
        [
            {
                "id": "studio-event",
                "source_request_id": "studio:0:1:0",
                "type": "studio_class",
                "resourceId": "R1",
                "start": "2026-02-30T13:00:00",
                "end": "2026-02-30T14:00:00",
                "extendedProps": {
                    "Instrument": "Piano",
                    "date": "2026-02-30",
                },
            }
        ],
    )

    assert warnings == []
    assert any(pair[1]["message"] == "Studio date cannot be validated." for pair in conflicts)


def test_integrity_replay_cli_is_repeatable_and_anonymous():
    payload = io.BytesIO()
    writer = pd.ExcelWriter(payload)
    pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0008",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Student No": "S1",
                "Student Name": "Student 0001",
                "Course Code": "MUS101 (Piano)",
            }
        ]
    ).to_excel(writer, sheet_name="Weekly Schedule", index=False)
    pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0009",
                "Instruments": "Piano",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "13:00-14:00",
            }
        ]
    ).to_excel(writer, sheet_name="Studio Schedule", index=False)
    pd.DataFrame(
        [{"Room Number": "R1", "Piano Specifications": "Yamaha upright piano"}]
    ).to_excel(writer, sheet_name="Room", index=False)
    writer.close()

    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_scheduler_integrity.py"
    with tempfile.TemporaryDirectory() as tmpdir:
        workbook = Path(tmpdir) / "Scheduler Workbook.xlsx"
        workbook.write_bytes(payload.getvalue())
        completed = subprocess.run(
            [sys.executable, str(script), "--workbook", str(workbook)],
            capture_output=True,
            text=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["replayed_twice"] is True
    assert result["input_directory_unchanged"] is True
    assert result["input_directory_digest_before"] == result["input_directory_digest_after"]
    assert result["source_request_count"] == 2
    assert result["reconciliation_reason_codes"] == []
    assert "Student 0001" not in completed.stdout
    assert "Instructor 0008" not in completed.stdout
