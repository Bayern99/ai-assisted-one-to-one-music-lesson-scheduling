"""Shared import helpers used by DataLoader wrappers and data-management UIs."""

import copy
import io
import logging

import pandas as pd

logger = logging.getLogger(__name__)


SPECIALIZED_ROOM_TYPES = ["Piano", "Percussion", "Voice", "Instrumental"]


class NamedBytesIO(io.BytesIO):
    def __init__(self, payload, name):
        super().__init__(payload)
        self.name = name


def load_excel_sheets(file_buffer):
    """Parse an Excel file (or CSV) and return a dict of DataFrames."""
    try:
        if file_buffer.name.lower().endswith(".csv"):
            df = pd.read_csv(file_buffer)
            return {"Sheet1": df}
        return pd.read_excel(file_buffer, sheet_name=None)
    except Exception as exc:
        logger.warning("Error loading excel sheets: %s", exc)
        return {}


def infer_room_records(df_room):
    if df_room is None or df_room.empty:
        raise ValueError("Uploaded room file is empty.")

    cols = {str(c).strip().lower(): c for c in df_room.columns}

    def _find_col(candidates):
        for candidate in candidates:
            key = candidate.strip().lower()
            if key in cols:
                return cols[key]
        return None

    room_id_col = _find_col(["Room Number", "Room No", "Room", "Room ID", "ID"])
    spec_col = _find_col(["Piano Specifications", "Piano Spec", "Specifications", "Equipment", "Piano"])

    if room_id_col is None:
        raise ValueError("Missing required room ID column (e.g. 'Room Number').")

    rooms = []
    seen = set()
    for _, row in df_room.iterrows():
        room_id = str(row.get(room_id_col, "")).strip()
        if not room_id or room_id.lower() in ("nan", "none", "null") or room_id in seen:
            continue
        seen.add(room_id)

        room_spec = str(row.get(spec_col, "")).strip() if spec_col else ""
        spec_lower = room_spec.lower()
        room_type = "General"
        if any(token in spec_lower for token in ("percussion", "drum", "marimba", "timpani")):
            room_type = "Percussion"
        elif any(token in spec_lower for token in ("piano", "steinway", "yamaha", "boston")):
            room_type = "Piano"

        rooms.append(
            {
                "id": room_id,
                "name": room_id,
                "eq": room_spec,
                "type": room_type,
                "types": [room_type],
            }
        )

    if not rooms:
        raise ValueError("No valid room records found in the uploaded file.")

    return rooms


def infer_student_records(df_std):
    if df_std is None or df_std.empty:
        raise ValueError("Uploaded student file is empty.")

    df_std = df_std.fillna("")
    df_std = copy.deepcopy(df_std)
    df_std.columns = [str(c).strip() for c in df_std.columns]

    students = []
    for _, row in df_std.iterrows():
        def get_val(keys, default=""):
            for key in keys:
                if key in row:
                    return str(row[key]).strip()
            return default

        student_id = str(row.get("Student No", "")).strip()
        name_en = str(row.get("English Name", "")).strip()
        name_ch = str(row.get("Chinese Name", "")).strip()
        course_code = get_val(["Course Code", "Course No", "Code", "Subject Code"])
        meta = row.to_dict()

        raw_inst = str(row.get("Instrument", "")).strip()
        inst = raw_inst.lower()
        if "piano" in inst:
            student_type = "Piano"
        elif any(token in inst for token in ("percussion", "drum", "timpani")):
            student_type = "Percussion"
        elif any(token in inst for token in ("voice", "vocal", "soprano", "tenor", "baritone", "bass")):
            student_type = "Voice"
        else:
            student_type = "Instrumental"

        raw_year = row.get("Study Year", 0)
        try:
            year_int = int(float(raw_year)) if raw_year else 0
            if year_int in [10, 20, 30, 40, 50]:
                year_int = year_int // 10
        except (ValueError, TypeError):
            year_int = 0

        students.append(
            {
                "student_id": student_id,
                "name_en": name_en,
                "name_ch": name_ch,
                "display_name": f"{name_en} {name_ch}".strip(),
                "year": year_int,
                "instructor": str(row.get("Instructor", "")).strip(),
                "instrument": raw_inst,
                "type": student_type,
                "course_code": course_code,
                "status": str(row.get("Note/Status", "")),
                "meta": meta,
            }
        )
    return students


