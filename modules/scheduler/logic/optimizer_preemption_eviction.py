def event_is_protected(event):
    if not isinstance(event, dict):
        return False
    props = event.get("extendedProps")
    sources = [event]
    if isinstance(props, dict):
        sources.append(props)
    for source in sources:
        if source.get("pinned") is True:
            return True
        if source.get("locked") is True:
            return True
        if source.get("committed") is True:
            return True
        if source.get("is_locked_lecture") is True:
            return True
    return False


def block_is_protected(block):
    return any(event_is_protected(event) for event in (block or {}).get("events") or [])


def evict_whole_block(
    *,
    block,
    assignments,
    blocks,
    parse_event_times,
    append_unassigned,
    preempted_reason,
    preempted_reason_code,
):
    if block_is_protected(block):
        return False

    is_tracked_block = block["id"] in blocks

    for event in block["events"]:
        if event in assignments:
            assignments.remove(event)

        start_min, end_min = parse_event_times(event)
        day_val = event.get("daysOfWeek", [0])[0] if "daysOfWeek" in event else 0
        props = event.get("extendedProps") or {}
        unassigned_lesson = {
            "id": event["id"],
            "source_request_id": event.get("source_request_id") or props.get("source_request_id"),
            "inst": block["inst_name"],
            "start": int(start_min / 60),
            "end": int(end_min / 60),
            "day": day_val,
            "instrument": block["instrument"],
            "raw_row": props,
        }
        append_unassigned(
            unassigned_lesson,
            preempted_reason,
            preempted_reason_code,
        )

    if is_tracked_block:
        del blocks[block["id"]]

    return True
