from modules.scheduler.logic.optimizer_studio_assignment import assign_studio_requests


def _request(inst, date, start, end, prefs=None, instrument="Piano", id_suffix="1_0"):
    return {
        "inst": inst,
        "date": date,
        "day": 1,
        "start": start,
        "end": end,
        "prefs": prefs or [],
        "instrument": instrument,
        "id_suffix": id_suffix,
        "raw_row": {"Instructor": inst},
    }


def test_assign_studio_requests_sorts_requests_and_checks_preferred_room_first():
    created = []
    resolved = []
    requests = [
        _request("LowPriority", "2026-03-31", 10, 11, prefs=[]),
        _request("HighPriority", "2026-03-30", 11, 12, prefs=["A"]),
        _request("Early", "2026-03-29", 9, 10, prefs=[]),
    ]

    def can_assign(room_id, req):
        if req["inst"] == "HighPriority" and room_id == "A":
            return False
        return room_id == "B"

    logs = assign_studio_requests(
        requests=requests,
        room_ids=["A", "B"],
        instructor_priority={"HighPriority": 9, "LowPriority": 1, "Early": 1},
        merge_requests=lambda items: list(items),
        can_assign=can_assign,
        score_room=lambda room_id, req: 100 if room_id == "B" else 10,
        resolve_preferred_room_conflict=lambda room_id, req: resolved.append((room_id, req["inst"])),
        append_assignment=lambda req, room_id: created.append((req["inst"], room_id)),
        append_unassigned=lambda req, reason, reason_code: None,
        build_failure_reason=lambda req: ("no_time_feasible_room", "No feasible room-time placement"),
        describe_room_occupant=lambda req, room_id: None,
    )

    assert logs[-1] == "✅ Scheduled 3/3 Studio Classes."
    assert resolved == [("A", "HighPriority")]
    assert [inst for inst, _room in created] == ["Early", "HighPriority", "LowPriority"]


def test_assign_studio_requests_uses_highest_scoring_room():
    created = []
    request = _request("Dr. Kim", "2026-03-30", 18, 19, prefs=[])

    assign_studio_requests(
        requests=[request],
        room_ids=["A", "B"],
        instructor_priority={},
        merge_requests=lambda items: list(items),
        can_assign=lambda room_id, req: True,
        score_room=lambda room_id, req: {"A": 80, "B": 100}[room_id],
        resolve_preferred_room_conflict=lambda room_id, req: None,
        append_assignment=lambda req, room_id: created.append((req["inst"], room_id)),
        append_unassigned=lambda req, reason, reason_code: None,
        build_failure_reason=lambda req: ("no_time_feasible_room", "No feasible room-time placement"),
        describe_room_occupant=lambda req, room_id: None,
    )

    assert created == [("Dr. Kim", "B")]


def test_assign_studio_requests_routes_failures_with_diagnostics_and_summary():
    request = _request("Dr. Kim", "2026-03-30", 18, 19, prefs=[], instrument="Piano")
    unassigned = []

    logs = assign_studio_requests(
        requests=[request],
        room_ids=["A", "B", "C"],
        instructor_priority={},
        merge_requests=lambda items: list(items),
        can_assign=lambda room_id, req: False,
        score_room=lambda room_id, req: 0,
        resolve_preferred_room_conflict=lambda room_id, req: None,
        append_assignment=lambda req, room_id: None,
        append_unassigned=lambda req, reason, reason_code: unassigned.append((req["inst"], reason_code, reason)),
        build_failure_reason=lambda req: ("blocked_by_locked_context", "Blocked by locked context"),
        describe_room_occupant=lambda req, room_id: {"A": "🔴 Locked (Lecture)", "B": "⛔ Closed (Time Constraint)"}.get(room_id),
    )

    assert logs == [
        "❌ Studio Failed: Dr. Kim @ 2026-03-30 (No Room/Time Constraint)",
        "      🔍 Saturation Check (Why did 'Piano' fail?):",
        "      - A: 🔴 Locked (Lecture)",
        "      - B: ⛔ Closed (Time Constraint)",
        "✅ Scheduled 0/1 Studio Classes.",
    ]
    assert unassigned == [("Dr. Kim", "blocked_by_locked_context", "Blocked by locked context")]
