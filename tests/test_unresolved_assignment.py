import copy

import pandas as pd
import pytest

from modules.api.services.scheduler import issue_groups
from modules.scheduler.logic import manual_override_primitives as primitives
from modules.scheduler.logic import (
    unresolved_assignment_primitives as assignment_primitives,
)
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.session_state import STEP4_EDIT_SESSION_KEY
from modules.scheduler.logic.step4_service import Step4DraftController
from modules.scheduler.logic.optimizer_rejections import build_studio_failed_unassigned
from modules.scheduler.logic.optimizer_studio import prepare_studio_requests
from modules.shared.save_outcome import SaveOutcome


class SessionManagerStub:
    def __init__(self):
        self.calls = 0
        self.saved = None

    def save_session(self, payload, **kwargs):
        self.calls += 1
        self.saved = copy.deepcopy(payload)
        return None


class OutcomeSessionManager(SessionManagerStub):
    def __init__(self, outcome):
        super().__init__()
        self.outcome = outcome

    def save_session(self, payload, **kwargs):
        super().save_session(payload, **kwargs)
        return self.outcome


class RaisingSessionManager(SessionManagerStub):
    def save_session(self, payload, **kwargs):
        super().save_session(payload, **kwargs)
        raise OSError("disk unavailable")


class ValidatorStub:
    def __init__(self, *, conflict=None, rule_result=None, rules=None):
        self.assignments = []
        self.rules = rules or {}
        self.rooms = [
            {"id": "R-Piano", "types": ["Piano"]},
            {"id": "R-Voice", "types": ["Voice"]},
        ]
        self.conflict = conflict
        self.rule_result = rule_result or {"allowed": True}
        self.calls = []

    def check_conflict(self, **kwargs):
        self.calls.append(kwargs)
        return self.conflict

    def validate_rules(self, room_id, instrument):
        return self.rule_result


def unresolved_record(**overrides):
    item = {
        "id": "wk_reject_S100_source-row-7",
        "student": "Student 0001",
        "sid": "S100",
        "inst": "Instructor 0002",
        "day": 1,
        "start": 9,
        "end": 10,
        "instrument": "Piano",
        "prefs": ["R-Piano", "R-Voice"],
        "raw_row": {
            "Student Name": "Student 0001",
            "Student No": "S100",
            "Instructor": "Instructor 0002",
            "Course Code": "MUS101 Piano",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Preferred Venue": "R-Piano, R-Voice",
        },
        "reason": "No feasible room",
        "reason_code": "no_time_feasible_room",
    }
    item.update(overrides)
    return item


def state_with_issue(item=None):
    issue = copy.deepcopy(item or unresolved_record())
    edit_session = {
        "assignments": [],
        "unassigned_lessons": [issue],
        "history": [],
        "redo_stack": [],
        "dirty": False,
        "last_save_outcome": None,
    }
    return {
        "generated_assignments": [],
        "unassigned_lessons": [copy.deepcopy(issue)],
        "override_history": [],
        "redo_stack": [],
        STEP4_EDIT_SESSION_KEY: edit_session,
    }


def controller_for(state, *, validator=None, session_mgr=None):
    return Step4DraftController(
        session_mgr=session_mgr or SessionManagerStub(),
        validator=validator or ValidatorStub(),
        primitive_ops=primitives,
        edit_session=state[STEP4_EDIT_SESSION_KEY],
        locked_context_assignments=[],
        booked_lectures=[],
        normalized_rules={},
    )


def test_issue_ids_and_source_request_ids_are_stable_across_reordering():
    missing_id = unresolved_record(id=None, sid="S200")
    first = unresolved_record()

    forward = issue_groups(
        {"no_time_feasible_room": 2},
        {"no_time_feasible_room": [first, missing_id]},
    )[0].items
    reverse = issue_groups(
        {"no_time_feasible_room": 2},
        {"no_time_feasible_room": [missing_id, first]},
    )[0].items

    assert {item.source_request_id: item.id for item in forward} == {
        item.source_request_id: item.id for item in reverse
    }
    assert forward[0].id == "wk_reject_S100_source-row-7"
    assert forward[0].source_request_id == "wk_reject_S100_source-row-7"
    assert not any(item.id.endswith("-0") or item.id.endswith("-1") for item in forward)


