from __future__ import annotations

from typing import Any, Optional


SEARCHABLE_STUDENT_FIELDS = (
    "student_id",
    "name_en",
    "name_ch",
    "instrument",
    "instructor",
)

EDITABLE_STUDENT_FIELDS = frozenset(
    {
        "name_en",
        "name_ch",
        "display_name",
        "year",
        "instructor",
        "instrument",
        "type",
        "course_code",
        "status",
    }
)


class StudentNotFound(LookupError):
    def __init__(self, student_id: str) -> None:
        self.student_id = str(student_id)
        super().__init__("Student not found: {0}".format(self.student_id))


class DuplicateStudentId(RuntimeError):
    def __init__(self, student_id: str) -> None:
        self.student_id = str(student_id)
        super().__init__("Duplicate student ID: {0}".format(self.student_id))


class StudentSaveFailed(RuntimeError):
    pass


def searchable_student_text(student: dict[str, Any]) -> str:
    return " ".join(str(student.get(field, "")) for field in SEARCHABLE_STUDENT_FIELDS).casefold()


def _normalized_student_id(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return None


def _student_records(loader) -> list[dict[str, Any]]:
    students = loader.get_data("students.json")
    if not isinstance(students, list):
        return []
    records = []
    for student in students:
        if not isinstance(student, dict):
            continue
        student_id = _normalized_student_id(student.get("student_id"))
        if student_id is None:
            continue
        record = dict(student)
        record["student_id"] = student_id
        records.append(record)
    return records


def list_students(loader, query: str = "", instrument: str = "") -> list[dict[str, Any]]:
    query_text = str(query or "").strip().casefold()
    records = [
        student
        for student in _student_records(loader)
        if (not query_text or query_text in searchable_student_text(student))
        and (not instrument or student.get("instrument") == instrument)
    ]
    return sorted(
        records,
        key=lambda student: (
            str(student.get("name_en", "")).casefold(),
            str(student.get("student_id", "")).casefold(),
        ),
    )


def get_student(loader, student_id: str) -> dict[str, Any]:
    target = _normalized_student_id(student_id)
    if target is None:
        raise StudentNotFound(student_id)
    matches = [
        student
        for student in _student_records(loader)
        if student.get("student_id") == target
    ]
    if len(matches) > 1:
        raise DuplicateStudentId(target)
    if not matches:
        raise StudentNotFound(target)
    return matches[0]


def update_student(
    loader,
    student_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    unexpected = set(changes) - EDITABLE_STUDENT_FIELDS
    if unexpected:
        raise ValueError(
            "Unsupported student fields: {0}".format(", ".join(sorted(unexpected)))
        )

    students = loader.get_data("students.json")
    if not isinstance(students, list):
        raise StudentNotFound(student_id)

    target = _normalized_student_id(student_id)
    if target is None:
        raise StudentNotFound(student_id)
    matches = [
        (index, student)
        for index, student in enumerate(students)
        if isinstance(student, dict)
        and _normalized_student_id(student.get("student_id")) == target
    ]
    if len(matches) > 1:
        raise DuplicateStudentId(target)
    if not matches:
        raise StudentNotFound(target)

    saved_students = list(students)
    index, student = matches[0]
    updated = dict(student)
    updated.update(changes)
    updated["student_id"] = target
    saved_students[index] = updated
    try:
        loader.save_data("students.json", saved_students)
    except Exception as exc:
        raise StudentSaveFailed("Student data could not be saved") from exc
    return dict(updated)


def delete_student(loader, student_id: str) -> str:
    students = loader.get_data("students.json")
    if not isinstance(students, list):
        raise StudentNotFound(student_id)

    target = _normalized_student_id(student_id)
    if target is None:
        raise StudentNotFound(student_id)
    matches = [
        index
        for index, student in enumerate(students)
        if isinstance(student, dict)
        and _normalized_student_id(student.get("student_id")) == target
    ]
    if len(matches) > 1:
        raise DuplicateStudentId(target)
    if not matches:
        raise StudentNotFound(target)

    saved_students = [student for index, student in enumerate(students) if index != matches[0]]
    try:
        loader.save_data("students.json", saved_students)
    except Exception as exc:
        raise StudentSaveFailed("Student data could not be saved") from exc
    return target


def delete_students(loader, student_ids: list[str]) -> list[str]:
    students = loader.get_data("students.json")
    if not isinstance(students, list):
        raise StudentNotFound(student_ids[0] if student_ids else "")

    targets: list[str] = []
    for student_id in student_ids:
        target = _normalized_student_id(student_id)
        if target is None:
            raise StudentNotFound(student_id)
        if target not in targets:
            targets.append(target)

    positions: dict[str, list[int]] = {target: [] for target in targets}
    for index, student in enumerate(students):
        if not isinstance(student, dict):
            continue
        stored = _normalized_student_id(student.get("student_id"))
        if stored in positions:
            positions[stored].append(index)
    for target, matches in positions.items():
        if len(matches) > 1:
            raise DuplicateStudentId(target)
        if not matches:
            raise StudentNotFound(target)

    removed = {matches[0] for matches in positions.values()}
    try:
        loader.save_data(
            "students.json",
            [student for index, student in enumerate(students) if index not in removed],
        )
    except Exception as exc:
        raise StudentSaveFailed("Student data could not be saved") from exc
    return targets
