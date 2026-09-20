import pandas as pd

from modules.scheduler.logic.instructor_profiles import (
    collect_instructor_profiles,
    format_instruments,
    sanitize_instructor_priority,
)


class _LoaderStub:
    def __init__(self, students=None, instructors=None):
        self._students = students or []
        self._instructors = instructors or []

    def get_data(self, filename):
        if filename == "students.json":
            return self._students
        if filename == "instructors.json":
            return self._instructors
        return []


def test_collect_instructor_profiles_merges_students_and_uploads():
    loader = _LoaderStub(
        students=[{"instructor": "Prof A", "instrument": "Piano"}],
        instructors=[{"name": "Prof B", "status": "Active"}],
    )
    session_state = {
        "wk_df": pd.DataFrame(
            [
                {
                    "Instructor": "Prof C",
                    "Course Code": "MUS4153 - Demo Instruction (Voice)",
                }
            ]
        )
    }

    profiles = collect_instructor_profiles(loader, session_state)
    by_name = {profile["name"]: profile["instruments"] for profile in profiles}

    assert by_name["Prof A"] == ["Piano"]
    assert by_name["Prof B"] == []
    assert by_name["Prof C"] == ["Voice"]


def test_format_instruments_handles_empty():
    assert format_instruments([]) == "—"
    assert format_instruments(["Piano", "Voice"]) == "Piano, Voice"


def test_sanitize_instructor_priority_drops_unknown_names():
    cleaned, dropped = sanitize_instructor_priority(
        {"Prof A": 8, "Former Teacher": 10},
        {"Prof A"},
    )

    assert cleaned == {"Prof A": 8}
    assert dropped == {"Former Teacher": 10}
