import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from optimizer_state_harness import (  # noqa: E402
    attach_tracked_block,
    make_allocator,
    make_block,
    make_studio_event,
    make_weekly_event,
)


def test_harness_attach_tracked_block_populates_assignments_blocks_and_block_map():
    allocator = make_allocator()
    evt1 = make_weekly_event("evt1", room_id="R1", day=1, start_time="09:00:00", end_time="10:00:00")
    evt2 = make_weekly_event("evt2", room_id="R1", day=1, start_time="10:00:00", end_time="11:00:00")
    block = make_block(
        "blk_1",
        [evt1, evt2],
        room_id="R1",
        priority=6,
        start=9,
        end=11,
        instrument="Piano",
        inst_name="Prof A",
    )

    attach_tracked_block(allocator, block)

    assert allocator.assignments == [evt1, evt2]
    assert allocator.blocks["blk_1"] is block
    assert allocator.block_map == {"evt1": "blk_1", "evt2": "blk_1"}
    assert evt1["extendedProps"]["block_id"] == "blk_1"
    assert evt2["extendedProps"]["block_id"] == "blk_1"


def test_harness_resolve_denied_preemption_preserves_state_and_logs_reason():
    allocator = make_allocator()
    victim = make_weekly_event(
        "evt1",
        room_id="R1",
        day=1,
        start_time="10:00:00",
        end_time="11:00:00",
        instructor="VoiceTeacher",
        normalized_instrument="Voice",
    )
    block = make_block(
        "blk_victim",
        [victim],
        room_id="R1",
        priority=6,
        start=10,
        end=11,
        instrument="Voice",
        inst_name="VoiceTeacher",
    )
    attach_tracked_block(allocator, block)

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "PianoTeacherHigh", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
    )

    assert resolved is False
    assert allocator.assignments == [victim]
    assert allocator.unassigned == []
    assert any("Preemption Denied" in line for line in allocator.logs)


def test_harness_resolve_relocation_success_moves_block_and_keeps_assignments():
    allocator = make_allocator()
    victim = make_weekly_event(
        "evt1",
        room_id="R1",
        day=1,
        start_time="10:00:00",
        end_time="11:00:00",
        instructor="Instructor Piano Low",
        normalized_instrument="Piano",
    )
    block = make_block(
        "blk_victim",
        [victim],
        room_id="R1",
        priority=4,
        start=10,
        end=11,
        instrument="Piano",
        inst_name="Instructor Piano Low",
    )
    attach_tracked_block(allocator, block)

    allocator._get_conflicting_events = lambda room_id, req: [victim]
    allocator._relocate_whole_block = lambda victim_block: (
        victim_block.update({"room_id": "R2"}),
        victim_block["events"][0].update({"resourceId": "R2", "room_id": "R2"}),
        True,
    )[-1]

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
    )

    assert resolved is True
    assert allocator.assignments[0]["resourceId"] == "R2"
    assert allocator.blocks["blk_victim"]["room_id"] == "R2"
    assert any("Relocated BLOCK" in line for line in allocator.logs)


