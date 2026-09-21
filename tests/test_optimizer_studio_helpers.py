import pandas as pd

from modules.scheduler.logic.optimizer_studio import prepare_studio_requests


class _NormalizerProbe:
    @staticmethod
    def normalize_instrument_type(raw_type):
        if not isinstance(raw_type, str):
            return "Instrumental"
        lowered = raw_type.lower()
        if "piano" in lowered:
            return "Piano"
        if "voice" in lowered or "vocal" in lowered:
            return "Voice"
        if "percussion" in lowered:
            return "Percussion"
        return "Instrumental"


def test_prepare_studio_requests_filters_incompatible_preferences_and_splits_slots():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0004",
                "Instruments": "Piano",
                "Preferred Venue": "CC105, R101",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "18:00-19:00, 19:00-20:00",
            }
        ]
    )

    requests, rejections = prepare_studio_requests(
        df,
        room_types={"CC105": ["Piano"], "R101": ["Voice"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )

    assert rejections == []
    assert len(requests) == 2
    assert [req["id_suffix"] for req in requests] == ["0_1_0", "0_1_1"]
    assert all(req["inst"] == "Instructor 0004" for req in requests)
    assert all(req["instrument"] == "Piano" for req in requests)
    assert all(req["prefs"] == ["CC105"] for req in requests)
    assert [req["start"] for req in requests] == [18, 19]
    assert [req["end"] for req in requests] == [19, 20]
    assert all(req["date"] == "2026-03-30" for req in requests)


def test_prepare_studio_requests_keeps_row_preferences_per_request_for_same_instructor():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0004",
                "Instruments": "Piano",
                "Preferred Venue": "CC105",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "18:00-19:00",
            },
            {
                "Instructor": "Instructor 0004",
                "Instruments": "Piano",
                "Preferred Venue": "CC106",
                "Studio 1 Date": "2026年3月31日 星期二",
                "Studio 1 Time": "18:00-19:00",
            },
        ]
    )

    requests, rejections = prepare_studio_requests(
        df,
        room_types={"CC105": ["Piano"], "CC106": ["Piano"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )

    assert rejections == []
    assert [(req["inst"], req["prefs"]) for req in requests] == [
        ("Instructor 0004", ["CC105"]),
        ("Instructor 0004", ["CC106"]),
    ]


def test_identical_studio_rows_receive_stable_unique_source_occurrences():
    row = {
        "Instructor": "Dr. Duplicate",
        "Instruments": "Piano",
        "Preferred Venue": "CC105",
        "Studio 1 Date": "2026年3月30日 星期一",
        "Studio 1 Time": "18:00-19:00",
    }
    frame = pd.DataFrame([row, row])

    first, first_rejections = prepare_studio_requests(
        frame,
        room_types={"CC105": ["Piano"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )
    second, second_rejections = prepare_studio_requests(
        frame.copy(),
        room_types={"CC105": ["Piano"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )

    assert first_rejections == second_rejections == []
    assert [item["source_row_index"] for item in first] == [0, 1]
    assert [item["id_suffix"] for item in first] == ["0_1_0", "1_1_0"]
    assert [item["id_suffix"] for item in second] == ["0_1_0", "1_1_0"]
    assert first[0]["raw_row"] | {
        "_source_row_index": 1,
        "source_request_id": "studio:1:1:0",
    } == first[1]["raw_row"]


def test_prepare_studio_requests_returns_invalid_date_rejection_descriptor():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Studio Teacher",
                "Instruments": "Piano",
                "Preferred Venue": "CC105",
                "Studio 1 Date": "2026/03/30",
                "Studio 1 Time": "18:00-19:00",
            }
        ]
    )

    requests, rejections = prepare_studio_requests(
        df,
        room_types={"CC105": ["Piano"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )

    assert requests == []
    assert len(rejections) == 1
    rejection = rejections[0]
    assert rejection["reason_code"] == "invalid_studio_date"
    assert "invalid studio date" in rejection["log_line"].lower()
    assert rejection["payload"]["inst"] == "Studio Teacher"
    assert rejection["payload"]["day"] == -1
    assert rejection["payload"]["start"] == 0
    assert rejection["payload"]["end"] == 0


def test_prepare_studio_requests_returns_malformed_time_rejection_descriptor():
    df = pd.DataFrame(
        [
            {
                "Instructor": "Instructor 0004",
                "Instruments": "Piano",
                "Preferred Venue": "CC105",
                "Studio 1 Date": "2026年3月30日 星期一",
                "Studio 1 Time": "badtime",
            }
        ]
    )

    requests, rejections = prepare_studio_requests(
        df,
        room_types={"CC105": ["Piano"]},
        normalize_instrument_type=_NormalizerProbe.normalize_instrument_type,
    )

    assert requests == []
    assert len(rejections) == 1
    rejection = rejections[0]
    assert rejection["reason_code"] == "invalid_course_time"
    assert "malformed class time" in rejection["log_line"].lower()
    assert rejection["payload"]["inst"] == "Instructor 0004"
    assert rejection["payload"]["date"] == "2026-03-30"
    assert rejection["payload"]["day"] == 1
    assert rejection["payload"]["start"] == 0
    assert rejection["payload"]["end"] == 0
