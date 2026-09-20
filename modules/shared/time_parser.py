import re
from datetime import date as dt_date, datetime as dt_datetime, timedelta


class TimeParser:
    CLOCK_RE = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?")
    ISO_DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")

    @classmethod
    def _extract_clock_fragment(cls, value, prefer_end=False):
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        if "T" in text:
            text = text.split("T", 1)[1]

        if "-" in text:
            parts = [part.strip() for part in text.split("-", 1)]
            text = parts[1] if prefer_end and len(parts) > 1 else parts[0]

        match = cls.CLOCK_RE.search(text)
        if not match:
            return None
        return match.group(0)

    @classmethod
    def normalize_clock(cls, value, prefer_end=False, allow_midnight=False):
        fragment = cls._extract_clock_fragment(value, prefer_end=prefer_end)
        if not fragment:
            return None

        match = cls.CLOCK_RE.match(fragment)
        if not match:
            return None

        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if allow_midnight and hour == 24 and minute == 0:
            return "24:00"
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return f"{hour:02d}:{minute:02d}"

    @classmethod
    def to_minutes(cls, value, default=0, prefer_end=False):
        normalized = cls.normalize_clock(value, prefer_end=prefer_end)
        if normalized is None:
            if re.fullmatch(r"24:00(?::00)?", str(value or "").strip()):
                return 24 * 60
            return default
        hour_str, minute_str = normalized.split(":")
        return int(hour_str) * 60 + int(minute_str)

    @classmethod
    def normalize_hour_interval(cls, start_value, end_value):
        """Expand a booking interval outward to the school hour grid.

        Requests shorter than one hour keep their requested start and expand
        only their end. Requests lasting an hour or longer reserve every
        touched school hour: 09:30-10:30 becomes 09:00-11:00 while
        09:30-09:45 becomes 09:30-10:00.
        """
        start_clock = cls.normalize_clock(start_value)
        end_clock = cls.normalize_clock(end_value, allow_midnight=True)
        if not start_clock or not end_clock:
            return None

        start_minute = cls.to_minutes(start_clock, default=None)
        end_minute = cls.to_minutes(end_clock, default=None)
        if start_minute is None or end_minute is None or end_minute <= start_minute:
            return None

        normalized_start = (
            start_minute
            if end_minute - start_minute < 60
            else (start_minute // 60) * 60
        )
        normalized_end = ((end_minute + 59) // 60) * 60
        return normalized_start, normalized_end

    @classmethod
    def normalize_hour_range(cls, value):
        """Parse and expand a ``HH:MM-HH:MM`` source value."""
        start_clock, end_clock = cls.parse_time_range(value)
        interval = cls.normalize_hour_interval(start_clock, end_clock)
        if interval is None:
            return None
        return cls.minute_range_to_clocks(*interval)

    @classmethod
    def course_request_interval(cls, value, end_value=None):
        """Parse one PI course request without changing its requested bounds.

        PI source requests are exactly one hour and may start only on the hour
        or half-hour.  The generic hour-grid normalizer remains available for
        non-course consumers; scheduler source paths use this strict contract.
        """
        if end_value is None:
            text = str(value or "").strip()
            if not re.fullmatch(
                r"\d{1,2}:\d{2}(?::\d{2})?\s*-\s*\d{1,2}:\d{2}(?::\d{2})?",
                text,
            ):
                return None
            start_clock, end_clock = cls.parse_time_range(value)
        else:
            if not re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", str(value or "").strip()):
                return None
            if not re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", str(end_value or "").strip()):
                return None
            start_clock = cls.normalize_clock(value)
            end_clock = cls.normalize_clock(
                end_value,
                prefer_end=True,
                allow_midnight=True,
            )
        if not start_clock or not end_clock:
            return None

        start_minute = cls.to_minutes(start_clock, default=None)
        end_minute = cls.to_minutes(end_clock, default=None)
        if start_minute is None or end_minute is None:
            return None
        if end_minute <= start_minute or end_minute - start_minute != 60:
            return None
        if start_minute % 30 or end_minute % 30:
            return None
        if start_minute % 60 != end_minute % 60:
            return None
        return start_minute, end_minute

    @classmethod
    def normalize_course_interval(cls, value, end_value=None):
        """Convert one valid course request to its final occupancy interval."""
        interval = cls.course_request_interval(value, end_value=end_value)
        if interval is None:
            return None
        start_minute, end_minute = interval
        if start_minute % 60 == 0:
            return interval
        return start_minute - 30, end_minute + 30

    @classmethod
    def normalize_course_range(cls, value):
        interval = cls.normalize_course_interval(value)
        if interval is None:
            return None
        return cls.minute_range_to_clocks(*interval)

    LECTURE_EVENT_TYPES = frozenset(
        {"lecture", "academic_lecture", "locked_lecture"}
    )

    @classmethod
    def board_event_occupancy(cls, event):
        """Return minute occupancy for an on-board booking event.

        Lecture types honour a legal ``0 <= start < end <= 1440`` range.
        Other types use canonical PI course occupancy (60/120 minutes).
        """
        if not isinstance(event, dict):
            return None

        start_minute, end_minute = cls.event_to_minute_range(event, default=None)
        if start_minute is None or end_minute is None:
            return None

        event_type = str(event.get("type") or "").strip().lower()
        if event_type in cls.LECTURE_EVENT_TYPES:
            if (
                isinstance(start_minute, int)
                and not isinstance(start_minute, bool)
                and isinstance(end_minute, int)
                and not isinstance(end_minute, bool)
                and 0 <= start_minute < end_minute <= 24 * 60
            ):
                return start_minute, end_minute
            return None

        return cls.canonical_course_occupancy(start_minute, end_minute)

    @classmethod
    def canonical_course_occupancy(cls, start_minute, end_minute):
        """Validate a persisted final occupancy without re-normalizing it."""
        if (
            not isinstance(start_minute, int)
            or isinstance(start_minute, bool)
            or not isinstance(end_minute, int)
            or isinstance(end_minute, bool)
            or start_minute < 0
            or end_minute > 24 * 60
            or end_minute <= start_minute
            or start_minute % 60
            or end_minute % 60
            or end_minute - start_minute not in (60, 120)
        ):
            return None
        return start_minute, end_minute

    @classmethod
    def course_proposal_from_occupancy(cls, start_minute, end_minute):
        """Return the editable one-hour request represented by final occupancy."""
        interval = cls.canonical_course_occupancy(start_minute, end_minute)
        if interval is None:
            return None
        start, end = interval
        if end - start == 120:
            start += 30
            end -= 30
        return cls.minute_range_to_clocks(start, end)

    @staticmethod
    def minute_to_clock(minutes):
        if minutes is None or not isinstance(minutes, int) or not 0 <= minutes <= 24 * 60:
            return None
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    @classmethod
    def minute_range_to_clocks(cls, start_minute, end_minute):
        start_clock = cls.minute_to_clock(start_minute)
        end_clock = cls.minute_to_clock(end_minute)
        if not start_clock or not end_clock or end_minute <= start_minute:
            return None
        return start_clock, end_clock

    @classmethod
    def extract_iso_date(cls, value):
        if value is None:
            return None
        if isinstance(value, dt_datetime):
            return value.date().isoformat()
        if isinstance(value, dt_date):
            return value.isoformat()

        text = str(value).strip()
        if not text:
            return None

        match = cls.ISO_DATE_RE.search(text)
        if not match:
            return None
        return match.group("date")

    @classmethod
    def parse_date(cls, value):
        iso_date = cls.extract_iso_date(value)
        if not iso_date:
            return None
        try:
            return dt_date.fromisoformat(iso_date)
        except ValueError:
            return None

    @classmethod
    def to_python_weekday(cls, value, default=0):
        parsed = cls.parse_date(value)
        if parsed is None:
            return default
        return parsed.weekday()

    @classmethod
    def to_js_weekday(cls, value, default=0):
        py_weekday = cls.to_python_weekday(value, default=None)
        if py_weekday is None:
            return default
        return (py_weekday + 1) % 7

    @classmethod
    def parse_time_range(cls, value):
        if value is None:
            return None, None

        text = str(value).strip()
        if "-" not in text:
            normalized = cls.normalize_clock(text)
            return normalized, normalized

        start = cls.normalize_clock(text, prefer_end=False)
        end = cls.normalize_clock(text, prefer_end=True, allow_midnight=True)
        return start, end

    @classmethod
    def date_clock_interval(cls, date_value, start_value, end_value):
        """Build a concrete date interval, rolling a strictly earlier end to tomorrow."""
        parsed_date = cls.parse_date(date_value)
        start_clock = cls.normalize_clock(start_value)
        end_clock = cls.normalize_clock(end_value, allow_midnight=True)
        if parsed_date is None or start_clock is None or end_clock is None:
            return None

        start_hour, start_minute = (int(part) for part in start_clock.split(":"))
        end_hour, end_minute = (int(part) for part in end_clock.split(":"))
        start_dt = dt_datetime.combine(parsed_date, dt_datetime.min.time()).replace(
            hour=start_hour,
            minute=start_minute,
        )
        if end_clock == "24:00":
            end_dt = dt_datetime.combine(parsed_date + timedelta(days=1), dt_datetime.min.time())
        else:
            end_dt = dt_datetime.combine(parsed_date, dt_datetime.min.time()).replace(
                hour=end_hour,
                minute=end_minute,
            )
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        return start_dt, end_dt

    @classmethod
    def event_datetime_pair(cls, event):
        if not isinstance(event, dict):
            return None
        start_value = event.get("start")
        end_value = event.get("end")
        if not cls.extract_iso_date(start_value) or not cls.extract_iso_date(end_value):
            return None
        try:
            return (
                dt_datetime.fromisoformat(str(start_value).replace("Z", "+00:00")),
                dt_datetime.fromisoformat(str(end_value).replace("Z", "+00:00")),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def event_specific_date(cls, event):
        if not isinstance(event, dict):
            return None

        iso_date = cls.extract_iso_date(event.get("start"))
        if iso_date:
            return iso_date

        props = event.get("extendedProps", {})
        if isinstance(props, dict):
            return cls.extract_iso_date(props.get("date"))
        return None

    @classmethod
    def event_clock_pair(cls, event, default=(None, None)):
        if not isinstance(event, dict):
            return default

        start_clock = cls.normalize_clock(event.get("startTime"))
        end_clock = cls.normalize_clock(event.get("endTime"), allow_midnight=True)
        if start_clock or end_clock:
            return start_clock, end_clock

        start_clock = cls.normalize_clock(event.get("start"))
        end_clock = cls.normalize_clock(event.get("end"), allow_midnight=True)
        if start_clock or end_clock:
            return start_clock, end_clock

        props = event.get("extendedProps", {})
        if isinstance(props, dict):
            class_time = props.get("Class Time") or props.get("class_time")
            if class_time:
                return cls.parse_time_range(class_time)

        return default

    @classmethod
    def event_primary_js_day(cls, event, default=None):
        if not isinstance(event, dict):
            return default

        days = event.get("daysOfWeek")
        if isinstance(days, list) and days:
            return days[0]

        return cls.to_js_weekday(cls.event_specific_date(event), default=default)

    @classmethod
    def extract_start_hour(cls, value, default=0):
        minutes = cls.to_minutes(value, default=None)
        if minutes is None:
            return default
        return minutes // 60

    @classmethod
    def extract_end_hour(cls, value, default=0):
        minutes = cls.to_minutes(value, default=None, prefer_end=True)
        if minutes is None:
            return default
        return minutes // 60

    @classmethod
    def event_to_minute_range(cls, event, default=0):
        if not isinstance(event, dict):
            return default, default

        datetime_pair = cls.event_datetime_pair(event)
        if datetime_pair:
            start_dt, end_dt = datetime_pair
            try:
                duration = int((end_dt - start_dt).total_seconds() / 60)
                if duration > 0:
                    start_minute = start_dt.hour * 60 + start_dt.minute
                    return start_minute, start_minute + duration
            except TypeError:
                pass

        start_clock, end_clock = cls.event_clock_pair(event, default=(None, None))
        if start_clock or end_clock:
            start_minute = cls.to_minutes(start_clock, default=default)
            end_minute = cls.to_minutes(end_clock, default=default)
            if (
                start_minute is not None
                and end_minute is not None
                and end_minute < start_minute
            ):
                end_minute += 24 * 60
            return start_minute, end_minute

        return default, default

    @classmethod
    def event_duration_minutes(cls, event, default=60):
        if not isinstance(event, dict):
            return default

        datetime_pair = cls.event_datetime_pair(event)
        if datetime_pair:
            start_dt, end_dt = datetime_pair
            try:
                duration = int((end_dt - start_dt).total_seconds() / 60)
                if duration > 0:
                    return duration
            except TypeError:
                pass

        start_min, end_min = cls.event_to_minute_range(event, default=None)
        if start_min is not None and end_min is not None and end_min > start_min:
            return end_min - start_min
        return default
