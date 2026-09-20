from copy import deepcopy

import pytest

from modules.info_hub.logic.dashboard_service import build_dashboard_summary
from modules.info_hub.logic.student_service import (
    DuplicateStudentId,
    StudentNotFound,
    get_student,
    list_students,
    searchable_student_text,
    update_student,
)


class FakeLoader:
    def __init__(self, data=None, workflow=None, bookings=None):
        self.data = deepcopy(data or {})
        self.workflow = deepcopy(workflow or {})
        self.bookings = deepcopy(bookings or [])
        self.saves = []

    def get_data(self, name):
        return deepcopy(self.data.get(name, []))

    def load_workflow_state(self):
        return deepcopy(self.workflow)

    def load_bookings(self):
        return deepcopy(self.bookings)

    def save_data(self, name, data):
        self.saves.append((name, deepcopy(data)))
        self.data[name] = deepcopy(data)
        return name


class FakeSessionManager:
    def __init__(self, activity=None, session=None):
        self.activity = deepcopy(activity)
        self.session = deepcopy(session)

    def load_activity(self):
        return deepcopy(self.activity)

    def load_session(self):
        return deepcopy(self.session)


STUDENTS = [
    {
        "student_id": "S2",
        "name_en": "Student 0002",
        "name_ch": "学生二",
        "display_name": "Student 0002 学生二",
        "year": 2,
        "instructor": "Instructor 0001",
        "instrument": "Piano",
        "type": "Piano",
        "course_code": "MUS200",
        "status": "active",
        "meta": {"source": "roster"},
    },
    {
        "student_id": "S1",
        "name_en": "Student 0001",
        "name_ch": "学生一",
        "display_name": "Student 0001 学生一",
        "year": 1,
        "instructor": "Instructor 0002",
        "instrument": "Violin",
        "type": "Instrumental",
        "course_code": "MUS100",
        "status": "active",
        "meta": {"source": "roster"},
    },
]


def test_searchable_student_text_uses_only_the_five_search_fields():
    student = {
        **STUDENTS[0],
        "course_code": "SECRET-COURSE",
        "meta": {"private_note": "SECRET-NOTE"},
    }

    text = searchable_student_text(student)

    assert text == "s2 student 0002 学生二 piano instructor 0001"
    assert "secret" not in text


def test_list_students_filters_dicts_searches_casefold_and_sorts_stably():
    loader = FakeLoader(
        data={"students.json": [STUDENTS[0], "bad-row", STUDENTS[1]]}
    )

    assert [item["student_id"] for item in list_students(loader)] == ["S1", "S2"]
    assert [item["student_id"] for item in list_students(loader, query="  STUDENT 0001 ")] == ["S1"]
    assert [item["student_id"] for item in list_students(loader, query="学生一")] == ["S1"]
    assert [item["student_id"] for item in list_students(loader, instrument="Piano")] == ["S2"]
    assert list_students(loader, instrument="piano") == []


def test_get_student_matches_string_id_and_not_found_is_domain_error():
    loader = FakeLoader(data={"students.json": STUDENTS})

    assert get_student(loader, "S2")["name_en"] == "Student 0002"
    with pytest.raises(StudentNotFound) as error:
        get_student(loader, "missing")
    assert error.value.student_id == "missing"


def test_numeric_student_id_reads_as_string_without_mutating_loader_record():
    loader = FakeLoader(data={"students.json": [{**STUDENTS[1], "student_id": 1001}]})
    loader.get_data = lambda name: loader.data.get(name, [])

    assert list_students(loader)[0]["student_id"] == "1001"
    assert get_student(loader, "1001")["student_id"] == "1001"
    assert loader.data["students.json"][0]["student_id"] == 1001


def test_update_numeric_student_id_normalizes_saved_id_to_string():
    invalid = [
        {"name_en": "Missing"},
        {"student_id": None, "name_en": "Null"},
        {"student_id": "", "name_en": "Empty"},
        {"student_id": True, "name_en": "Bool"},
    ]
    loader = FakeLoader(
        data={"students.json": [*invalid, {**STUDENTS[1], "student_id": 1001}]}
    )

    updated = update_student(loader, "1001", {"instructor": "Dr. New"})

    assert updated["student_id"] == "1001"
    assert updated["meta"] == {"source": "roster"}
    assert loader.saves[0][1][:-1] == invalid
    assert loader.saves[0][1][-1]["student_id"] == "1001"


def test_invalid_student_ids_are_hidden_and_never_match_get_or_update():
    invalid = [
        {"name_en": "Missing"},
        {"student_id": None, "name_en": "Null"},
        {"student_id": "", "name_en": "Empty"},
        {"student_id": "   ", "name_en": "Whitespace"},
        {"student_id": True, "name_en": "True"},
        {"student_id": False, "name_en": "False"},
    ]
    loader = FakeLoader(data={"students.json": invalid})

    assert list_students(loader) == []
    for student_id in ("None", "", "   ", "True", "False"):
        with pytest.raises(StudentNotFound):
            get_student(loader, student_id)
        with pytest.raises(StudentNotFound):
            update_student(loader, student_id, {"instructor": "Dr. New"})
    assert loader.saves == []


