from pathlib import Path


def test_typescript_contains_no_scheduler_rule_engine():
    banned = (
        "checkConflict(",
        "roomIsAvailable(",
        "enforceInstructorBlocks(",
        "minBreakBetweenLessons",
        "commitCurrentRound(",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("frontend/src").rglob("*.ts*")
    )

    for token in banned:
        assert token not in source, f"Scheduler rule leaked into TypeScript: {token}"
