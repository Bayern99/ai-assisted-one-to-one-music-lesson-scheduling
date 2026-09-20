from modules.scheduler.logic.optimizer_preemption_resolution import resolve_grandmaster_conflicts


def test_resolve_grandmaster_conflicts_returns_true_when_no_conflicts():
    logs = []

    resolved = resolve_grandmaster_conflicts(
        room_id="R1",
        req={"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
        conflicts=[],
        resolve_victim_block=lambda event: event,
        check_food_chain=lambda req, victim: True,
        relocate_whole_block=lambda victim: False,
        evict_whole_block=lambda victim: True,
        append_log=logs.append,
    )

    assert resolved is True
    assert logs == []


def test_resolve_grandmaster_conflicts_denied_short_circuits_before_relocation():
    logs = []
    conflict = {"id": "evt1"}
    victim = {"id": "blk_1", "inst_name": "VoiceTeacher"}
    called = []

    resolved = resolve_grandmaster_conflicts(
        room_id="R1",
        req={"inst": "PianoTeacherHigh", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
        conflicts=[conflict],
        resolve_victim_block=lambda event: victim,
        check_food_chain=lambda req, victim_block: False,
        relocate_whole_block=lambda victim_block: called.append("relocate") or False,
        evict_whole_block=lambda victim_block: called.append("evict") or True,
        append_log=logs.append,
    )

    assert resolved is False
    assert called == []
    assert logs == ["      ⛔ Preemption Denied: PianoTeacherHigh cannot kick VoiceTeacher (priority rules)."]


def test_resolve_grandmaster_conflicts_relocates_then_evicts_in_order():
    logs = []
    conflicts = [{"id": "evt1"}, {"id": "evt2"}]
    victims = {
        "evt1": {"id": "blk_1", "inst_name": "Instructor Piano Low"},
        "evt2": {"id": "blk_2", "inst_name": "Instructor Piano Low"},
    }
    seen = []

    def relocate(victim_block):
        seen.append(("relocate", victim_block["id"]))
        return victim_block["id"] == "blk_1"

    def evict(victim_block):
        seen.append(("evict", victim_block["id"]))
        return True

    resolved = resolve_grandmaster_conflicts(
        room_id="R1",
        req={"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 9, "end": 11},
        conflicts=conflicts,
        resolve_victim_block=lambda event: victims[event["id"]],
        check_food_chain=lambda req, victim_block: True,
        relocate_whole_block=relocate,
        evict_whole_block=evict,
        append_log=logs.append,
    )

    assert resolved is True
    assert seen == [("relocate", "blk_1"), ("relocate", "blk_2"), ("evict", "blk_2")]
    assert logs == [
        "      🔀 Relocated BLOCK 'Instructor Piano Low' from R1.",
        "      👋 Evicted BLOCK 'Instructor Piano Low' from R1 (Yielded to higher priority).",
    ]


def test_resolve_grandmaster_conflicts_denied_for_pinned_block():
    logs = []
    conflict = {"id": "evt1"}
    victim = {
        "id": "blk_1",
        "inst_name": "Instructor Piano Low",
        "events": [{"id": "evt1", "pinned": True}],
    }
    called = []

    resolved = resolve_grandmaster_conflicts(
        room_id="R1",
        req={"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
        conflicts=[conflict],
        resolve_victim_block=lambda event: victim,
        check_food_chain=lambda req, victim_block: called.append("food") or True,
        relocate_whole_block=lambda victim_block: called.append("relocate") or False,
        evict_whole_block=lambda victim_block: called.append("evict") or True,
        append_log=logs.append,
    )

    assert resolved is False
    assert called == []
    assert logs == [
        "      ⛔ Preemption Denied: HighPriorityPiano cannot move pinned or locked block Instructor Piano Low."
    ]
