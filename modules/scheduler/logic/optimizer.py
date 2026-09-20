"""
Teacher-Centric Room Allocator (v6 - Unified Scheduling Architecture)
Optimizes for:
1. Teacher Continuity (Block Scheduling) - Minimize room switches
2. Functional Matching - Instrument vs Room Type
3. Preferences - Instructors' preferred venues
4. Unified Logic - Same rules for Weekly and Studio
"""
import pandas as pd
import logging

from modules.scheduler.logic.optimizer_output import (
    build_optimizer_init_lines,
    build_weekly_assignment,
)
from modules.scheduler.logic.optimizer_path import solve_fragmented_block_min_switches
from modules.scheduler.logic.optimizer_availability import (
    can_assign_against_bookings,
    is_time_overlap,
)
from modules.scheduler.logic.optimizer_normalization import (
    build_block,
    group_lessons_into_blocks,
    prepare_weekly_lessons,
)
from modules.scheduler.logic.optimizer_studio_assignment import assign_studio_requests
from modules.scheduler.logic.optimizer_weekly_phase import (
    NO_SINGLE_ROOM_FOR_GROUP,
    NO_SINGLE_ROOM_FOR_GROUP_MESSAGE,
    schedule_weekly_blocks,
)
from modules.scheduler.logic.optimizer_block_linkage import (
    build_block_linkage_map,
    register_block_groups,
)
from modules.scheduler.logic.optimizer_preemption_conflicts import (
    get_conflicting_events,
)
from modules.scheduler.logic.optimizer_preemption_relocation import (
    relocate_whole_block,
)
from modules.scheduler.logic.optimizer_preemption_eviction import (
    evict_whole_block,
)
from modules.scheduler.logic.optimizer_preemption_resolution import (
    resolve_grandmaster_conflicts,
)
from modules.scheduler.logic.optimizer_preemption_food_chain import (
    check_food_chain,
)
from modules.scheduler.logic.optimizer_scoring import (
    compatible_room_ids,
    score_room_unified,
)
from modules.scheduler.logic.optimizer_reason_routing import (
    classify_unassigned_reason,
)
from modules.scheduler.logic.optimizer_diagnostics import (
    build_room_occupant_line,
    build_studio_failure_header,
    build_studio_saturation_intro,
    build_studio_summary_line,
)
from modules.scheduler.logic.optimizer_rejections import (
    append_unassigned_entry,
    build_studio_failed_unassigned,
    build_weekly_rejection_entry,
)
from modules.scheduler.logic.optimizer_studio import prepare_studio_requests
from modules.scheduler.logic.room_location import build_room_profile_map
from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.source_requests import frame_with_source_row_indexes
from modules.scheduler.logic.rules_schema import DEFAULT_INSTRUCTOR_PRIORITY

logger = logging.getLogger(__name__)


UNASSIGNED_REASON_MESSAGES = {
    "normalization_failed": "Normalization failed",
    "missing_student_no": "Missing Student No",
    "duplicate_student": "Duplicate Student Entry",
    "missing_day_or_time": "Missing Day of Week or Class Time",
    "invalid_course_time": "Invalid course time: requests must be exactly one hour starting at :00 or :30",
    "unsupported_weekday": "Unsupported weekday",
    "invalid_studio_date": "Malformed Studio Date",
    "malformed_class_time": "Malformed Class Time",
    "invalid_preferred_venue": "Preferred venue is invalid or unavailable",
    "no_room_type_match": "No compatible room type match",
    "blocked_by_locked_context": "Blocked by locked context",
    "rule_constraint_rejection": "Rejected by scheduling rules",
    "outside_scheduling_window": "Outside the configured scheduling window",
    "no_time_feasible_room": "No feasible room-time placement",
    "preempted_by_higher_priority_block": "Evicted by higher-priority reassignment",
    NO_SINGLE_ROOM_FOR_GROUP: NO_SINGLE_ROOM_FOR_GROUP_MESSAGE,
}

