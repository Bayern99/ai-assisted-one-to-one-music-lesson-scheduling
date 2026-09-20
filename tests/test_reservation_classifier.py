from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from modules.scheduler.logic.reservation_classifier import (
    CONTENTION,
    RESERVATION_INTERNAL,
    classify_reservation_state,
    classify_unresolved_reservations,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "reservation_classifier"
    / "golden_cases.json"
)


@pytest.fixture(scope="module")
def golden_cases():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case_name", [item["name"] for item in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]])
def test_reservation_classifier_golden_cases(case_name, golden_cases):
    case = next(item for item in golden_cases if item["name"] == case_name)
    assignments = copy.deepcopy(case["assignments"])
    unassigned = copy.deepcopy(case["unassigned_lessons"])
    before = classify_reservation_state(assignments, unassigned)
    labels = classify_unresolved_reservations(assignments, unassigned)
    after = classify_reservation_state(assignments, unassigned)

    assert before["assigned_count"] == after["assigned_count"]
    assert before["unresolved_count"] == after["unresolved_count"]

    for issue_id, expected in case["expect"].items():
        assert issue_id in labels, case["name"]
        assert labels[issue_id]["label"] == expected["label"]
        if expected.get("magnet_room"):
            assert labels[issue_id]["magnet_room"] == expected["magnet_room"]
        if expected["label"] == RESERVATION_INTERNAL:
            assert labels[issue_id]["reservation_note"]
        if expected["label"] == CONTENTION:
            assert labels[issue_id]["reservation_note"] is None


def test_classifier_accepts_integer_studio_hours():
    assignments = [
        {
            "id": "wk_voice_a",
            "type": "weekly_lesson",
            "resourceId": "CC322",
            "daysOfWeek": [2],
            "startTime": "12:00:00",
            "endTime": "13:00:00",
            "source_request_id": "weekly:voice-a:0",
            "extendedProps": {"Instructor": "Voice A"},
        }
    ]
    unassigned = [
        {
            "id": "stu_voice_a_int",
            "type": "studio_class",
            "date": "2026-10-27",
            "day": 2,
            "start": 12,
            "end": 13,
            "source_request_id": "studio:voice-a:1:0:12:00",
            "raw_row": {"Instructor": "Voice A", "Event Type": "Studio Class"},
        }
    ]
    labels = classify_unresolved_reservations(assignments, unassigned)
    assert labels["stu_voice_a_int"]["label"] == RESERVATION_INTERNAL
    assert labels["stu_voice_a_int"]["magnet_room"] == "CC322"


def test_classifier_does_not_label_unrelated_waiting_studio():
    assignments = []
    unassigned = [
        {
            "id": "stu_waiting",
            "type": "studio_class",
            "date": "2026-04-01",
            "day": 3,
            "start": "09:00",
            "end": "10:00",
            "source_request_id": "studio:orphan:1:0:09:00",
            "raw_row": {"Instructor": "Ms. Solo TEACHER", "Event Type": "Studio Class"},
        }
    ]
    labels = classify_unresolved_reservations(assignments, unassigned)
    assert labels == {}
