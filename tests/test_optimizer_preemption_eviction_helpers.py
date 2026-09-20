from modules.scheduler.logic.optimizer import RoomAllocator, UNASSIGNED_REASON_MESSAGES
from modules.scheduler.logic.optimizer_preemption_eviction import evict_whole_block


def _make_allocator():
    allocator = RoomAllocator(
        students=[],
        rooms=[
            {"id": "R1", "type": ["Piano"], "types": ["Piano"]},
            {"id": "R2", "type": ["Piano"], "types": ["Piano"]},
            {"id": "R3", "type": ["Voice"], "types": ["Voice"]},
        ],
        existing_bookings=[],
        rules={"room_types": {}, "constraints": {}, "instructor_priority": {}},
    )
    allocator.assignments = []
    allocator.unassigned = []
    allocator.blocks = {}
    return allocator


def test_evict_whole_block_moves_events_to_unassigned_and_drops_tracked_block():
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R1",
        "daysOfWeek": [3],
        "startTime": "13:00:00",
        "endTime": "14:00:00",
        "extendedProps": {"Student Name": "Student 0001", "Instructor": "Instructor Piano Low"},
    }
    block = {
        "id": "blk_1",
        "events": [evt],
        "room_id": "R1",
        "priority": 4,
        "start": 13,
        "end": 14,
        "instrument": "Piano",
        "inst_name": "Instructor Piano Low",
    }
    allocator.assignments = [evt]
    allocator.blocks = {"blk_1": block}

    assert evict_whole_block(
        block=block,
        assignments=allocator.assignments,
        blocks=allocator.blocks,
        parse_event_times=allocator._parse_event_times,
        append_unassigned=lambda lesson, reason, reason_code: allocator._append_unassigned(
            lesson,
            reason,
            reason_code,
        ),
        preempted_reason=UNASSIGNED_REASON_MESSAGES["preempted_by_higher_priority_block"],
        preempted_reason_code="preempted_by_higher_priority_block",
    ) is True
    assert allocator.assignments == []
    assert "blk_1" not in allocator.blocks
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["reason_code"] == "preempted_by_higher_priority_block"
    assert allocator.unassigned[0]["id"] == "evt1"


def test_evict_whole_block_preserves_weekly_day_and_studio_defaults():
    allocator = _make_allocator()
    weekly_evt = {
        "id": "weekly_evt",
        "resourceId": "R1",
        "room_id": "R1",
        "daysOfWeek": [3],
        "startTime": "13:00:00",
        "endTime": "14:00:00",
        "extendedProps": {"Student Name": "Weekly Student 0001", "Instructor": "Instructor Piano Low"},
    }
    studio_evt = {
        "id": "studio_evt",
        "resourceId": "R3",
        "room_id": "R3",
        "start": "2026-03-30T19:00:00",
        "end": "2026-03-30T20:00:00",
        "extendedProps": {
            "Student Name": "Studio Student 0002",
            "Instructor": "HighPriorityVoice",
            "is_studio": True,
        },
    }
    block = {
        "id": "blk_mix",
        "events": [weekly_evt, studio_evt],
        "room_id": "R1",
        "priority": 9,
        "start": 13,
        "end": 20,
        "instrument": "Voice",
        "inst_name": "HighPriorityVoice",
    }
    allocator.assignments = [weekly_evt, studio_evt]
    allocator.blocks = {"blk_mix": block}

    evict_whole_block(
        block=block,
        assignments=allocator.assignments,
        blocks=allocator.blocks,
        parse_event_times=allocator._parse_event_times,
        append_unassigned=lambda lesson, reason, reason_code: allocator._append_unassigned(
            lesson,
            reason,
            reason_code,
        ),
        preempted_reason=UNASSIGNED_REASON_MESSAGES["preempted_by_higher_priority_block"],
        preempted_reason_code="preempted_by_higher_priority_block",
    )

    assert allocator.assignments == []
    assert len(allocator.unassigned) == 2
    weekly_unassigned = next(item for item in allocator.unassigned if item["id"] == "weekly_evt")
    studio_unassigned = next(item for item in allocator.unassigned if item["id"] == "studio_evt")
    assert weekly_unassigned["day"] == 3
    assert weekly_unassigned["start"] == 13
    assert weekly_unassigned["end"] == 14
    assert studio_unassigned["day"] == 0
    assert studio_unassigned["start"] == 19
    assert studio_unassigned["end"] == 20
    assert weekly_unassigned["reason_code"] == "preempted_by_higher_priority_block"
    assert studio_unassigned["reason_code"] == "preempted_by_higher_priority_block"


def test_evict_whole_block_keeps_blocks_dict_unchanged_for_untracked_atomic_block():
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Instructor Piano Low"},
    }
    block = {
        "id": "atomic_evt1",
        "events": [evt],
        "room_id": "R1",
        "priority": 4,
        "start": 10,
        "end": 11,
        "instrument": "Piano",
        "inst_name": "Instructor Piano Low",
    }
    allocator.assignments = [evt]
    allocator.blocks = {"other_block": {"id": "other_block"}}

    evict_whole_block(
        block=block,
        assignments=allocator.assignments,
        blocks=allocator.blocks,
        parse_event_times=allocator._parse_event_times,
        append_unassigned=lambda lesson, reason, reason_code: allocator._append_unassigned(
            lesson,
            reason,
            reason_code,
        ),
        preempted_reason=UNASSIGNED_REASON_MESSAGES["preempted_by_higher_priority_block"],
        preempted_reason_code="preempted_by_higher_priority_block",
    )

    assert allocator.assignments == []
    assert "other_block" in allocator.blocks
    assert "atomic_evt1" not in allocator.blocks


def test_evict_whole_block_refuses_pinned_events():
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R1",
        "pinned": True,
        "daysOfWeek": [3],
        "startTime": "13:00:00",
        "endTime": "14:00:00",
        "extendedProps": {"Instructor": "Instructor Piano Low"},
    }
    block = {
        "id": "blk_1",
        "events": [evt],
        "room_id": "R1",
        "priority": 4,
        "start": 13,
        "end": 14,
        "instrument": "Piano",
        "inst_name": "Instructor Piano Low",
    }
    allocator.assignments = [evt]
    allocator.blocks = {"blk_1": block}

    assert evict_whole_block(
        block=block,
        assignments=allocator.assignments,
        blocks=allocator.blocks,
        parse_event_times=allocator._parse_event_times,
        append_unassigned=lambda lesson, reason, reason_code: allocator._append_unassigned(
            lesson,
            reason,
            reason_code,
        ),
        preempted_reason=UNASSIGNED_REASON_MESSAGES["preempted_by_higher_priority_block"],
        preempted_reason_code="preempted_by_higher_priority_block",
    ) is False
    assert allocator.assignments == [evt]
    assert allocator.unassigned == []
    assert "blk_1" in allocator.blocks
