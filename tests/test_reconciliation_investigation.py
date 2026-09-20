import copy
from types import SimpleNamespace

import pytest

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.api.services.pi_reconciliation import _operator_rpc_prompt
from modules.scheduler.logic.reconciliation_investigation import (
    ReconciliationInvestigation,
    public_record_from_persisted,
)
from modules.scheduler.logic.validation_authority import build_occupancy_assignments


def _runtime(*, assignments=None, unresolved=None, rules=None, rooms=None, locked_context=None):
    assignments = assignments or []
    unresolved = unresolved or []
    locked_context = locked_context or []
    rooms = rooms or [{"id": "R1"}, {"id": "R2"}]
    rules = rules or {
        "room_types": {"R1": ["Piano"], "R2": ["Piano"]},
        "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
        "instructor_time_change_eligibility": {"Instructor 0008": "ask_allowed", "Instructor 0009": "ask_allowed"},
    }
    validator = ConflictValidator(
        {
            "assignments": build_occupancy_assignments(locked_context, assignments),
            "lectures": [],
            "rooms": rooms,
            "rules": rules,
        }
    )
    return SimpleNamespace(
        session_mgr=None,
        booked_lectures=[],
        locked_context_assignments=locked_context,
        rooms_cache=rooms,
        normalized_rules=rules,
        edit_session={
            "assignments": assignments,
            "unassigned_lessons": unresolved,
            "history": [],
            "redo_stack": [],
        },
        validator=validator,
    )


def _assignment(event_id, room, start, instructor="Instructor 0008", day=1):
    hour = int(start[:2])
    return {
        "id": event_id,
        "source_request_id": event_id,
        "type": "weekly_lesson",
        "resourceId": room,
        "daysOfWeek": [day],
        "startTime": f"{start}:00",
        "endTime": f"{hour + 1:02d}:00:00",
        "extendedProps": {"Instructor": instructor, "Instrument": "Piano", "source_request_id": event_id},
    }


def _issue(issue_id="issue-1", *, instructor="Instructor 0008", day=1, start="10:00", end="11:00"):
    return {
        "id": issue_id,
        "source_request_id": f"source-{issue_id}",
        "instructor": instructor,
        "instrument": "Piano",
        "day": day,
        "start": start,
        "end": end,
    }


def _investigate(runtime, **kwargs):
    return ReconciliationInvestigation(
        runtime,
        workspace_version="v1",
        run_id="run-1",
        day=kwargs.pop("day", 1),
        **kwargs,
    )


def test_investigation_aliases_are_stable_and_do_not_expose_student_or_ids():
    runtime = _runtime(
        assignments=[_assignment("private-event", "R1", "10:00")],
        unresolved=[
            {
                "id": "private-issue",
                "source_request_id": "private-source",
                "student": "Student Secret",
                "instructor": "Instructor 0008",
                "instrument": "Piano",
                "day": 1,
                "start": "10:00",
                "end": "11:00",
            }
        ],
    )
    investigator = _investigate(runtime)

    first = investigator.inspect_reconciliation()
    second = investigator.inspect_reconciliation([first["case_index"][0]["subject_alias"]])

    text = repr(first)
    assert "Student Secret" not in text
    assert "private-source" not in text
    assert "private-issue" not in text
    assert first["case_index"] == second["case_index"]


def test_model_task_replaces_known_identities_but_local_record_keeps_original_text():
    assignment = _assignment("private-event", "R1", "10:00", "Instructor Secret")
    assignment["title"] = "Student Secret piano"
    assignment["extendedProps"].update(
        {"Student": "Student Secret", "Email": "secret@example.test", "Phone": "+1 555 867 5309"}
    )
    runtime = _runtime(assignments=[assignment], unresolved=[_issue(instructor="Instructor Secret")])
    investigator = _investigate(
        runtime,
        goal="Keep Student Secret with Instructor Secret; call +1 555 867 5309 or secret@example.test.",
        prior_decisions=[
            {
                "status": "rejected",
                "note": "Student Secret asked Instructor Secret to preserve the ordinary piano setup.",
                "subject_ids": ["private-event"],
            }
        ],
    )

    inspected = investigator.inspect_reconciliation()
    model_text = repr(inspected["task"])
    assert "Student Secret" not in model_text
    assert "Instructor Secret" in model_text
    assert "secret@example.test" not in model_text
    assert "+1 555 867 5309" not in model_text
    assert "ordinary piano setup" in model_text

    local_text = repr(investigator.persisted_record()["task"])
    assert "Student Secret" in local_text
    assert "Instructor Secret" in local_text
    assert "secret@example.test" in local_text


