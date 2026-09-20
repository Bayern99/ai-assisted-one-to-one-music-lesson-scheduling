from modules.scheduler.logic.optimizer_output import (
    build_optimizer_init_lines,
    build_weekly_assignment,
)
from modules.scheduler.logic.optimizer_path import solve_fragmented_block_min_switches


def test_build_optimizer_init_lines_preserves_two_line_contract():
    lines = build_optimizer_init_lines(None)

    assert len(lines) == 2
    assert "Rules Source: Unavailable" in lines[0]
    assert lines[1] == "🚀 Starting Unified Optimization (v6)..."


def test_build_weekly_assignment_preserves_pass_through_shape():
    lesson = {
        "id": "wk_123",
        "day": 1,
        "start": 10,
        "end": 11,
        "instrument": "Piano",
        "raw_row": {
            "Student Name": "Student 0001",
            "Instructor": "Instructor 0001",
            "Course Code": "MUS101",
            "Study Year": 1,
        },
    }

    evt = build_weekly_assignment(lesson, "CC105")

    assert evt["id"] == "wk_123"
    assert evt["resourceId"] == "CC105"
    assert evt["type"] == "weekly_lesson"
    assert evt["daysOfWeek"] == [1]
    assert evt["startTime"] == "10:00:00"
    assert evt["endTime"] == "11:00:00"
    assert evt["extendedProps"]["Student Name"] == "Student 0001"
    assert evt["extendedProps"]["Instructor"] == "Instructor 0001"
    assert evt["extendedProps"]["Course Code"] == "MUS101"
    assert evt["extendedProps"]["Study Year"] == "1"
    assert evt["extendedProps"]["normalized_instrument"] == "Piano"


def test_solve_fragmented_block_min_switches_pure_helper_prefers_staying_put():
    lessons = [
        {"id": "l1", "day": 1, "start": 11, "end": 12, "instrument": "Piano"},
        {"id": "l2", "day": 1, "start": 12, "end": 13, "instrument": "Piano"},
    ]
    candidate_rooms = ["A", "B"]

    availability = {
        ("A", 11): True,
        ("A", 12): True,
        ("B", 11): True,
        ("B", 12): True,
    }
    scores = {"A": 100, "B": 90}

    result = solve_fragmented_block_min_switches(
        lessons,
        candidate_rooms,
        can_assign=lambda room_id, day, start, end: availability.get((room_id, start), False),
        score_room=lambda room_id, lesson: scores[room_id],
    )

    assert [lesson["id"] for lesson, _room in result] == ["l1", "l2"]
    assert [room for _lesson, room in result] == ["A", "A"]
