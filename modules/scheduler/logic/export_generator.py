import pandas as pd
import logging
import re

from modules.shared.time_parser import TimeParser
from modules.scheduler.logic.reservation_classifier import classify_unresolved_reservations

logger = logging.getLogger(__name__)


def _duration_label(event):
    start_min, end_min = TimeParser.event_to_minute_range(event, default=None)
    if start_min is None or end_min is None:
        try:
            start_min = int(event.get("start")) * 60
            end_min = int(event.get("end")) * 60
        except (TypeError, ValueError):
            return "1h"
    normalized = TimeParser.canonical_course_occupancy(start_min, end_min)
    if normalized is None:
        return "1h"
    return f"{max(1, (normalized[1] - normalized[0]) // 60)}h"

def get_day_from_date(date_str):
    """Derive English Day of Week from YYYY-MM-DD string."""
    if not date_str or not isinstance(date_str, str): return ""
    parsed = TimeParser.parse_date(date_str)
    return parsed.strftime("%A") if parsed else ""

def normalize_instructor_name(name, valid_instructors):
    """
    Normalizes a given instructor name to a canonical form found in valid_instructors.
    Handles: "Instructor 0004" -> "Instructor 0004", "Instructor 0004 Reversed" -> "Instructor 0004"
    """
    if not name:
        return ""
    
    name = str(name).strip()
    
    # 1. Exact Match check
    if name in valid_instructors:
        return name
        
    # 2. Case-insensitive Match
    valid_map_lower = {v.lower(): v for v in valid_instructors}
    if name.lower() in valid_map_lower:
        return valid_map_lower[name.lower()]
        
    # 3. Strip Titles for fuzzy comparison
    def strip_title(n):
        return re.sub(r'^(Mr\.|Ms\.|Dr\.|Prof\.)\s*', '', n, flags=re.IGNORECASE).strip()
        
    clean_name = strip_title(name)
    
    # Map cleaned canonicals
    # canonical: "Instructor 0004" -> clean: "instructor four"
    # map: "four instructor" -> "Instructor 0004" (reversed)
    # map: "instructor four alt" -> "Instructor 0004" (variant)
    
    fuzzy_map = {}
    for v in valid_instructors:
        clean_v = strip_title(v).lower()
        fuzzy_map[clean_v] = v
        
        # Add reversed comparison (e.g. "four instructor")
        parts = clean_v.split()
        if len(parts) >= 2:
            reversed_v = " ".join(parts[::-1])
            fuzzy_map[reversed_v] = v
            # Also handle comma format just in case: "Four, Instructor"
            # (Though our inputs seem to be space separated)
            
    if clean_name.lower() in fuzzy_map:
        return fuzzy_map[clean_name.lower()]
        
    # 4. Check if input is reversed? (name="Instructor 0004 Reversed", valid="Instructor 0004")
    parts = clean_name.lower().split()
    if len(parts) >= 2:
        reversed_input = " ".join(parts[::-1])
        if reversed_input in fuzzy_map:
            return fuzzy_map[reversed_input]

    # Fallback: Return original if no match
    return name

def _is_studio_by_content(b):
    """Detect Studio events by content signals, regardless of 'type' field.
    Handles misclassified events (type='weekly_lesson' but actually Studio)."""
    if b.get('type') == 'studio_class':
        return True
    title = str(b.get('title', '')).lower()
    student_name = str(b.get('extendedProps', {}).get('Student Name', '')).lower()
    event_id = str(b.get('id', '')).lower()
    # Check multiple signals
    if 'studio' in title or 'studio' in student_name:
        return True
    if event_id.startswith('stu_'):
        return True
    if 'n/a' in student_name and 'studio' in student_name:
        return True
    return False

