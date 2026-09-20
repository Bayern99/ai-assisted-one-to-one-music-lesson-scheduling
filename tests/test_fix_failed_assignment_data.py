
import pytest
import re
from datetime import datetime, time, date

# --- Mock Logic Under Test ---

def parse_time_from_raw(raw_row):
    """
    Simulates the logic currently in scheduling.py to extract time.
    Current behavior: Try 'Requested Time', then 'Time Slot'.
    FIX SHOULD: Add 'Class Time', 'Timeslot', 'time', etc.
    """
    # Current simplistic logic (simulated from code view)
    requested_time = raw_row.get('Requested Time', raw_row.get('Time Slot', '?'))
    return str(requested_time)

def extract_start_end(time_str):
    """
    Simulated regex extraction logic.
    """
    time_match = re.findall(r'(\d{1,2}:\d{2})', str(time_str))
    if len(time_match) >= 2:
        return time_match[0], time_match[1]
    elif len(time_match) == 1:
        # Default 1h logic
        h, m = map(int, time_match[0].split(':'))
        end_h = h + 1
        return f"{h:02d}:{m:02d}", f"{end_h:02d}:{m:02d}"
    else:
        return "09:00", "10:00"

def sort_events(events):
    """
    Simulated sorting logic for editor cards.
    Current: No sort (order of list).
    Target: Day -> Start Time.
    """
    # Helper for day index
    def get_day(e):
        days = e.get('daysOfWeek', [])
        return days[0] if days else 7 # 7 = Unknown/End
    
    # Helper for start time minutes
    def get_min(e):
        t_str = e.get('startTime') or e.get('start', '00:00:00')
        if 'T' in t_str: t_str = t_str.split('T')[1]
        try:
            h, m = map(int, t_str[:5].split(':'))
            return h * 60 + m
        except:
            return 0
            
    return sorted(events, key=lambda x: (get_day(x), get_min(x)))


# --- Tests ---

def test_time_missing_from_class_time_key():
    """Reproduce Issue 1: Data has 'Class Time' but logic ignores it"""
    raw_row = {
        "Student Name": "Student 0001", 
        "Class Time": "11:00-12:00", # The likely key in user data
        "Day of Week": "Thursday"
    }
    
    val = parse_time_from_raw(raw_row)
    # Current behavior fails (returns '?')
    # If this assertions PASSES, it means the bug IS reproduced (logic failed to find key)
    assert val == '?' or val == 'None'
    
    # Check extraction
    s, e = extract_start_end(val)
    assert s == "09:00" # Default fallback triggered

def test_proposed_fix_includes_class_time():
    """Verify the Fix: Logic should look for 'Class Time'"""
    raw_row = {
        "Student Name": "Student 0001", 
        "Class Time": "11:00-12:00"
    }
    
    # Improved Logic
    keys_to_try = ['Requested Time', 'Time Slot', 'Class Time', 'Time', 'time']
    val = next((raw_row.get(k) for k in keys_to_try if raw_row.get(k)), '?')
    
    assert val == "11:00-12:00"
    s, e = extract_start_end(val)
    assert s == "11:00"
    assert e == "12:00"

def test_editor_sorting_logic():
    """Verify Issue 2: Events should be sorted by Day then Time"""
    events = [
        {"id": 1, "daysOfWeek": [2], "startTime": "14:00:00", "title": "Wed PM"},
        {"id": 2, "daysOfWeek": [1], "startTime": "09:00:00", "title": "Tue AM"},
        {"id": 3, "daysOfWeek": [1], "startTime": "15:00:00", "title": "Tue PM"},
        {"id": 4, "daysOfWeek": [0], "startTime": "10:00:00", "title": "Mon AM"},
    ]
    
    sorted_evts = sort_events(events)
    
    # Mon -> Tue AM -> Tue PM -> Wed
    assert sorted_evts[0]['id'] == 4 # Mon
    assert sorted_evts[1]['id'] == 2 # Tue 09:00
    assert sorted_evts[2]['id'] == 3 # Tue 15:00
    assert sorted_evts[3]['id'] == 1 # Wed
