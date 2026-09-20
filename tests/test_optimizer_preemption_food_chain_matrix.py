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
                "HighPriorityPianoHigher": 10,
                "HighPriorityVoice": 9,
                "HighPriorityVoice Higher": 11,
                "PianoTeacherHigh": 6,
                "Instructor Piano Low": 4,
                "VoiceTeacher": 6,
                "Instrumental A": 3,
                "Instrumental B": 2,
                "Percussion A": 5,
                "Percussion B": 4,
            },
        },
    )
    allocator.assignments = []
    allocator.unassigned = []
    allocator.blocks = {}
    return allocator


def test_check_food_chain_allows_higher_vip_god_over_lower_vip_god():
    allocator = _make_allocator()

    req = {"inst": "HighPriorityPianoHigher", "instrument": "Piano"}
    victim = {"priority": 8, "instrument": "Piano", "inst_name": "HighPriorityPiano"}

    assert allocator._check_food_chain(req, victim) is True


def test_check_food_chain_rejects_lower_vip_god_against_higher_vip_god():
    allocator = _make_allocator()

    req = {"inst": "HighPriorityPiano", "instrument": "Piano"}
    victim = {"priority": 10, "instrument": "Piano", "inst_name": "HighPriorityPianoHigher"}

    assert allocator._check_food_chain(req, victim) is False


def test_check_food_chain_rejects_same_type_mortal_when_vip_not_higher():
    allocator = _make_allocator()

    req_equal = {"inst": "VoiceTeacher", "instrument": "Voice"}
    victim_equal = {"priority": 6, "instrument": "Voice", "inst_name": "Other VoiceTeacher"}
    req_lower = {"inst": "Instructor Piano Low", "instrument": "Piano"}
    victim_higher = {"priority": 6, "instrument": "Piano", "inst_name": "PianoTeacherHigh"}

    assert allocator._check_food_chain(req_equal, victim_equal) is False
    assert allocator._check_food_chain(req_lower, victim_higher) is False


def test_check_food_chain_allows_mortal_to_kick_instrumental_expendable():
    allocator = _make_allocator()

    req = {"inst": "VoiceTeacher", "instrument": "Voice"}
    victim = {"priority": 3, "instrument": "Instrumental", "inst_name": "Instrumental A"}

    assert allocator._check_food_chain(req, victim) is True


def test_check_food_chain_expendable_vs_expendable_requires_higher_vip():
    allocator = _make_allocator()

    req_higher = {"inst": "Instrumental A", "instrument": "Instrumental"}
    victim_lower = {"priority": 2, "instrument": "Instrumental", "inst_name": "Instrumental B"}
    req_equal = {"inst": "Instrumental B", "instrument": "Instrumental"}
    victim_equal = {"priority": 2, "instrument": "Instrumental", "inst_name": "Other Instrumental"}

    assert allocator._check_food_chain(req_higher, victim_lower) is True
    assert allocator._check_food_chain(req_equal, victim_equal) is False


def test_check_food_chain_treats_percussion_requester_as_expendable_tier():
    allocator = _make_allocator()

    req = {"inst": "Percussion A", "instrument": "Percussion"}
    victim = {"priority": 4, "instrument": "Piano", "inst_name": "Instructor Piano Low"}

    assert allocator._check_food_chain(req, victim) is False


def test_check_food_chain_treats_percussion_victim_as_expendable_cross_type_mortal():
    allocator = _make_allocator()

    req = {"inst": "PianoTeacherHigh", "instrument": "Piano"}
    victim = {"priority": 4, "instrument": "Percussion", "inst_name": "Percussion B"}

    assert allocator._check_food_chain(req, victim) is True