def test_harness_get_conflicting_events_matches_weekly_same_room_overlap_only():
    allocator = make_allocator()
    hit = make_weekly_event("hit", room_id="R1", day=1, start_time="10:00:00", end_time="11:00:00")
    miss_other_room = make_weekly_event("miss_room", room_id="R2", day=1, start_time="10:00:00", end_time="11:00:00")
    miss_other_day = make_weekly_event("miss_day", room_id="R1", day=2, start_time="10:00:00", end_time="11:00:00")
    allocator.assignments = [hit, miss_other_room, miss_other_day]

    conflicts = allocator._get_conflicting_events(
        "R1",
        {"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
    )

    assert [evt["id"] for evt in conflicts] == ["hit"]


def test_harness_get_conflicting_events_matches_same_date_studio_overlap():
    allocator = make_allocator()
    studio_hit = make_studio_event("studio1", room_id="R3", date="2026-03-30", start_hour=19, end_hour=20, instructor="HighPriorityVoice")
    studio_miss = make_studio_event("studio2", room_id="R3", date="2026-03-31", start_hour=19, end_hour=20, instructor="HighPriorityVoice")
    allocator.assignments = [studio_hit, studio_miss]

    conflicts = allocator._get_conflicting_events(
        "R3",
        {"inst": "Other Voice", "instrument": "Voice", "day": 1, "start": 19, "end": 20, "date": "2026-03-30"},
    )

    assert [evt["id"] for evt in conflicts] == ["studio1"]


def test_harness_build_block_map_splits_all_events_when_block_enforcement_disabled():
    allocator = make_allocator(
        rules={
            "room_types": {},
            "constraints": {
                "enforce_instructor_blocks": False,
                "min_break_between_lessons": 60,
            },
            "instructor_priority": {"Prof A": 7},
        }
    )
    evt1 = make_weekly_event("evt1", room_id="R1", day=1, start_time="09:00:00", end_time="10:00:00", instructor="Prof A")
    evt2 = make_weekly_event("evt2", room_id="R1", day=1, start_time="10:00:00", end_time="11:00:00", instructor="Prof A")
    allocator.assignments = [evt1, evt2]

    allocator._build_block_map()

    assert len(allocator.blocks) == 2
    assert allocator.block_map["evt1"] != allocator.block_map["evt2"]


def test_harness_build_block_map_does_not_link_gaps_over_sixty_minutes():
    allocator = make_allocator(
        rules={
            "room_types": {},
            "constraints": {
                "enforce_instructor_blocks": True,
                "min_break_between_lessons": 60,
            },
            "instructor_priority": {"Prof A": 7},
        }
    )
    evt1 = make_weekly_event("evt1", room_id="R1", day=1, start_time="09:00:00", end_time="10:00:00", instructor="Prof A")
    evt2 = make_weekly_event("evt2", room_id="R1", day=1, start_time="13:00:00", end_time="14:00:00", instructor="Prof A")
    allocator.assignments = [evt1, evt2]

    allocator._build_block_map()

    assert len(allocator.blocks) == 2
    assert allocator.block_map["evt1"] != allocator.block_map["evt2"]


def test_harness_resolve_can_evict_synthetic_atomic_victim_without_tracked_block():
    allocator = make_allocator()
    victim = make_weekly_event(
        "evt1",
        room_id="R1",
        day=1,
        start_time="10:00:00",
        end_time="11:00:00",
        instructor="Instructor Piano Low",
        normalized_instrument="Piano",
    )
    allocator.assignments = [victim]
    allocator._get_conflicting_events = lambda room_id, req: [victim]
    allocator._relocate_whole_block = lambda victim_block: False

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 10, "end": 11},
    )

    assert resolved is True
    assert allocator.assignments == []
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["id"] == "evt1"
    assert allocator.unassigned[0]["reason_code"] == "preempted_by_higher_priority_block"
    assert any("Evicted BLOCK" in line for line in allocator.logs)


def test_harness_relocate_studio_block_without_resolvable_date_returns_false():
    allocator = make_allocator()
    broken_studio = {
        "id": "studio_broken",
        "resourceId": "R3",
        "room_id": "R3",
        "start": "bad-date",
        "end": "bad-date",
        "type": "studio_class",
        "extendedProps": {"Instructor": "HighPriorityVoice", "normalized_instrument": "Voice", "is_studio": True},
    }
    block = make_block(
        "blk_studio_broken",
        [broken_studio],
        room_id="R3",
        priority=9,
        start=19,
        end=20,
        instrument="Voice",
        inst_name="HighPriorityVoice",
    )

    assert allocator._relocate_whole_block(block) is False
    assert broken_studio["resourceId"] == "R3"


def test_harness_get_conflicting_events_counts_weekly_blocker_for_studio_request_same_weekday():
    allocator = make_allocator()
    weekly_hit = make_weekly_event("weekly1", room_id="R1", day=1, start_time="19:00:00", end_time="20:00:00")
    weekly_miss = make_weekly_event("weekly2", room_id="R1", day=2, start_time="19:00:00", end_time="20:00:00")
    allocator.assignments = [weekly_hit, weekly_miss]

    conflicts = allocator._get_conflicting_events(
        "R1",
        {"inst": "Other Voice", "instrument": "Voice", "day": 1, "start": 19, "end": 20, "date": "2026-03-30"},
    )

    assert [evt["id"] for evt in conflicts] == ["weekly1"]