def build_export_dataframe(bookings, unassigned_lessons, student_map, valid_instructors, uploaded_studio_df=None):
    """
    Generates a unified DataFrame for Master Export.
    Merges scheduled bookings and unassigned lessons.
    Normalizes instructor names.
    Uses English Headers.
    """
    # Initialize Lookup Table for Studio Dates
    uploaded_studio_date_lookup = {}
    if uploaded_studio_df is not None and not uploaded_studio_df.empty:
        uploaded_studio_date_lookup = _build_studio_date_lookup(uploaded_studio_df, valid_instructors)

    export_rows = []
    scheduled_assignments = [
        booking
        for booking in bookings
        if booking.get("type") in ("weekly_lesson", "studio_class", "studio")
    ]
    reservation_labels = classify_unresolved_reservations(
        scheduled_assignments,
        unassigned_lessons,
    )
    
    # --- 1. Process Scheduled Bookings ---
    for b in bookings:
        type_ = b.get('type')
        if type_ not in ['weekly_lesson', 'studio_class']:
            continue
        
        # Smart type detection: override type if content signals say Studio
        is_studio = _is_studio_by_content(b)
            
        props = b.get('extendedProps', {})
        
        # Extract Raw Info
        raw_inst = props.get('Instructor', props.get('instructor', ''))
        # Normalize!
        instructor = normalize_instructor_name(raw_inst, valid_instructors)
        
        # Student Info
        sid = str(props.get('Student No', props.get('student_id', ''))).strip()
        stu_info = student_map.get(sid, {})
        
        # Title logic
        title = b.get('title', '')
        
        if is_studio:
            # --- STUDIO CLASS (Content-Based) ---
            record = {
                "Instructor": instructor,
                "Student Name (EN)": "Studio Class",
                "Student Name (CN)": "",
                "Student ID": "",
                "Instrument": props.get('Instrument', props.get('instrument', '')),
                "Year": "",
                "Course Code": "STU",
                "Event Type": "Studio Class",
                "Day": "",
                "Date": "",
                "Time": "",
                "Room": b.get('resourceId', ''),
                "Duration": _duration_label(b),
            }
            
            # 1. Determine Time & Day from Optimization Result (The "Truth" of the Schedule)
            # Time Fallback
            if props.get('class_time'):
                record["Time"] = props.get('class_time')
            elif props.get('Class Time'):
                record["Time"] = props.get('Class Time')
            elif b.get('startTime') and b.get('endTime'):
                record["Time"] = f"{b['startTime'][:5]} - {b['endTime'][:5]}"
            else:
                s_t, e_t = TimeParser.event_clock_pair(b, default=(None, None))
                record["Time"] = f"{s_t} - {e_t}" if s_t and e_t else s_t
            
            # Day Fallback
            if props.get('day_en'):
                record["Day"] = props['day_en']
            elif props.get('Day of Week'):
                record["Day"] = props['Day of Week']
            elif b.get('daysOfWeek'):
                day_names = {0:'Sunday', 1:'Monday', 2:'Tuesday', 3:'Wednesday', 4:'Thursday', 5:'Friday', 6:'Saturday'}
                record["Day"] = day_names.get(b['daysOfWeek'][0], '')
            else:
                record["Day"] = get_day_from_date(TimeParser.event_specific_date(b) or "")

            # 2. Re-hydrate Date from Step 1 Upload (Lookup)
            # Since optimization uses Weekday logic, we must fetch the ORIGINAL specific date
            if uploaded_studio_date_lookup:
                # Key: (Normalized Inst, DayIndex, StartHour)
                # Need to derive DayIndex and StartHour from the record/booking
                
                day_map_inv = {'Monday':1, 'Tuesday':2, 'Wednesday':3, 'Thursday':4, 'Friday':5, 'Saturday':6, 'Sunday':0}
                day_idx = day_map_inv.get(record["Day"])
                
                start_hour = None
                try:
                    # Prefer the rendered export time range, but fall back to
                    # booking-level start fields for legacy/minimal studio events.
                    if record["Time"]:
                        start_hour = TimeParser.extract_start_hour(record["Time"], default=None)
                    if start_hour is None:
                        start_hour = TimeParser.extract_start_hour(
                            b.get("startTime") or b.get("start"),
                            default=None,
                        )
                except Exception:
                    logger.warning("build_export_dataframe: failed to derive studio lookup hour for booking %r", b.get("id"), exc_info=True)
                
                if day_idx is not None and start_hour is not None:
                    lookup_key = (instructor, day_idx, start_hour)
                    
                    if lookup_key in uploaded_studio_date_lookup:
                        candidates = uploaded_studio_date_lookup[lookup_key]
                        if candidates:
                            # Pop the first candidate (Sequential consumption)
                            # But wait! We must VERIFY it matches the Day!
                            
                            # Strategy: Look for a candidate that matches the Day
                            # (Though the key already implies Day, we double check Calendar validity)
                            
                            found_date = None
                            for i, c_date in enumerate(candidates):
                                # Calendar Check
                                if TimeParser.to_js_weekday(c_date, default=None) == day_idx:
                                    found_date = c_date
                                    # Remove consumed date to prevent reuse?
                                    # For multi-week classes, we want to consume sequentially.
                                    del candidates[i]
                                    break
                            
                            if found_date:
                                record["Date"] = found_date
            
            # 3. Last Resort Fallback (if no upload or lookup failed)
            if not record["Date"]:
                # If we have an ISO start, use it
                event_date = TimeParser.event_specific_date(b)
                if event_date:
                    record["Date"] = event_date
                elif record["Day"]:
                     record["Date"] = record["Day"] # Minimal fallback


        elif type_ == 'weekly_lesson':
            record = {
                "Instructor": instructor,
                "Student Name (EN)": props.get('Student Name', stu_info.get('name_en', title.split('(')[0].replace('👤','').strip())),
                "Student Name (CN)": stu_info.get('name_ch', ''),
                "Student ID": sid,
                "Instrument": stu_info.get('instrument', ''),
                "Year": props.get('Study Year', stu_info.get('year', '')),
                "Course Code": props.get('Course Code', stu_info.get('course_code', '')),
                "Event Type": "Weekly Lesson",
                "Day": b.get('extendedProps', {}).get('day_en', ''), 
                "Date": "", 
                "Time": "",
                "Room": b.get('resourceId') or b.get('room_id', ''),
                "Duration": _duration_label(b),
            }
            
            # Helper for Time Extraction (Support camelCase and snake_case)
            s_t = b.get('startTime') or b.get('start_time', '')
            e_t = b.get('endTime') or b.get('end_time', '')
            if s_t and e_t:
                record["Time"] = f"{s_t[:5]} - {e_t[:5]}"
            
            # Day fallback if missing in props (from daysOfWeek)
            if not record["Day"] and b.get('daysOfWeek'):
                days = {0:'Sunday', 1:'Monday', 2:'Tuesday', 3:'Wednesday', 4:'Thursday', 5:'Friday', 6:'Saturday'}
                record["Day"] = days.get(b['daysOfWeek'][0], '')
                
        else:
            continue  # Unknown type, skip

        export_rows.append(record)

    # --- 2. Process Unassigned Lessons ---
    for u in unassigned_lessons:
        # Check source type
        # Weekly Unassigned usually has 'raw_row'
        raw = u.get('raw_row', {})
        if not raw and 'Student Name' in u: raw = u # Handle flat dict
        
        raw_inst = raw.get('Instructor', u.get('instructor', ''))
        instructor = normalize_instructor_name(raw_inst, valid_instructors)
        
        sid = str(raw.get('Student No', u.get('student_id', ''))).strip()
        stu_info = student_map.get(sid, {})
        
        # Raw name extraction
        raw_name = raw.get('Student Name', u.get('student', ''))
        
        
        # [DEBUG FIX] Clean up Failed Studio Logic
        # Detect if it is a Studio Class (Legacy 'N/A' or Optimizer 'Studio')
        is_studio_artifact = False
        s_name_str = str(raw_name)
        c_code_str = str(raw.get('Course Code', raw.get('course_code', '')))
        
        if ("N/A" in s_name_str and "Studio" in s_name_str) or \
           s_name_str == "Studio" or \
           "STU" in c_code_str or \
           "Studio" in c_code_str:
            is_studio_artifact = True
        
        # Extract Day/Time robustly (Schema Mismatch Fix)
        day_val = raw.get('Day of Week') or raw.get('day_en') or raw.get('Day') or str(u.get('day', ''))
        # If day is int, map it? (Optimizer outputs int day index usually)
        if isinstance(day_val, int) or (isinstance(day_val, str) and day_val.isdigit()):
            # Optimizer uses JS convention: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
            # (Source: field_schema.py DAY_MAP_EN {'Monday':1, 'Sunday':0})
            day_map_rev = {0:'Sunday', 1:'Monday', 2:'Tuesday', 3:'Wednesday', 4:'Thursday', 5:'Friday', 6:'Saturday'}
            try:
                day_idx = int(day_val)
                if day_idx in day_map_rev:
                    day_val = day_map_rev[day_idx]
            except Exception:
                logger.warning("build_export_dataframe: failed to normalize day value %r for unassigned row", day_val, exc_info=True)
            
        time_val = raw.get('Class Time') or raw.get('class_time') or raw.get('Time') or ''
        
        if is_studio_artifact:
            issue_id = str(u.get("id") or "").strip()
            reservation_note = (reservation_labels.get(issue_id) or {}).get(
                "reservation_note"
            )
            # Try to get Date from top-level unassigned dict if available
            date_val = u.get('date', raw.get('Date', ''))
            
            # If we have Date, trust calendar-derived weekday as source of truth.
            if date_val:
                derived_day = get_day_from_date(str(date_val))
                if derived_day:
                    day_val = derived_day
            
            record = {
                "Instructor": instructor,
                "Student Name (EN)": "Studio Class",
                "Student Name (CN)": "",
                "Student ID": "",
                "Instrument": raw.get('Instrument', u.get('instrument', '')), 
                "Year": "",
                "Course Code": "STU", # Normalize to STU for studio
                "Event Type": "Studio Class", 
                "Day": day_val,
                "Date": str(date_val),
                "Time": time_val,
                "Room": "Unassigned",
                "Duration": _duration_label(u),
            }
            if reservation_note:
                record["Reservation Note"] = reservation_note
        else:
            record = {
                "Instructor": instructor,
                "Student Name (EN)": raw_name,
                "Student Name (CN)": stu_info.get('name_ch', ''),
                "Student ID": sid,
                "Instrument": raw.get('Instrument', u.get('instrument', '')), 
                "Year": raw.get('Study Year', ''),
                "Course Code": raw.get('Course Code', ''),
                "Event Type": "Weekly Lesson", 
                "Day": day_val,
                "Date": "",
                "Time": time_val,
                "Room": "Unassigned",
                "Duration": _duration_label(u),
            }
            
        export_rows.append(record)

    # --- 3. Create DataFrame & Sort ---
    df = pd.DataFrame(export_rows)
    
    if not df.empty:
        # Helper for sorting Days
        day_map = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }
        df['_day_rank'] = df['Day'].map(day_map).fillna(99)
        
        # Sort: Instructor -> Day -> Time
        df = df.sort_values(by=['Instructor', '_day_rank', 'Time'])
        
        # Cleanup
        df = df.drop(columns=['_day_rank'])
        
    return df

