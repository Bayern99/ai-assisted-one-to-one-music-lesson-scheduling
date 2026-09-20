"""Output-formatting helpers extracted from optimizer.py.

These helpers are intentionally behavior-preserving. They provide a structural
split seam for event formatting and optimizer provenance logs without changing
room policy, scoring, or orchestration.
"""

import datetime
import os


def _clock_text(minutes, fallback_hour):
    if isinstance(minutes, int):
        return f"{minutes // 60:02d}:{minutes % 60:02d}:00"
    if isinstance(fallback_hour, (int, float)):
        fallback_minutes = round(fallback_hour * 60)
        return f"{fallback_minutes // 60:02d}:{fallback_minutes % 60:02d}:00"
    return "00:00:00"


def build_optimizer_init_lines(rules_source_path):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rules_path = rules_source_path or "Unavailable"
    rules_mtime = "Unknown"
    if rules_source_path and os.path.exists(rules_source_path):
        rules_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(rules_path)).strftime("%Y-%m-%d %H:%M:%S")

    return [
        f"⏱️ Optimizer Init: {now_str} | Rules Source: {rules_path} | Rules Version: {rules_mtime}",
        "🚀 Starting Unified Optimization (v6)...",
    ]


def build_weekly_assignment(lesson, room_id):
    raw = lesson.get("raw_row", {})

    return {
        "id": lesson["id"],
        "source_request_id": lesson.get("source_request_id"),
        "resourceId": room_id,
        "startTime": _clock_text(lesson.get("start_minute"), lesson["start"]),
        "endTime": _clock_text(lesson.get("end_minute"), lesson["end"]),
        "daysOfWeek": [lesson["day"]],
        "type": "weekly_lesson",
        "editable": True,
        "backgroundColor": "#3788d8",
        "title": f"👤 {raw.get('Student Name', '')} ({raw.get('Instructor', '')})",
        "extendedProps": {
            **{k: str(v) if v is not None else "" for k, v in raw.items()},
            "auto_generated": True,
            "normalized_instrument": lesson["instrument"],
            "source_request_id": lesson.get("source_request_id"),
        },
    }
