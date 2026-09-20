#!/usr/bin/env python3
"""One-shot sanitizer for public companion branding and synthetic fixtures."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", "frontend/dist", ".venv", "__pycache__"}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".swift", ".sh", ".command", ".md", ".txt",
    ".json", ".csv", ".ini", ".toml", ".html", ".css", ".gitignore", ".yml", ".yaml",
}

# Order matters: longer / more specific patterns first.
REPLACEMENTS = [
    # Legacy app / bundle branding
    ("Music Lesson Scheduler", "Music Lesson Scheduler"),
    ("MusicLessonSchedulerSwiftTests", "MusicLessonSchedulerSwiftTests"),
    ("MusicLessonSchedulerApp", "MusicLessonSchedulerApp"),
    ("MusicLessonSchedulerSwift", "MusicLessonSchedulerSwift"),
    ("MusicLessonSchedulerNativeShell", "MusicLessonSchedulerNativeShell"),
    ("com.research.music-lesson-scheduler", "com.research.music-lesson-scheduler"),
    ("edu.research.music-lesson-scheduler", "edu.research.music-lesson-scheduler"),
    ("music-lesson-scheduler-react", "music-lesson-scheduler-react"),
    ("music_lesson_scheduler_session_locks", "music_lesson_scheduler_session_locks"),
    ("music_lesson_scheduler_shadow", "music_lesson_scheduler_shadow"),
    ("music-lesson-scheduler-e2e-token", "music-lesson-scheduler-e2e-token"),
    ("music-lesson-scheduler-e2e-", "music-lesson-scheduler-e2e-"),
    ("music-lesson-scheduler-swift-app.", "music-lesson-scheduler-swift-app."),
    ("music-lesson-scheduler-text-size", "music-lesson-scheduler-text-size"),
    (".music-lesson-scheduler.lock", ".music-lesson-scheduler.lock"),
    ("/tmp/music-lesson-scheduler-data", "/tmp/music-lesson-scheduler-data"),
    ("/tmp/music-lesson-scheduler", "/tmp/music-lesson-scheduler"),
    ("Music Lesson Scheduler", "Music Lesson Scheduler"),
    ("Lesson-Scheduler-export.xlsx", "Lesson-Scheduler-export.xlsx"),
    ("Source_Data_Backup.xlsx", "Source_Data_Backup.xlsx"),
    ("Student_Register.xlsx", "Student_Register.xlsx"),
    ("Scheduler Workbook.xlsx", "Scheduler Workbook.xlsx"),
    ("Demo Student Names.xlsx", "Demo Student Names.xlsx"),
    ("synthetic_blockage_audit", "synthetic_blockage_audit"),
    # Institution-specific room codes → generic demo rooms
    ("R104", "R104"),
    ("R101", "R101"),
    ("R102", "R102"),
    ("R106", "R106"),
    ("R105", "R105"),
    ("R103", "R103"),
    ("R107", "R107"),
    ("Hall-A", "Hall-A"),
    # Course / programme labels tied to a specific department offering
    ("Demo Course I (Piano)", "Demo Course I (Piano)"),
    ("Demo Instruction", "Demo Instruction"),
    # Instructor placeholders (longer first)
    ("Instructor 0001", "Instructor 0001"),
    ("Instructor 0007", "Instructor 0007"),
    ("Instructor 0006", "Instructor 0006"),
    ("Instructor 0005", "Instructor 0005"),
    ("Instructor 0003", "Instructor 0003"),
    ("Instructor 0002", "Instructor 0002"),
    ("Instructor 0001", "Instructor 0001"),
    ("Instructor 0012", "Instructor 0012"),
    ("Instructor 0009", "Instructor 0009"),
    ("Instructor 0008", "Instructor 0008"),
    ("Instructor 0004 Alt", "Instructor 0004 Alt"),
    ("Instructor 0004", "Instructor 0004"),
    ("Instructor 0010", "Instructor 0010"),
    ("Instructor 0002", "Instructor 0002"),
    ("Instructor 0001", "Instructor 0001"),
    ("Instructor 0004 Reversed", "Instructor 0004 Reversed"),
    ("Instructor 0004 Alt", "Instructor 0004 Alt"),
    ("Instructor 0004", "Instructor 0004"),
    ("0004 Instructor", "0004 Instructor"),
    ("Instructor 0003", "Instructor 0003"),
    ("Instructor 0001", "Instructor 0001"),
    ("Instructor 0004", "Instructor 0004"),
    ("Instructor 0005", "Instructor 0005"),
    ("Instructor 0006", "Instructor 0006"),
    ("Instructor 0007", "Instructor 0007"),
    ("Instructor 0002", "Instructor 0002"),
    ("Instructor Secret", "Instructor Secret"),
    ("Instructor 0008", "Instructor 0008"),
    ("Instructor 0009", "Instructor 0009"),
    ("Staff Facilitator", "Staff Facilitator"),
    ("Instructor 0011", "Instructor 0011"),
    ("Instructor 0001", "Instructor 0001"),  # fix double-replace edge cases
    # Student placeholders
    ("Student 0003", "Student 0003"),
    ("Student Secret", "Student Secret"),  # keep for privacy-redaction tests
    ("Student 0001", "Student 0001"),
    ("Student 0002", "Student 0002"),
    ("Student 0001", "Student 0001"),
    ("Student 0002", "Student 0002"),
    ("Student 0003", "Student 0003"),
    ("Student 0001 学生一", "Student 0001 学生一"),
    ("Student 0002 学生二", "Student 0002 学生二"),
    ("Student 0001 学生甲", "Student 0001 学生甲"),
    ("Student 0001", "Student 0001"),
    ("Student 0002", "Student 0002"),
    ("Student 0002", "Student 0002"),
    ("Student 0004", "Student 0004"),
    ("Student 0005", "Student 0005"),
    ("Student 0006", "Student 0006"),
    ("Student 0007", "Student 0007"),
    ("学生一", "学生一"),
    ("学生二", "学生二"),
    ("学生甲", "学生甲"),
    ("学生三", "学生三"),
    ("学生一", "学生一"),
    ("学生二", "学生二"),
    # Misc forensic ids
    ("wk_student_0003_wed", "wk_student_0003_wed"),
    ("studio_instructor_0002_mar4", "studio_instructor_0002_mar4"),
    ("studio_instructor_0002_mar4", "studio_instructor_0002_mar4"),
    ("data_with_instructor_0002_studio", "data_with_instructor_0002_studio"),
    ("data_with_instructor_0002_studio", "data_with_instructor_0002_studio"),
    ("key_instructor_0002", "key_instructor_0002"),
    ("key_instructor_0001", "key_instructor_0001"),
    ("key_instructor_0001", "key_instructor_0001"),
    ("key_instructor_0002", "key_instructor_0002"),
    ("diagnose_room_r105", "diagnose_room_r105"),
    ("r105", "r105"),
]


def should_visit(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return False
    if path.suffix == ".png":
        return False
    if path.name.endswith(".bundle"):
        return False
    return path.suffix in TEXT_SUFFIXES or path.name in {".gitignore", "AGENTS.md", "CONTEXT.md"}


def main() -> None:
    changed = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if not should_visit(path):
                continue
            original = path.read_text(encoding="utf-8")
            updated = original
            for old, new in REPLACEMENTS:
                updated = updated.replace(old, new)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                changed += 1
    print(f"Updated {changed} files under {ROOT}")


if __name__ == "__main__":
    main()
