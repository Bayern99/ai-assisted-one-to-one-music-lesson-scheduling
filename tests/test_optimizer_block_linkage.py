from modules.scheduler.logic.optimizer import RoomAllocator


def _make_allocator():
    allocator = RoomAllocator(
        students=[],
        rooms=[
            {"id": "R1", "type": ["Piano"], "types": ["Piano"]},
            {"id": "R2", "type": ["Piano"], "types": ["Piano"]},
            {"id": "R3", "type": ["Voice"], "types": ["Voice"]},
        ],
        existing_bookings=[],
        rules={
            "constraints": {
                "enforce_instructor_blocks": True,
                "min_break_between_lessons": 60,
            },
            "instructor_priority": {
                "Prof A": 7,
                "Prof B": 3,
            },
        },
    )
    allocator.assignments = []
    allocator.block_map = {}
    allocator.blocks = {}
    return allocator


def test_build_block_map_groups_contiguous_weekly_events_by_instructor_and_day():
    allocator = _make_allocator()
    evt1 = {
        "id": "evt1",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    evt2 = {
        "id": "evt2",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    evt3 = {
        "id": "evt3",
        "resourceId": "R1",
        "daysOfWeek": [2],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    studio_evt = {
        "id": "studio1",
        "resourceId": "R3",
        "start": "2026-03-30T19:00:00",
        "end": "2026-03-30T20:00:00",
        "extendedProps": {
            "Instructor": "Prof A",
            "normalized_instrument": "Voice",
            "is_studio": True,
        },
    }
    allocator.assignments = [evt3, studio_evt, evt2, evt1]

    allocator._build_block_map()

    assert "studio1" not in allocator.block_map
    assert len(allocator.blocks) == 2
    monday_block_id = allocator.block_map["evt1"]
    assert monday_block_id == allocator.block_map["evt2"]
    monday_block = allocator.blocks[monday_block_id]
    assert monday_block["room_id"] == "R1"
    assert monday_block["priority"] == 7
    assert monday_block["start"] == 9
    assert monday_block["end"] == 11
    assert monday_block["instrument"] == "Piano"
    assert [evt["id"] for evt in monday_block["events"]] == ["evt1", "evt2"]
    assert allocator.block_map["evt3"] != monday_block_id


def test_build_block_map_re_splits_contiguous_events_when_room_changes():
    allocator = _make_allocator()
    evt1 = {
        "id": "evt1",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "09:00:00",
        "endTime": "10:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    evt2 = {
        "id": "evt2",
        "resourceId": "R2",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    evt3 = {
        "id": "evt3",
        "resourceId": "R2",
        "daysOfWeek": [1],
        "startTime": "11:00:00",
        "endTime": "12:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    allocator.assignments = [evt1, evt2, evt3]

    allocator._build_block_map()

    assert len(allocator.blocks) == 2
    block1 = allocator.blocks[allocator.block_map["evt1"]]
    block2 = allocator.blocks[allocator.block_map["evt2"]]
    assert block1["id"].endswith("_r0")
    assert block2["id"].endswith("_r1")
    assert block1["room_id"] == "R1"
    assert [evt["id"] for evt in block1["events"]] == ["evt1"]
    assert block2["room_id"] == "R2"
    assert [evt["id"] for evt in block2["events"]] == ["evt2", "evt3"]
    assert allocator.block_map["evt2"] == allocator.block_map["evt3"]
    assert allocator.block_map["evt1"] != allocator.block_map["evt2"]


def test_register_block_adds_missing_extended_props_and_block_metadata():
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R3",
        "daysOfWeek": [4],
        "startTime": "13:00:00",
        "endTime": "14:00:00",
    }

    allocator._register_block("blk_manual", [evt])

    block_id = allocator.block_map["evt1"]
    block = allocator.blocks[block_id]
    assert block_id == "blk_manual_r0"
    assert evt["extendedProps"]["block_id"] == block_id
    assert block["inst_name"] is None
    assert block["instrument"] == "Instrumental"
    assert block["start"] == 13
    assert block["end"] == 14
