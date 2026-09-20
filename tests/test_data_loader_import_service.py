"""TDD for DataLoader thin wrappers over shared import service."""

from modules.shared.data_loader import DataLoader
from modules.shared.import_service import (
    import_rooms_from_excel,
    import_student_roster,
    import_students_from_excel,
    load_excel_sheets,
)


class _NamedBuffer:
    def __init__(self, name):
        self.name = name


def test_data_loader_load_excel_sheets_delegates_to_shared_service(monkeypatch):
    loader = DataLoader(base_dir="data_test")
    sentinel = {"Sheet1": object()}

    monkeypatch.setattr("modules.shared.import_service.load_excel_sheets", lambda file_buffer: sentinel)

    assert loader.load_excel_sheets(_NamedBuffer("weekly.csv")) is sentinel


def test_data_loader_import_student_roster_delegates_to_shared_service(monkeypatch):
    loader = DataLoader(base_dir="data_test")

    monkeypatch.setattr(
        "modules.shared.import_service.import_student_roster",
        lambda target_loader, file: "students-ok",
    )

    assert loader.import_student_roster(_NamedBuffer("students.csv")) == "students-ok"


def test_data_loader_import_students_from_excel_delegates_to_shared_service(monkeypatch):
    loader = DataLoader(base_dir="data_test")

    monkeypatch.setattr(
        "modules.shared.import_service.import_students_from_excel",
        lambda target_loader, file: "students-xlsx-ok",
    )

    assert loader.import_students_from_excel(_NamedBuffer("students.xlsx")) == "students-xlsx-ok"


def test_data_loader_import_rooms_from_excel_delegates_to_shared_service(monkeypatch):
    loader = DataLoader(base_dir="data_test")

    monkeypatch.setattr(
        "modules.shared.import_service.import_rooms_from_excel",
        lambda target_loader, file: "rooms-ok",
    )

    assert loader.import_rooms_from_excel(_NamedBuffer("rooms.xlsx")) == "rooms-ok"
