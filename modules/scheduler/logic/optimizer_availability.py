"""Availability helpers extracted from optimizer.py.

These helpers are intentionally behavior-preserving. They keep booking conflict
evaluation separate from optimizer orchestration without changing room policy.
"""

from modules.shared.time_parser import TimeParser


def is_time_overlap(t1_start, t1_end, t2_start, t2_end):
    return (t1_start < t2_end) and (t1_end > t2_start)


def can_assign_against_bookings(
    bookings,
    room_id,
    day_idx,
    start_h,
    end_h,
    specific_date=None,
    instructor_id=None,
    exclude_ids=None,
    parse_event_times=None,
    logger=None,
):
    if parse_event_times is None:
        raise ValueError("parse_event_times callback is required")

    start_min = int(start_h * 60)
    end_min = int(end_h * 60)
    excluded = {str(item) for item in (exclude_ids or []) if item is not None}

    for booking in bookings:
        if booking.get("resourceId") != room_id:
            continue
        if str(booking.get("id")) in excluded:
            continue

        if specific_date is None:
            booking_date = TimeParser.event_specific_date(booking)
            if booking_date:
                booking_day = TimeParser.to_js_weekday(booking_date, default=None)
                relevant = booking_day == day_idx
            else:
                booking_days = booking.get("daysOfWeek") or []
                relevant = bool(booking_days and day_idx in booking_days)
            if relevant:
                booking_start, booking_end = parse_event_times(booking)
                if is_time_overlap(start_min, end_min, booking_start, booking_end):
                    return False
        else:
            booking_date = TimeParser.event_specific_date(booking)

            if booking_date == specific_date:
                booking_start, booking_end = parse_event_times(booking)
                if is_time_overlap(start_min, end_min, booking_start, booking_end):
                    return False

            if booking_date and specific_date and booking_date != specific_date:
                booking_dow = TimeParser.to_python_weekday(booking_date, default=None)
                target_dow = TimeParser.to_python_weekday(specific_date, default=None)
                if booking_dow is None or target_dow is None:
                    if logger is not None:
                        logger.warning("can_assign: studio date parse failed, skipping studio-vs-studio check")
                elif booking_dow == target_dow:
                    booking_start, booking_end = parse_event_times(booking)
                    if is_time_overlap(start_min, end_min, booking_start, booking_end):
                        return False

            target_js_dow = TimeParser.to_js_weekday(specific_date, default=None)
            if target_js_dow is None:
                if logger is not None:
                    logger.warning("can_assign: specific_date parse failed, skipping weekly-vs-date check")

            booking_days = booking.get("daysOfWeek")
            if booking_days and target_js_dow in booking_days:
                booking_start, booking_end = parse_event_times(booking)
                if is_time_overlap(start_min, end_min, booking_start, booking_end):
                    return False

    return True
