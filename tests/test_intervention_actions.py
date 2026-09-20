import pytest

from modules.scheduler.logic.intervention_actions import (
    InterventionActionError,
    build_intervention_action_catalog,
    resolve_intervention_actions,
)


def _option(room="R1", day=4, start="09:00", end="10:00", confirmation=False):
    return {
        "room": room,
        "day": day,
        "start": start,
        "end": end,
        "preferred": room == "R1",
        "time_changed": day != 4,
        "requires_teacher_confirmation": confirmation,
    }


def test_catalog_issues_stable_server_owned_ids_for_same_and_cross_day_options():
    cases = [
        {
            "issues": [
                {
                    "issue_id": "issue-1",
                    "options": [_option()],
                    "cross_day_options": [_option(room="R2", day=1, confirmation=True)],
                }
            ]
        }
    ]

    first = build_intervention_action_catalog(cases)
    second = build_intervention_action_catalog(cases)

    assert list(first) == list(second)
    assert len(first) == 2
    assert {item["source"] for item in first.values()} == {"same_day", "cross_day"}
    assert all(item["action_id"] in first for item in first.values())
    assert all(item["type"] == "assign_issue" for item in first.values())


def test_catalog_exposes_block_move_without_embedded_fills():
    catalog = build_intervention_action_catalog(
        [],
        piano_leverage=[
            {
                "id": "piano-1",
                "moves": [{"assignment_id": "assigned-1"}],
                "fills": [{"issue_id": "issue-1"}],
            }
        ],
    )

    action = next(iter(catalog.values()))
    assert action["type"] == "move_block"
    assert action["proposal_id"] == "piano-1"
    assert action["proposal"]["fills"] == []
    assert action["requires_teacher_confirmation"] is True


def test_resolve_actions_preserves_order_and_rejects_repeats_or_unknown_ids():
    catalog = build_intervention_action_catalog(
        [
            {
                "issues": [
                    {"issue_id": "issue-1", "options": [_option()]},
                    {"issue_id": "issue-2", "options": [_option(room="R2")]},
                ]
            }
        ]
    )
    action_ids = list(catalog)

    resolved = resolve_intervention_actions(catalog, action_ids[::-1])
    assert [item["action_id"] for item in resolved] == action_ids[::-1]

    with pytest.raises(InterventionActionError, match="cannot repeat"):
        resolve_intervention_actions(catalog, [action_ids[0], action_ids[0]])
    with pytest.raises(InterventionActionError, match="unknown"):
        resolve_intervention_actions(catalog, ["action-missing"])