def test_same_teacher_same_slot_studio_requests_get_unique_stable_identities():
    base = unresolved_record(
        id="stu_InstructorTwo_1_0_failed",
        type="studio_class",
        student="Studio",
        date="2026-03-04",
        day=3,
        start="10:00",
        end="11:00",
    )
    first = copy.deepcopy(base)
    first["source_row_index"] = 0
    first["raw_row"]["_source_row_index"] = 0
    second = copy.deepcopy(base)
    second["source_row_index"] = 1
    second["raw_row"]["_source_row_index"] = 1

    first_ids = (
        assignment_primitives.issue_id(first),
        assignment_primitives.source_request_id(first),
    )
    second_ids = (
        assignment_primitives.issue_id(second),
        assignment_primitives.source_request_id(second),
    )

    assert first_ids != second_ids
    assert first_ids == (
        assignment_primitives.issue_id(copy.deepcopy(first)),
        assignment_primitives.source_request_id(copy.deepcopy(first)),
    )

    state = state_with_issue(first)
    state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"].append(copy.deepcopy(second))
    state["unassigned_lessons"] = copy.deepcopy(state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"])
    controller = controller_for(state)
    first_result = controller.assign(state, first_ids[0], "R-Piano", 3, "10:00", "11:00")
    second_result = controller.assign(
        state,
        second_ids[0],
        "R-Piano",
        3,
        "12:00",
        "13:00",
        teacher_confirmed=True,
    )
    assert first_result.success is True
    assert second_result.success is True
    assignments = state[STEP4_EDIT_SESSION_KEY]["assignments"]
    assert len({item["id"] for item in assignments}) == 2
    assert controller.undo(state).success is True
    assert len(state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"]) == 1
    assert assignment_primitives.issue_id(state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"][0]) == second_ids[0]
    assert controller.redo(state).success is True
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []


def test_identical_studio_rows_flow_from_parser_through_resolution_history():
    source_row = {
        "Instructor": "Dr. Duplicate",
        "Instruments": "Piano",
        "Preferred Venue": "R-Piano",
        "Studio 1 Date": "2026年3月30日 星期一",
        "Studio 1 Time": "18:00-19:00",
    }
    requests, rejections = prepare_studio_requests(
        pd.DataFrame([source_row, source_row]),
        room_types={"R-Piano": ["Piano"]},
        normalize_instrument_type=lambda value: str(value),
    )
    assert rejections == []
    failures = [
        build_studio_failed_unassigned(
            request,
            "No feasible room",
            "no_time_feasible_room",
        )
        for request in requests
    ]
    exposed = issue_groups(
        {"no_time_feasible_room": 2},
        {"no_time_feasible_room": failures},
    )[0].items
    assert len({issue.id for issue in exposed}) == 2
    assert len({issue.source_request_id for issue in exposed}) == 2

    state = state_with_issue(failures[0])
    state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"].append(copy.deepcopy(failures[1]))
    state["unassigned_lessons"] = copy.deepcopy(failures)
    controller = controller_for(state)
    for issue, start, end in zip(exposed, ("18:00", "20:00"), ("19:00", "21:00")):
        assert controller.assign(
            state,
            issue.id,
            "R-Piano",
            1,
            start,
            end,
            teacher_confirmed=start != "18:00",
        ).success is True
    assignment_ids = [item["id"] for item in state[STEP4_EDIT_SESSION_KEY]["assignments"]]
    assert len(set(assignment_ids)) == 2
    assert controller.undo(state).success is True
    assert assignment_primitives.issue_id(state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"][0]) == exposed[1].id
    assert controller.redo(state).success is True
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []


def test_issue_exposes_complete_canonical_assignment_context():
    issue = issue_groups(
        {"no_time_feasible_room": 1},
        {"no_time_feasible_room": [unresolved_record()]},
    )[0].items[0]

    assert issue.instructor == "Instructor 0002"
    assert issue.course_code == "MUS101 Piano"
    assert issue.student_name == "Student 0001"
    assert issue.student_id == "S100"
    assert issue.type == "weekly_lesson"
    assert issue.instrument == "Piano"
    assert issue.duration_minutes == 60
    assert issue.original_day == 1
    assert issue.original_start == "09:00"
    assert issue.original_end == "10:00"
    assert issue.original_date is None
    assert issue.preferred_venues == ["R-Piano", "R-Voice"]
    assert issue.room_types == ["Piano"]
    assert issue.reason == "No feasible room"
    assert issue.payload["raw_row"]["Preferred Venue"] == "R-Piano, R-Voice"


def test_generic_unresolved_instrument_is_enriched_from_canonical_student_id():
    unresolved = unresolved_record(instrument="Instrumental")
    students = [{
        "student_id": "S100",
        "name_en": "Student 0001",
        "instrument": "Strings: Cello",
    }]

    assignment_primitives.enrich_student_instruments([unresolved], students)

    assert assignment_primitives.build_context(unresolved)["instrument"] == "Strings: Cello"


def test_specific_unresolved_instrument_is_not_overwritten_by_student_registry():
    unresolved = unresolved_record(instrument="Piano")

    assignment_primitives.enrich_student_instruments(
        [unresolved],
        [{"student_id": "S100", "instrument": "Strings: Cello"}],
    )

    assert assignment_primitives.build_context(unresolved)["instrument"] == "Piano"


def test_assignment_primitives_apply_revert_and_replay_without_losing_source_payload():
    unresolved = unresolved_record()
    assignments = []
    issues = [copy.deepcopy(unresolved)]
    proposal = assignment_primitives.build_assignment(
        unresolved,
        room="R-Piano",
        day=3,
        start="14:00",
        end="15:00",
    )

    record = assignment_primitives.apply(assignments, issues, issues[0], proposal)

    assert assignments[0]["source_request_id"] == unresolved["id"]
    assert assignments[0]["raw_row"]["Preferred Venue"] == "R-Piano, R-Voice"
    assert assignments[0]["extendedProps"]["Preferred Venue"] == "R-Piano, R-Voice"
    assert issues == []

    assignment_primitives.revert_record(assignments, issues, record)
    assert assignments == []
    assert issues == [unresolved]

    assignment_primitives.replay_record(assignments, issues, record)
    assert issues == []
    assert assignments[0]["resourceId"] == "R-Piano"


def test_studio_assignment_preserves_specific_date_for_python_conflict_validation():
    unresolved = unresolved_record(
        id="stu-InstructorTwo-1-failed",
        student="Studio",
        date="2026-03-04",
        day=3,
        start=10,
        end=12,
        instrument="Piano",
    )
    validator = ValidatorStub()

    result = assignment_primitives.validate(
        validator,
        unresolved,
        "R-Piano",
        3,
        "13:30",
        "14:30",
    )

    assert result["success"] is True
    assert result["specific_date"] == "2026-03-04"
    assert result["assignment"]["type"] == "studio_class"
    assert result["assignment"]["start"] == "2026-03-04T13:00:00"
    assert result["assignment"]["end"] == "2026-03-04T15:00:00"
    assert "daysOfWeek" not in result["assignment"]
    assert validator.calls == [
        {
            "room_id": "R-Piano",
            "day_idx": 3,
            "start_min": 780,
            "end_min": 900,
            "specific_date": "2026-03-04",
        }
    ]


def test_move_dated_studio_rejects_overnight_interval():
    slot = {
        "id": "studio-1",
        "type": "studio_class",
        "resourceId": "R-Piano",
        "start": "2026-03-04T20:00:00",
        "end": "2026-03-04T21:00:00",
    }
    validator = ValidatorStub()

    wrong_day = primitives.validate_move(
        validator, slot, "R-Piano", 4, "23:00", "01:00"
    )
    accepted = primitives.validate_move(
        validator, slot, "R-Piano", 3, "23:00", "01:00"
    )
    assert wrong_day == {"success": False, "message": "End time must be after start time."}
    assert accepted == {"success": False, "message": "End time must be after start time."}
    assert validator.calls == []


def test_studio_day_comes_from_original_date_and_validate_and_commit_reject_mismatch():
    unresolved = unresolved_record(
        id="stu-InstructorTwo-day-failed",
        type="studio_class",
        student="Studio",
        date="2026-03-04",
        day=5,
        start="10:00",
        end="12:00",
    )
    validator = ValidatorStub()

    context = assignment_primitives.build_context(unresolved)
    validation = assignment_primitives.validate(
        validator,
        unresolved,
        "R-Piano",
        5,
        "13:00",
        "15:00",
    )

    assert context["original_day"] == 3
    assert validation == {
        "success": False,
        "message": "Studio date 2026-03-04 is Wednesday; day must remain 3.",
    }
    assert validator.calls == []

    state = state_with_issue(unresolved)
    manager = SessionManagerStub()
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before = copy.deepcopy(state)

    committed = controller.assign(
        state,
        unresolved["id"],
        "R-Piano",
        5,
        "13:00",
        "15:00",
    )

    assert committed.success is False
    assert committed.message == validation["message"]
    assert state == before
    assert manager.calls == 0


def test_overnight_studio_keeps_raw_duration_but_is_rejected_by_step4():
    unresolved = unresolved_record(
        id="stu-InstructorTwo-overnight-failed",
        type="studio_class",
        student="Studio",
        date="2026-03-04",
        day=3,
        start="23:00",
        end="01:00",
        duration_minutes=None,
        raw_row={
            "Instructor": "Instructor 0002",
            "Course Code": "MUS101 Piano",
            "Class Time": "23:00-01:00",
            "Studio Date": "2026-03-04",
        },
    )
    validator = ValidatorStub()

    context = assignment_primitives.build_context(unresolved)
    validation = assignment_primitives.validate(
        validator,
        unresolved,
        "R-Piano",
        3,
        "23:00",
        "01:00",
    )

    assert context["duration_minutes"] == 120
    assert validation == {"success": False, "message": "End time must be after start time."}
    assert validator.calls == []

    state = state_with_issue(unresolved)
    manager = SessionManagerStub()
    controller = controller_for(state, validator=validator, session_mgr=manager)

    committed = controller.assign(
        state,
        unresolved["id"],
        "R-Piano",
        3,
        "23:00",
        "01:00",
    )
    assert committed.success is False
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"] == []
    assert manager.calls == 0


def test_overnight_studio_conflict_detection_covers_the_next_calendar_date():
    unresolved = unresolved_record(
        id="stu-InstructorTwo-overnight-conflict",
        type="studio_class",
        student="Studio",
        date="2026-03-04",
        day=3,
        start="23:00",
        end="01:00",
    )
    validator = ConflictValidator(
        {
            "assignments": [
                {
                    "id": "existing-next-day-studio",
                    "title": "Existing overnight conflict",
                    "type": "studio_class",
                    "resourceId": "R-Piano",
                    "start": "2026-03-05T00:30:00",
                    "end": "2026-03-05T01:30:00",
                }
            ],
            "lectures": [],
            "rooms": [{"id": "R-Piano", "types": ["Piano"]}],
            "rules": {},
        }
    )

    result = assignment_primitives.validate(
        validator,
        unresolved,
        "R-Piano",
        3,
        "23:00",
        "01:00",
    )

    assert result["success"] is False
    assert result["message"] == "End time must be after start time."


@pytest.mark.parametrize(
    "recurring",
    [
        {
            "id": "wednesday-overnight",
            "title": "Wednesday overnight recurring",
            "resourceId": "R-Piano",
            "daysOfWeek": [3],
            "startTime": "23:30:00",
            "endTime": "00:30:00",
        },
        {
            "id": "thursday-early",
            "title": "Thursday early recurring",
            "resourceId": "R-Piano",
            "daysOfWeek": [4],
            "startTime": "00:00:00",
            "endTime": "01:00:00",
        },
    ],
)
def test_dated_overnight_studio_detects_recurring_conflicts_on_both_weekdays(recurring):
    validator = ConflictValidator(
        {
            "assignments": [recurring],
            "lectures": [],
            "rooms": [{"id": "R-Piano"}],
            "rules": {},
        }
    )

    conflict = validator.check_conflict(
        room_id="R-Piano",
        day_idx=3,
        start_min=1380,
        end_min=1500,
        specific_date="2026-03-04",
    )

    assert conflict["id"] == recurring["id"]


def test_unrelated_dated_malformed_event_is_ignored_before_fail_closed_time_parse():
    validator = ConflictValidator(
        {
            "assignments": [
                {
                    "id": "far-malformed",
                    "title": "Far malformed studio",
                    "resourceId": "R-Piano",
                    "start": "2030-01-01Tbad-time",
                    "end": "2030-01-01Tstill-bad",
                }
            ],
            "lectures": [],
            "rooms": [{"id": "R-Piano"}],
            "rules": {},
        }
    )

    conflict = validator.check_conflict(
        room_id="R-Piano",
        day_idx=3,
        start_min=1380,
        end_min=1500,
        specific_date="2026-03-04",
    )

    assert conflict is None


@pytest.mark.parametrize("event_date", ["2026-03-04", "2026-03-05"])
def test_dated_malformed_event_on_target_interval_calendar_date_fails_closed(event_date):
    validator = ConflictValidator(
        {
            "assignments": [
                {
                    "id": "related-malformed",
                    "title": "Related malformed studio",
                    "resourceId": "R-Piano",
                    "start": f"{event_date}Tbad-time",
                    "end": f"{event_date}Tstill-bad",
                }
            ],
            "lectures": [],
            "rooms": [{"id": "R-Piano"}],
            "rules": {},
        }
    )

    conflict = validator.check_conflict(
        room_id="R-Piano",
        day_idx=3,
        start_min=1380,
        end_min=1500,
        specific_date="2026-03-04",
    )

    assert conflict["id"] == "related-malformed"
    assert conflict["is_malformed_time"] is True


def test_controller_validate_assignment_is_read_only_and_blocks_room_mismatch():
    state = state_with_issue()
    manager = SessionManagerStub()
    validator = ValidatorStub(
        rule_result={"allowed": False, "reason": "Room Type Mismatch"}
    )
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before = copy.deepcopy(state)

    result = controller.validate_assignment(
        "wk_reject_S100_source-row-7",
        "R-Voice",
        3,
        "14:00",
        "15:00",
    )

    assert result == {"success": False, "message": "Room Type Mismatch"}
    assert state == before
    assert controller.history_count == 0
    assert manager.calls == 0


def test_controller_simulates_a_multi_issue_plan_without_mutating_the_draft():
    first = unresolved_record()
    second = unresolved_record(
        id="wk_reject_S101_source-row-8",
        sid="S101",
        student="Student 0002",
        raw_row={
            "Student Name": "Student 0002",
            "Student No": "S101",
            "Instructor": "Instructor 0002",
            "Course Code": "MUS101 Piano",
            "Day of Week": "Monday",
            "Class Time": "09:00-10:00",
            "Preferred Venue": "R-Piano",
        },
    )
    state = state_with_issue(first)
    state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"].append(second)
    validator = ConflictValidator(
        {
            "assignments": [],
            "lectures": [],
            "rooms": [{"id": "R-Piano", "types": ["Piano"]}],
            "rules": {"room_types": {"R-Piano": ["Piano"]}},
        }
    )
    controller = controller_for(state, validator=validator)
    before = copy.deepcopy(state)

    result = controller.simulate_assignment_plan(
        [
            {
                "issue_id": "wk_reject_S100_source-row-7",
                "room": "R-Piano",
                "day": 1,
                "start": "09:00",
                "end": "10:00",
            },
            {
                "issue_id": "wk_reject_S101_source-row-8",
                "room": "R-Piano",
                "day": 1,
                "start": "09:00",
                "end": "10:00",
            },
        ]
    )

    assert result["feasible"] is False
    assert result["resolved_count"] == 1
    assert result["actions"][0]["success"] is True
    assert result["actions"][1]["success"] is False
    assert state == before
    assert controller.history_count == 0
    assert len(controller._unassigned_lessons) == 2
    assert validator.assignments == []


def test_controller_blocks_unresolved_time_change_outside_proposal_pool():
    state = state_with_issue()
    manager = SessionManagerStub()
    validator = ValidatorStub(
        rules={"instructor_time_change_eligibility": {"Instructor 0002": False}},
    )
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before = copy.deepcopy(state)

    result = controller.assign(
        state,
        "wk_reject_S100_source-row-7",
        "R-Piano",
        3,
        "14:00",
        "15:00",
        teacher_confirmed=True,
    )

    assert result.success is False
    assert "original-time options only" in result.message
    assert state == before
    assert manager.calls == 0


def test_controller_assignment_uses_stable_id_and_round_trips_undo_redo():
    state = state_with_issue()
    manager = SessionManagerStub()
    controller = controller_for(state, session_mgr=manager)

    assigned = controller.assign(
        state,
        "wk_reject_S100_source-row-7",
        "R-Piano",
        3,
        "14:00",
        "15:00",
        teacher_confirmed=True,
    )

    assert assigned.success is True
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R-Piano"
    assert state[STEP4_EDIT_SESSION_KEY]["history"][-1]["action"] == "assign"
    assert state[STEP4_EDIT_SESSION_KEY]["redo_stack"] == []

    undone = controller.undo(state)
    assert undone.success is True
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"] == []
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"][0]["id"] == "wk_reject_S100_source-row-7"

    redone = controller.redo(state)
    assert redone.success is True
    assert state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"] == []
    assert state[STEP4_EDIT_SESSION_KEY]["assignments"][0]["resourceId"] == "R-Piano"
    assert manager.calls == 3


def test_controller_assignment_rejects_not_found_unknown_room_and_conflict_without_writes():
    state = state_with_issue()
    manager = SessionManagerStub()
    validator = ValidatorStub(conflict={"title": "Existing lesson"})
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before = copy.deepcopy(state)

    missing = controller.validate_assignment("missing", "R-Piano", 1, "09:00", "10:00")
    unknown = controller.validate_assignment(
        "wk_reject_S100_source-row-7", "R-404", 1, "09:00", "10:00"
    )
    conflict = controller.assign(
        state,
        "wk_reject_S100_source-row-7",
        "R-Piano",
        1,
        "09:00",
        "10:00",
    )

    assert missing == {"success": False, "message": "Issue missing not found."}
    assert unknown == {"success": False, "message": "Unknown room: R-404"}
    assert conflict.success is False
    assert "Existing lesson" in conflict.message
    assert state == before
    assert manager.calls == 0


def test_controller_assignment_rolls_back_every_runtime_surface_on_cas_conflict():
    state = state_with_issue()
    manager = OutcomeSessionManager(
        SaveOutcome(
            status="conflict",
            path="/tmp/session.json",
            warning="Session changed before save",
        )
    )
    validator = ValidatorStub()
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before_state = copy.deepcopy(state)
    before_validator = copy.deepcopy(validator.assignments)

    result = controller.assign(
        state,
        "wk_reject_S100_source-row-7",
        "R-Piano",
        3,
        "14:00",
        "15:00",
        teacher_confirmed=True,
    )

    assert result.status == "conflict"
    assert state == before_state
    assert controller._assignments == []
    assert controller._unassigned_lessons == before_state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"]
    assert controller._history == []
    assert controller._redo_stack == []
    assert validator.assignments == before_validator


def test_controller_assignment_rolls_back_before_propagating_persistence_error():
    state = state_with_issue()
    manager = RaisingSessionManager()
    validator = ValidatorStub()
    controller = controller_for(state, validator=validator, session_mgr=manager)
    before_state = copy.deepcopy(state)
    before_validator = copy.deepcopy(validator.assignments)

    with pytest.raises(OSError, match="disk unavailable"):
        controller.assign(
            state,
            "wk_reject_S100_source-row-7",
            "R-Piano",
            3,
            "14:00",
            "15:00",
            teacher_confirmed=True,
        )

    assert state == before_state
    assert controller._assignments == []
    assert controller._unassigned_lessons == before_state[STEP4_EDIT_SESSION_KEY]["unassigned_lessons"]
    assert controller._history == []
    assert controller._redo_stack == []
    assert validator.assignments == before_validator