def _build_studio_date_lookup(uploaded_studio_df, valid_instructors):
    """
    Builds a lookup table from Step 1 Raw Data.
    Key: (Instructor, DayIndex, StartHour)
    Value: List of ISO dates [date1, date2, ...] sorted.
    """
    lookup = {} # dict of list
    
    if uploaded_studio_df is None or uploaded_studio_df.empty:
        return lookup
        
    from modules.shared.field_schema import parse_studio_date
    
    for idx, row in uploaded_studio_df.iterrows():
        raw_inst = str(row.get('Instructor', '')).strip()
        instructor = normalize_instructor_name(raw_inst, valid_instructors)
        if not instructor: continue
        
        # Iterate 3 potential slots
        for i in range(1, 4):
            col_date = f"Studio {i} Date"
            col_time = f"Studio {i} Time"
            
            date_str = str(row.get(col_date, "") or "")
            if not date_str or date_str.lower() in ['nat', 'nan', 'none']: continue
            
            # Parse Date
            dt_obj, day_idx, _ = parse_studio_date(date_str)
            if not dt_obj: continue
            
            iso_date = dt_obj.strftime("%Y-%m-%d")
            
            # Parse Time -> Start Hour
            time_str = str(row.get(col_time, "19:00-20:00"))
            
            chunks = time_str.replace('，', ',').split(',')
            for chunk in chunks:
                if '-' not in chunk: continue
                try:
                    start_hour = TimeParser.extract_start_hour(chunk, default=None)
                    if start_hour is None:
                        continue
                    
                    key = (instructor, day_idx, start_hour)
                    if key not in lookup:
                        lookup[key] = []
                    
                    lookup[key].append(iso_date)
                    
                except Exception:
                    logger.warning(
                        "_build_studio_date_lookup: failed to parse studio time chunk %r for instructor %r",
                        chunk,
                        instructor,
                        exc_info=True,
                    )
                    continue
    
    # Sort dates in each list for deterministic Pop
    for k in lookup:
        lookup[k].sort()
        
    return lookup
