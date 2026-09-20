from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.optimizer_preemption_relocation import relocate_whole_block
from modules.shared.time_parser import TimeParser


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
    return allocator


def test_relocate_whole_block_moves_all_events_and_updates_block():
    allocator = _make_allocator()
    block = {
        "id": "blk_1",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "room_id": "R1",
                "daysOfWeek": [1],
                "startTime": "10:00:00",
                "endTime": "11:00:00",
                "extendedProps": {"Instructor": "PianoTeacherHigh", "normalized_instrument": "Piano"},
            },
            {
                "id": "evt2",
                "resourceId": "R1",
                "room_id": "R1",
                "daysOfWeek": [1],
                "startTime": "11:00:00",
                "endTime": "12:00:00",
                "extendedProps": {"Instructor": "PianoTeacherHigh", "normalized_instrument": "Piano"},
            },
        ],
        "room_id": "R1",
        "priority": 6,
        "start": 10,
        "end": 12,
        "instrument": "Piano",
        "inst_name": "PianoTeacherHigh",
    }

    moved = relocate_whole_block(
        block=block,
        room_ids=["R1", "R2", "R3"],
        can_assign=lambda room_id, day, start, end, specific_date=None: room_id == "R2",
        score_room=lambda room_id, req: 100 if room_id == "R2" else -1,
        event_specific_date=None,
        to_js_weekday=None,
    )

    assert moved is True
    assert block["room_id"] == "R2"
    assert {evt["resourceId"] for evt in block["events"]} == {"R2"}
    assert {evt["room_id"] for evt in block["events"]} == {"R2"}


def test_relocate_whole_block_returns_false_when_no_candidate_room():
    block = {
        "id": "blk_1",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "room_id": "R1",
                "daysOfWeek": [1],
                "startTime": "10:00:00",
                "endTime": "11:00:00",
                "extendedProps": {"Instructor": "PianoTeacherHigh", "normalized_instrument": "Piano"},
            }
        ],
        "room_id": "R1",
        "priority": 6,
        "start": 10,
        "end": 11,
        "instrument": "Piano",
        "inst_name": "PianoTeacherHigh",
    }

    moved = relocate_whole_block(
        block=block,
        room_ids=["R1", "R2", "R3"],
        can_assign=lambda room_id, day, start, end, specific_date=None: False,
        score_room=lambda room_id, req: -1,
        event_specific_date=None,
        to_js_weekday=None,
    )

    assert moved is False
    assert block["room_id"] == "R1"


def test_relocate_whole_block_supports_studio_specific_date():
    observed = {}
    block = {
        "id": "blk_studio",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "room_id": "R1",
                "start": "2026-03-30T19:00:00",
                "end": "2026-03-30T20:00:00",
                "extendedProps": {"Instructor": "HighPriorityVoice", "normalized_instrument": "Voice"},
            }
        ],
        "room_id": "R1",
        "priority": 9,
        "start": 19,
        "end": 20,
        "instrument": "Voice",
        "inst_name": "HighPriorityVoice",
    }

    def can_assign(room_id, day, start, end, specific_date=None):
        observed["day"] = day
        observed["specific_date"] = specific_date
        return room_id == "R3"

    moved = relocate_whole_block(
        block=block,
        room_ids=["R1", "R2", "R3"],
        can_assign=can_assign,
        score_room=lambda room_id, req: 100 if room_id == "R3" else -1,
        event_specific_date=TimeParser.event_specific_date,
        to_js_weekday=TimeParser.to_js_weekday,
    )

    assert moved is True
    assert observed["specific_date"] == "2026-03-30"
    assert observed["day"] == 1
    assert block["room_id"] == "R3"


def test_relocate_whole_block_returns_false_for_studio_without_resolvable_date():
    block = {
        "id": "blk_studio",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "room_id": "R1",
                "start": "bad-date",
                "end": "bad-date",
                "extendedProps": {"Instructor": "HighPriorityVoice", "normalized_instrument": "Voice"},
            }
        ],
        "room_id": "R1",
        "priority": 9,
        "start": 19,
        "end": 20,
        "instrument": "Voice",
        "inst_name": "HighPriorityVoice",
    }

    moved = relocate_whole_block(
        block=block,
        room_ids=["R1", "R2", "R3"],
        can_assign=lambda room_id, day, start, end, specific_date=None: True,
        score_room=lambda room_id, req: 100,
        event_specific_date=lambda evt: None,
        to_js_weekday=lambda specific_date, default=None: default,
    )

    assert moved is False


def test_relocate_whole_block_refuses_pinned_events():
    block = {
        "id": "blk_1",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "room_id": "R1",
                "pinned": True,
                "daysOfWeek": [1],
                "startTime": "10:00:00",
                "endTime": "11:00:00",
                "extendedProps": {"Instructor": "PianoTeacherHigh", "normalized_instrument": "Piano"},
            }
        ],
        "room_id": "R1",
        "instrument": "Piano",
        "inst_name": "PianoTeacherHigh",
    }

    moved = relocate_whole_block(
        block=block,
        room_ids=["R1", "R2", "R3"],
        can_assign=lambda room_id, day, start, end, specific_date=None: room_id == "R2",
        score_room=lambda room_id, req: 100 if room_id == "R2" else -1,
        event_specific_date=None,
        to_js_weekday=None,
    )

    assert moved is False
    assert block["room_id"] == "R1"
    assert block["events"][0]["resourceId"] == "R1"
