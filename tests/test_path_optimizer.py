import pytest

from modules.scheduler.logic.optimizer import RoomAllocator


def _make_allocator():
    return RoomAllocator(
        students=[],
        rooms=[{"id": "A", "type": "General"}, {"id": "B", "type": "General"}, {"id": "C", "type": "General"}],
        existing_bookings=[],
        rules={"room_types": {}, "constraints": {}, "instructor_priority": {}},
    )


def test_solver_returns_empty_for_empty_lessons():
    allocator = _make_allocator()

    assert allocator._solve_fragmented_block_min_switches([], ["A", "B"]) == []


def test_solver_returns_empty_for_empty_candidate_rooms():
    allocator = _make_allocator()

    lessons = [{"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano", "raw_row": {}, "prefs": []}]
    assert allocator._solve_fragmented_block_min_switches(lessons, []) == []


def test_solver_returns_empty_when_no_valid_start(monkeypatch):
    allocator = _make_allocator()
    lessons = [{"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano", "raw_row": {}, "prefs": []}]

    monkeypatch.setattr(allocator, "can_assign", lambda room_id, day, start, end, specific_date=None, instructor_id=None: False)
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, lesson: 100)

    assert allocator._solve_fragmented_block_min_switches(lessons, ["A", "B"]) == []


def test_solver_returns_empty_when_path_breaks_midway(monkeypatch):
    allocator = _make_allocator()
    lessons = [
        {"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano", "raw_row": {}, "prefs": []},
        {"id": "l2", "day": 1, "start": 12, "end": 13, "instrument": "Piano", "raw_row": {}, "prefs": []},
    ]
    availability = {("A", 11): True, ("B", 11): False, ("A", 12): False, ("B", 12): False}

    monkeypatch.setattr(
        allocator,
        "can_assign",
        lambda room_id, day, start, end, specific_date=None, instructor_id=None: availability.get((room_id, start), False),
    )
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, lesson: 100)

    assert allocator._solve_fragmented_block_min_switches(lessons, ["A", "B"]) == []


def test_solver_prefers_fewer_switches_over_small_score_advantage(monkeypatch):
    allocator = _make_allocator()
    lessons = [
        {"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano", "raw_row": {}, "prefs": []},
        {"id": "l2", "day": 1, "start": 12, "end": 13, "instrument": "Piano", "raw_row": {}, "prefs": []},
        {"id": "l3", "day": 1, "start": 13, "end": 14, "instrument": "Piano", "raw_row": {}, "prefs": []},
    ]
    availability = {
        ("A", 11): True,
        ("A", 12): False,
        ("A", 13): True,
        ("B", 11): False,
        ("B", 12): True,
        ("B", 13): True,
        ("C", 11): True,
        ("C", 12): True,
        ("C", 13): False,
    }
    scores = {"A": 100, "B": 100, "C": 100}

    monkeypatch.setattr(
        allocator,
        "can_assign",
        lambda room_id, day, start, end, specific_date=None, instructor_id=None: availability.get((room_id, start), False),
    )
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, lesson: scores[room_id])

    assignments = allocator._solve_fragmented_block_min_switches(lessons, ["A", "B", "C"])

    assert [lesson["id"] for lesson, _room in assignments] == ["l1", "l2", "l3"]
    path = [room for _lesson, room in assignments]
    switches = sum(1 for idx in range(1, len(path)) if path[idx] != path[idx - 1])
    assert switches <= 1


def test_solver_preserves_lesson_order_in_traceback(monkeypatch):
    allocator = _make_allocator()
    lessons = [
        {"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano", "raw_row": {}, "prefs": []},
        {"id": "l2", "day": 1, "start": 12, "end": 13, "instrument": "Piano", "raw_row": {}, "prefs": []},
        {"id": "l3", "day": 1, "start": 13, "end": 14, "instrument": "Piano", "raw_row": {}, "prefs": []},
    ]

    monkeypatch.setattr(allocator, "can_assign", lambda room_id, day, start, end, specific_date=None, instructor_id=None: True)
    monkeypatch.setattr(allocator, "_score_room_unified", lambda room_id, lesson: {"A": 100, "B": 90}[room_id])

    assignments = allocator._solve_fragmented_block_min_switches(lessons, ["A", "B"])

    assert [lesson["id"] for lesson, _room in assignments] == ["l1", "l2", "l3"]
    assert [room for _lesson, room in assignments] == ["A", "A", "A"]
