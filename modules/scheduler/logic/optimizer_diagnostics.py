"""Diagnostic/log text helpers extracted from optimizer.py.

These helpers preserve current optimizer log copy while keeping text
construction separate from scheduling orchestration.
"""


def build_studio_failure_header(req):
    return f"❌ Studio Failed: {req['inst']} @ {req['date']} (No Room/Time Constraint)"


def build_studio_saturation_intro(req):
    return f"      🔍 Saturation Check (Why did '{req['instrument']}' fail?):"


def build_room_occupant_line(room_id, occupant):
    return f"      - {room_id}: {occupant}"


def build_studio_summary_line(success_count, total_count):
    return f"✅ Scheduled {success_count}/{total_count} Studio Classes."
