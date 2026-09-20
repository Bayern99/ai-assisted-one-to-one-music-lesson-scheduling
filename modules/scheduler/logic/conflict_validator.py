from datetime import timedelta

from modules.scheduler.logic.room_location import build_room_profile_map
from modules.shared.time_parser import TimeParser

class ConflictValidator:
    """
    Safety gate for Manual Overrides.
    Validates rules, room types, and time conflicts before allowing a move.
    """
    def __init__(self, scheduler_data):
        """
        :param scheduler_data: Dict with 'assignments', 'lectures', 'rules'
        """
        self.assignments = scheduler_data.get('assignments', [])
        self.lectures = scheduler_data.get('lectures', [])
        self.rules = scheduler_data.get('rules', {})
        self.rooms = scheduler_data.get("rooms", [])
        self.room_profiles = build_room_profile_map(self.rooms, self.rules)
        self.room_types = {
            room_id: list(profile.get("effective_types", []))
            for room_id, profile in self.room_profiles.items()
        }

    def check_conflict(self, room_id, day_idx, start_min, end_min, specific_date=None, exclude_instructor=None, exclude_id=None):
        """
        Return the first conflicting event/lecture, or None if valid.
        
        :param room_id: Target Room
        :param day_idx: 0=Mon, 6=Sun
        :param start_min: Minutes from midnight (e.g. 840 for 14:00)
        :param end_min: Minutes from midnight
        :param specific_date: String 'YYYY-MM-DD' (Optional, for Studio overrides)
        :param exclude_id: Event id to skip (the event being moved must not conflict with itself)
        """
        if start_min is None or end_min is None or end_min <= start_min:
            return {
                "is_malformed_time": True,
                "title": "Candidate",
                "id": "candidate",
            }

        # 1. Check Locked Lectures (Highest Priority)
        for lec in self.lectures:
            # Check Room
            if lec.get('resourceId') != room_id: continue
            
            # Check Day (Weekly)
            if specific_date:
                relevant, malformed, overlaps = self._specific_date_overlap(
                    lec,
                    specific_date,
                    start_min,
                    end_min,
                )
                if not relevant:
                    continue
                if malformed:
                    return {
                        'is_locked_lecture': True,
                        'is_malformed_time': True,
                        'title': lec.get('title', 'Lecture'),
                        'id': lec.get('id'),
                    }
                if overlaps:
                    return {'is_locked_lecture': True, 'title': lec.get('title', 'Lecture')}
                continue
            else:
                lec_days = lec.get('daysOfWeek', [])
                if day_idx not in lec_days: continue

            # Check Time
            s, e = self._parse_time(lec)
            if s is None or e is None:
                return {
                    'is_locked_lecture': True,
                    'is_malformed_time': True,
                    'title': lec.get('title', 'Lecture'),
                    'id': lec.get('id'),
                }
            if self._is_overlap(start_min, end_min, s, e):
                return {'is_locked_lecture': True, 'title': lec.get('title', 'Lecture')}

        # 2. Check Existing Assignments
        for evt in self.assignments:
            # Check Room
            if evt.get('resourceId') != room_id: continue

            # Skip the event being moved: it cannot conflict with itself
            if exclude_id and evt.get('id') == exclude_id:
                continue
            
            # Check Conflict
            is_conflict = False
            
            # A. Target is Weekly (No specific date)
            if not specific_date:
                # Check Weekly vs Weekly
                if 'daysOfWeek' in evt:
                    if day_idx in evt['daysOfWeek']:
                        s, e = self._parse_time(evt)
                        if s is None or e is None:
                            malformed = dict(evt)
                            malformed["is_malformed_time"] = True
                            return malformed
                        if self._is_overlap(start_min, end_min, s, e): is_conflict = True
                else:
                    event_date = TimeParser.event_specific_date(evt)
                    event_day = TimeParser.to_js_weekday(event_date, default=None)
                    if event_day == day_idx:
                        s, e = self._parse_time(evt)
                        if s is None or e is None:
                            malformed = dict(evt)
                            malformed["is_malformed_time"] = True
                            return malformed
                        if self._is_overlap(start_min, end_min, s, e):
                            is_conflict = True
            
            # B. Target is Studio (Has specific date)
            else:
                relevant, malformed_time, is_conflict = self._specific_date_overlap(
                    evt,
                    specific_date,
                    start_min,
                    end_min,
                )
                if relevant and malformed_time:
                    malformed = dict(evt)
                    malformed["is_malformed_time"] = True
                    return malformed
            
            if is_conflict:
                return evt
                
        return None

    def validate_rules(self, room_id, instrument):
        """
        Check if instrument facilitates constraints for room.
        """
        # Normalize
        inst_type = self._normalize_instrument(instrument)
        
        # Get Allowed Types for Room
        profile = self.room_profiles.get(room_id)
        if profile is None:
            return {"allowed": True}

        allowed = self.room_types.get(room_id, [])
        if not allowed:
            return {
                "allowed": False,
                "reason": f"Room Type Mismatch. {room_id} has no compatible room types configured.",
            }
            
        # Check
        # allowed might be list of strings ["Piano", "Voice"]
        # or dict? Based on rules.json: "R101": ["Piano"]
        if inst_type not in allowed:
            # RELAXATION [2026-02-12]: Allow 'Instrumental' (Generic) in Piano/Voice rooms
            # This handles "Demo Instruction" or "Unknown" codes during Manual Override.
            raw_inst = str(instrument).strip().lower()
            generic_labels = {
                "", "instrumental", "general", "unknown", "n/a", "na",
                "demo instruction", "demo lesson"
            }
            if (
                inst_type == 'Instrumental'
                and raw_inst in generic_labels
                and ('Piano' in allowed or 'Voice' in allowed)
            ):
                return {"allowed": True}
                
            return {
                "allowed": False, 
                "reason": f"Room Type Mismatch. {room_id} allows {allowed}, but instrument is {inst_type}."
            }
            
        return {"allowed": True}

    def within_time_range(self, start_min, end_min):
        constraints = self.rules.get("constraints", {})
        time_range = constraints.get("time_range", {})
        if not isinstance(time_range, dict):
            return True
        if not time_range:
            return True
        lower = TimeParser.to_minutes(time_range.get("start"), default=None)
        upper = TimeParser.to_minutes(time_range.get("end"), default=None)
        return (
            lower is not None
            and upper is not None
            and lower <= start_min
            and end_min <= upper
        )

    def _parse_time(self, evt):
        return TimeParser.board_event_occupancy(evt) or (None, None)

    def _get_event_date(self, evt):
        return TimeParser.event_specific_date(evt)

    def _specific_date_overlap(self, event, specific_date, start_min, end_min):
        """Compare a concrete target interval with recurring or dated events."""
        base_date = TimeParser.parse_date(specific_date)
        if base_date is None:
            return False, False, False

        event_days = event.get('daysOfWeek')
        first_target_day = start_min // 1440
        last_target_day = max(first_target_day, (max(start_min, end_min - 1)) // 1440)
        if isinstance(event_days, list):
            offsets = [
                offset
                for offset in range(first_target_day - 1, last_target_day + 1)
                if TimeParser.to_js_weekday(
                    base_date + timedelta(days=offset),
                    default=None,
                ) in event_days
            ]
        else:
            event_start_date = (
                TimeParser.parse_date(event.get('start'))
                or TimeParser.parse_date(self._get_event_date(event))
            )
            event_end_date = TimeParser.parse_date(event.get('end')) or event_start_date
            target_start_date = base_date + timedelta(days=first_target_day)
            target_end_date = base_date + timedelta(days=last_target_day)
            relevant = bool(
                event_start_date
                and event_end_date
                and event_start_date <= target_end_date
                and event_end_date >= target_start_date
            )
            offsets = [] if not relevant else [(event_start_date - base_date).days]

        if not offsets:
            return False, False, False
        event_start, event_end = self._parse_time(event)
        if event_start is None or event_end is None:
            return True, True, False
        overlaps = any(
            self._is_overlap(
                start_min,
                end_min,
                event_start + offset * 1440,
                event_end + offset * 1440,
            )
            for offset in offsets
        )
        return True, False, overlaps

    def _is_overlap(self, s1, e1, s2, e2):
        return max(s1, s2) < min(e1, e2)

    def _normalize_instrument(self, inst):
        if not isinstance(inst, str):
            return 'Instrumental'
        # Simple mapping
        inst = inst.lower()
        if 'piano' in inst: return 'Piano'
        if 'voice' in inst or 'soprano' in inst: return 'Voice'
        if 'percussion' in inst: return 'Percussion'
        return 'Instrumental' # Default