class RoomAllocator:
    def __init__(self, students, rooms, existing_bookings, rules, rules_source_path=None):
        self.students = students # List of dicts
        self.rooms = rooms       # List of dicts
        self.bookings = existing_bookings # List of dicts
        self.rules = rules
        self.rules_source_path = rules_source_path
        self.assignments = []
        self.unassigned = []
        self.duplicates = [] # [NEW] Track duplicates for reporting
        self.logs = []
        self.pinned_source_ids = set()

        room_profiles = build_room_profile_map(rooms, self.rules)
        imported_room_objs = {}
        for room in rooms:
            if not isinstance(room, dict):
                continue
            room_id = str(room.get("id", "")).strip()
            if not room_id:
                continue
            imported_room_objs[room_id] = room

        self.room_types = {}
        self.room_objs = {}
        for room_id, profile in room_profiles.items():
            self.room_types[room_id] = list(profile.get("effective_types", []))
            self.room_objs[room_id] = imported_room_objs.get(room_id, {"id": room_id, "name": room_id})

        self.rooms = list(self.room_objs.values())

    # ============================
    # UNIFIED CONSTRAINT & SCORING
    # ============================
    
    def _check_global_constraints(self, start_h, end_h):
        """Phase 6: Unified Time Constraint Check"""
        constraints = self.rules.get('constraints', {})
        time_limit = constraints.get('time_range', {})
        if time_limit:
            try:
                min_h = TimeParser.extract_start_hour(time_limit.get('start', '08:00'), default=8)
                max_h = TimeParser.extract_end_hour(time_limit.get('end', '23:00'), default=23)
                # Strict check: Lesson must be fully within bounds
                if start_h < min_h or end_h > max_h:
                    return False
            except Exception:
                logger.warning("_check_global_constraints: time parse failed, skipping check", exc_info=True)
        return True

    def time_str_to_minutes(self, t_str):
        """Helper: Convert 'HH:MM:SS' or 'HH:MM' to minutes from midnight."""
        return TimeParser.to_minutes(t_str, default=0)

    def _is_time_overlap(self, t1_start, t1_end, t2_start, t2_end):
        """Helper for time overlap"""
        return is_time_overlap(t1_start, t1_end, t2_start, t2_end)

    def can_assign(
        self,
        room_id,
        day_idx,
        start_h,
        end_h,
        specific_date=None,
        instructor_id=None,
        exclude_ids=None,
    ):
        """
        Unified Availability Check (Weekly + Studio)
        
        Args:
            day_idx: 0-6 (Mon=1, Sun=0)
            start_h, end_h: Hours (e.g. 13, 14)
            specific_date: "YYYY-MM-DD" string (Optional, for Studio)
            instructor_id: Name of instructor (Optional, for Self-Healing)
        """
        # 1. Global Constraints
        if not self._check_global_constraints(start_h, end_h):
            return False

        return self._can_assign_against_bookings(
            self.bookings + self.assignments,
            room_id,
            day_idx,
            start_h,
            end_h,
            specific_date=specific_date,
            instructor_id=instructor_id,
            exclude_ids=exclude_ids,
        )

    def _can_assign_against_bookings(
        self,
        bookings,
        room_id,
        day_idx,
        start_h,
        end_h,
        specific_date=None,
        instructor_id=None,
        exclude_ids=None,
    ):
        return can_assign_against_bookings(
            bookings,
            room_id,
            day_idx,
            start_h,
            end_h,
            specific_date=specific_date,
            instructor_id=instructor_id,
            exclude_ids=exclude_ids,
            parse_event_times=self._parse_event_times,
            logger=logger,
        )

    def _compatible_room_ids(self, req):
        return compatible_room_ids(
            room_ids=self.room_objs,
            req=req,
            score_room=self._score_room_unified,
        )

    def _blocked_by_locked_context(self, req, specific_date=None):
        compatible = self._compatible_room_ids(req)
        if not compatible:
            return False

        day_idx = req.get("day", -1)
        start_h = req.get("start", 0)
        end_h = req.get("end", 0)
        instructor_id = req.get("inst")

        for room_id in compatible:
            if self._can_assign_against_bookings(
                self.bookings,
                room_id,
                day_idx,
                start_h,
                end_h,
                specific_date=specific_date,
                instructor_id=instructor_id,
            ):
                return False
        return True

    def _classify_unassigned_reason(self, req, specific_date=None):
        return classify_unassigned_reason(
            req=req,
            room_ids=self.room_objs,
            compatible_room_ids=self._compatible_room_ids,
            check_global_constraints=self._check_global_constraints,
            blocked_by_locked_context=self._blocked_by_locked_context,
            reason_messages=UNASSIGNED_REASON_MESSAGES,
            specific_date=specific_date,
        )

    def _parse_event_times(self, evt):
        """Helper to get start/end minutes from event dict (Robust)"""
        try:
            s, e = TimeParser.event_to_minute_range(evt, default=None)
            if s is not None and e is not None and 0 <= s < e <= 24 * 60:
                # Honour the real range: course events are canonical one-hour
                # slots, but locked context (e.g. 3-4h lectures) legitimately
                # spans multiple hours and must not block the whole day.
                return s, e
        except Exception:
            logger.warning("_parse_event_times: event_to_minute_range failed", exc_info=True)
        logger.warning("_parse_event_times: malformed event time payload detected: %s", evt)
        # Fail closed so malformed events block scheduling instead of becoming invisible.
        return 0, 24 * 60

    def _score_room_unified(self, room_id, req):
        """
        Unified Scoring Logic (Weekly + Studio)
        Same logic, same priority matrix.
        """
        return score_room_unified(
            room_id=room_id,
            req=req,
            room_types=self.room_types,
            rules=self.rules,
            normalize_instrument_type=self._normalize_instrument_type,
        )

    def _normalize_instrument_type(self, raw_type):
        if not isinstance(raw_type, str): return 'Instrumental'
        t = raw_type.lower()
        if 'piano' in t: return 'Piano'
        if 'voice' in t or 'vocal' in t: return 'Voice'
        if 'percussion' in t: return 'Percussion'
        return 'Instrumental'

    # ============================
    # PHASE 2: SPLICING LOGIC
    # ============================

    def _splice_into_blocks(self, weekly_df):
        """
        Convert Weekly Schedule rows into Instructor Time Blocks.
        Rule: Gap <= 60 mins -> Same Block.
        """
        raw_lessons = prepare_weekly_lessons(
            weekly_df,
            duplicate_sink=self.duplicates,
            reject_weekly=self._record_weekly_rejection,
        )
        return group_lessons_into_blocks(raw_lessons, self.rules)

    def _finalize_block(self, lessons):
        return build_block(lessons)

    def _append_unassigned(self, payload, reason, reason_code):
        return append_unassigned_entry(self.unassigned, payload, reason, reason_code)

    def _record_weekly_rejection(self, raw_row, reason, normalized=None, row_idx=None, reason_code=None):
        """
        Route rejected weekly rows into the standard unassigned channel so
        end-to-end accounting and manual follow-up stay consistent.
        """
        entry = build_weekly_rejection_entry(
            raw_row,
            reason,
            normalized=normalized,
            row_idx=row_idx,
            reason_code=reason_code,
            existing_unassigned_count=len(self.unassigned),
            warning_logger=lambda message: logger.warning(message, exc_info=True),
        )
        self.unassigned.append(entry)
        return entry

    # ============================
    # MAIN OPTIMIZER (Unified)
    # ============================
    def optimize(self, weekly_df, studio_df=None, pinned_assignments=None):
        self.logs.extend(build_optimizer_init_lines(self.rules_source_path))
        
        # 0. Load Pinned Assignments
        self.assignments = [] # Start fresh
        self.unassigned = []

        weekly_df = frame_with_source_row_indexes(weekly_df)
        studio_df = frame_with_source_row_indexes(studio_df)
        
        pinned_ids = set()
        self.pinned_source_ids = set()
        if pinned_assignments:
            for p in pinned_assignments:
                # CRITICAL: Only lock if explicitly pinned!
                if p.get('pinned'):
                    self.assignments.append(p)
                    if 'id' in p:
                        pinned_ids.add(p['id'])
                    source_id = p.get("source_request_id") or p.get(
                        "extendedProps", {}
                    ).get("source_request_id")
                    if source_id:
                        pinned_ids.add(source_id)
                        self.pinned_source_ids.add(str(source_id))
            self.logs.append(f"🔒 Locking {len(pinned_ids)} pinned assignments...")
                
        # Filter DataFrames
        if weekly_df is not None and not weekly_df.empty and pinned_assignments:
            initial_len = len(weekly_df)
            source_ids = weekly_df.apply(
                lambda row: row.get("source_request_id")
                or f"weekly:{row.get('_source_row_index', row.name)}",
                axis=1,
            )
            legacy_ids = weekly_df.get("id", pd.Series(index=weekly_df.index, dtype=object))
            weekly_df = weekly_df[~source_ids.isin(pinned_ids) & ~legacy_ids.isin(pinned_ids)]
            skipped = initial_len - len(weekly_df)
            if skipped > 0: self.logs.append(f"⏭️ Skipped {skipped} Weekly items (Pinned).")
                
        if studio_df is not None and not studio_df.empty and pinned_assignments:
            # Studio rows expand into multiple source requests; filtering is
            # done after expansion so one pinned slot does not hide its peers.
            if "id" in studio_df.columns:
                studio_df = studio_df.copy()
        
        # --- PHASE 1: WEEKLY ---
        # Only process if weekly_df is provided and not empty
        if weekly_df is not None and not weekly_df.empty:
            blocks = self._splice_into_blocks(weekly_df)
            self.logs.extend(
                schedule_weekly_blocks(
                    blocks=blocks,
                    room_ids=list(self.room_objs.keys()),
                    instructor_priority=self.rules.get("instructor_priority", {}),
                    normalize_instrument_type=self._normalize_instrument_type,
                    can_assign=lambda room_id, day, start, end: self.can_assign(room_id, day, start, end),
                    score_room=self._score_room_unified,
                    create_assignment=self._create_assignment,
                    classify_unassigned_reason=self._classify_unassigned_reason,
                    append_unassigned=self._append_unassigned,
                )
            )

        # --- PHASE 1.5: BUILD BLOCK MAP (GRANDMASTER LOGIC) ---
        # Critical: Index assignments into Atomic Blocks for Phase 2 manipulation
        self.logs.append("🔗 Phase 1.5: Linking Adjacent Instructor Blocks...")
        self._build_block_map()

        # --- PHASE 2: STUDIO ---
        if studio_df is not None and not studio_df.empty:
            self.logs.append("🎹 Phase 2: Processing Studio Schedule (Unified Rules)...")
            self._process_studio(studio_df)

        return self.assignments, self.duplicates, self.logs

    def _process_studio(self, studio_df):
        studio_events_buffer, rejections = prepare_studio_requests(
            studio_df,
            room_types=self.room_types,
            normalize_instrument_type=self._normalize_instrument_type,
        )
        if self.pinned_source_ids:
            before_requests = len(studio_events_buffer)
            studio_events_buffer = [
                request
                for request in studio_events_buffer
                if request.get("source_request_id") not in self.pinned_source_ids
            ]
            rejections = [
                rejection
                for rejection in rejections
                if rejection.get("payload", {}).get("source_request_id")
                not in self.pinned_source_ids
            ]
            skipped = before_requests - len(studio_events_buffer)
            if skipped:
                self.logs.append(f"⏭️ Skipped {skipped} Studio requests (Pinned).")
        for rejection in rejections:
            warning = rejection.get("warning")
            if warning:
                logger.warning(warning["message"], *warning["args"])
            self.logs.append(rejection["log_line"])
            self._append_unassigned(
                rejection["payload"],
                rejection["reason"],
                rejection["reason_code"],
            )
        self.logs.extend(
            assign_studio_requests(
                requests=studio_events_buffer,
                room_ids=list(self.room_objs.keys()),
                instructor_priority=self.rules.get("instructor_priority", {}),
                merge_requests=self._merge_studio_blocks,
                can_assign=lambda room_id, req: self.can_assign(
                    room_id,
                    req["day"],
                    req["start"],
                    req["end"],
                    specific_date=req["date"],
                    instructor_id=req["inst"],
                ),
                score_room=self._score_room_unified,
                resolve_preferred_room_conflict=self._resolve_with_grandmaster_logic,
                append_assignment=self._create_studio_assignment,
                append_unassigned=lambda req, reason, reason_code: self.unassigned.append(
                    build_studio_failed_unassigned(req, reason, reason_code)
                ),
                build_failure_reason=lambda req: self._classify_unassigned_reason(
                    req,
                    specific_date=req.get("date"),
                ),
                describe_room_occupant=self._describe_studio_room_occupant,
            )
        )

    def _merge_studio_blocks(self, events):
        """
        [ATOMIC MODIFICATION]
        We do NOT merge consecutive requests anymore.
        To fix the 'Merge-Split Double Booking' bug, we treat every hour as an atomic event.
        So this simply sorts the events and returns them as-is.
        """
        if not events: return []
        
        # Determine sorting keys
        # We want to process them in chronological order
        
        # Sort key: Date, Instructor, Start
        def sort_key(e):
            return (e['date'], e['inst'], e['start'])
            
        sorted_events = sorted(events, key=sort_key)
        
        return sorted_events # Return LIST of objects, not merged block

    def _resolve_with_grandmaster_logic(self, room_id, req):
        """
        Phase 9 (Grandmaster): Recursive Block Resolution.
        Iteratively tries to free up 'room_id' for 'req'.
        """
        conflicts = self._get_conflicting_events(room_id, req)

        def resolve_victim_block(conflict_event):
            block_id = conflict_event.get("extendedProps", {}).get("block_id")
            if block_id and block_id in self.blocks:
                return self.blocks[block_id]

            start_min, end_min = self._parse_event_times(conflict_event)
            props = conflict_event.get("extendedProps", {})
            return {
                "id": f"atomic_{conflict_event['id']}",
                "events": [conflict_event],
                "room_id": room_id,
                "priority": self.rules.get("instructor_priority", {}).get(
                    props.get("Instructor"),
                    DEFAULT_INSTRUCTOR_PRIORITY,
                ),
                "inst_name": props.get("Instructor"),
                "start": int(start_min / 60),
                "end": int(end_min / 60),
                "instrument": props.get("normalized_instrument", "Instrumental"),
            }

        return resolve_grandmaster_conflicts(
            room_id=room_id,
            req=req,
            conflicts=conflicts,
            resolve_victim_block=resolve_victim_block,
            check_food_chain=self._check_food_chain,
            relocate_whole_block=self._relocate_whole_block,
            evict_whole_block=self._evict_whole_block,
            append_log=self.logs.append,
        )

    def _get_conflicting_events(self, room_id, req):
        """
        Helper to find what events (Weekly or Studio) overlap with req in room_id.
        Crucial for Preemption Logic.
        """
        return get_conflicting_events(
            assignments=self.assignments,
            room_id=room_id,
            req=req,
            parse_event_times=self._parse_event_times,
            is_time_overlap=self._is_time_overlap,
        )

    def _check_food_chain(self, req, victim_block):
        """
        True if Req is allowed to kick Victim.
        Rules:
        1. T0 (high priority: Piano>=8, Voice>=9) -> Kick T1/T2.
        2. T1 (standard Piano/Voice) -> Kick T2 (Instrumental) or lower-priority same-type.
        3. T2 (Instrumental/Percussion) -> Limited preemption within tier.
        """
        return check_food_chain(
            req=req,
            victim_block=victim_block,
            instructor_priority=self.rules.get("instructor_priority", {}),
            normalize_instrument_type=self._normalize_instrument_type,
        )

    def _relocate_whole_block(self, block):
        """Try to move ALL events in block to a new room."""
        def can_assign(room_id, day, start, end, specific_date=None, exclude_ids=None):
            try:
                return self.can_assign(
                    room_id,
                    day,
                    start,
                    end,
                    specific_date=specific_date,
                    exclude_ids=exclude_ids,
                )
            except TypeError as exc:
                if "exclude_ids" not in str(exc):
                    raise
                return self.can_assign(
                    room_id,
                    day,
                    start,
                    end,
                    specific_date=specific_date,
                )

        return relocate_whole_block(
            block=block,
            room_ids=self.room_objs,
            can_assign=can_assign,
            score_room=self._score_room_unified,
            event_specific_date=TimeParser.event_specific_date,
            to_js_weekday=TimeParser.to_js_weekday,
            logger=logger,
        )

    def _evict_whole_block(self, block):
        """Move ALL events in block to Unassigned."""
        return evict_whole_block(
            block=block,
            assignments=self.assignments,
            blocks=self.blocks,
            parse_event_times=self._parse_event_times,
            append_unassigned=self._append_unassigned,
            preempted_reason=UNASSIGNED_REASON_MESSAGES["preempted_by_higher_priority_block"],
            preempted_reason_code="preempted_by_higher_priority_block",
        )

    def _create_assignment(self, lesson, room_id):
        evt = build_weekly_assignment(lesson, room_id)
        self.assignments.append(evt)

    def _create_studio_assignment(self, req, room_id):
        start_minute = req.get("start_minute", req["start"] * 60)
        end_minute = req.get("end_minute", req["end"] * 60)
        evt = {
            "id": f"stu_{req['inst']}_{req['id_suffix']}_opt",
            "source_request_id": req.get("source_request_id"),
            "resourceId": room_id,
            "title": f"🎹 Studio: {req['inst']}",
            "start": f"{req['date']}T{start_minute // 60:02d}:{start_minute % 60:02d}:00",
            "end": f"{req['date']}T{end_minute // 60:02d}:{end_minute % 60:02d}:00",
            "type": "studio_class",
            "editable": True,
            "backgroundColor": "#2c3e50",
            "extendedProps": {
                **req["raw_row"],
                "auto_generated": True,
                "is_studio": True,
                "original_prefs": req["prefs"],
                "normalized_instrument": req["instrument"],
                "source_request_id": req.get("source_request_id"),
            },
        }
        self.assignments.append(evt)

    def _describe_studio_room_occupant(self, req, room_id):
        norm_req = self._normalize_instrument_type(req["instrument"])
        if norm_req not in self.room_types.get(room_id, []):
            return None

        occupant = "🟢 Free (Logic Error?)"
        start_min = req.get("start_minute", req["start"] * 60)
        end_min = req.get("end_minute", req["end"] * 60)

        if not self._check_global_constraints(req["start"], req["end"]):
            return "⛔ Closed (Time Constraint)"

        for booking in self.bookings:
            if booking.get("resourceId") != room_id:
                continue
            booking_start, booking_end = self._parse_event_times(booking)
            if self._is_time_overlap(start_min, end_min, booking_start, booking_end):
                return f"🔴 Locked ({booking.get('title', 'Lecture')})"

        for event in self.assignments:
            event_room_id = event.get("resourceId", event.get("room_id"))
            if event_room_id != room_id:
                continue

            is_overlap = False
            if "daysOfWeek" in event and req["day"] in event["daysOfWeek"]:
                event_start, event_end = self._parse_event_times(event)
                if event_start is None or event_end is None:
                    occupant = f"🔴 {event.get('title', 'Weekly')} (Malformed Time)"
                    is_overlap = True
                elif self._is_time_overlap(start_min, end_min, event_start, event_end):
                    occupant = f"🔴 {event.get('title', 'Weekly')} (Weekly)"
                    is_overlap = True
            elif event.get("extendedProps", {}).get("is_studio") and event.get("start") == req["date"]:
                pass

            if is_overlap:
                break

        return occupant

    # ==========================================
    # PHASE 1.5: BLOCK LINKAGE (GRANDMASTER)
    # ==========================================

    def _build_block_map(self):
        """
        Post-Phase 1: Identify and Link contiguous assignments into Atomic Blocks.
        Rule: Gap < 2 Hours => Same Block.
        """
        self.block_map, self.blocks = build_block_linkage_map(
            assignments=self.assignments,
            rules=self.rules,
            time_str_to_minutes=self.time_str_to_minutes,
            normalize_instrument_type=self._normalize_instrument_type,
        )
            
    def _register_block(self, bid, events):
        """Helper to store block metadata"""
        self.block_map, self.blocks = register_block_groups(
            block_map=self.block_map,
            blocks=self.blocks,
            block_id=bid,
            events=events,
            rules=self.rules,
            normalize_instrument_type=self._normalize_instrument_type,
        )

    # ==========================================
    # PHASE 9: PATH OPTIMIZER (Anti-Fragmentation)
    # ==========================================
    def _solve_fragmented_block_min_switches(self, lessons, candidate_rooms):
        return solve_fragmented_block_min_switches(
            lessons,
            candidate_rooms,
            can_assign=lambda room_id, day, start, end: self.can_assign(room_id, day, start, end),
            score_room=self._score_room_unified,
        )
