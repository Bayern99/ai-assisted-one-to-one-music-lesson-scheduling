from types import SimpleNamespace
from time import perf_counter

from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.resolution_advice import build_resolution_advice
from modules.scheduler.logic.resolution_availability import ResolutionAvailability


def _runtime(
    *,
    assignments=None,
    unresolved=None,
    rooms=None,
    room_types=None,
    time_change_eligibility=None,
):
    assignments = assignments or []
    rooms = rooms or [{"id": "R1"}, {"id": "R2"}]
    rules = {
        "constraints": {"time_range": {"start": "08:00", "end": "18:00"}},
        "room_types": room_types or {"R1": ["Piano"], "R2": ["Voice"]},
        "instructor_time_change_eligibility": time_change_eligibility or {},
    }
    validator = ConflictValidator(
        {"assignments": assignments, "lectures": [], "rooms": rooms, "rules": rules}
    )
    return SimpleNamespace(
        locked_context_assignments=[],
        edit_session={"assignments": assignments, "unassigned_lessons": unresolved or []},
        rooms_cache=rooms,
        normalized_rules=rules,
        validator=validator,
    )


def _issue(instructor="Instructor 0001", start="10:00", end="11:00"):
    return {
        "id": f"issue-{instructor}-{start}",
        "type": "weekly_lesson",
        "instructor": instructor,
        "instrument": "Piano",
        "day": 1,
        "start": start,
        "end": end,
        "preferred_venues": ["R1"],
    }


def _assignment(instructor, room, start="10:00", end="11:00"):
    return {
        "id": f"assigned-{instructor}-{room}",
        "resourceId": room,
        "daysOfWeek": [1],
        "startTime": f"{start}:00",
        "endTime": f"{end}:00",
        "extendedProps": {"Instructor": instructor},
    }


def test_advice_prefers_original_time_and_compatible_preferred_room():
    advice = build_resolution_advice(_runtime(unresolved=[_issue()]))

    item = advice["cases"][0]["issues"][0]
    assert item["status"] == "place_now"
    assert item["options"][0]["room"] == "R1"
    assert item["options"][0]["time_changed"] is False


def test_advice_checks_teacher_timeline_before_suggesting_a_room():
    runtime = _runtime(
        assignments=[_assignment("Instructor 0001", "R2")],
        unresolved=[_issue()],
    )

    item = build_resolution_advice(runtime)["cases"][0]["issues"][0]

    assert item["status"] == "same_day_alternative"
    assert all(option["start"] != "10:00" for option in item["options"])
    assert "Teacher is occupied" in item["reason"]


def test_advice_offers_cross_day_options_when_same_day_is_full():
    rooms = [{"id": "R1"}, {"id": "R2"}]
    assignments = [
        _assignment("Holder R1", "R1", start="08:00", end="18:00"),
        _assignment("Holder R2", "R2", start="08:00", end="18:00"),
    ]

    item = build_resolution_advice(
        _runtime(
            assignments=assignments,
            unresolved=[_issue()],
            rooms=rooms,
            room_types={"R1": ["Piano"], "R2": ["Piano"]},
        )
    )["cases"][0]["issues"][0]

    assert item["status"] == "blocked"
    assert item["options"] == []
    assert item["cross_day_options"]
    assert item["cross_day_options"][0]["day"] == 2
    assert item["cross_day_options"][0]["start"] == "10:00"
    assert item["cross_day_options"][0]["requires_teacher_confirmation"] is True
    assert "cross-day alternatives exist" in item["reason"]


def test_advice_keeps_excluded_instructor_at_original_time_only():
    runtime = _runtime(
        assignments=[_assignment("Other", "R1")],
        unresolved=[_issue()],
        time_change_eligibility={"Instructor 0001": False},
    )

    item = build_resolution_advice(runtime)["cases"][0]["issues"][0]

    assert item["status"] == "blocked"
    assert item["options"] == []
    assert item["cross_day_options"] == []
    assert item["time_change_allowed"] is False
    assert "Original-time options only" in item["reason"]


def test_advice_still_offers_original_time_room_to_excluded_instructor():
    runtime = _runtime(
        unresolved=[_issue()],
        time_change_eligibility={"Instructor 0001": False},
    )

    item = build_resolution_advice(runtime)["cases"][0]["issues"][0]

    assert item["status"] == "place_now"
    assert item["time_change_allowed"] is False
    assert item["options"][0]["time_changed"] is False


