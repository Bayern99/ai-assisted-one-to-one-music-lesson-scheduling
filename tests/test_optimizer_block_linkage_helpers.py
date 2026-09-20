from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.optimizer_block_linkage import (
    build_block_linkage_map,
    register_block_groups,
)


def _make_allocator():
    return RoomAllocator(
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


def test_build_block_linkage_map_groups_contiguous_weekly_events_and_skips_studio():
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

    block_map, blocks = build_block_linkage_map(
        assignments=[evt3, studio_evt, evt2, evt1],
        rules=allocator.rules,
        time_str_to_minutes=allocator.time_str_to_minutes,
        normalize_instrument_type=allocator._normalize_instrument_type,
    )

    assert "studio1" not in block_map
    assert len(blocks) == 2
    monday_block_id = block_map["evt1"]
    assert monday_block_id == block_map["evt2"]
    monday_block = blocks[monday_block_id]
    assert monday_block["room_id"] == "R1"
    assert monday_block["priority"] == 7
    assert monday_block["start"] == 9
    assert monday_block["end"] == 11
    assert monday_block["instrument"] == "Piano"
    assert [evt["id"] for evt in monday_block["events"]] == ["evt1", "evt2"]
    assert block_map["evt3"] != monday_block_id
    assert evt1["extendedProps"]["block_id"] == monday_block_id


def test_build_block_linkage_map_bridges_sixty_minute_same_room_gap():
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
        "startTime": "11:00:00",
        "endTime": "12:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    evt3 = {
        "id": "evt3",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "14:00:00",
        "endTime": "15:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }

    block_map, blocks = build_block_linkage_map(
        assignments=[evt1, evt2, evt3],
        rules=allocator.rules,
        time_str_to_minutes=allocator.time_str_to_minutes,
        normalize_instrument_type=allocator._normalize_instrument_type,
    )

    assert block_map["evt1"] == block_map["evt2"]
    assert block_map["evt3"] != block_map["evt1"]
    bridged = blocks[block_map["evt1"]]
    assert [evt["id"] for evt in bridged["events"]] == ["evt1", "evt2"]
    assert bridged["start"] == 9
    assert bridged["end"] == 12


def test_register_block_groups_re_splits_room_changes_and_adds_block_metadata():
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

    block_map, blocks = register_block_groups(
        block_map={},
        blocks={},
        block_id="blk_manual",
        events=[evt1, evt2, evt3],
        rules=allocator.rules,
        normalize_instrument_type=allocator._normalize_instrument_type,
    )

    block1 = blocks[block_map["evt1"]]
    block2 = blocks[block_map["evt2"]]
    assert block1["id"].endswith("_r0")
    assert block2["id"].endswith("_r1")
    assert block1["room_id"] == "R1"
    assert [evt["id"] for evt in block1["events"]] == ["evt1"]
    assert block2["room_id"] == "R2"
    assert [evt["id"] for evt in block2["events"]] == ["evt2", "evt3"]
    assert block_map["evt2"] == block_map["evt3"]
    assert block_map["evt1"] != block_map["evt2"]


def test_register_block_groups_adds_missing_extended_props_and_defaults():
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R3",
        "daysOfWeek": [4],
        "startTime": "13:00:00",
        "endTime": "14:00:00",
    }

    block_map, blocks = register_block_groups(
        block_map={},
        blocks={},
        block_id="blk_manual",
        events=[evt],
        rules=allocator.rules,
        normalize_instrument_type=allocator._normalize_instrument_type,
    )

    block_id = block_map["evt1"]
    block = blocks[block_id]
    assert block_id == "blk_manual_r0"
    assert evt["extendedProps"]["block_id"] == block_id
    assert block["inst_name"] is None
    assert block["instrument"] == "Instrumental"
    assert block["start"] == 13
    assert block["end"] == 14
