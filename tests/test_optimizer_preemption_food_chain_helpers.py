from modules.scheduler.logic.optimizer_preemption_food_chain import check_food_chain


def _normalize_instrument_type(raw_type):
    value = str(raw_type or "").strip().lower()
    if "piano" in value:
        return "Piano"
    if "voice" in value:
        return "Voice"
    if "percussion" in value:
        return "Percussion"
    if "instrumental" in value:
        return "Instrumental"
    return "Instrumental"


INSTRUCTOR_PRIORITY = {
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
}


def test_check_food_chain_helper_allows_higher_vip_god_over_lower_vip_god():
    req = {"inst": "HighPriorityPianoHigher", "instrument": "Piano"}
    victim = {"priority": 8, "instrument": "Piano", "inst_name": "HighPriorityPiano"}

    assert check_food_chain(
        req=req,
        victim_block=victim,
        instructor_priority=INSTRUCTOR_PRIORITY,
        normalize_instrument_type=_normalize_instrument_type,
    ) is True


def test_check_food_chain_helper_rejects_same_type_mortal_when_vip_not_higher():
    req = {"inst": "VoiceTeacher", "instrument": "Voice"}
    victim = {"priority": 6, "instrument": "Voice", "inst_name": "Other VoiceTeacher"}

    assert check_food_chain(
        req=req,
        victim_block=victim,
        instructor_priority=INSTRUCTOR_PRIORITY,
        normalize_instrument_type=_normalize_instrument_type,
    ) is False


def test_check_food_chain_helper_treats_percussion_victim_as_expendable():
    req = {"inst": "PianoTeacherHigh", "instrument": "Piano"}
    victim = {"priority": 4, "instrument": "Percussion", "inst_name": "Percussion B"}

    assert check_food_chain(
        req=req,
        victim_block=victim,
        instructor_priority=INSTRUCTOR_PRIORITY,
        normalize_instrument_type=_normalize_instrument_type,
    ) is True
