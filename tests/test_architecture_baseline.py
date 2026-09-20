import ast
import json
from collections import Counter
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _non_empty_values(records, key):
    return [
        str(item[key])
        for item in records
        if isinstance(item, dict) and item.get(key) not in (None, "")
    ]


def _duplicates(values):
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _public_data_workspace_available() -> bool:
    return DATA_DIR.is_dir() and any(DATA_DIR.glob("*.json"))


def test_runtime_json_files_parse():
    if not _public_data_workspace_available():
        pytest.skip("Public companion does not ship a live data/ workspace.")
    json_files = sorted(DATA_DIR.glob("*.json"))

    assert json_files
    for path in json_files:
        _load_json(path)


def test_required_runtime_json_files_exist():
    if not _public_data_workspace_available():
        pytest.skip("Public companion does not ship a live data/ workspace.")
    required = {
        "bookings.json",
        "students.json",
        "rooms.json",
        "workflow_state.json",
        "scheduling_rules.json",
    }

    missing = sorted(name for name in required if not (DATA_DIR / name).is_file())
    assert missing == []


def test_core_runtime_identifiers_are_consistent():
    if not _public_data_workspace_available():
        pytest.skip("Public companion does not ship a live data/ workspace.")
    rooms = _load_json(DATA_DIR / "rooms.json")
    students = _load_json(DATA_DIR / "students.json")
    bookings = _load_json(DATA_DIR / "bookings.json")

    room_ids = _non_empty_values(rooms, "id")
    student_ids = _non_empty_values(students, "student_id")

    assert _duplicates(room_ids) == []
    assert _duplicates(student_ids) == []

    room_id_set = set(room_ids)
    unknown_resource_ids = sorted(
        {
            str(booking["resourceId"])
            for booking in bookings
            if isinstance(booking, dict)
            and booking.get("resourceId") not in (None, "")
            and str(booking["resourceId"]) not in room_id_set
        }
    )

    assert unknown_resource_ids == []


def test_shared_modules_do_not_import_scheduler_directly():
    shared_root = PROJECT_ROOT / "modules" / "shared"

    offenders = []
    for path in shared_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if (
            "modules.scheduler" in source
            or "from modules.scheduler" in source
            or "import modules.scheduler" in source
        ):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_scheduler_architecture_reports_reflect_post_split_baseline():
    pytest.skip("Internal architecture reports are not shipped in the public companion.")
