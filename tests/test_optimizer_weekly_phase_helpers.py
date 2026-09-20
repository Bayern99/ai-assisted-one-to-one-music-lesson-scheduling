from modules.scheduler.logic.optimizer_weekly_phase import (
    NO_SINGLE_ROOM_FOR_GROUP,
    NO_SINGLE_ROOM_FOR_GROUP_MESSAGE,
    schedule_weekly_blocks,
)


def _lesson(lesson_id, inst, instrument, start=9, end=10, **extra):
    payload = {
        "id": lesson_id,
        "inst": inst,
        "instrument": instrument,
        "start": start,
        "end": end,
        "day": 1,
        "raw_row": {},
        "prefs": [],
    }
    payload.update(extra)
    return payload


def _classify(_lesson):
    return "no_time_feasible_room", "No feasible room-time placement"


def _schedule(blocks, room_ids, can_assign, score_room, assigned, unassigned=None, instructor_priority=None):
    captured = [] if unassigned is None else unassigned
    return schedule_weekly_blocks(
        blocks=blocks,
        room_ids=room_ids,
        instructor_priority=instructor_priority or {},
        normalize_instrument_type=lambda raw: {"Piano": "Piano", "Percussion": "Percussion"}.get(raw, "Instrumental"),
        can_assign=can_assign,
        score_room=score_room,
        create_assignment=lambda lesson, room_id: assigned.append((lesson["id"], room_id)),
        classify_unassigned_reason=_classify,
        append_unassigned=lambda payload, reason, reason_code: captured.append(
            (payload, reason_code, reason)
        ),
    )


def test_schedule_weekly_blocks_sorts_by_instrument_group_then_vip_then_duration():
    blocks = [
        {"inst": "Inst Teacher", "day": 1, "duration": 1, "lessons": [_lesson("inst", "Inst Teacher", "Violin")]},
        {"inst": "Perc Teacher", "day": 1, "duration": 1, "lessons": [_lesson("perc", "Perc Teacher", "Percussion")]},
        {"inst": "HighPriorityPiano", "day": 1, "duration": 1, "lessons": [_lesson("piano", "HighPriorityPiano", "Piano")]},
    ]
    assigned = []

    logs = _schedule(
        blocks=blocks,
        room_ids=["R1"],
        can_assign=lambda room_id, day, start, end: True,
        score_room=lambda room_id, lesson: 10,
        assigned=assigned,
        instructor_priority={"HighPriorityPiano": 8, "Perc Teacher": 1, "Inst Teacher": 1},
    )

    assert logs[0] == "📦 Phase 1: Scheduling 3 Weekly Blocks..."
    assert [lesson_id for lesson_id, _room in assigned] == ["piano", "perc", "inst"]


def test_schedule_weekly_blocks_hands_whole_group_to_resolve_when_no_single_room():
    lessons = [
        _lesson("l1", "Dr. Kim", "Piano", 9, 10),
        _lesson("l2", "Dr. Kim", "Piano", 10, 11),
    ]
    assigned = []
    unassigned = []

    logs = schedule_weekly_blocks(
        blocks=[{"inst": "Dr. Kim", "day": 1, "duration": 2, "lessons": lessons}],
        room_ids=["A", "B"],
        instructor_priority={},
        normalize_instrument_type=lambda raw: "Piano",
        can_assign=lambda room_id, day, start, end: False,
        score_room=lambda room_id, lesson: 10,
        create_assignment=lambda lesson, room_id: assigned.append((lesson["id"], room_id)),
        classify_unassigned_reason=_classify,
        append_unassigned=lambda payload, reason, reason_code: unassigned.append(
            (payload, reason_code, reason)
        ),
    )

    assert assigned == []
    assert [payload["id"] for payload, _code, _reason in unassigned] == ["l1", "l2"]
    assert all(code == NO_SINGLE_ROOM_FOR_GROUP for _payload, code, _reason in unassigned)
    assert all(reason == NO_SINGLE_ROOM_FOR_GROUP_MESSAGE for _payload, _code, reason in unassigned)
    group_ids = {payload["placement_group_id"] for payload, _code, _reason in unassigned}
    assert group_ids == {"weekly-group:Dr. Kim:1:l1"}
    assert all(payload["placement_group_size"] == 2 for payload, _code, _reason in unassigned)
    assert "    ⚠️ No single-room placement: Dr. Kim (Day 1); handing 2 lessons to Resolve." in logs
    assert "Block Fragmented" not in "\n".join(logs)
    assert "Greedy Fallback" not in "\n".join(logs)


def test_schedule_weekly_blocks_does_not_partially_fill_across_rooms():
    lessons = [
        _lesson("l1", "Dr. Kim", "Piano", 9, 10),
        _lesson("l2", "Dr. Kim", "Piano", 10, 11),
        _lesson("l3", "Dr. Kim", "Piano", 11, 12),
    ]
    assigned = []
    unassigned = []
    availability = {
        ("R1", 9): True,
        ("R1", 10): False,
        ("R1", 11): False,
        ("R2", 9): False,
        ("R2", 10): True,
        ("R2", 11): False,
    }

    _schedule(
        blocks=[{"inst": "Dr. Kim", "day": 1, "duration": 3, "lessons": lessons}],
        room_ids=["R1", "R2"],
        can_assign=lambda room_id, day, start, end: availability.get((room_id, start), False),
        score_room=lambda room_id, lesson: 20 if room_id == "R2" else 10,
        assigned=assigned,
        unassigned=unassigned,
    )

    assert assigned == []
    assert [payload["id"] for payload, _code, _reason in unassigned] == ["l1", "l2", "l3"]
    assert {payload["placement_group_id"] for payload, _code, _reason in unassigned} == {
        "weekly-group:Dr. Kim:1:l1"
    }


def test_schedule_weekly_blocks_does_not_unassign_protected_lessons():
    lessons = [
        _lesson("l1", "Dr. Kim", "Piano", 9, 10, pinned=True),
        _lesson("l2", "Dr. Kim", "Piano", 10, 11),
    ]
    assigned = []
    unassigned = []

    _schedule(
        blocks=[{"inst": "Dr. Kim", "day": 1, "duration": 2, "lessons": lessons}],
        room_ids=["R1"],
        can_assign=lambda room_id, day, start, end: False,
        score_room=lambda room_id, lesson: 10,
        assigned=assigned,
        unassigned=unassigned,
    )

    assert assigned == []
    assert [payload["id"] for payload, _code, _reason in unassigned] == ["l2"]
    assert unassigned[0][0]["placement_group_id"] == "weekly-group:Dr. Kim:1:l2"
    assert unassigned[0][0]["placement_group_size"] == 1
