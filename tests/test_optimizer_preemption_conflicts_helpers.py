from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.optimizer_preemption_conflicts import get_conflicting_events


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
    return allocator


def test_get_conflicting_events_matches_weekly_overlap_same_room_only():
    allocator = _make_allocator()
    hit = {
        "id": "hit",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    miss_other_room = {
        "id": "miss_room",
        "resourceId": "R2",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }
    miss_other_day = {
        "id": "miss_day",
        "resourceId": "R1",
        "daysOfWeek": [2],
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }

    conflicts = get_conflicting_events(
        assignments=[hit, miss_other_room, miss_other_day],
        room_id="R1",
        req={"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
        parse_event_times=allocator._parse_event_times,
        is_time_overlap=allocator._is_time_overlap,
    )

    assert [evt["id"] for evt in conflicts] == ["hit"]


def test_get_conflicting_events_matches_same_date_studio_overlap_only():
    allocator = _make_allocator()
    studio_hit = {
        "id": "studio1",
        "resourceId": "R3",
        "start": "2026-03-30T19:00:00",
        "end": "2026-03-30T20:00:00",
        "extendedProps": {"Instructor": "HighPriorityVoice", "normalized_instrument": "Voice", "is_studio": True},
    }
    studio_miss = {
        "id": "studio2",
        "resourceId": "R3",
        "start": "2026-03-31T19:00:00",
        "end": "2026-03-31T20:00:00",
        "extendedProps": {"Instructor": "HighPriorityVoice", "normalized_instrument": "Voice", "is_studio": True},
    }

    conflicts = get_conflicting_events(
        assignments=[studio_hit, studio_miss],
        room_id="R3",
        req={"inst": "Other Voice", "instrument": "Voice", "day": 1, "start": 19, "end": 20, "date": "2026-03-30"},
        parse_event_times=allocator._parse_event_times,
        is_time_overlap=allocator._is_time_overlap,
    )

    assert [evt["id"] for evt in conflicts] == ["studio1"]


def test_get_conflicting_events_treats_malformed_weekly_time_as_blocking():
    allocator = _make_allocator()
    malformed = {
        "id": "broken_weekly",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "bad",
        "endTime": "still-bad",
        "extendedProps": {"Instructor": "Prof A", "normalized_instrument": "Piano"},
    }

    conflicts = get_conflicting_events(
        assignments=[malformed],
        room_id="R1",
        req={"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
        parse_event_times=allocator._parse_event_times,
        is_time_overlap=allocator._is_time_overlap,
    )

    assert [evt["id"] for evt in conflicts] == ["broken_weekly"]
