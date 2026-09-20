from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.optimizer_preemption_eviction import block_is_protected


def relocate_whole_block(
    *,
    block,
    room_ids,
    can_assign,
    score_room,
    event_specific_date,
    to_js_weekday,
    logger=None,
):
    """Relocate only when one candidate room fits every event in the block."""
    events = list(block.get("events") or [])
    if not events or block_is_protected(block):
        return False

    candidates = []
    exclude_ids = [event.get("id") for event in events]
    for room_id in room_ids:
        if room_id == block["room_id"]:
            continue

        aggregate_score = 0
        possible = True
        for event in events:
            event_date = (
                event_specific_date(event)
                if event_specific_date
                else TimeParser.event_specific_date(event)
            )
            event_days = event.get("daysOfWeek") or []
            if event_days:
                day = event_days[0]
                specific_date = None
            elif event_date:
                day = (
                    to_js_weekday(event_date, default=None)
                    if to_js_weekday
                    else TimeParser.to_js_weekday(event_date, default=None)
                )
                specific_date = event_date
            else:
                possible = False
                if logger:
                    logger.warning(
                        "_relocate_whole_block: event missing resolvable day/date, skipping"
                    )
                break

            start_minute, end_minute = TimeParser.event_to_minute_range(
                event,
                default=None,
            )
            if start_minute is None or end_minute is None:
                possible = False
                break
            interval = TimeParser.canonical_course_occupancy(start_minute, end_minute)
            if day is None or interval is None:
                possible = False
                break
            start_h = interval[0] // 60
            end_h = interval[1] // 60
            try:
                fits = can_assign(
                    room_id,
                    day,
                    start_h,
                    end_h,
                    specific_date=specific_date,
                    exclude_ids=exclude_ids,
                )
            except TypeError:
                # Compatibility for small direct helper probes using the old
                # callback signature; the production allocator supports IDs.
                fits = can_assign(
                    room_id,
                    day,
                    start_h,
                    end_h,
                    specific_date=specific_date,
                )
            if not fits:
                possible = False
                break

            props = event.get("extendedProps", {})
            request = {
                "inst": block["inst_name"],
                "instrument": props.get(
                    "normalized_instrument",
                    block["instrument"],
                ),
                "raw_row": props,
                "prefs": props.get("original_prefs", []),
            }
            score = score_room(room_id, request)
            if score <= 0:
                possible = False
                break
            aggregate_score += score

        if possible:
            candidates.append((aggregate_score, room_id))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return False

    new_room = candidates[0][1]
    for event in events:
        event["resourceId"] = new_room
        event["room_id"] = new_room
    block["room_id"] = new_room
    return True
