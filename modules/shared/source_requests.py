"""Stable source-request identity helpers shared by scheduling and audits."""

import math


def is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in {"", "nan", "nat", "none", "null"}


def stable_row_index(row, fallback: int) -> int:
    value = row.get("_source_row_index", row.get("source_row_index", fallback))
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def weekly_source_request_id(row, fallback_index: int) -> str:
    return f"weekly:{stable_row_index(row, fallback_index)}"


def studio_source_request_id(
    row,
    fallback_index: int,
    slot_index: int,
    time_index: int = 0,
) -> str:
    row_index = stable_row_index(row, fallback_index)
    return f"studio:{row_index}:{slot_index}:{time_index}"


def studio_time_tokens(value) -> list[str]:
    """Return non-empty Studio request tokens in their canonical order."""
    if is_missing(value):
        return []
    return [
        token.strip()
        for token in str(value).replace("，", ",").split(",")
        if token.strip()
    ]


def frame_with_source_row_indexes(frame):
    """Attach stable row numbers without depending on a DataFrame index later."""
    if frame is None or not hasattr(frame, "copy"):
        return frame
    result = frame.copy()
    if "_source_row_index" not in result.columns:
        result["_source_row_index"] = list(range(len(result)))
    return result


def source_request_ids(weekly=None, studio=None) -> set[str]:
    ids = set()
    for fallback, row in enumerate(_records(weekly)):
        ids.add(weekly_source_request_id(row, fallback))
    for fallback, row in enumerate(_records(studio)):
        for slot_index in range(1, 4):
            date_value = row.get(f"Studio {slot_index} Date")
            time_value = row.get(f"Studio {slot_index} Time")
            if is_missing(date_value) and is_missing(time_value):
                continue
            tokens = studio_time_tokens(time_value)
            for time_index, _token in enumerate(tokens):
                ids.add(studio_source_request_id(row, fallback, slot_index, time_index))
    return ids


def _records(value):
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return value.to_dict(orient="records")
    return [item for item in value if isinstance(item, dict)]