def test_advice_treats_two_hour_half_hour_occupancy_as_one_hour_proposal():
    item = build_resolution_advice(
        _runtime(unresolved=[_issue(start="09:00", end="11:00")])
    )["cases"][0]["issues"][0]

    assert item["status"] == "place_now"
    assert item["options"][0]["start"] == "09:30"
    assert item["options"][0]["end"] == "10:30"


def test_advice_does_not_emit_fifteen_minute_proposals():
    item = build_resolution_advice(
        _runtime(
            assignments=[_assignment("Instructor 0001", "R1", start="10:00", end="11:00")],
            unresolved=[_issue(start="09:00", end="11:00")],
        )
    )["cases"][0]["issues"][0]

    assert all(
        int(option["start"].split(":")[1]) in {0, 30}
        and int(option["end"].split(":")[1]) in {0, 30}
        and (int(option["end"].split(":")[0]) * 60 + int(option["end"].split(":")[1]))
        - (int(option["start"].split(":")[0]) * 60 + int(option["start"].split(":")[1]))
        == 60
        for option in item["options"]
    )


def test_advice_exposes_related_intervention_groups():
    runtime = _runtime(
        unresolved=[
            _issue(instructor="Instructor 0001", start="10:00", end="11:00"),
            _issue(instructor="Dr. B", start="10:00", end="11:00"),
        ]
    )

    advice = build_resolution_advice(runtime)

    assert len(advice["intervention_groups"]) == 1
    group = advice["intervention_groups"][0]
    assert group["size"] == 2
    assert group["relation_reasons"] == ["shared_room_time"]
    assert group["recommended"] is True


def test_advice_groups_unresolved_by_instructor_and_day():
    runtime = _runtime(
        unresolved=[_issue(start="10:00", end="11:00"), _issue(start="12:00", end="13:00")]
    )

    advice = build_resolution_advice(runtime)

    assert advice["summary"]["total"] == 2
    assert advice["summary"]["cases"] == 1
    assert len(advice["cases"][0]["issues"]) == 2


def test_advice_handles_ninety_five_blocked_cases_without_candidate_explosion():
    rooms = [{"id": f"R{index}"} for index in range(10)]
    assignments = [
        {
            "id": f"block-{room['id']}",
            "resourceId": room["id"],
            "daysOfWeek": [1],
            "startTime": "08:00:00",
            "endTime": "18:00:00",
            "extendedProps": {"Instructor": f"Room holder {room['id']}"},
        }
        for room in rooms
    ]
    assignments.extend(
        {
            "id": f"irrelevant-{index}",
            "resourceId": rooms[index % len(rooms)]["id"],
            "daysOfWeek": [2 + index % 5],
            "startTime": "18:00:00",
            "endTime": "19:00:00",
            "extendedProps": {"Instructor": f"Other {index}"},
        }
        for index in range(290)
    )
    unresolved = [
        {
            **_issue(instructor=f"Teacher {index}"),
            "id": f"issue-{index}",
            "preferred_venues": ["R0"],
        }
        for index in range(95)
    ]
    runtime = _runtime(
        assignments=assignments,
        unresolved=unresolved,
        rooms=rooms,
        room_types={room["id"]: ["Piano"] for room in rooms},
    )

    started = perf_counter()
    advice = build_resolution_advice(runtime)
    elapsed = perf_counter() - started

    assert advice["summary"]["blocked"] == 95
    assert elapsed < 2.0


def _lecture():
    return {
        "id": "lec-theory",
        "resourceId": "R1",
        "daysOfWeek": [1],
        "startTime": "10:00:00",
        "endTime": "14:00:00",
        "type": "lecture",
        "title": "Theory",
        "locked": True,
    }


def _runtime_with_lecture(unresolved):
    runtime = _runtime(unresolved=unresolved)
    runtime.validator = ConflictValidator(
        {
            "assignments": [],
            "lectures": [_lecture()],
            "rooms": runtime.rooms_cache,
            "rules": runtime.normalized_rules,
        }
    )
    return runtime