def test_harness_resolve_processes_multiple_conflicts_in_order_and_mixes_relocate_then_evict():
    allocator = make_allocator()
    evt1 = make_weekly_event("evt1", room_id="R1", day=1, start_time="09:00:00", end_time="10:00:00", instructor="Instructor Piano Low")
    evt2 = make_weekly_event("evt2", room_id="R1", day=1, start_time="10:00:00", end_time="11:00:00", instructor="Instructor Piano Low")
    blk1 = make_block("blk_1", [evt1], room_id="R1", priority=4, start=9, end=10, instrument="Piano", inst_name="Instructor Piano Low")
    blk2 = make_block("blk_2", [evt2], room_id="R1", priority=4, start=10, end=11, instrument="Piano", inst_name="Instructor Piano Low")
    allocator.assignments = [evt1, evt2]
    allocator.blocks = {"blk_1": blk1, "blk_2": blk2}
    evt1["extendedProps"]["block_id"] = "blk_1"
    evt2["extendedProps"]["block_id"] = "blk_2"

    allocator._get_conflicting_events = lambda room_id, req: [evt1, evt2]
    seen = []

    def relocate(victim_block):
        seen.append(("relocate", victim_block["id"]))
        if victim_block["id"] == "blk_1":
            victim_block["room_id"] = "R2"
            victim_block["events"][0]["resourceId"] = "R2"
            victim_block["events"][0]["room_id"] = "R2"
            return True
        return False

    allocator._relocate_whole_block = relocate

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "HighPriorityPiano", "instrument": "Piano", "day": 1, "start": 9, "end": 11},
    )

    assert resolved is True
    assert seen == [("relocate", "blk_1"), ("relocate", "blk_2")]
    assert evt1["resourceId"] == "R2"
    assert evt2 not in allocator.assignments
    assert len(allocator.unassigned) == 1
    assert allocator.unassigned[0]["id"] == "evt2"
    assert any("Relocated BLOCK 'Instructor Piano Low' from R1." in line for line in allocator.logs)
    assert any("Evicted BLOCK 'Instructor Piano Low' from R1 (Yielded to higher priority)." in line for line in allocator.logs)


def test_harness_resolve_short_circuits_after_preemption_denied():
    allocator = make_allocator()
    evt1 = make_weekly_event("evt1", room_id="R1", day=1, start_time="09:00:00", end_time="10:00:00", instructor="VoiceTeacher", normalized_instrument="Voice")
    evt2 = make_weekly_event("evt2", room_id="R1", day=1, start_time="10:00:00", end_time="11:00:00", instructor="Instructor Piano Low", normalized_instrument="Piano")
    blk1 = make_block("blk_1", [evt1], room_id="R1", priority=6, start=9, end=10, instrument="Voice", inst_name="VoiceTeacher")
    blk2 = make_block("blk_2", [evt2], room_id="R1", priority=4, start=10, end=11, instrument="Piano", inst_name="Instructor Piano Low")
    allocator.assignments = [evt1, evt2]
    allocator.blocks = {"blk_1": blk1, "blk_2": blk2}
    evt1["extendedProps"]["block_id"] = "blk_1"
    evt2["extendedProps"]["block_id"] = "blk_2"

    allocator._get_conflicting_events = lambda room_id, req: [evt1, evt2]
    called = []
    allocator._relocate_whole_block = lambda victim_block: called.append(victim_block["id"]) or False

    resolved = allocator._resolve_with_grandmaster_logic(
        "R1",
        {"inst": "PianoTeacherHigh", "instrument": "Piano", "day": 1, "start": 9, "end": 11},
    )

    assert resolved is False
    assert called == []
    assert allocator.assignments == [evt1, evt2]
    assert allocator.unassigned == []
    assert any("Preemption Denied" in line for line in allocator.logs)


def test_harness_evict_whole_block_preserves_weekly_day_and_studio_defaults():
    allocator = make_allocator()
    weekly_evt = make_weekly_event(
        "weekly_evt",
        room_id="R1",
        day=3,
        start_time="13:00:00",
        end_time="14:00:00",
        instructor="Instructor Piano Low",
        extra_props={"Student Name": "Weekly Student 0001"},
    )
    studio_evt = make_studio_event(
        "studio_evt",
        room_id="R3",
        date="2026-03-30",
        start_hour=19,
        end_hour=20,
        instructor="HighPriorityVoice",
        extra_props={"Student Name": "Studio Student 0002"},
    )
    block = make_block(
        "blk_mix",
        [weekly_evt, studio_evt],
        room_id="R1",
        priority=9,
        start=13,
        end=20,
        instrument="Voice",
        inst_name="HighPriorityVoice",
    )
    allocator.assignments = [weekly_evt, studio_evt]
    allocator.blocks = {"blk_mix": block}

    allocator._evict_whole_block(block)

    assert allocator.assignments == []
    assert len(allocator.unassigned) == 2
    weekly_unassigned = next(item for item in allocator.unassigned if item["id"] == "weekly_evt")
    studio_unassigned = next(item for item in allocator.unassigned if item["id"] == "studio_evt")
    assert weekly_unassigned["day"] == 3
    assert weekly_unassigned["start"] == 13
    assert weekly_unassigned["end"] == 14
    assert studio_unassigned["day"] == 0
    assert studio_unassigned["start"] == 19
    assert studio_unassigned["end"] == 20
    assert weekly_unassigned["reason_code"] == "preempted_by_higher_priority_block"
    assert studio_unassigned["reason_code"] == "preempted_by_higher_priority_block"
