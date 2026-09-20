from modules.scheduler.logic import manual_override_primitives as primitives


class ValidatorStub:
    def __init__(self, conflict=None):
        self.conflict = conflict
        self.calls = []

    def check_conflict(self, **kwargs):
        self.calls.append(kwargs)
        return self.conflict


def test_validate_move_returns_normalized_payload_when_slot_is_free():
    validator = ValidatorStub()
    slot = {"id": "wk_1", "type": "weekly_lesson"}

    result = primitives.validate_move(validator, slot, "R105", 1, "14:00:00", "15:00:00")

    assert result == {
        "success": True,
        "proposal_start": "14:00",
        "proposal_end": "15:00",
        "start_norm": "14:00",
        "end_norm": "15:00",
        "specific_date": None,
        "warnings": [],
        "requires_teacher_confirmation": False,
        "teacher_confirmation_message": None,
    }


def test_validate_move_excludes_the_slot_itself_from_conflict_check():
    validator = ValidatorStub()
    slot = {"id": "wk_1", "type": "weekly_lesson"}

    primitives.validate_move(validator, slot, "R105", 1, "14:00:00", "15:00:00")

    assert validator.calls[0].get("exclude_id") == "wk_1"


def test_apply_move_updates_slot_and_marks_it_pinned():
    slot = {
        "id": "wk_1",
        "resourceId": "R101",
        "daysOfWeek": [1],
        "startTime": "14:00:00",
        "endTime": "15:00:00",
        "type": "weekly_lesson",
    }

    snapshot = primitives.apply_move(slot, "R105", 3, "16:00", "17:00")

    assert slot["resourceId"] == "R105"
    assert slot["room_id"] == "R105"
    assert slot["daysOfWeek"] == [3]
    assert slot["startTime"] == "16:00:00"
    assert slot["endTime"] == "17:00:00"
    assert slot["pinned"] is True
    assert snapshot["resourceId"] == "R105"


def test_apply_move_updates_recurring_shaped_studio_without_specific_date():
    slot = {
        "id": "manual_studio_1",
        "resourceId": "R101",
        "daysOfWeek": [3],
        "startTime": "19:00:00",
        "endTime": "20:00:00",
        "type": "studio_class",
    }

    primitives.apply_move(slot, "R105", 5, "20:00", "21:00", specific_date=None)

    assert slot["resourceId"] == "R105"
    assert slot["daysOfWeek"] == [5]
    assert slot["startTime"] == "20:00:00"
    assert slot["endTime"] == "21:00:00"


def test_apply_move_keeps_dated_studio_on_its_specific_date():
    slot = {
        "id": "studio_1",
        "resourceId": "R101",
        "start": "2026-03-04T10:00:00",
        "end": "2026-03-04T12:00:00",
        "type": "studio_class",
    }

    primitives.apply_move(slot, "R105", 3, "13:00", "15:00", specific_date="2026-03-04")

    assert slot["resourceId"] == "R105"
    assert slot["start"] == "2026-03-04T13:00:00"
    assert slot["end"] == "2026-03-04T15:00:00"
    assert "daysOfWeek" not in slot


def test_apply_unassign_moves_slot_and_enriches_failed_payload():
    slot = {
        "id": "wk_1",
        "type": "weekly_lesson",
        "extendedProps": {"Instructor": "Instructor 0001"},
    }
    assignments = [slot]
    unassigned = []

    snapshot = primitives.apply_unassign(assignments, unassigned, slot)

    assert assignments == []
    assert unassigned[0]["id"] == "wk_1"
    assert "raw_row" in unassigned[0]
    assert snapshot["id"] == "wk_1"


def test_revert_and_replay_unassign_record_restore_expected_lists():
    prev_state = {"id": "wk_1", "resourceId": "R101", "type": "weekly_lesson"}
    new_state = {"id": "wk_1", "resourceId": "R101", "type": "weekly_lesson", "raw_row": {}}
    record = {
        "action": "unassign",
        "slot_id": "wk_1",
        "prev_state": prev_state,
        "new_state": new_state,
    }

    assignments = [{"id": "wk_1", "resourceId": "R101", "type": "weekly_lesson"}]
    unassigned = []
    primitives.replay_record(assignments, unassigned, record)

    assert assignments == []
    assert unassigned[0]["id"] == "wk_1"

    primitives.revert_record(assignments, unassigned, record)
    assert assignments[0]["id"] == "wk_1"
    assert unassigned == []


def test_compound_record_reverts_and_replays_as_one_action():
    assignments = [{"id": "a", "resourceId": "R2"}, {"id": "new"}]
    unassigned = []
    record = {
        "action": "compound",
        "records": [
            {
                "action": "move",
                "slot_id": "a",
                "prev_state": {"id": "a", "resourceId": "R1"},
                "new_state": {"id": "a", "resourceId": "R2"},
            },
            {
                "action": "assign",
                "slot_id": "new",
                "issue_id": "issue-new",
                "unassigned_index": 0,
                "prev_state": {"id": "issue-new"},
                "new_state": {"id": "new"},
            },
        ],
    }

    primitives.revert_record(assignments, unassigned, record)
    assert assignments == [{"id": "a", "resourceId": "R1"}]
    assert unassigned == [{"id": "issue-new"}]

    primitives.replay_record(assignments, unassigned, record)
    assert assignments == [{"id": "a", "resourceId": "R2"}, {"id": "new"}]
    assert unassigned == []