def test_simulation_is_final_state_and_order_independent():
    runtime = _runtime(
        assignments=[
            _assignment("event-a", "R1", "10:00"),
            _assignment("event-b", "R2", "11:00"),
        ],
    )
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    aliases = {item["subject_alias"] for item in inspected["subjects"]}
    assignment_aliases = sorted(alias for alias in aliases if alias.startswith("assignment-"))

    first = investigator.simulate_package([
        {"subject_alias": assignment_aliases[1], "target": {"room": "R1", "day": 1, "start": "11:00", "end": "12:00"}},
        {"subject_alias": assignment_aliases[0], "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    second = investigator.simulate_package([
        {"subject_alias": assignment_aliases[0], "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}},
        {"subject_alias": assignment_aliases[1], "target": {"room": "R1", "day": 1, "start": "11:00", "end": "12:00"}},
    ])

    assert first["package_hash"] == second["package_hash"]
    assert first["simulation_id"] == second["simulation_id"]
    assert second["duplicate"] is True
    assert first["status"] == "feasible"
    assert second["status"] == "feasible"
    assert first["metrics"]["room_switches"] == 2
    assert len(investigator.persisted_record()["simulations"]) == 1


def test_brief_references_only_recorded_simulations():
    runtime = _runtime(unresolved=[_issue()])
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    simulation = investigator.simulate_package([
        {
            "subject_alias": inspected["case_index"][0]["subject_alias"],
            "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
        }
    ])
    brief = investigator.submit_reconciliation_brief({
        "primary_simulation_id": simulation["simulation_id"],
        "title": "Keep the original time",
        "rationale": "A compatible room is available.",
        "trade_offs": [],
        "limitations": [],
        "termination": "recommendation_ready",
    })

    assert brief["status"] == "proposed"
    assert brief["primary_simulation_id"] == simulation["simulation_id"]


def test_failure_projection_is_pseudonymous_and_snapshot_change_is_stale():
    runtime = _runtime(assignments=[_assignment("private-event", "R1", "10:00", "Instructor Secret")])
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    alias = inspected["case_index"][0]["subject_alias"] if inspected["case_index"] else inspected["subjects"][0]["subject_alias"]
    failed = investigator.simulate_package([
        {"subject_alias": alias, "target": {"room": "R2", "day": 2, "start": "10:00", "end": "11:00"}}
    ])

    assert all("teacher secret" not in str(code).casefold() for code in failed["failure_codes"])

    runtime.edit_session["assignments"][0]["resourceId"] = "R2"
    current_hash = ReconciliationInvestigation.snapshot_hash_for_runtime(runtime)
    public = public_record_from_persisted(
        investigator.persisted_record(),
        current_snapshot_hash=current_hash,
    )
    assert public["stale"] is True


def test_package_moves_a_blocker_and_places_the_target_together():
    """'先拆再排' in final-state form: free the room by moving the blocker."""
    runtime = _runtime(
        assignments=[_assignment("event-blocker", "R1", "10:00")],
        unresolved=[_issue(instructor="Instructor 0009")],
        rules={
            "room_types": {"R1": ["Piano"], "R2": ["Piano"]},
            "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            "instructor_time_change_eligibility": {"Instructor 0008": "ask_allowed", "Instructor 0009": "ask_allowed"},
        },
    )
    investigator = _investigate(runtime)
    subjects = investigator.inspect_reconciliation()["subjects"]
    blocker = next(item["subject_alias"] for item in subjects if item["kind"] == "assignment")
    target = next(item["subject_alias"] for item in subjects if item["kind"] == "issue")

    result = investigator.simulate_package([
        {"subject_alias": blocker, "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}},
        {"subject_alias": target, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    assert result["status"] == "feasible"
    assert result["metrics"]["resolved_delta"] == 1
    assert result["metrics"]["remaining_unresolved"] == 0
    assert result["metrics"]["moved_assignments"] == 1
    assert result["metrics"]["room_switches"] == 1
    assert result["required_teacher_confirmations"] == []


def _block_runtime(rules=None, assignments=None, unresolved=None, rooms=None):
    return _runtime(
        rooms=rooms,
        assignments=assignments or [
            _assignment("block-event-a", "R1", "10:00", "Instructor 0009"),
            _assignment("block-event-b", "R1", "12:00", "Instructor 0009"),
        ],
        unresolved=unresolved or [_issue(instructor="Instructor 0008")],
        rules=rules or {
            "room_types": {"R1": ["Piano"], "R2": ["Piano"], "R3": ["Voice"]},
            "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            "instructor_time_change_eligibility": {"Instructor 0008": "ask_allowed", "Instructor 0009": "ask_allowed"},
        },
    )


def test_prior_thread_is_aliased_for_the_model():
    investigator = _investigate(
        _runtime(unresolved=[_issue(instructor="Instructor Secret")]),
        goal="Try the small room.",
        prior_thread={
            "goal": "Move Instructor Secret first.",
            "goals": ["Move Instructor Secret first.", "Keep piano in place."],
            "termination": "no_feasible_package_found",
            "failure_codes": ["room_type_mismatch"],
            "pending": [{
                "kind": "exception_authorization",
                "detail": "Use R3 for Instructor Secret.",
                "teacher": "Instructor Secret",
            }],
            "remaining_issue_ids": ["issue-1"],
        },
    )
    task = investigator.model_task()
    thread = task["prior_thread"]
    assert "Instructor Secret" in repr(task)
    assert thread["goal"] == "Move Instructor Secret first."
    assert thread["goals"] == ["Move Instructor Secret first.", "Keep piano in place."]
    assert thread["termination"] == "no_feasible_package_found"
    assert thread["failure_codes"] == ["room_type_mismatch"]
    assert thread["pending_decisions"][0]["kind"] == "exception_authorization"
    assert thread["remaining_issue_aliases"] == ["issue-1"]


def test_operator_rpc_prompt_is_the_user_turn():
    investigator = _investigate(
        _runtime(unresolved=[_issue(instructor="Instructor Secret")]),
        goal="Try the small room.",
        prior_thread={"goal": "Move Instructor Secret first."},
    )
    prompt = _operator_rpc_prompt(investigator)
    assert "Instructor Secret" in prompt
    assert "Try the small room." in prompt
    assert "Move Instructor Secret first." in prompt


def test_inspect_exposes_teacher_day_blocks_with_candidate_rooms():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()

    assert len(inspected["blocks"]) == 1
    block = inspected["blocks"][0]
    assert block["day"] == 1
    assert block["room"] == "R1"
    assert block["event_aliases"] == ["assignment-1", "assignment-2"]
    assert [(item["start"], item["end"]) for item in block["intervals"]] == [
        ("10:00", "11:00"),
        ("12:00", "13:00"),
    ]
    # R2 is free and Piano-compatible; R3 is the wrong room type.
    assert block["candidate_rooms"] == ["R2"]


def test_block_contains_the_whole_teacher_day_not_only_the_conflict_window():
    """Regression: the blocker's later lesson must not be dropped from its block."""
    runtime = _block_runtime(
        assignments=[
            _assignment("block-event-a", "R1", "10:00", "Instructor 0009"),
            _assignment("block-event-b", "R1", "12:00", "Instructor 0009"),
            _assignment("late-lesson", "R3", "16:00", "Instructor 0009"),
        ],
    )
    inspector = _investigate(runtime)
    inspected = inspector.inspect_reconciliation()

    block = next(item for item in inspected["blocks"] if len(item["event_aliases"]) == 3)
    assert block["day"] == 1

    result = inspector.simulate_package([
        {"subject_alias": block["subject_alias"], "target": {"room": "R2"}},
    ])

    assert result["status"] == "feasible"
    # Every lesson of the teacher's day moves together, so no lesson is left
    # behind in another room without being reported.
    assert result["metrics"]["moved_assignments"] == 3
    assert result["metrics"]["teacher_day_splits"] == 0
    assert {row["teacher"] for row in result["changes"]} == {"Instructor 0009"}
    assert len(result["changes"]) == 3


def test_same_time_teacher_day_blocks_can_swap_rooms():
    """Final-state swap is legal even when each room starts occupied by the other block."""
    runtime = _runtime(
        assignments=[
            _assignment("event-a", "R1", "10:00", "Instructor 0008"),
            _assignment("event-b", "R2", "10:00", "Instructor 0009"),
        ],
    )
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    blocks = {item["room"]: item for item in inspected["blocks"]}
    assert blocks["R1"]["candidate_rooms"] == []
    assert blocks["R2"]["candidate_rooms"] == []
    assert blocks["R1"]["swap_required"] is True
    assert blocks["R2"]["swap_required"] is True

    swapped = investigator.simulate_package([
        {"subject_alias": blocks["R1"]["subject_alias"], "target": {"room": "R2"}},
        {"subject_alias": blocks["R2"]["subject_alias"], "target": {"room": "R1"}},
    ])

    assert swapped["status"] == "feasible"
    assert swapped["failure_codes"] == []
    assert {row["from"]["room"]: row["to"]["room"] for row in swapped["changes"]} == {
        "R1": "R2",
        "R2": "R1",
    }


def test_block_moves_as_a_unit_and_cannot_be_retimed_or_cross_day():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    subject_alias = inspected["blocks"][0]["event_aliases"][0]

    whole = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
    ])
    assert whole["status"] == "feasible"
    assert whole["normalized_changes"] == [
        {"subject_alias": block_alias, "target": {"room": "R2", "day": 1}},
    ]
    moved_event_ids = [
        change["subject_alias"] for change in investigator.raw_changes_for(whole["normalized_changes"])
    ]
    assert sorted(moved_event_ids) == ["block-event-a", "block-event-b"]

    retimed = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2", "day": 3}},
    ])
    assert retimed["status"] == "infeasible"
    assert retimed["failure_codes"] == ["cross_day_out_of_scope"]

    wrong_room = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R3"}},
    ])
    assert wrong_room["status"] == "infeasible"
    assert wrong_room["failure_codes"] == ["unknown_room"]
    assert subject_alias  # the single-lesson alias stays addressable