def infer_instructor_records(df_instructor):
    if df_instructor is None or df_instructor.empty:
        raise ValueError("Uploaded instructor file is empty.")

    columns = {
        str(column).strip().lower(): column
        for column in df_instructor.columns
    }
    name_column = next(
        (
            columns[name]
            for name in ("instructor", "teacher", "name")
            if name in columns
        ),
        None,
    )
    if name_column is None:
        raise ValueError("Missing required instructor name column.")

    records = []
    seen = set()
    for value in df_instructor[name_column]:
        name = str(value).strip()
        if not name or name.lower() in ("nan", "none", "null") or name in seen:
            continue
        seen.add(name)
        records.append({"name": name, "status": "Active"})
    if not records:
        raise ValueError("No valid instructor records found in the uploaded file.")
    return records


def infer_course_records(df_course):
    if df_course is None or df_course.empty:
        raise ValueError("Uploaded course file is empty.")

    columns = {
        str(column).strip().lower(): column
        for column in df_course.columns
    }
    code_column = next(
        (
            columns[name]
            for name in ("course name", "course code", "course", "code")
            if name in columns
        ),
        None,
    )
    if code_column is None:
        raise ValueError("Missing required course name or code column.")

    records = []
    seen = set()
    for value in df_course[code_column]:
        code = str(value).strip()
        if not code or code.lower() in ("nan", "none", "null") or code in seen:
            continue
        seen.add(code)
        records.append(
            {
                "code": code,
                "title": "",
                "convener": "",
                "category": "Demo Instruction",
                "credits": 1,
            }
        )
    if not records:
        raise ValueError("No valid course records found in the uploaded file.")
    return records


def import_rooms_from_excel(loader, file):
    """Import room definitions and infer room types."""
    try:
        if file.name.lower().endswith(".csv"):
            df_room = pd.read_csv(file)
        else:
            sheets = pd.read_excel(file, sheet_name=None)
            if not sheets:
                return "❌ Room Import Failed: No sheets found in uploaded file."
            if "Room" in sheets:
                df_room = sheets["Room"]
            else:
                first_sheet = next(iter(sheets.keys()))
                df_room = sheets[first_sheet]

        rooms = infer_room_records(df_room)

        saved_path = loader.save_data("rooms.json", rooms)
        primary_rooms_path = f"{loader.base_dir}/rooms.json"
        if str(saved_path) != str(primary_rooms_path):
            return (
                f"⚠️ Parsed {len(rooms)} Rooms. "
                f"Primary `rooms.json` is locked, saved to `{saved_path}` instead."
            )
        return f"✅ Parsed {len(rooms)} Rooms. Types inferred."
    except Exception as exc:
        return f"❌ Room Import Failed: {str(exc)}"


def import_student_roster(loader, file):
    """Legacy CSV student import."""
    try:
        df = pd.read_csv(file)
        cleaned_records = []
        for _, row in df.iterrows():
            year_raw = str(row.get("Study Year", "")).replace(".", "").strip()
            try:
                year = int(year_raw)
            except Exception:
                year = 0
            cleaned_records.append(
                {
                    "name_en": str(row.get("English Name", "")).strip(),
                    "name_ch": str(row.get("Chinese Name", "")).strip(),
                    "student_id": str(row.get("Student No", "")).strip(),
                    "year": year,
                    "programme": str(row.get("Programme", "")).strip(),
                    "instructor": str(row.get("Instructor", "")).strip(),
                    "instrument": str(row.get("Instrument", "")).strip(),
                }
            )
        loader.save_data("students.json", cleaned_records)
        return len(cleaned_records)
    except Exception as exc:
        return f"Error: {str(exc)}"


def import_students_from_excel(loader, file):
    """Strict student roster import from Excel."""
    try:
        df_std = pd.read_excel(file, sheet_name="Student Info")
        students = infer_student_records(df_std)
        loader.save_data("students.json", students)
        return f"✅ Parsed {len(students)} Students. Types inferred."
    except Exception as exc:
        return f"❌ Student Import Failed: {str(exc)}"
