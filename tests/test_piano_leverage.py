from types import SimpleNamespace

from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.piano_leverage import build_piano_leverage_proposals


def _assignment(event_id, instructor, room, day, start, end):
    return {
        "id": event_id,
        "type": "weekly_lesson",
        "resourceId": room,
        "daysOfWeek": [day],
        "startTime": f"{start}:00",
        "endTime": f"{end}:00",
        "extendedProps": {"Instructor": instructor, "Instrument": "Piano"},
    }


def _issue(event_id, instructor, room, start):
    hour = int(start[:2]) + 1
    return {
        "id": event_id,
        "type": "weekly_lesson",
        "instructor": instructor,
        "instrument": "Piano",
        "day": 3,
        "start": start,
        "end": f"{hour:02d}:00",
        "preferred_venues": [room],
    }


def _runtime(assignments, unresolved, *, time_change_eligibility=None):
    rooms = [{"id": "R101"}, {"id": "R106"}]
    rules = {
        "constraints": {"time_range": {"start": "08:00", "end": "23:00"}},
        "room_types": {"R101": ["Piano"], "R106": ["Piano"]},
        "instructor_time_change_eligibility": time_change_eligibility or {},
    }
    return SimpleNamespace(
        locked_context_assignments=[],
        booked_lectures=[],
        edit_session={"assignments": assignments, "unassigned_lessons": unresolved},
        rooms_cache=rooms,
        normalized_rules=rules,
        validator=ConflictValidator(
            {"assignments": assignments, "lectures": [], "rooms": rooms, "rules": rules}
        ),
    )


def test_piano_leverage_finds_instructor_friday_r101_package_with_net_gain_four():
    assignments = [
        _assignment("inst5-11", "Instructor 0005", "R101", 3, "11:00", "12:00"),
        _assignment("inst5-12", "Instructor 0005", "R101", 3, "12:00", "13:00"),
        _assignment("inst5-13", "Instructor 0005", "R101", 3, "13:00", "14:00"),
        _assignment("inst5-15", "Instructor 0005", "R106", 3, "15:00", "16:00"),
        _assignment("inst5-16", "Instructor 0005", "R106", 3, "16:00", "17:00"),
        _assignment("inst5-17", "Instructor 0005", "R106", 3, "17:00", "18:00"),
        _assignment("friday-block-08", "Other", "R101", 4, "08:00", "10:00"),
        _assignment("friday-block-10", "Other", "R101", 4, "10:00", "12:00"),
        _assignment("friday-block-12", "Other", "R101", 4, "12:00", "14:00"),
    ]
    for blocker in assignments[-3:]:
        blocker["extendedProps"]["Instrument"] = "Voice"
    unresolved = [
        _issue("open-11", "Teacher 1", "R101", "11:00"),
        _issue("open-12", "Teacher 2", "R101", "12:00"),
        _issue("open-15", "Teacher 3", "R106", "15:00"),
        _issue("open-16", "Teacher 4", "R106", "16:00"),
    ]
    proposals = build_piano_leverage_proposals(_runtime(assignments, unresolved))

    assert proposals[0]["instructor"] == "Instructor 0005"
    assert proposals[0]["target_room"] == "R101"
    assert proposals[0]["target_day"] == 4
    assert proposals[0]["target_start"] == "14:00"
    assert proposals[0]["target_end"] == "21:00"
    assert proposals[0]["gain"] == 4
    assert len(proposals[0]["moves"]) == 6
    assert proposals[0]["fills"][0]["instructor"].startswith("Teacher")


def test_piano_leverage_does_not_split_an_instructors_source_day():
    assignments = [
        _assignment("piano-10", "Instructor 0001", "R101", 3, "10:00", "11:00"),
        _assignment("piano-11", "Instructor 0001", "R106", 3, "11:00", "12:00"),
        _assignment("voice-15", "Instructor 0001", "R106", 3, "15:00", "16:00"),
    ]
    assignments[-1]["extendedProps"]["Instrument"] = "Voice"

    proposals = build_piano_leverage_proposals(
        _runtime(assignments, [_issue("open-10", "Instructor 0009", "R101", "10:00")])
    )

    assert proposals == []


def test_piano_leverage_excludes_instructors_outside_time_change_pool():
    assignments = [
        _assignment("piano-10", "Instructor 0001", "R101", 3, "10:00", "11:00"),
        _assignment("piano-11", "Instructor 0001", "R106", 3, "11:00", "12:00"),
    ]

    proposals = build_piano_leverage_proposals(
        _runtime(
            assignments,
            [_issue("open-10", "Instructor 0009", "R101", "10:00")],
            time_change_eligibility={"Instructor 0001": False},
        )
    )

    assert proposals == []


def test_piano_leverage_skips_non_hour_grid_candidate_offsets_without_error():
    assignments = [
        _assignment("inst5-11", "Instructor 0005", "R101", 3, "11:00", "12:00"),
        _assignment("inst5-12", "Instructor 0005", "R101", 3, "12:00", "13:00"),
    ]

    proposals = build_piano_leverage_proposals(_runtime(assignments, []))

    assert isinstance(proposals, list)


def test_piano_leverage_never_falls_back_to_a_weekend():
    assignments = [
        _assignment("piano-10", "Instructor 0001", "R101", 3, "10:00", "11:00"),
        _assignment("piano-11", "Instructor 0001", "R106", 3, "11:00", "12:00"),
    ]
    for day in (1, 2, 4, 5):
        assignments.append(
            _assignment(f"block-{day}", f"Other {day}", "R101", day, "08:00", "23:00")
        )

    proposals = build_piano_leverage_proposals(
        _runtime(assignments, [_issue("open-10", "Instructor 0009", "R101", "10:00")])
    )

    assert proposals == []