def test_same_day_split_of_an_individual_lesson_is_a_disclosed_cost():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    event_alias = inspected["blocks"][0]["event_aliases"][0]

    split = investigator.simulate_package([
        {"subject_alias": event_alias, "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    assert split["status"] == "feasible"
    assert split["metrics"]["teacher_day_splits"] == 1
    assert split["split_teacher_days"] == [
        {"teacher_alias": "Instructor 0009", "day": 1, "rooms": ["R1", "R2"]},
    ]


def test_explicit_lock_participates_in_teacher_day_split_cost():
    locked = _assignment("locked-event", "R1", "09:00", "Instructor 0009")
    locked["committed"] = True
    investigator = _investigate(
        _runtime(
            assignments=[_assignment("editable-event", "R1", "10:00", "Instructor 0009")],
            locked_context=[locked],
        )
    )
    inspected = investigator.inspect_reconciliation()
    event_alias = next(item["subject_alias"] for item in inspected["subjects"] if item["kind"] == "assignment")

    split = investigator.simulate_package(
        [
            {
                "subject_alias": event_alias,
                "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
            }
        ]
    )

    assert split["status"] == "feasible"
    assert split["metrics"]["teacher_day_splits"] == 1
    assert split["split_teacher_days"] == [
        {"teacher_alias": "Instructor 0009", "day": 1, "rooms": ["R1", "R2"]},
    ]


def test_stale_l1_context_is_not_reintroduced_as_current_occupancy():
    stale = _assignment("stale-event", "R2", "10:00", "Teacher C")
    runtime = _runtime(unresolved=[_issue(instructor="Instructor 0008")], locked_context=[stale])
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()

    assert investigator.snapshot["locked_context_assignments"] == []
    result = investigator.simulate_package(
        [
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
            }
        ]
    )
    assert result["status"] == "feasible"


def test_block_relocation_frees_the_room_for_the_target_issue():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]

    result = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    assert result["status"] == "feasible"
    assert result["metrics"]["resolved_delta"] == 1
    assert result["metrics"]["remaining_unresolved"] == 0
    assert result["metrics"]["moved_assignments"] == 2
    assert result["metrics"]["room_switches"] == 2


def test_inspect_and_state_after_expose_available_rooms():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    target_alias = inspected["case_index"][0]["subject_alias"]
    target = next(item for item in inspected["subjects"] if item["subject_alias"] == target_alias)
    assert target["available_rooms"] == ["R2"]

    before = investigator.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])
    assert before["state_after"]["unresolved"][0]["available_rooms"] == ["R1"]

    after = investigator.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert after["state_after"]["unresolved"] == []
    assert after["state_after"]["placed_issue_aliases"] == [target_alias]

    rejected = investigator.simulate_package([
        {"subject_alias": target_alias, "target": {"room": "R3", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert rejected["status"] == "infeasible"
    assert rejected["state_after"]["unresolved"][0]["available_rooms"] == ["R2"]


def test_inspect_exposes_incompatible_empty_rooms_without_making_them_legal():
    runtime = _block_runtime(rooms=[{"id": "R1"}, {"id": "R2"}, {"id": "R3"}])
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    target = next(item for item in inspected["subjects"] if item["kind"] == "issue")
    assert target["available_rooms"] == ["R2"]
    assert target["incompatible_empty_rooms"] == ["R3"]
    rejected = investigator.simulate_package([
        {"subject_alias": target["subject_alias"], "target": {"room": "R3", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert rejected["failure_codes"] == ["room_type_mismatch"]


def test_unresolved_inst_field_gets_a_teacher_alias():
    issue = _issue()
    issue.pop("instructor")
    issue["inst"] = "Instructor 0007"
    investigator = _investigate(_runtime(unresolved=[issue], assignments=[]))
    inspected = investigator.inspect_reconciliation()
    subject = next(item for item in inspected["subjects"] if item["kind"] == "issue")
    assert subject["teacher_alias"] != "teacher-unknown"
    assert "teacher-unknown" not in inspected["availability"]["teacher_aliases"]


def test_change_view_reports_real_teacher_and_lesson_labels():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]

    result = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    rows = result["changes"]
    assert {row["teacher"] for row in rows} == {"Instructor 0008", "Instructor 0009"}
    moved = [row for row in rows if row["teacher"] == "Instructor 0009"]
    assert len(moved) == 2
    assert {row["group_alias"] for row in moved} == {block_alias}
    assert all(row["from"]["room"] == "R1" and row["to"]["room"] == "R2" for row in moved)
    place = next(row for row in rows if row["action"] == "place")
    assert place["from"]["room"] is None and place["to"]["room"] == "R1"


def test_no_time_change_without_an_explicit_exception():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    target_alias = inspected["case_index"][0]["subject_alias"]

    refused = investigator.simulate_package([
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "14:00", "end": "15:00"}},
    ])
    assert refused["status"] == "infeasible"
    assert refused["failure_codes"] == ["time_change_not_authorized"]
    assert all("Instructor 0008" not in str(item) for item in refused["failure_codes"])

    permitted = _investigate(_block_runtime(), allow_time_change_teachers=["Instructor 0008"])
    permitted_inspected = permitted.inspect_reconciliation()
    allowed = permitted.simulate_package([
        {
            "subject_alias": permitted_inspected["case_index"][0]["subject_alias"],
            "target": {"room": "R1", "day": 1, "start": "14:00", "end": "15:00"},
        }
    ])
    assert allowed["status"] == "conditional"
    assert allowed["same_day_time_change"] is True
    assert [item["teacher_alias"] for item in allowed["required_teacher_confirmations"]] == ["Instructor 0008"]
    task = permitted.public_task()
    assert task["time_is_fixed"] is True
    assert task["time_change_exception_teacher_aliases"] == ["Instructor 0008"]


def test_withdraw_is_disclosed_as_a_sacrifice_and_needs_its_own_authorization():
    investigator = _investigate(_tight_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]
    assert inspected["blocks"][0]["candidate_rooms"] == []
    assert inspected["blocks"][0]["withdrawable"] is True

    result = investigator.simulate_package([
        {"subject_alias": block_alias, "withdraw": True},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    assert result["status"] == "conditional"
    assert result["requires_sacrifice_authorization"] is True
    assert result["metrics"]["sacrificed_assignments"] == 2
    assert [item["subject_alias"] for item in result["sacrifices"]] == [
        "assignment-1",
        "assignment-2",
    ]
    assert all(item["teacher_alias"] == "Instructor 0009" for item in result["sacrifices"])
    assert all(row["is_sacrifice"] for row in result["changes"] if row["action"] == "withdraw")
    # The withdrawn lessons keep their own identity on the board's unresolved side.
    assert result["state_after"]["unresolved"] == []
    assert result["metrics"]["remaining_unresolved"] == 2

    brief = investigator.submit_reconciliation_brief({
        "termination": "recommendation_ready",
        "primary_simulation_id": result["simulation_id"],
        "title": "Free the room by sacrificing the block",
        "rationale": "No room can hold the block unchanged.",
        "trade_offs": ["One teacher-day block loses its place."],
        "limitations": ["No further rooms available."],
    })
    assert brief["requires_sacrifice_authorization"] is True
    assert len(brief["sacrifices"]) == 2


def test_brief_rejects_sacrifice_primary_when_preservation_exists():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]
    preservation = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    sacrifice = investigator.simulate_package([
        {"subject_alias": block_alias, "withdraw": True},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert preservation["status"] == "feasible"
    assert sacrifice["requires_sacrifice_authorization"] is True

    with pytest.raises(Exception) as error:
        investigator.submit_reconciliation_brief({
            "termination": "recommendation_ready",
            "primary_simulation_id": sacrifice["simulation_id"],
            "fallback_simulation_id": preservation["simulation_id"],
            "title": "Sacrifice first",
            "rationale": "Count looks better.",
            "trade_offs": [],
            "limitations": [],
        })
    assert "preservation" in str(error.value).casefold()

    brief = investigator.submit_reconciliation_brief({
        "termination": "recommendation_ready",
        "primary_simulation_id": preservation["simulation_id"],
        "fallback_simulation_id": sacrifice["simulation_id"],
        "title": "Keep assigned lessons",
        "rationale": "Move the block instead of withdrawing it.",
        "trade_offs": [],
        "limitations": [],
    })
    assert brief["requires_sacrifice_authorization"] is False
    assert brief["sacrifices"] == []


def _tight_runtime(**kwargs):
    """Block can only sit in R1; R3 exists but is the wrong room type."""
    return _block_runtime(
        rules={
            "room_types": {"R1": ["Piano"], "R3": ["Voice"]},
            "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            "instructor_time_change_eligibility": {
                "Instructor 0008": "ask_allowed",
                "Instructor 0009": "ask_allowed",
            },
        },
        assignments=kwargs.pop("assignments", None) or [
            _assignment("block-event-a", "R1", "10:00", "Instructor 0009"),
            _assignment("block-event-b", "R1", "12:00", "Instructor 0009"),
        ],
    )


def test_protection_and_locked_rooms_are_enforced_before_any_change():
    protected = _investigate(_block_runtime(), protect_teachers=["Instructor 0009"])
    inspected = protected.inspect_reconciliation()
    blocked = protected.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])
    assert blocked["status"] == "infeasible"
    assert blocked["failure_codes"] == ["protected_subject"]
    assert inspected["blocks"][0]["withdrawable"] is False

    locked = _investigate(
        _block_runtime(),
        locked_room_days=[{"room": "R2", "day": 1}],
    )
    locked_inspected = locked.inspect_reconciliation()
    assert locked_inspected["blocks"][0]["candidate_rooms"] == []
    locked_move = locked.simulate_package([
        {"subject_alias": locked_inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])
    assert locked_move["status"] == "infeasible"
    assert locked_move["failure_codes"] == ["locked_room_window"]
    assert locked_inspected["task"]["locked_room_days"] == [{"room": "R2", "day": 1}]


def test_tool_budget_stops_exploration_but_always_allows_the_final_brief():
    budgeted = _investigate(_block_runtime(), max_tool_calls=1)
    inspected = budgeted.inspect_reconciliation()
    assert inspected["coverage"]["subjects_total"] >= 1
    with pytest.raises(Exception) as error:
        budgeted.inspect_reconciliation()
    assert "budget exhausted" in str(error.value)

    brief = budgeted.submit_reconciliation_brief({
        "termination": "budget_exhausted",
        "title": "Interrupted",
        "rationale": "The bounded search stopped before covering every route.",
        "trade_offs": [],
        "limitations": ["Only the first inspection completed."],
        "remaining_issues": [
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "reason": "No package was selected before the limit.",
            }
        ],
    })
    assert brief["termination"] == "budget_exhausted"


def test_no_package_brief_requires_full_inspection_and_complete_remaining_issues():
    uninspected = _investigate(_runtime(unresolved=[_issue()]))
    issue_alias = uninspected.focus_aliases()[0]
    payload = {
        "termination": "no_feasible_package_found",
        "title": "No package",
        "rationale": "No fixed-time placement was found.",
        "remaining_issues": [{"subject_alias": issue_alias, "reason": "No room."}],
    }
    with pytest.raises(Exception, match="inspection of every unresolved"):
        uninspected.submit_reconciliation_brief(payload)

    incomplete = _investigate(_runtime(unresolved=[_issue()]))
    incomplete.inspect_reconciliation()
    with pytest.raises(Exception, match="account for every unresolved"):
        incomplete.submit_reconciliation_brief({**payload, "remaining_issues": []})

    complete = _investigate(_runtime(unresolved=[_issue()]))
    complete.inspect_reconciliation()
    brief = complete.submit_reconciliation_brief(payload)
    assert brief["termination"] == "no_feasible_package_found"
    assert brief["remaining_issues"][0]["subject_alias"] == issue_alias


def test_stop_reason_must_match_actual_state():
    investigator = _investigate(_runtime(unresolved=[_issue()]), max_tool_calls=2)
    inspected = investigator.inspect_reconciliation()
    remaining = [{"subject_alias": inspected["case_index"][0]["subject_alias"], "reason": "Unresolved."}]
    with pytest.raises(Exception, match="only after the exploration limit"):
        investigator.submit_reconciliation_brief(
            {
                "termination": "budget_exhausted",
                "title": "Stopped",
                "rationale": "Claimed too early.",
                "remaining_issues": remaining,
            }
        )

    recommended = _investigate(_runtime(unresolved=[_issue()]))
    inspected = recommended.inspect_reconciliation()
    simulation = recommended.simulate_package(
        [
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
            }
        ]
    )
    with pytest.raises(Exception, match="cannot reference a recommendation"):
        recommended.submit_reconciliation_brief(
            {
                "termination": "no_feasible_package_found",
                "primary_simulation_id": simulation["simulation_id"],
                "title": "No package",
                "rationale": "Contradiction.",
            }
        )
    with pytest.raises(Exception, match="placing package was already found"):
        recommended.submit_reconciliation_brief(
            {
                "termination": "no_feasible_package_found",
                "title": "No package",
                "rationale": "Contradiction.",
            }
        )


def test_brief_carries_pending_decisions_and_remaining_issues():
    investigator = _investigate(_block_runtime(), allow_time_change_teachers=["Instructor 0008"])
    inspected = investigator.inspect_reconciliation()
    target_alias = inspected["case_index"][0]["subject_alias"]
    simulation = investigator.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])

    brief = investigator.submit_reconciliation_brief({
        "termination": "recommendation_ready",
        "primary_simulation_id": simulation["simulation_id"],
        "title": "Move the block",
        "rationale": "The block moves as a unit.",
        "trade_offs": ["Instructor 0009 changes room once."],
        "limitations": ["Only one day was searched."],
        "pending_decisions": [
            {"kind": "business_tradeoff", "detail": "If the block may not move, the target stays unresolved."},
        ],
        "remaining_issues": [{"subject_alias": target_alias, "reason": "Needs a business decision."}],
    })

    assert brief["pending_decisions"] == [
        {"kind": "business_tradeoff", "detail": "If the block may not move, the target stays unresolved.", "teacher_alias": None}
    ]
    assert brief["remaining_issues"][0]["subject_alias"] == target_alias
    assert brief["remaining_issues"][0]["reason"] == "Needs a business decision."
    assert brief["remaining_issues"][0]["teacher_alias"]
    assert brief["remaining_issues"][0]["label"]

    with pytest.raises(Exception):
        investigator.submit_reconciliation_brief({"title": "x", "rationale": "x", "termination": "recommendation_ready"})

    unknown = _investigate(_block_runtime())
    unknown.inspect_reconciliation()
    unknown_sim = unknown.simulate_package([
        {"subject_alias": unknown._blocks["block-1"]["alias"], "target": {"room": "R2"}},
    ])
    with pytest.raises(Exception):
        unknown.submit_reconciliation_brief({
            "termination": "recommendation_ready",
            "primary_simulation_id": unknown_sim["simulation_id"],
            "title": "x",
            "rationale": "x",
            "remaining_issues": [{"subject_alias": "issue-999", "reason": "nope"}],
        })


def test_prior_decisions_are_mapped_onto_current_aliases():
    investigator = _investigate(
        _block_runtime(),
        prior_decisions=[
            {
                "status": "rejected",
                "decided_at": "2026-01-01T00:00:00+00:00",
                "note": "too disruptive",
                "subject_ids": ["block-event-a", "issue-1"],
                "packages": [
                    {
                        "package_hash": "canonical-hash",
                        "changes": [
                            {
                                "subject_alias": "block-event-a",
                                "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
                            }
                        ],
                    }
                ],
            }
        ],
    )
    task = investigator.public_task()

    assert task["prior_decisions"] == [
        {
            "status": "rejected",
            "decided_at": "2026-01-01T00:00:00+00:00",
            "note": "too disruptive",
            "subject_aliases": ["assignment-1", "issue-1"],
            "packages": [
                {
                    "package_hash": "canonical-hash",
                    "changes": [
                        {
                            "subject_alias": "assignment-1",
                            "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
                        }
                    ],
                    "applicable": True,
                }
            ],
        }
    ]


def test_withdrawn_lesson_keeps_canonical_identity_and_counts_once():
    runtime = _tight_runtime()
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]

    result = investigator.simulate_package([
        {"subject_alias": block_alias, "withdraw": True},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert result["status"] == "conditional"

    controller = investigator._build_controller()
    controller.simulate_reconciliation_package(
        investigator.raw_changes_for(result["normalized_changes"]),
        keep_state=True,
    )
    ids = [str(item.get("id")) for item in controller._assignments]
    unresolved_sources = {
        unresolved_assignment_primitives.source_request_id(item)
        for item in controller._unassigned_lessons
    }
    assert "block-event-a" not in ids
    assert "block-event-b" not in ids
    assert len(ids) == 1
    assert len(unresolved_sources) == len(controller._unassigned_lessons)
    assert all(source for source in unresolved_sources)


def test_package_size_is_bounded(monkeypatch):
    from modules.scheduler.logic import reconciliation_investigation as module

    monkeypatch.setattr(module, "MAX_PACKAGE_CHANGES", 2)
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]

    allowed = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
    ])
    assert allowed["status"] == "feasible"

    oversized = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert oversized["status"] == "infeasible"
    assert oversized["failure_codes"] == ["package_rejected"]


