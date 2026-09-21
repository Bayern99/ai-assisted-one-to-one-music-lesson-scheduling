from modules.scheduler.logic.optimizer_diagnostics import (
    build_room_occupant_line,
    build_studio_failure_header,
    build_studio_saturation_intro,
    build_studio_summary_line,
)


def test_build_studio_failure_header_preserves_current_copy():
    req = {"inst": "Instructor 0004", "date": "2026-03-30"}

    line = build_studio_failure_header(req)

    assert line == "❌ Studio Failed: Instructor 0004 @ 2026-03-30 (No Room/Time Constraint)"


def test_build_studio_saturation_intro_mentions_instrument():
    req = {"instrument": "Piano"}

    line = build_studio_saturation_intro(req)

    assert line == "      🔍 Saturation Check (Why did 'Piano' fail?):"


def test_build_room_occupant_line_preserves_indent_and_shape():
    line = build_room_occupant_line("CC105", "🔴 Locked (Theory)")

    assert line == "      - CC105: 🔴 Locked (Theory)"


def test_build_studio_summary_line_preserves_success_counter_copy():
    line = build_studio_summary_line(2, 5)

    assert line == "✅ Scheduled 2/5 Studio Classes."
