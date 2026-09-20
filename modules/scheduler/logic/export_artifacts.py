from dataclasses import dataclass
from io import BytesIO
import json
import re
import zipfile

import pandas as pd

from modules.scheduler.logic.export_generator import build_export_dataframe


@dataclass(frozen=True)
class ExportArtifacts:
    files: dict[str, bytes]
    preview_records: list[dict]

    def __getitem__(self, key):
        """Keep existing Step 5 direct callers working during extraction."""
        if key == "files":
            return self.files
        if key == "dataframes":
            master = pd.DataFrame(self.preview_records)
            return {
                "master": master,
                "weekly": _read_optional_workbook(self.files, "Weekly_Schedule.xlsx"),
                "studio": _read_optional_workbook(self.files, "Studio_Schedule.xlsx"),
            }
        raise KeyError(key)


def _read_optional_workbook(files, name):
    payload = files.get(name)
    return None if payload is None else pd.read_excel(BytesIO(payload))


def dataframe_to_xlsx_bytes(df):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return out.getvalue()


def build_download_artifacts(
    bookings,
    unassigned,
    student_map,
    valid_instructors,
    uploaded_studio_df=None,
):
    df_export = build_export_dataframe(
        bookings,
        unassigned,
        student_map,
        valid_instructors,
        uploaded_studio_df=uploaded_studio_df,
    )
    files = {"Master_Schedule.xlsx": dataframe_to_xlsx_bytes(df_export)}

    weekly_bookings = [
        booking for booking in bookings if booking.get("type") == "weekly_lesson"
    ]
    if weekly_bookings:
        weekly = build_export_dataframe(
            weekly_bookings,
            [],
            student_map,
            valid_instructors,
            uploaded_studio_df=uploaded_studio_df,
        )
        files["Weekly_Schedule.xlsx"] = dataframe_to_xlsx_bytes(weekly)

    studio_bookings = [
        booking for booking in bookings if booking.get("type") == "studio_class"
    ]
    if studio_bookings:
        studio = build_export_dataframe(
            studio_bookings,
            [],
            student_map,
            valid_instructors,
            uploaded_studio_df=uploaded_studio_df,
        )
        files["Studio_Schedule.xlsx"] = dataframe_to_xlsx_bytes(studio)

    return ExportArtifacts(
        files=files,
        preview_records=json.loads(
            df_export.to_json(orient="records", date_format="iso", date_unit="ms")
        ),
    )


def build_instructor_bundle_zip(df_export):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(
        zip_buffer, "a", zipfile.ZIP_DEFLATED, allowZip64=False
    ) as zip_file:
        unique_instructors = (
            sorted(df_export["Instructor"].dropna().unique())
            if "Instructor" in df_export.columns
            else []
        )
        for instructor in unique_instructors:
            if not instructor or instructor == "Unknown":
                continue
            instructor_df = df_export[df_export["Instructor"] == instructor]
            if instructor_df.empty:
                continue
            safe_name = re.sub(r"[^\w\s-]", "", instructor).strip().replace(" ", "_")
            zip_file.writestr(
                "{0}_Schedule.xlsx".format(safe_name),
                dataframe_to_xlsx_bytes(instructor_df),
            )
    return zip_buffer.getvalue()