def test_dated_occupancy_is_checked_against_the_real_date():
    investigator = _investigate(_block_runtime())

    class _RecordingAvailability:
        def __init__(self):
            self.calls = []

        def room_allowed(self, room, instrument):
            return {"allowed": True}

        def room_free(self, *, room, day, start, end, date=None):
            self.calls.append(date)
            return True

    dated_event = {
        "id": "studio-dated",
        "type": "studio_class",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "start": "2026-09-07T10:00:00",
        "end": "2026-09-07T11:00:00",
        "extendedProps": {"Instructor": "Instructor 0008", "Instrument": "Piano"},
    }
    recorder = _RecordingAvailability()
    assert investigator._block_event_fits(recorder, 1, dated_event, "R2") is True
    assert recorder.calls == ["2026-09-07"]


def test_brief_must_account_for_every_lesson_left_unresolved():
    runtime = _block_runtime(
        unresolved=[
            _issue(instructor="Instructor 0008"),
            _issue(issue_id="issue-second", instructor="Instructor 0008", start="14:00", end="15:00"),
        ],
    )
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]
    target_alias = inspected["case_index"][0]["subject_alias"]
    left_over = next(
        item["subject_alias"] for item in inspected["case_index"] if item["subject_alias"] != target_alias
    )

    simulation = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R2"}},
        {"subject_alias": target_alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert simulation["state_after"]["unresolved"][0]["subject_alias"] == left_over

    with pytest.raises(Exception) as error:
        investigator.submit_reconciliation_brief({
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Partial",
            "rationale": "Places one of two.",
            "trade_offs": [],
            "limitations": [],
        })
    assert "account for every unresolved" in str(error.value)

    brief = investigator.submit_reconciliation_brief({
        "termination": "recommendation_ready",
        "primary_simulation_id": simulation["simulation_id"],
        "title": "Partial",
        "rationale": "Places one of two.",
        "trade_offs": [],
        "limitations": [],
        "remaining_issues": [
            {"subject_alias": left_over, "reason": "No acceptable route inside this day."}
        ],
    })
    assert brief["remaining_issues"][0]["subject_alias"] == left_over


def test_growing_an_existing_split_is_disclosed_as_a_cost():
    runtime = _block_runtime(
        rooms=[{"id": "R1"}, {"id": "R2"}, {"id": "R3"}],
        rules={
            "room_types": {"R1": ["Piano"], "R2": ["Piano"], "R3": ["Piano"]},
            "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            "instructor_time_change_eligibility": {
                "Instructor 0008": "ask_allowed",
                "Instructor 0009": "ask_allowed",
            },
        },
        assignments=[
            _assignment("split-a", "R1", "09:00", "Instructor 0009"),
            _assignment("split-b", "R2", "11:00", "Instructor 0009"),
            _assignment("split-c", "R2", "13:00", "Instructor 0009"),
        ],
    )
    investigator = _investigate(runtime)
    inspected = investigator.inspect_reconciliation()
    block = next(item for item in inspected["blocks"] if len(item["event_aliases"]) == 3)
    lesson_in_r2 = next(
        item["subject_alias"]
        for item in inspected["subjects"]
        if item.get("room") == "R2" and item["teacher_alias"] == block["teacher_alias"]
    )

    result = investigator.simulate_package([
        {"subject_alias": lesson_in_r2, "target": {"room": "R3", "day": 1, "start": "11:00", "end": "12:00"}},
    ])

    assert result["status"] == "feasible"
    assert result["metrics"]["teacher_day_splits"] == 1
    assert result["split_teacher_days"] == [
        {"teacher_alias": "Instructor 0009", "day": 1, "rooms": ["R1", "R2", "R3"]},
    ]


