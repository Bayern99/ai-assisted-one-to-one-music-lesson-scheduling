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
            "room_types": {},
            "constraints": {},
            "instructor_priority": {
                "HighPriorityPiano": 8,
                "HighPriorityVoice": 9,
                "PianoTeacherHigh": 6,
                "Instructor Piano Low": 4,
                "VoiceTeacher": 6,
                "Instrumental A": 3,
                "Instrumental B": 2,
            },
        },
    )
    allocator.assignments = []
    allocator.unassigned = []
    allocator.blocks = {}
    return allocator


def test_check_food_chain_allows_self_preemption():
    allocator = _make_allocator()

    req = {"inst": "Instructor Piano Low", "instrument": "Piano"}
    victim = {"priority": 10, "instrument": "Voice", "inst_name": "Instructor Piano Low"}

    assert allocator._check_food_chain(req, victim) is True


def test_check_food_chain_allows_t0_to_kick_lower_tiers():
    allocator = _make_allocator()

    req = {"inst": "HighPriorityPiano", "instrument": "Piano"}
    victim = {"priority": 4, "instrument": "Piano", "inst_name": "Instructor Piano Low"}

    assert allocator._check_food_chain(req, victim) is True


def test_check_food_chain_allows_higher_vip_same_type_mortal():
    allocator = _make_allocator()

    req = {"inst": "PianoTeacherHigh", "instrument": "Piano"}
    victim = {"priority": 4, "instrument": "Piano", "inst_name": "Instructor Piano Low"}

    assert allocator._check_food_chain(req, victim) is True


def test_check_food_chain_rejects_cross_type_same_tier_mortal_kick():
    allocator = _make_allocator()

    req = {"inst": "PianoTeacherHigh", "instrument": "Piano"}
    victim = {"priority": 6, "instrument": "Voice", "inst_name": "VoiceTeacher"}

    assert allocator._check_food_chain(req, victim) is False


def test_check_food_chain_limits_t2_to_lower_expendables():
    allocator = _make_allocator()

    req = {"inst": "Instrumental A", "instrument": "Instrumental"}
    victim = {"priority": 6, "instrument": "Piano", "inst_name": "PianoTeacherHigh"}
    lower_victim = {"priority": 2, "instrument": "Instrumental", "inst_name": "Instrumental B"}

    assert allocator._check_food_chain(req, victim) is False
    assert allocator._check_food_chain(req, lower_victim) is True


def test_relocate_whole_block_moves_all_events_and_updates_block(monkeypatch):
    allocator = _make_allocator()
    block = {
        "id": "blk_1",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
                "daysOfWeek": [1],
                "startTime": "10:00:00",
                "endTime": "11:00:00",
                "extendedProps": {"Instructor": "PianoTeacherHigh", "normalized_instrument": "Piano"},
            },
            {
                "id": "evt2",
                "resourceId": "R1",
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

    monkeypatch.setattr(
        allocator,
        "can_assign",
        lambda room_id, day, start, end, specific_date=None, instructor_id=None: room_id == "R2",
    )
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, req: 100 if room_id == "R2" else -1)

    assert allocator._relocate_whole_block(block) is True
    assert block["room_id"] == "R2"
    assert {evt["resourceId"] for evt in block["events"]} == {"R2"}
    assert {evt["room_id"] for evt in block["events"]} == {"R2"}


def test_relocate_whole_block_returns_false_when_no_candidate_room(monkeypatch):
    allocator = _make_allocator()
    block = {
        "id": "blk_1",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
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

    monkeypatch.setattr(allocator, "can_assign", lambda room_id, day, start, end, specific_date=None, instructor_id=None: False)
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, req: -1)

    assert allocator._relocate_whole_block(block) is False
    assert block["room_id"] == "R1"


def test_relocate_whole_block_supports_studio_specific_date(monkeypatch):
    allocator = _make_allocator()
    observed = {}
    block = {
        "id": "blk_studio",
        "events": [
            {
                "id": "evt1",
                "resourceId": "R1",
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

    def can_assign(room_id, day, start, end, specific_date=None, instructor_id=None):
        observed["day"] = day
        observed["specific_date"] = specific_date
        return room_id == "R3"

    monkeypatch.setattr(allocator, "can_assign", can_assign)
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, req: 100 if room_id == "R3" else -1)

    assert allocator._relocate_whole_block(block) is True
    assert observed["specific_date"] == "2026-03-30"
    assert observed["day"] == 1
    assert block["room_id"] == "R3"


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

    assert allocator._evict_whole_block(block) is True
    assert allocator.assignments == []
    assert "blk_1" not in allocator.blocks
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["reason_code"] == "preempted_by_higher_priority_block"
    assert allocator.unassigned[0]["id"] == "evt1"


def test_resolve_with_grandmaster_logic_evicts_victim_when_relocation_fails(monkeypatch):
    allocator = _make_allocator()
    evt = {
        "id": "evt1",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {
            "block_id": "blk_1",
            "Instructor": "Instructor Piano Low",
            "normalized_instrument": "Piano",
            "Student Name": "Student 0001",
        },
    }
    block = {
        "id": "blk_1",
        "events": [evt],
        "room_id": "R1",
        "priority": 4,
        "start": 10,
        "end": 11,
        "instrument": "Piano",
        "inst_name": "Instructor Piano Low",
    }
    allocator.assignments = [evt]
    allocator.blocks = {"blk_1": block}

    monkeypatch.setattr(allocator, "_get_conflicting_events", lambda room_id, req: [evt])
    monkeypatch.setattr(allocator, "_relocate_whole_block", lambda victim_block: False)

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
    )

    assert resolved is True
    assert allocator.assignments == []
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["reason_code"] == "preempted_by_higher_priority_block"
    assert "blk_1" not in allocator.blocks
