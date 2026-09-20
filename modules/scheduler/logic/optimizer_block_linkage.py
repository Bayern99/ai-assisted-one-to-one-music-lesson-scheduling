from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.optimizer_normalization import WEEKLY_GROUP_MAX_GAP_MINUTES
from modules.scheduler.logic.rules_schema import DEFAULT_INSTRUCTOR_PRIORITY


def _event_interval(event):
    start, end = TimeParser.event_clock_pair(event, default=(None, None))
    return TimeParser.canonical_course_occupancy(
        TimeParser.to_minutes(start, default=None),
        TimeParser.to_minutes(end, default=None),
    )


def register_block_groups(
    *,
    block_map,
    blocks,
    block_id,
    events,
    rules,
    normalize_instrument_type,
):
    if not events:
        return block_map, blocks

    room_groups = []
    current_group = [events[0]]
    current_room = events[0].get("resourceId")

    for event in events[1:]:
        room_id = event.get("resourceId")
        if room_id == current_room:
            current_group.append(event)
            continue
        room_groups.append(current_group)
        current_group = [event]
        current_room = room_id
    room_groups.append(current_group)

    for idx, group in enumerate(room_groups):
        real_block_id = f"{block_id}_r{idx}"

        first_props = group[0].setdefault("extendedProps", {})
        instructor = first_props.get("Instructor")
        priority = rules.get("instructor_priority", {}).get(
            instructor,
            DEFAULT_INSTRUCTOR_PRIORITY,
        )

        instrument = "Instrumental"
        raw_instrument = first_props.get("normalized_instrument", "")
        if raw_instrument:
            instrument = normalize_instrument_type(raw_instrument)

        first_interval = _event_interval(group[0])
        last_interval = _event_interval(group[-1])
        blocks[real_block_id] = {
            "id": real_block_id,
            "events": group,
            "room_id": group[0].get("resourceId"),
            "priority": priority,
            "start": first_interval[0] // 60 if first_interval else 0,
            "end": last_interval[1] // 60 if last_interval else 0,
            "instrument": instrument,
            "inst_name": instructor,
        }

        for event in group:
            event.setdefault("extendedProps", {})
            event["extendedProps"]["block_id"] = real_block_id
            block_map[event["id"]] = real_block_id

    return block_map, blocks


def build_block_linkage_map(
    *,
    assignments,
    rules,
    time_str_to_minutes,
    normalize_instrument_type,
):
    block_map = {}
    blocks = {}

    grouped = {}
    for event in assignments:
        if event.get("extendedProps", {}).get("is_studio"):
            continue

        raw = event.get("extendedProps", {})
        instructor = raw.get("Instructor", "Unknown")
        days = event.get("daysOfWeek", [])
        day = days[0] if days else -1
        grouped.setdefault((instructor, day), []).append(event)

    block_idx = 0
    constraints = rules.get("constraints", {})
    enforce = constraints.get("enforce_instructor_blocks", True)

    for (instructor, day), events in grouped.items():
        events.sort(key=lambda event: TimeParser.extract_start_hour(event.get("startTime"), default=0))
        if not events:
            continue

        current_block_id = f"blk_{instructor}_{day}_{block_idx}"
        block_idx += 1
        current_events = [events[0]]

        for idx in range(1, len(events)):
            prev = events[idx - 1]
            curr = events[idx]
            prev_interval = _event_interval(prev)
            curr_interval = _event_interval(curr)
            if prev_interval is None or curr_interval is None:
                gap_min = None
            else:
                prev_end_min = prev_interval[1]
                curr_start_min = curr_interval[0]
                gap_min = curr_start_min - prev_end_min

            if (
                enforce
                and gap_min is not None
                and 0 <= gap_min <= WEEKLY_GROUP_MAX_GAP_MINUTES
            ):
                current_events.append(curr)
                continue

            block_map, blocks = register_block_groups(
                block_map=block_map,
                blocks=blocks,
                block_id=current_block_id,
                events=current_events,
                rules=rules,
                normalize_instrument_type=normalize_instrument_type,
            )
            current_block_id = f"blk_{instructor}_{day}_{block_idx}"
            block_idx += 1
            current_events = [curr]

        block_map, blocks = register_block_groups(
            block_map=block_map,
            blocks=blocks,
            block_id=current_block_id,
            events=current_events,
            rules=rules,
            normalize_instrument_type=normalize_instrument_type,
        )

    return block_map, blocks
