"""
Single Source of Truth for all field names, format definitions, and conversion rules.
Every module MUST import from here - no hardcoded field names elsewhere.
"""
import re
from datetime import datetime
from typing import Optional, Tuple, List, Dict

# ============================
# INPUT FIELDS (from CSV)
# ============================
WEEKLY_FIELDS = [
    "Student Name",
    "Student No",
    "Instructor",
    "Study Year",
    "Course Code",
    "Day of Week",
    "Class Time",
    "Preferred Venue",
]

STUDIO_FIELDS = [
    "Instructor",
    "Instruments",
    "Studio 1 Date",
    "Studio 1 Time",
    "Studio 2 Date",
    "Studio 2 Time",
    "Studio 3 Date",
    "Studio 3 Time",
    "Preferred Venue",
]

LECTURE_FIELDS = [
    "Course Code",
    "Course Title & Session",
    "Teachers",
    "Class Schedule",
    "Hours",
    "Classroom",
]

# ============================
# OUTPUT FIELDS (for Export)
# ============================
OUTPUT_FIELDS = WEEKLY_FIELDS + ["Room"]

# ============================
# N/A PLACEHOLDERS
# ============================
NA_STUDIO = "N/A (Studio)"
NA_LECTURE = "N/A (Lecture)"

# ============================
# DAY OF WEEK MAPPINGS
# ============================
DAY_MAP_EN = {
    'Monday': 1, 'Tuesday': 2, 'Wednesday': 3,
    'Thursday': 4, 'Friday': 5, 'Saturday': 6, 'Sunday': 0
}

DAY_MAP_EN_SHORT = {
    'Mon': 1, 'Tue': 2, 'Wed': 3, 'Thu': 4, 'Fri': 5, 'Sat': 6, 'Sun': 0
}

DAY_MAP_CN = {
    '星期一': 1, '星期二': 2, '星期三': 3,
    '星期四': 4, '星期五': 5, '星期六': 6, '星期日': 0, '星期天': 0
}

DAY_IDX_TO_EN = {
    0: 'Sunday', 1: 'Monday', 2: 'Tuesday', 3: 'Wednesday',
    4: 'Thursday', 5: 'Friday', 6: 'Saturday'
}

# ============================
# FORMAT DEFINITIONS
# ============================
TIME_FORMAT = "HH:MM-HH:MM"  # Example: "16:00-17:00"
DATE_FORMAT_STUDIO = "YYYY年M月D日 星期X"  # Example: "2026年3月30日 星期一"
DATE_FORMAT_ISO = "YYYY-MM-DD"  # Example: "2026-03-30"

# ============================
# PARSING FUNCTIONS
# ============================

def parse_studio_date(date_str: str) -> Tuple[Optional[datetime], Optional[int], Optional[str]]:
    """
    Parse Chinese date format from Studio CSV.
    
    Input:  "2026年3月30日 星期一"
    Output: (datetime(2026, 3, 30), 1, "Monday")
    
    Returns: (date_obj, day_idx, day_en)
    """
    if not date_str or not isinstance(date_str, str):
        return None, None, None
    
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(星期.)', date_str.strip())
    if match:
        year, month, day, dow_cn = match.groups()
        try:
            date_obj = datetime(int(year), int(month), int(day))
            dow_idx = DAY_MAP_CN.get(dow_cn)
            dow_en = DAY_IDX_TO_EN.get(dow_idx, "")
            return date_obj, dow_idx, dow_en
        except ValueError:
            return None, None, None
    
    return None, None, None


