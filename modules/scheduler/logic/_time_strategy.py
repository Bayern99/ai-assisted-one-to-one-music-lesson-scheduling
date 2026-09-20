"""Time-application strategies for scheduler slot mutations."""

from modules.shared.time_parser import TimeParser


def uses_recurring_time_fields(slot, specific_date=None):
    slot_type = slot.get('type')
    return slot_type == 'weekly_lesson' or (slot_type == 'studio_class' and not specific_date)


def apply_time_to_slot(slot, new_day_idx, start_norm, end_norm, specific_date=None):
    """Apply normalized time/duration to a slot based on its type."""
    normalized_range = TimeParser.canonical_course_occupancy(
        TimeParser.to_minutes(start_norm, default=None),
        TimeParser.to_minutes(end_norm, default=None),
    )
    if normalized_range is None:
        raise ValueError("Invalid hour-grid interval")
    start_norm, end_norm = TimeParser.minute_range_to_clocks(*normalized_range)
    sh, sm = map(int, start_norm.split(':'))
    eh, em = map(int, end_norm.split(':'))

    slot_type = slot.get('type')
    if uses_recurring_time_fields(slot, specific_date):
        slot['startTime'] = f"{sh:02d}:{sm:02d}:00"
        slot['endTime'] = f"{eh:02d}:{em:02d}:00"
        slot['daysOfWeek'] = [new_day_idx]
    elif slot_type == 'studio_class' and specific_date:
        interval = TimeParser.date_clock_interval(specific_date, start_norm, end_norm)
        if interval is None:
            raise ValueError("Invalid dated studio interval")
        start_dt, end_dt = interval
        slot['start'] = start_dt.isoformat()
        slot['end'] = end_dt.isoformat()
