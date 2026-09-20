"""Scheduler adapter compatibility wrapper."""

from modules.shared.scheduler_data_service import (
    detect_scheduler_conflicts as _detect_scheduler_conflicts,
    export_schedule_to_excel as _export_schedule_to_excel,
    import_schedule_from_excel as _import_schedule_from_excel,
    parse_lectures_from_csv as _parse_lectures_from_csv,
)
from modules.scheduler.logic.lecture_service import save_lectures as _save_lectures


def parse_lectures_from_csv(loader, file):
    return _parse_lectures_from_csv(loader, file)


def save_lectures(loader, events):
    return _save_lectures(loader, events)


def import_schedule_from_excel(loader, file):
    return _import_schedule_from_excel(loader, file)


def export_schedule_to_excel(loader):
    return _export_schedule_to_excel(loader)


def detect_scheduler_conflicts(loader):
    return _detect_scheduler_conflicts(loader)