def test_duplicate_student_ids_list_but_block_get_and_update_without_save():
    duplicates = [
        {**STUDENTS[1], "student_id": 7, "name_en": "Student 0001"},
        {**STUDENTS[0], "student_id": "7", "name_en": "Student 0002"},
    ]
    loader = FakeLoader(data={"students.json": duplicates})

    assert [student["student_id"] for student in list_students(loader)] == ["7", "7"]
    with pytest.raises(DuplicateStudentId):
        get_student(loader, "7")
    with pytest.raises(DuplicateStudentId):
        update_student(loader, "7", {"instructor": "Dr. New"})
    assert loader.saves == []


def test_update_student_partial_change_preserves_id_and_all_unmentioned_fields():
    loader = FakeLoader(data={"students.json": STUDENTS})

    updated = update_student(loader, "S1", {"instructor": "Dr. New"})

    assert updated == {**STUDENTS[1], "instructor": "Dr. New"}
    assert updated["student_id"] == "S1"
    assert updated["name_en"] == "Student 0001"
    assert updated["meta"] == {"source": "roster"}
    assert loader.saves == [
        (
            "students.json",
            [STUDENTS[0], {**STUDENTS[1], "instructor": "Dr. New"}],
        )
    ]


def test_update_student_rejects_id_or_internal_field_and_does_not_save():
    loader = FakeLoader(data={"students.json": STUDENTS})

    with pytest.raises(ValueError):
        update_student(loader, "S1", {"student_id": "S9"})
    with pytest.raises(ValueError):
        update_student(loader, "S1", {"meta": {"injected": True}})

    assert loader.saves == []


def test_update_student_not_found_does_not_save():
    loader = FakeLoader(data={"students.json": STUDENTS})

    with pytest.raises(StudentNotFound):
        update_student(loader, "missing", {"instructor": "Dr. New"})

    assert loader.saves == []


def test_dashboard_maps_saved_scheduler_activity_to_resolution_cta():
    loader = FakeLoader(
        data={
            "students.json": STUDENTS,
            "instructors.json": [{"name": "Instructor 0001"}],
            "rooms.json": [{"id": "R1"}],
        },
        workflow={"current_phase": "scheduling"},
        bookings=[{"id": "B1"}],
    )
    manager = FakeSessionManager(
        activity={
            "page_title": "Smart Scheduler",
            "timestamp": "not-an-iso-timestamp",
        },
        session={"round_committed": False},
    )

    summary = build_dashboard_summary(
        loader,
        manager,
        {"status": "warning", "checks": [], "recommendations": []},
    )

    assert summary.continue_action is not None
    assert summary.continue_action.continue_path == "/schedule/resolve"
    assert summary.continue_action.continue_label == "Continue schedule resolution"
    assert summary.continue_action.timestamp == "not-an-iso-timestamp"
    assert summary.counts.students == 2
    assert summary.counts.instructors == 1
    assert summary.counts.rooms == 1
    assert summary.counts.bookings == 1
    assert summary.health["status"] == "warning"


def test_dashboard_empty_sources_are_honest_zero_none_values():
    summary = build_dashboard_summary(
        FakeLoader(),
        FakeSessionManager(),
        {"status": "ok", "checks": [], "recommendations": []},
    )

    assert summary.workflow_state == {}
    assert summary.continue_action is None
    assert summary.counts.students == 0
    assert summary.counts.instructors == 0
    assert summary.counts.rooms == 0
    assert summary.counts.bookings == 0
    assert summary.session.active_step is None
    assert summary.session.round_committed is False
    assert summary.session.draft_dirty is False


@pytest.mark.parametrize(
    "activity,workflow",
    [
        ({"page_title": "Dashboard"}, {}),
        ({"page_title": "Unknown", "timestamp": {}}, {"current_phase": "scheduling"}),
        ({"page_title": []}, {"current_phase": "scheduling"}),
    ],
)
def test_dashboard_unmapped_or_malformed_navigation_has_no_cta(activity, workflow):
    summary = build_dashboard_summary(
        FakeLoader(workflow=workflow),
        FakeSessionManager(activity=activity),
        {"status": "ok", "checks": [], "recommendations": []},
    )

    assert summary.continue_action is None


@pytest.mark.parametrize("activity", [None, {}])
def test_dashboard_missing_activity_uses_known_workflow_phase(activity):
    summary = build_dashboard_summary(
        FakeLoader(workflow={"current_phase": "scheduling"}),
        FakeSessionManager(activity=activity),
        {"status": "ok", "checks": [], "recommendations": []},
    )

    assert summary.continue_action is not None
    assert summary.continue_action.page_title == "Smart Scheduler"
    assert summary.continue_action.continue_path == "/schedule/resolve"
