"""Aggregate instructor names and instruments from scheduling data sources."""

from __future__ import annotations

from modules.shared.field_schema import extract_instrument_from_course_code

_INSTRUCTOR_COL_HINTS = ("instructor", "teacher", "faculty")
_COURSE_CODE_COL_HINTS = ("course code", "course_code")
_INSTRUMENT_COL_HINTS = ("instruments", "instrument")


def _is_blank(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in ("nan", "none", "null")


def _find_column(df, hints):
    for col in df.columns:
        col_name = str(col).strip().lower()
        if any(hint in col_name for hint in hints):
            return col
    return None


def _add_instrument(profiles: dict[str, set[str]], name, instrument) -> None:
    if _is_blank(name):
        return
    clean_name = str(name).strip()
    profiles.setdefault(clean_name, set())
    if _is_blank(instrument):
        return
    clean_inst = str(instrument).strip()
    profiles[clean_name].add(clean_inst)


def _extract_names_from_df(df):
    names = set()
    instructor_col = _find_column(df, _INSTRUCTOR_COL_HINTS)
    if instructor_col is None:
        return names
    for raw in df[instructor_col].dropna().astype(str).tolist():
        name = raw.strip()
        if name and name.lower() not in ("nan", "none", "null"):
            names.add(name)
    return names


def _instruments_from_df(df) -> dict[str, set[str]]:
    profiles: dict[str, set[str]] = {}
    if df is None or getattr(df, "empty", True):
        return profiles

    instructor_col = _find_column(df, _INSTRUCTOR_COL_HINTS)
    if instructor_col is None:
        return profiles

    course_col = _find_column(df, _COURSE_CODE_COL_HINTS)
    instrument_col = _find_column(df, _INSTRUMENT_COL_HINTS)

    for _, row in df.iterrows():
        name = row.get(instructor_col)
        if _is_blank(name):
            continue

        if instrument_col is not None and not _is_blank(row.get(instrument_col)):
            raw_inst = str(row.get(instrument_col)).strip()
            for part in raw_inst.replace(";", ",").split(","):
                inst = part.strip()
                if inst:
                    _add_instrument(profiles, name, inst)
            continue

        if course_col is not None:
            instrument = extract_instrument_from_course_code(str(row.get(course_col, "")))
            _add_instrument(profiles, name, instrument)
        else:
            _add_instrument(profiles, name, "")

    return profiles


def collect_instructor_profiles(loader, session_state) -> list[dict]:
    """Return sorted instructor profiles: name + aggregated instruments."""
    merged: dict[str, set[str]] = {}

    def merge_profiles(source: dict[str, set[str]]) -> None:
        for name, instruments in source.items():
            merged.setdefault(name, set()).update(instruments)

    def add_name_only(name) -> None:
        if not _is_blank(name):
            merged.setdefault(str(name).strip(), set())

    try:
        students = loader.get_data("students.json") or []
    except Exception:
        students = []

    for student in students:
        if not isinstance(student, dict):
            continue
        name = student.get("instructor")
        if _is_blank(name):
            continue
        instrument = student.get("instrument") or student.get("type") or ""
        if _is_blank(instrument):
            add_name_only(name)
        else:
            _add_instrument(merged, name, instrument)

    try:
        instructors = loader.get_data("instructors.json") or []
    except Exception:
        instructors = []
    for record in instructors:
        if isinstance(record, dict):
            add_name_only(record.get("name"))

    for key in ("wk_df", "stu_df", "uploaded_weekly", "uploaded_studio"):
        df = session_state.get(key)
        if df is None:
            continue
        merge_profiles(_instruments_from_df(df))
        for name in _extract_names_from_df(df):
            add_name_only(name)

    return [
        {"name": name, "instruments": sorted(merged[name])}
        for name in sorted(merged)
    ]


def format_instruments(instruments) -> str:
    if not instruments:
        return "—"
    return ", ".join(instruments)


def sanitize_instructor_priority(priorities, valid_names):
    valid_names = {str(name).strip() for name in valid_names if str(name).strip()}
    sanitized = {}
    dropped = {}
    if not isinstance(priorities, dict):
        return sanitized, dropped

    for instructor, value in priorities.items():
        clean = str(instructor).strip()
        if not clean:
            continue
        if clean in valid_names:
            sanitized[clean] = value
        else:
            dropped[clean] = value

    return sanitized, dropped
