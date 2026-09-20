from modules.scheduler.logic.teacher_day_package import (
    build_teacher_day_package,
    validate_teacher_day_placement,
)


def _event(event_id, start, end, room="R1", day=4):
    return {
        "id": event_id,
        "resourceId": room,
        "daysOfWeek": [day],
        "startTime": start,
        "endTime": end,
        "extendedProps": {"Instructor": "Instructor 0008"},
    }


def _placement(event_id, day, start, end, room):
    return {
        "event_id": event_id,
        "day": day,
        "start": start,
        "end": end,
        "room": room,
    }


def test_package_preserves_original_time_gaps_when_moved_as_one_day_package():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "12:00"),
            _event("b", "14:00", "17:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "12:00", "R2"),
            _placement("b", 1, "14:00", "17:00", "R2"),
        ],
    )

    assert result == {"valid": True, "errors": []}
    assert package["source_day"] == 4
    assert package["source_gaps_minutes"] == [120]


def test_package_may_use_two_rooms_with_one_transition():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "12:00"),
            _event("b", "14:00", "16:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "12:00", "R2"),
            _placement("b", 1, "14:00", "16:00", "R3"),
        ],
    )

    assert result == {"valid": True, "errors": []}


def test_package_rejects_split_across_two_days():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "12:00"),
            _event("b", "14:00", "17:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "12:00", "R2"),
            _placement("b", 2, "14:00", "17:00", "R2"),
        ],
    )

    assert result["valid"] is False
    assert "package_must_remain_on_one_day" in result["errors"]


def test_package_rejects_changed_internal_gap():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "12:00"),
            _event("b", "14:00", "17:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "12:00", "R2"),
            _placement("b", 1, "13:00", "16:00", "R2"),
        ],
    )

    assert result["valid"] is False
    assert "original_time_gaps_must_be_preserved" in result["errors"]


def test_package_rejects_more_than_one_room_transition():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "12:00"),
            _event("b", "14:00", "16:00"),
            _event("c", "16:00", "17:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "12:00", "R2"),
            _placement("b", 1, "14:00", "16:00", "R3"),
            _placement("c", 1, "16:00", "17:00", "R2"),
        ],
    )

    assert result["valid"] is False
    assert "at_most_one_room_transition" in result["errors"]


def test_package_accepts_different_block_lengths():
    package = build_teacher_day_package(
        [
            _event("a", "09:00", "13:00"),
            _event("b", "14:00", "16:00"),
        ]
    )

    result = validate_teacher_day_placement(
        package,
        [
            _placement("a", 1, "09:00", "13:00", "R2"),
            _placement("b", 1, "14:00", "16:00", "R2"),
        ],
    )

    assert result == {"valid": True, "errors": []}
