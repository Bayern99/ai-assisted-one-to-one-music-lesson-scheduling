from modules.scheduler.logic.intervention_scope import (
    build_related_intervention_groups,
)


def _issue(issue_id, options):
    return {"issue_id": issue_id, "options": options}


def _option(room, day, start, end):
    return {"room": room, "day": day, "start": start, "end": end}


def _case(case_id, *issues):
    return {"id": case_id, "issues": list(issues)}


def test_same_case_issues_stay_in_one_group():
    groups = build_related_intervention_groups(
        [
            _case(
                "case-a",
                _issue("issue-1", []),
                _issue("issue-2", []),
            )
        ]
    )

    assert len(groups) == 1
    assert groups[0]["issue_ids"] == ["issue-1", "issue-2"]
    assert groups[0]["relation_reasons"] == ["same_case"]
    assert groups[0]["recommended"] is True


def test_overlapping_candidate_room_time_links_different_cases():
    groups = build_related_intervention_groups(
        [
            _case(
                "case-a",
                _issue("issue-1", [_option("R1", 4, "09:00", "10:00")]),
            ),
            _case(
                "case-b",
                _issue("issue-2", [_option("R1", 4, "09:30", "10:30")]),
            ),
        ]
    )

    assert len(groups) == 1
    assert groups[0]["issue_ids"] == ["issue-1", "issue-2"]
    assert groups[0]["relation_reasons"] == ["shared_room_time"]


def test_non_overlapping_or_different_room_options_stay_separate():
    groups = build_related_intervention_groups(
        [
            _case(
                "case-a",
                _issue("issue-1", [_option("R1", 4, "09:00", "10:00")]),
            ),
            _case(
                "case-b",
                _issue("issue-2", [_option("R1", 4, "10:00", "11:00")]),
            ),
            _case(
                "case-c",
                _issue("issue-3", [_option("R2", 4, "09:30", "10:30")]),
            ),
        ]
    )

    assert len(groups) == 3
    assert all(group["size"] == 1 for group in groups)


def test_connected_component_is_not_silently_split_when_over_limit():
    cases = [
        _case(
            f"case-{index}",
            _issue(
                f"issue-{index}",
                [_option("R1", 4, "09:00", "10:00")],
            ),
        )
        for index in range(9)
    ]

    groups = build_related_intervention_groups(cases, max_issues=8)

    assert len(groups) == 1
    assert groups[0]["size"] == 9
    assert groups[0]["over_limit"] is True
