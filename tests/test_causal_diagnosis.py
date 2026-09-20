from modules.scheduler.logic.causal_diagnosis import build_local_causal_diagnosis


def test_local_causal_diagnosis_identifies_room_saturation_and_leverage():
    cases = [
        {
            "issues": [
                {
                    "issue_id": "issue-1",
                    "rejection_trace": [
                        {
                            "code": "locked_lecture",
                            "room": "R101",
                            "blocker_id": "lecture-1",
                            "blocker_kind": "locked_lecture",
                            "movable": False,
                        },
                        {
                            "code": "room_occupied",
                            "room": "CC130",
                            "blocker_id": "assignment-1",
                            "blocker_kind": "scheduled_assignment",
                            "movable": True,
                        },
                    ],
                }
            ]
        }
    ]
    diagnosis = build_local_causal_diagnosis(
        cases,
        piano_proposals=[
            {
                "id": "piano-1",
                "instructor": "Instructor 0008",
                "target_room": "R101",
                "target_day": 1,
                "target_start": "13:00",
                "target_end": "16:00",
                "gain": 2,
                "moves": [{"assignment_id": "a-1", "from_room": "R103", "to_room": "R101"}],
                "fills": [{"issue_id": "issue-2", "room": "R101", "day": 1, "start": "13:00", "end": "14:00"}],
            }
        ],
    )

    assert diagnosis["primary_bottleneck"] == "compatible_room_saturation"
    assert diagnosis["locked_blockers"] == 1
    assert diagnosis["movable_blockers"] == 1
    assert diagnosis["room_saturation"][0] == {"room": "R101", "blocker_count": 1}
    assert diagnosis["best_leverage"][0]["proposal_id"] == "piano-1"
    assert diagnosis["leverage_chains"][0]["releases"][0]["issue_id"] == "issue-2"


def test_local_causal_diagnosis_does_not_invent_bottlenecks():
    diagnosis = build_local_causal_diagnosis([], piano_proposals=[])

    assert diagnosis["primary_bottleneck"] == "candidate_or_time_data"
    assert diagnosis["trace_count"] == 0
    assert diagnosis["best_leverage"] == []
    assert diagnosis["continue_local_adjustment"] is False