def test_weekly_advice_indexes_the_real_lecture_window():
    availability = ResolutionAvailability(_runtime_with_lecture([_issue()]))
    assert availability.room_free(room="R1", day=1, start=12 * 60, end=13 * 60) is False
    assert availability.room_free(room="R1", day=1, start=16 * 60, end=17 * 60) is True
    assert availability.room_free(room="R2", day=1, start=12 * 60, end=13 * 60) is True


def test_advice_keeps_room_free_outside_a_multi_hour_lecture():
    item = build_resolution_advice(
        _runtime_with_lecture([_issue(start="16:00", end="17:00")])
    )["cases"][0]["issues"][0]
    assert item["status"] == "place_now"
    assert item["options"][0]["room"] == "R1"
    assert item["options"][0]["time_changed"] is False


def test_advice_does_not_offer_original_time_inside_a_multi_hour_lecture():
    item = build_resolution_advice(
        _runtime_with_lecture([_issue(start="12:00", end="13:00")])
    )["cases"][0]["issues"][0]
    assert all(
        not (option["room"] == "R1" and option["start"] == "12:00")
        for option in item["options"]
    )


def test_advice_omits_reservation_internal_rows_from_the_work_queue():
    runtime = _runtime(
        assignments=[_assignment("Voice A", "R1", "12:00", "13:00")],
        unresolved=[
            {
                "id": "stu_voice_a",
                "type": "studio_class",
                "day": 1,
                "start": "12:00",
                "end": "13:00",
                "source_request_id": "studio:voice-a:1:0:12:00",
                "instructor": "Voice A",
                "raw_row": {"Instructor": "Voice A", "Event Type": "Studio Class"},
            },
            _issue(instructor="Instructor 0001", start="10:00", end="11:00"),
        ],
        room_types={"R1": ["Piano"], "R2": ["Voice"]},
    )
    advice = build_resolution_advice(runtime)
    issue_ids = [item["issue_id"] for case in advice["cases"] for item in case["issues"]]
    assert "stu_voice_a" not in issue_ids
    assert advice["summary"]["total"] == 1


def test_advice_keeps_placement_group_on_one_shared_room():
    unresolved = [
        {
            **_issue(start="09:00", end="10:00"),
            "id": "g1a",
            "placement_group_id": "weekly-group:Instructor 0001:1:g1a",
            "placement_group_size": 2,
        },
        {
            **_issue(start="11:00", end="12:00"),
            "id": "g1b",
            "placement_group_id": "weekly-group:Instructor 0001:1:g1a",
            "placement_group_size": 2,
        },
    ]
    advice = build_resolution_advice(
        _runtime(
            unresolved=unresolved,
            rooms=[{"id": "R1"}, {"id": "R2"}],
            room_types={"R1": ["Piano"], "R2": ["Piano"]},
        )
    )
    issues = advice["cases"][0]["issues"]
    assert {item["status"] for item in issues} == {"place_now"}
    assert {item["single_room"] for item in issues} == {True}
    assert {item["placement_group_id"] for item in issues} == {"weekly-group:Instructor 0001:1:g1a"}
    assert all(item["placement_group_size"] == 2 for item in issues)
    assert all(option["room"] in {"R1", "R2"} for item in issues for option in item["options"])
    assert "keep every lesson in the same room" in issues[0]["reason"]


def test_advice_does_not_offer_split_rooms_for_a_placement_group():
    unresolved = [
        {
            **_issue(start="09:00", end="10:00"),
            "id": "g1a",
            "placement_group_id": "weekly-group:Instructor 0001:1:g1a",
            "placement_group_size": 2,
        },
        {
            **_issue(start="11:00", end="12:00"),
            "id": "g1b",
            "placement_group_id": "weekly-group:Instructor 0001:1:g1a",
            "placement_group_size": 2,
        },
    ]
    advice = build_resolution_advice(
        _runtime(
            assignments=[
                _assignment("Holder R1", "R1", start="11:00", end="12:00"),
                _assignment("Holder R2", "R2", start="09:00", end="10:00"),
            ],
            unresolved=unresolved,
            rooms=[{"id": "R1"}, {"id": "R2"}],
            room_types={"R1": ["Piano"], "R2": ["Piano"]},
        )
    )
    issues = advice["cases"][0]["issues"]
    assert {item["status"] for item in issues} == {"blocked"}
    assert {item["single_room"] for item in issues} == {False}
    assert all(item["options"] == [] for item in issues)
    assert "No single-room placement for this instructor-day group" in issues[0]["reason"]
