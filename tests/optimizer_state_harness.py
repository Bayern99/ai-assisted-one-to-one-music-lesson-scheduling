from modules.scheduler.logic.optimizer import RoomAllocator


DEFAULT_ROOMS = [
    {"id": "R1", "type": ["Piano"], "types": ["Piano"]},
    {"id": "R2", "type": ["Piano"], "types": ["Piano"]},
    {"id": "R3", "type": ["Voice"], "types": ["Voice"]},
]


DEFAULT_RULES = {
    "room_types": {},
    "constraints": {
        "enforce_instructor_blocks": True,
        "min_break_between_lessons": 60,
    },
    "instructor_priority": {
        "HighPriorityPiano": 8,
        "HighPriorityVoice": 9,
        "PianoTeacherHigh": 6,
        "Instructor Piano Low": 4,
        "VoiceTeacher": 6,
        "Instrumental A": 3,
        "Instrumental B": 2,
        "Prof A": 7,
        "Prof B": 3,
    },
}


def make_allocator(*, rooms=None, bookings=None, rules=None):
    allocator = RoomAllocator(
        students=[],
        rooms=rooms or DEFAULT_ROOMS,
        existing_bookings=bookings or [],
        rules=rules or DEFAULT_RULES,
    )
    allocator.assignments = []
    allocator.unassigned = []
    allocator.logs = []
    allocator.blocks = {}
    allocator.block_map = {}
    return allocator


def make_weekly_event(
    event_id,
    *,
    room_id="R1",
    day=1,
    start_time="10:00:00",
    end_time="11:00:00",
    instructor="Prof A",
    normalized_instrument="Piano",
    title=None,
    extra_props=None,
):
    props = {
        "Instructor": instructor,
        "normalized_instrument": normalized_instrument,
    }
    if extra_props:
        props.update(extra_props)
    return {
        "id": event_id,
        "resourceId": room_id,
        "room_id": room_id,
        "daysOfWeek": [day],
        "startTime": start_time,
        "endTime": end_time,
        "title": title or f"Weekly {event_id}",
        "type": "weekly_lesson",
        "extendedProps": props,
    }


def make_studio_event(
    event_id,
    *,
    room_id="R3",
    date="2026-03-30",
    start_hour=19,
    end_hour=20,
    instructor="HighPriorityVoice",
    normalized_instrument="Voice",
    extra_props=None,
):
    props = {
        "Instructor": instructor,
        "normalized_instrument": normalized_instrument,
        "is_studio": True,
    }
    if extra_props:
        props.update(extra_props)
    return {
        "id": event_id,
        "resourceId": room_id,
        "room_id": room_id,
        "start": f"{date}T{start_hour:02d}:00:00",
        "end": f"{date}T{end_hour:02d}:00:00",
        "title": f"Studio {event_id}",
        "type": "studio_class",
        "extendedProps": props,
    }


def make_block(
    block_id,
    events,
    *,
    room_id,
    priority,
    start,
    end,
    instrument,
    inst_name,
):
    return {
        "id": block_id,
        "events": events,
        "room_id": room_id,
        "priority": priority,
        "start": start,
        "end": end,
        "instrument": instrument,
        "inst_name": inst_name,
    }


def attach_tracked_block(allocator, block):
    allocator.blocks[block["id"]] = block
    allocator.assignments = list(block["events"])
    for event in block["events"]:
        event.setdefault("extendedProps", {})
        event["extendedProps"]["block_id"] = block["id"]
        allocator.block_map[event["id"]] = block["id"]
    return allocator