def test_compute_slot_duration_preserves_two_hour_lesson():
    slot = {
        "id": "wk_1",
        "startTime": "14:00:00",
        "endTime": "16:00:00",
        "type": "weekly_lesson",
    }
    assert primitives.compute_slot_duration_minutes(slot) == 120


def test_compute_slot_duration_preserves_iso_studio_duration():
    slot = {
        "id": "studio_1",
        "start": "2026-03-04T10:00:00",
        "end": "2026-03-04T12:00:00",
        "type": "studio_class",
    }

    assert primitives.compute_slot_duration_minutes(slot) == 120


def test_compute_slot_duration_preserves_cross_midnight_iso_studio_duration():
    slot = {
        "id": "studio_overnight",
        "start": "2026-03-04T23:00:00",
        "end": "2026-03-05T01:00:00",
        "type": "studio_class",
    }

    assert primitives.compute_slot_duration_minutes(slot) == 120


def test_compute_slot_duration_defaults_to_60_on_missing_times():
    slot = {"id": "wk_1", "type": "weekly_lesson"}
    assert primitives.compute_slot_duration_minutes(slot) == 60


class ValidatorWithRulesStub:
    def __init__(self, conflict=None, rules_result=None, rules=None):
        self.conflict = conflict
        self.rules_result = rules_result or {"allowed": True}
        self.rules = rules or {}

    def check_conflict(self, **kwargs):
        return self.conflict

    def validate_rules(self, room_id, instrument):
        return self.rules_result


def test_validate_move_blocks_room_type_mismatch():
    validator = ValidatorWithRulesStub(
        conflict=None,
        rules_result={
            "allowed": False,
            "reason": "Room Type Mismatch. R101 allows ['Piano'], but instrument is Percussion.",
        },
    )
    slot = {
        "id": "wk_1",
        "type": "weekly_lesson",
        "extendedProps": {"normalized_instrument": "Percussion"},
    }

    result = primitives.validate_move(validator, slot, "R101", 1, "14:00:00", "15:00:00")

    assert result == {
        "success": False,
        "message": "Room Type Mismatch. R101 allows ['Piano'], but instrument is Percussion.",
    }


def test_validate_move_blocks_time_change_outside_proposal_pool():
    validator = ValidatorWithRulesStub(
        rules={"instructor_time_change_eligibility": {"Instructor 0001": False}},
    )
    slot = {
        "id": "wk_1",
        "type": "weekly_lesson",
        "resourceId": "R101",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Instructor 0001"},
    }

    result = primitives.validate_move(
        validator,
        slot,
        "R101",
        1,
        "11:00",
        "12:00",
        teacher_confirmed=True,
    )

    assert result["success"] is False
    assert "original-time options only" in result["message"]


def test_validate_move_no_warning_when_rules_pass():
    validator = ValidatorWithRulesStub(conflict=None, rules_result={"allowed": True})
    slot = {
        "id": "wk_1",
        "type": "weekly_lesson",
        "extendedProps": {"normalized_instrument": "Piano"},
    }

    result = primitives.validate_move(validator, slot, "R101", 1, "14:00:00", "15:00:00")

    assert result["success"] is True
    assert result.get("warnings", []) == []


def test_validate_move_rejects_end_time_not_after_start_time():
    validator = ValidatorStub()
    slot = {"id": "wk_1", "type": "weekly_lesson"}

    result = primitives.validate_move(validator, slot, "R105", 1, "22:00:00", "00:00:00")

    assert result == {"success": False, "message": "End time must be after start time."}
    assert validator.calls == []


def test_validate_move_handles_null_extended_properties():
    validator = ValidatorWithRulesStub(conflict=None, rules_result={"allowed": True})
    slot = {"id": "wk_1", "type": "weekly_lesson", "extendedProps": None}

    result = primitives.validate_move(validator, slot, "R105", 1, "14:00:00", "15:00:00")

    assert result["success"] is True
    assert result["warnings"] == []


def test_validate_move_blocks_studio_instruments_metadata_mismatch():
    validator = ValidatorWithRulesStub(
        conflict=None,
        rules_result={"allowed": False, "reason": "Room Type Mismatch"},
    )
    slot = {
        "id": "studio_1",
        "type": "studio_class",
        "extendedProps": {"Instruments": "Percussion"},
    }

    result = primitives.validate_move(validator, slot, "R101", 1, "14:00:00", "15:00:00")

    assert result == {"success": False, "message": "Room Type Mismatch"}


def test_validate_move_blocks_manually_promoted_instrument_metadata_mismatch():
    validator = ValidatorWithRulesStub(
        conflict=None,
        rules_result={"allowed": False, "reason": "Room Type Mismatch"},
    )
    slot = {
        "id": "manual_1",
        "type": "weekly_lesson",
        "extendedProps": {"Instrument": "Voice"},
    }

    result = primitives.validate_move(validator, slot, "R101", 1, "14:00:00", "15:00:00")

    assert result == {"success": False, "message": "Room Type Mismatch"}


def test_validate_move_blocks_instructor_overlap_before_commit():
    validator = ValidatorWithRulesStub(conflict=None, rules_result={"allowed": True})
    validator.assignments = [
        {
            "id": "other",
            "resourceId": "R105",
            "daysOfWeek": [1],
            "startTime": "14:00:00",
            "endTime": "15:00:00",
            "extendedProps": {"Instructor": "Dr. Same"},
        }
    ]
    slot = {
        "id": "moving",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "dr. same"},
    }

    result = primitives.validate_move(
        validator, slot, "R101", 1, "14:00", "15:00"
    )

    assert result["success"] is False
    assert "Instructor time conflict" in result["message"]