def parse_lecture_schedule(schedule_str: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse Lecture schedule format.
    
    Input:  "Mon 13:00-14:00"
    Output: ("Monday", "13:00-14:00")
    """
    if not schedule_str or not isinstance(schedule_str, str):
        return None, None
    
    parts = schedule_str.strip().split(' ')
    if len(parts) >= 2:
        day_short = parts[0]
        time_range = parts[1]
        day_idx = DAY_MAP_EN_SHORT.get(day_short)
        day_en = DAY_IDX_TO_EN.get(day_idx, "")
        return day_en, time_range
    
    return None, None


def split_multi_time_slots(time_str: str) -> List[str]:
    """
    Split comma-separated time slots.
    
    Input:  "18:00-19:00, 19:00-20:00, 20:00-21:00"
    Output: ["18:00-19:00", "19:00-20:00", "20:00-21:00"]
    """
    if not time_str:
        return []
    
    # Handle both Chinese and English commas
    val = str(time_str).replace('，', ',')
    slots = val.split(',')
    return [s.strip() for s in slots if s.strip() and '-' in s]


def extract_instrument_from_course_code(course_code: str) -> str:
    """
    Extract instrument from Course Code.
    
    Input:  "MUS4153 - Demo Instruction VIII (Piano)"
    Output: "Piano"
    """
    if not course_code or not isinstance(course_code, str):
        return 'Instrumental'
    
    # Try to extract from parentheses at the end
    # Matches "(Piano)" or "(Piano) (1001)" -> extract "Piano"
    # We look for the parenthesis that contains the instrument name
    
    # Strategy 1: Look for known instruments in parentheses
    lower_code = course_code.lower()
    
    if 'piano' in lower_code: return 'Piano'
    if 'voice' in lower_code or 'vocal' in lower_code: return 'Voice'
    if 'percussion' in lower_code: return 'Percussion'
    if 'guzheng' in lower_code: return 'Guzheng' # Specific Chinese Instrument
    if 'pipa' in lower_code: return 'Pipa'       # Specific Chinese Instrument
    
    # Strategy 2: Keyword detection without parentheses
    if 'string' in lower_code or 'violin' in lower_code or 'cello' in lower_code or 'viola' in lower_code: return 'Instrumental'
    if 'brass' in lower_code or 'trumpet' in lower_code or 'horn' in lower_code: return 'Instrumental'
    if 'woodwind' in lower_code or 'flute' in lower_code or 'clarinet' in lower_code: return 'Instrumental'
    if 'guitar' in lower_code: return 'Instrumental'
    
    return 'Instrumental'  # Default fallback


# ============================
# CANONICAL FORMAT CONVERSION
# ============================

def normalize_to_weekly_format(source_type: str, raw_data: dict, extra: dict = None) -> dict:
    """
    Convert any source (Weekly/Studio/Lecture) to Weekly canonical format.
    
    This is the SINGLE format used for:
    - Scheduling (optimizer)
    - Conflict detection
    - Export
    - Validation
    
    Args:
        source_type: "weekly", "studio", or "lecture"
        raw_data: Original row data from CSV
        extra: Additional computed fields (e.g., parsed date for Studio)
    
    Returns:
        Dict with exactly 8 Weekly fields
    """
    extra = extra or {}
    
    if source_type == "weekly":
        return {
            "Student Name": str(raw_data.get("Student Name", "")).strip(),
            "Student No": str(raw_data.get("Student No", "")).strip(),
            "Instructor": str(raw_data.get("Instructor", "")).strip(),
            "Study Year": str(raw_data.get("Study Year", "")).strip(),
            "Course Code": str(raw_data.get("Course Code", "")).strip(),
            "Day of Week": str(raw_data.get("Day of Week", "")).strip(),
            "Class Time": str(raw_data.get("Class Time", "")).strip(),
            "Preferred Venue": str(raw_data.get("Preferred Venue", "")).strip(),
        }
    
    elif source_type == "studio":
        # extra should contain: day_en (from parsed date), class_time (from slot)
        # Note: Studio doesn't have Course Code, usually implies Instrument or Group Class
        # We map "Instruments" column to "Course Code" logic field to preserve it
        inst_val = str(raw_data.get("Instruments", "")).strip()
        
        return {
            "Student Name": NA_STUDIO,
            "Student No": NA_STUDIO,
            "Instructor": str(raw_data.get("Instructor", "")).strip(),
            "Study Year": NA_STUDIO,
            "Course Code": inst_val if inst_val else "Studio Class", # Map Instruments -> Course Code
            "Day of Week": extra.get("day_en", ""),  # Converted from Chinese
            "Class Time": extra.get("class_time", ""),  # Single slot
            "Preferred Venue": str(raw_data.get("Preferred Venue", "")).strip(),
        }
    
    elif source_type == "lecture":
        # extra should contain: day_en, class_time (from parsed schedule)
        return {
            "Student Name": NA_LECTURE,
            "Student No": NA_LECTURE,
            "Instructor": str(raw_data.get("Teachers", "")).strip(),
            "Study Year": NA_LECTURE,
            "Course Code": str(raw_data.get("Course Code", "")).strip(),
            "Day of Week": extra.get("day_en", ""),
            "Class Time": extra.get("class_time", ""),
            "Preferred Venue": str(raw_data.get("Classroom", "")).strip(),
        }
    
    else:
        raise ValueError(f"Unknown source type: {source_type}")
