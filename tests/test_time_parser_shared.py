from modules.shared.time_parser import TimeParser


def test_to_minutes_supports_hhmm_and_hhmmss():
    assert TimeParser.to_minutes("14:30") == 14 * 60 + 30
    assert TimeParser.to_minutes("14:30:45") == 14 * 60 + 30


def test_parse_time_range_returns_normalized_bounds():
    assert TimeParser.parse_time_range("09:00-10:30") == ("09:00", "10:30")
    assert TimeParser.parse_time_range("09:00 - 10:30") == ("09:00", "10:30")


def test_event_to_minute_range_supports_weekly_and_iso_events():
    weekly = {"startTime": "08:15:00", "endTime": "09:45:00"}
    studio = {"start": "2026-03-04T18:00:00", "end": "2026-03-04T19:30:00"}

    assert TimeParser.event_to_minute_range(weekly) == (8 * 60 + 15, 9 * 60 + 45)
    assert TimeParser.event_to_minute_range(studio) == (18 * 60, 19 * 60 + 30)


def test_event_to_minute_range_normalizes_recurring_overnight_end_to_next_day():
    weekly = {"startTime": "23:30:00", "endTime": "00:30:00"}

    assert TimeParser.event_to_minute_range(weekly) == (1410, 1470)


def test_extract_start_hour_handles_ranges_and_iso_values():
    assert TimeParser.extract_start_hour("14:00-15:00") == 14
    assert TimeParser.extract_start_hour("2026-03-04T18:00:00") == 18


def test_normalize_clock_rejects_invalid_hour_and_minute_values():
    assert TimeParser.normalize_clock("24:00") is None
    assert TimeParser.normalize_clock("09:60") is None
    assert TimeParser.normalize_clock("not-a-time") is None


def test_to_minutes_can_fail_closed_with_none_default():
    assert TimeParser.to_minutes("09:30", default=None) == 9 * 60 + 30
    assert TimeParser.to_minutes("09:75", default=None) is None
    assert TimeParser.to_minutes("bad", default=None) is None


def test_event_to_minute_range_can_fail_closed_with_none_default():
    malformed = {"startTime": "25:00:00", "endTime": "26:00:00"}

    assert TimeParser.event_to_minute_range(malformed, default=None) == (None, None)


def test_extract_iso_date_and_parse_date_support_iso_datetime_payloads():
    assert TimeParser.extract_iso_date("2026-03-04T18:00:00") == "2026-03-04"
    assert TimeParser.parse_date("2026-03-04T18:00:00").isoformat() == "2026-03-04"


def test_event_specific_date_and_primary_js_day_support_iso_events():
    event = {"start": "2026-03-04T18:00:00", "end": "2026-03-04T19:30:00"}

    assert TimeParser.event_specific_date(event) == "2026-03-04"
    assert TimeParser.event_primary_js_day(event, default=None) == 3


def test_event_clock_pair_supports_iso_and_extended_props_fallbacks():
    iso_event = {"start": "2026-03-04T18:00:00", "end": "2026-03-04T19:30:00"}
    props_event = {"extendedProps": {"Class Time": "09:00-10:30"}}

    assert TimeParser.event_clock_pair(iso_event) == ("18:00", "19:30")
    assert TimeParser.event_clock_pair(props_event) == ("09:00", "10:30")


def test_to_js_weekday_returns_default_for_invalid_date():
    assert TimeParser.to_js_weekday("not-a-date", default=None) is None


def test_board_event_occupancy_honours_multi_hour_lecture_range():
    lecture = {
        "type": "lecture",
        "startTime": "10:00:00",
        "endTime": "14:00:00",
    }

    assert TimeParser.board_event_occupancy(lecture) == (600, 840)


def test_board_event_occupancy_uses_canonical_pi_for_weekly_lesson():
    weekly = {
        "type": "weekly_lesson",
        "startTime": "10:00:00",
        "endTime": "11:00:00",
    }

    assert TimeParser.board_event_occupancy(weekly) == (600, 660)


def test_board_event_occupancy_rejects_illegal_lecture_range():
    lecture = {
        "type": "locked_lecture",
        "startTime": "bad",
        "endTime": "14:00:00",
    }

    assert TimeParser.board_event_occupancy(lecture) is None
