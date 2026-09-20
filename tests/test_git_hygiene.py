import subprocess
from pathlib import Path


def test_private_workbook_and_cleanup_script_are_not_tracked():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        ["git", "ls-files", "--", "Scheduler Workbook.xlsx", "clean_pi_scheduling.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked == []
    assert "/Scheduler Workbook.xlsx" in (root / ".gitignore").read_text(encoding="utf-8")
