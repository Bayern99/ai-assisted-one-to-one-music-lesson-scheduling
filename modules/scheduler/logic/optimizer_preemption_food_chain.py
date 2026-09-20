from modules.scheduler.logic.rules_schema import DEFAULT_INSTRUCTOR_PRIORITY


def check_food_chain(
    *,
    req,
    victim_block,
    instructor_priority,
    normalize_instrument_type,
):
    req_priority = instructor_priority.get(
        req["inst"],
        DEFAULT_INSTRUCTOR_PRIORITY,
    )
    req_inst = normalize_instrument_type(req["instrument"])

    req_tier = 1
    if req_inst == "Piano" and req_priority >= 8:
        req_tier = 0
    if req_inst == "Voice" and req_priority >= 9:
        req_tier = 0
    if req_inst == "Instrumental" or req_inst == "Percussion":
        req_tier = 2

    victim_priority = victim_block["priority"]
    victim_inst = normalize_instrument_type(victim_block["instrument"])

    victim_tier = 1
    if victim_inst == "Piano" and victim_priority >= 8:
        victim_tier = 0
    if victim_inst == "Voice" and victim_priority >= 9:
        victim_tier = 0
    if victim_inst in {"Instrumental", "Percussion"}:
        victim_tier = 2

    if req["inst"] == victim_block.get("inst_name"):
        return True

    if req_tier == 0:
        if victim_tier > 0:
            return True
        if victim_tier == 0:
            return req_priority > victim_priority

    if req_tier == 1:
        if victim_tier == 2:
            return True
        if victim_tier == 1:
            if req_inst == victim_inst:
                return req_priority > victim_priority
            return False

    if req_tier == 2:
        if victim_tier == 2:
            return req_priority > victim_priority

    return False