def test_oversized_expanded_package_is_rejected():
    assignments = []
    for teacher in range(5):
        for index in range(15):
            assignments.append(
                _assignment(f"t{teacher}-l{index}", "R1", f"{8 + index:02d}:00", f"TT{teacher}")
            )
    investigator = _investigate(
        _block_runtime(
            rooms=[{"id": f"R{i}"} for i in range(1, 9)],
            rules={
                "room_types": {f"R{i}": ["Piano"] for i in range(1, 9)},
                "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            },
            unresolved=[_issue(instructor="Instructor 0008")],
            assignments=assignments,
        )
    )
    inspected = investigator.inspect_reconciliation()
    assert len(inspected["blocks"]) == 5

    result = investigator.simulate_package([
        {"subject_alias": block["subject_alias"], "target": {"room": "R5"}}
        for block in inspected["blocks"]
    ])

    assert result["status"] == "infeasible"
    assert result["failure_codes"] == ["package_rejected"]


def test_a_block_and_its_member_in_one_package_is_reported_not_raised():
    """A block alias plus one of its own lessons must fail as a reviewable result."""
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block = inspected["blocks"][0]["subject_alias"]
    member = inspected["blocks"][0]["event_aliases"][0]

    result = investigator.simulate_package([
        {"subject_alias": block, "target": {"room": "R2"}},
        {"subject_alias": member, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])

    assert result["status"] == "infeasible"
    assert result["failure_codes"] == ["duplicate_subject"]
    assert result["state_after"]["blocks"]


def test_applying_a_contradictory_package_is_refused_without_partial_state():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    block = inspected["blocks"][0]["subject_alias"]
    member = inspected["blocks"][0]["event_aliases"][0]
    controller = investigator._build_controller()

    before = copy.deepcopy(controller._assignments)
    result = controller.apply_reconciliation_package(
        {"step4_edit_session": controller.edit_session},
        investigator.raw_changes_for([
            {"subject_alias": block, "target": {"room": "R2"}},
            {"subject_alias": member, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
        ]),
    )

    assert result.success is False
    assert controller._assignments == before


def test_withdraw_and_move_on_the_same_subject_is_rejected():
    investigator = _investigate(_tight_runtime())
    inspected = investigator.inspect_reconciliation()
    block_alias = inspected["blocks"][0]["subject_alias"]

    contradictory = investigator.simulate_package([
        {"subject_alias": block_alias, "target": {"room": "R1"}, "withdraw": True},
    ])

    assert contradictory["status"] == "infeasible"
    assert contradictory["failure_codes"] == ["package_rejected"]


def test_no_package_brief_allows_legal_moves_that_do_not_place_unresolved_work():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    shuffle = investigator.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])
    assert shuffle["status"] == "feasible"
    assert shuffle["metrics"]["resolved_delta"] == 0
    issue_alias = inspected["case_index"][0]["subject_alias"]
    brief = investigator.submit_reconciliation_brief({
        "termination": "no_feasible_package_found",
        "title": "No placing package",
        "rationale": "Only already-assigned blocks were moved.",
        "remaining_issues": [{"subject_alias": issue_alias, "reason": "Still no room."}],
    })
    assert brief["termination"] == "no_feasible_package_found"
    assert brief["primary_simulation_id"] is None


def test_server_bound_close_does_not_recommend_non_placing_packages():
    investigator = _investigate(_block_runtime())
    inspected = investigator.inspect_reconciliation()
    investigator.simulate_package([
        {"subject_alias": inspected["blocks"][0]["subject_alias"], "target": {"room": "R2"}},
    ])
    brief = investigator.close_at_server_bound(bound="runtime")
    assert brief["termination"] == "budget_exhausted"
    assert not brief["primary_simulation_id"]
    assert {item["subject_alias"] for item in brief["remaining_issues"]} == {
        inspected["case_index"][0]["subject_alias"]
    }


def test_server_bound_close_keeps_a_placing_package():
    investigator = _investigate(_runtime(unresolved=[_issue()]))
    inspected = investigator.inspect_reconciliation()
    placed = investigator.simulate_package([
        {
            "subject_alias": inspected["case_index"][0]["subject_alias"],
            "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
        }
    ])
    assert placed["metrics"]["resolved_delta"] == 1
    brief = investigator.close_at_server_bound(bound="runtime")
    assert brief["termination"] == "budget_exhausted"
    assert brief["primary_simulation_id"] == placed["simulation_id"]

def test_instructor_names_stay_real_while_students_stay_aliased():
    assignment = _assignment("event-1", "R1", "10:00", "Instructor 0006")
    unresolved = _issue(instructor="Instructor 0006")
    unresolved["student"] = "Student Secret"
    runtime = _runtime(
        assignments=[assignment],
        unresolved=[unresolved],
        rules={
            "room_types": {"R1": ["Piano"], "R2": ["Piano"]},
            "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
            "instructor_time_change_eligibility": {"Instructor 0006": "ask_allowed"},
        },
    )
    investigator = _investigate(runtime, goal="instructor six needs R106; keep Student Secret")
    task = investigator.model_task()
    assert "instructor six needs R106" in task["goal"]
    assert "Student Secret" not in task["goal"]
    inspected = investigator.inspect_reconciliation()
    assert {item["teacher_alias"] for item in inspected["subjects"]} == {"Instructor 0006"}
    assert "teacher-1" not in repr(inspected)
    assert "Student Secret" not in repr(inspected["task"])


def test_invalid_simulate_payload_returns_a_usable_failure_code():
    investigator = _investigate(_runtime(unresolved=[_issue()]))
    empty = investigator.simulate_package([])
    assert empty["feasible"] is False
    assert empty["failure_codes"] == ["empty_package"]
    assert "at least one change" in empty["rejection"].casefold()
    assert investigator.persisted_record()["simulations"] == {}

    unknown = investigator.simulate_package([
        {"subject_alias": "issue-99", "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert unknown["failure_codes"] == ["unknown_subject_alias"]
    assert "issue-99" in unknown["rejection"]
    assert investigator.persisted_record()["simulations"] == {}
