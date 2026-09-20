from modules.shared.time_parser import TimeParser


def get_conflicting_events(
    *,
    assignments,
    room_id,
    req,
    parse_event_times,
    is_time_overlap,
):
    conflicts = []
    day_idx = req["day"]
    specific_date = req.get("date")
    start_min = req["start"] * 60
    end_min = req["end"] * 60

    for event in assignments:
        event_room_id = event.get("resourceId", event.get("room_id"))
        if event_room_id != room_id:
            continue

        is_conflict = False
        if "daysOfWeek" in event:
            if day_idx in event["daysOfWeek"]:
                event_start, event_end = parse_event_times(event)
                if is_time_overlap(start_min, end_min, event_start, event_end):
                    is_conflict = True
        elif specific_date:
            event_date = TimeParser.event_specific_date(event)
            if event_date == specific_date:
                event_start, event_end = parse_event_times(event)
                if is_time_overlap(start_min, end_min, event_start, event_end):
                    is_conflict = True
            elif event_date:
                event_day = TimeParser.to_js_weekday(event_date, default=None)
                target_day = TimeParser.to_js_weekday(specific_date, default=None)
                if event_day == target_day:
                    event_start, event_end = parse_event_times(event)
                    if is_time_overlap(start_min, end_min, event_start, event_end):
                        is_conflict = True
        else:
            event_date = TimeParser.event_specific_date(event)
            event_day = TimeParser.to_js_weekday(event_date, default=None)
            if event_day == day_idx:
                event_start, event_end = parse_event_times(event)
                if is_time_overlap(start_min, end_min, event_start, event_end):
                    is_conflict = True

        if is_conflict:
            conflicts.append(event)

    return conflicts
