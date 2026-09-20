#!/usr/bin/env python3
"""Read-only A/B/C/D gap report for Optimizer baseline vs human final.

Categories:
  A — authority inconsistency / false occupancy (e.g. lecture all-day fold)
  B — higher-scoring room was available but Optimizer missed it
  C — equal rule score; room-table order bias
  D — human chose a lower-scoring room (whole-board rearrangement)

This script is informational only. It is NOT gated by verify_release or CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.shared.time_parser import TimeParser

LECTURE_TYPES = TimeParser.LECTURE_EVENT_TYPES


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("assignments", "bookings", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _instrument_label(event: dict, index: int) -> str:
    props = event.get("extendedProps") or {}
    instrument = (
        props.get("Instrument")
        or props.get("Instruments")
        or props.get("Course Code")
        or event.get("title")
        or "Unknown"
    )
    text = str(instrument).strip() or "Unknown"
    letter = chr(ord("A") + (index % 26))
    return f"{text[:24]} {letter}"


def lecture_authority_gaps(bookings: Sequence[dict]) -> List[dict]:
    """Return A-class samples where canonical occupancy would mis-handle a lecture."""
    samples = []
    for index, event in enumerate(bookings):
        event_type = str(event.get("type") or "").strip().lower()
        if event_type not in LECTURE_TYPES:
            continue
        start_min, end_min = TimeParser.event_to_minute_range(event, default=None)
        if start_min is None or end_min is None:
            continue
        canonical = TimeParser.canonical_course_occupancy(start_min, end_min)
        board = TimeParser.board_event_occupancy(event)
        if canonical is None and board is not None:
            samples.append(
                {
                    "class": "A",
                    "reason": "lecture_real_range_vs_canonical",
                    "label": _instrument_label(event, index),
                    "room": event.get("resourceId") or event.get("room_id"),
                    "minutes": board,
                }
            )
    return samples


def _room_key(event: dict) -> Optional[str]:
    room = event.get("resourceId") or event.get("room_id")
    return str(room).strip() if room else None


def _assignment_identity(event: dict) -> Optional[str]:
    identity = event.get("id") or event.get("source_request_id")
    if identity:
        return str(identity)
    props = event.get("extendedProps") or {}
    for key in ("source_request_id", "Student Name", "Course Code"):
        value = props.get(key)
        if value:
            return str(value)
    return None


def room_change_gaps(
    baseline: Sequence[dict],
    final: Sequence[dict],
) -> List[dict]:
    """Classify room changes between two assignment snapshots."""
    baseline_by_id = {}
    for event in baseline:
        identity = _assignment_identity(event)
        if identity:
            baseline_by_id[identity] = event

    samples: List[dict] = []
    for index, event in enumerate(final):
        identity = _assignment_identity(event)
        if not identity or identity not in baseline_by_id:
            continue
        before = baseline_by_id[identity]
        before_room = _room_key(before)
        after_room = _room_key(event)
        if not before_room or not after_room or before_room == after_room:
            continue

        props = event.get("extendedProps") or {}
        preferred = props.get("Preferred Venue") or props.get("preferred_venue")
        if preferred and str(preferred).strip() == after_room:
            gap_class = "B"
            reason = "human_moved_to_preferred_venue"
        elif preferred and str(preferred).strip() == before_room:
            gap_class = "C"
            reason = "optimizer_took_preferred_but_human_moved"
        else:
            gap_class = "D"
            reason = "whole_board_rearrangement"

        samples.append(
            {
                "class": gap_class,
                "reason": reason,
                "label": _instrument_label(event, index),
                "from_room": before_room,
                "to_room": after_room,
            }
        )
    return samples


def summarize(samples: Iterable[dict]) -> Dict[str, int]:
    counts = Counter(item["class"] for item in samples)
    return {key: counts.get(key, 0) for key in ("A", "B", "C", "D")}


def build_report(
    *,
    data_dir: Path,
    baseline_path: Optional[Path] = None,
    sample_limit: int = 5,
) -> dict:
    bookings_path = data_dir / "bookings.json"
    if not bookings_path.exists():
        raise FileNotFoundError(f"Missing bookings.json in {data_dir}")

    final_bookings = _events(_load_json(bookings_path))
    samples = lecture_authority_gaps(final_bookings)

    if baseline_path and baseline_path.exists():
        baseline_events = _events(_load_json(baseline_path))
        samples.extend(room_change_gaps(baseline_events, final_bookings))

    counts = summarize(samples)
    anonymized = {}
    for gap_class in ("A", "B", "C", "D"):
        class_samples = [item for item in samples if item["class"] == gap_class]
        anonymized[gap_class] = class_samples[:sample_limit]

    return {
        "data_dir": str(data_dir),
        "baseline_path": str(baseline_path) if baseline_path else None,
        "counts": counts,
        "samples": anonymized,
        "ci_gated": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report Optimizer vs final A/B/C/D gaps (read-only, not CI-gated)."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "data",
        help="Directory containing bookings.json (default: repo data/)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Optional JSON file with Optimizer baseline assignments",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=5,
        help="Maximum anonymized samples per class",
    )
    args = parser.parse_args(argv)

    report = build_report(
        data_dir=args.data_dir.resolve(),
        baseline_path=args.baseline.resolve() if args.baseline else None,
        sample_limit=args.sample_limit,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
