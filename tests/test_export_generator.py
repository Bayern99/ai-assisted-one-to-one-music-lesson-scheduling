
import pytest
import pandas as pd
from datetime import datetime

# Logic we strictly expect to implement
try:
    from modules.scheduler.logic.export_generator import build_export_dataframe, normalize_instructor_name
except ImportError:
    pass

def test_normalize_instructor_name():
    """
    Test Case 4: Instructor Name Normalization
    Ensure variants map to the canonical name in the provided list.
    """
    valid_instructors = ["Instructor 0004", "Instructor 0001"]
    
    assert normalize_instructor_name("Instructor 0004", valid_instructors) == "Instructor 0004"
    assert normalize_instructor_name("0004 Instructor", valid_instructors) == "Instructor 0004"
    assert normalize_instructor_name("Instructor 0004", valid_instructors) == "Instructor 0004"
    assert normalize_instructor_name("Unknown Teacher", valid_instructors) == "Unknown Teacher"

def test_build_export_dataframe_integration():
    """
    Integration Test:
    - Merging Bookings + Unassigned
    - Normalizing Names
    - English Headers
    - Handling "N/A (Studio)" in Unassigned
    - Handling "Optimizer Generated" Unassigned Studios (Bug #2)
    """
    # 1. Setup Data
    valid_instructors = ["Instructor 0004", "Instructor 0001"]
    
    # Mock Booking (Scheduled)
    bookings = [{
        "type": "weekly_lesson",
        "title": "👤 Student 0001 (Instructor 0004)",
        "daysOfWeek": [1], 
        "startTime": "10:00:00",
        "endTime": "11:00:00",
        "resourceId": "Room 101",
        "extendedProps": {
            "Instructor": "0004 Instructor",
            "Student Name": "Student 0001",
            "Student No": "1001",
            "Course Code": "MUS101",
            "Study Year": 1
        }
    }]
    
    # Mock Unassigned (Failed)
    unassigned = [
        # Case 1: Normal Weekly Student
        {
            "student": "Student 0002",
            "instrument": "Piano",
            "instructor": "Instructor 0004",
            "raw_row": {
                "Student Name": "Student 0002",
                "Student No": "1002",
                "Instructor": "Instructor 0004",
                "Course Code": "MUS102",
                "Day of Week": "Tuesday",
                "Class Time": "12:00-13:00"
            }
        },
        # Case 2: FAILED STUDIO (Legacy Artifact "N/A (Studio)")
        {
            "student": "N/A (Studio)",
            "instrument": "Woodwinds: Flute",
            "instructor": "Instructor 0001",
            "raw_row": {
                 "Student Name": "N/A (Studio)",
                 "Student No": "N/A (Studio)",
                 "Instructor": "Instructor 0001",
                 "Class Time": "17:00-18:00",
                 "Day of Week": "Wednesday"
            }
        },
        # Case 3: FAILED STUDIO (Optimizer Generated - The "Weekly" Bug)
        # Optimizer outputs: student="Studio" (No "N/A")
        {
            "id": "stu_failed_optimization",
            "student": "Studio",  # <--- Optimizer sets this
            "inst": "Instructor 0001",
            "start": 10,
            "end": 11,
            "day": 2, # Tuesday
            "date": "2026-03-10",
            # raw_row from optimizer often has these keys from normalize_to_weekly
            "raw_row": {
                "Instructor": "Instructor 0001",
                "Course Code": "STU",
                "Day of Week": "Tuesday",
                "Class Time": "10:00-11:00", # Correct key in raw
                "day_en": "Tuesday", # Might exist?
                # "class_time": "10:00-11:00" # MIGHT BE MISSING in raw if normalization varied
            }
        }
    ]
    
    # Student Map
    student_map = {
        "1001": {"name_ch": "学生一", "instrument": "Piano"},
        "1002": {"name_ch": "学生二", "instrument": "Piano"}
    }
    
    # 2. Execute Logic
    try:
        from modules.scheduler.logic.export_generator import build_export_dataframe
        df = build_export_dataframe(bookings, unassigned, student_map, valid_instructors)
    except ImportError:
        pytest.fail("Module modules.scheduler.logic.export_generator not implemented yet")
    
    # 3. Assertions
    
    # A. Check Headers
    expected_headers = [
        "Instructor", "Student Name (EN)", "Student Name (CN)", 
        "Student ID", "Instrument", "Year", "Course Code",
        "Event Type", "Day", "Date", "Time", "Room", "Duration"
    ]
    for h in expected_headers:
        assert h in df.columns
        
    # B. Check Normalization
    assert df[df["Student Name (EN)"]=="Student 0001"]["Instructor"].iloc[0] == "Instructor 0004"
    
    # E. Check Failed Studio Cleanup (Case 2)
    df_failed_legacy = df[df["Time"] == "17:00-18:00"]
    assert len(df_failed_legacy) == 1
    row_legacy = df_failed_legacy.iloc[0]
    assert row_legacy["Student Name (EN)"] == "Studio Class"
    assert row_legacy["Event Type"] == "Studio Class"

    # F. Check Optimizer Failed Studio (Case 3) - THE BUG REPRO
    # It has Time "10:00-11:00"
    df_opt_failed = df[df["Time"] == "10:00-11:00"]
    if df_opt_failed.empty:
        # If time failed to parse, look by instructor and unassigned
        df_opt_failed = df[(df["Instructor"] == "Instructor 0001") & (df["Room"] == "Unassigned")]
        # Filter out the other one (17:00)
        df_opt_failed = df_opt_failed[df_opt_failed["Event Type"] != "Studio Class"] # If it was mislabeled
        
    # We expect to find it
    assert not df_opt_failed.empty, "Could not find the optimizer-generated failed studio in export"
    
    row_opt = df_opt_failed.iloc[0]
    
    # 1. Verify Event Type is NOT "Weekly Lesson"
    assert row_opt["Event Type"] == "Studio Class", f"Bad Event Type: {row_opt['Event Type']}"
    
    # 2. Verify Time and Day are present (Schema Fix)
    assert row_opt["Day"] == "Tuesday", f"Missing Day: {row_opt['Day']}"
    assert row_opt["Time"] == "10:00-11:00", f"Missing Time: {row_opt['Time']}"

def test_date_day_consistency():
    """
    Test Case G: Date/Day Consistency
    - Scenario 1: Scheduled Studio has Date -> Should derive Day if missing.
    - Scenario 2: Unassigned Studio has Date in top-level dict -> Should exist in export.
    """
    valid_instructors = ["Mr. Test"]
    student_map = {}
    
    # Scenario 1: Scheduled, Date exists, Day missing in props
    bookings = [{
        "type": "studio_class",
        "title": "🎹 Studio: Mr. Test",
        "start": "2026-03-30T10:00:00", # March 30 2026 is a Monday
        "end": "2026-03-30T11:00:00",
        "resourceId": "Room 101",
        "extendedProps": {
            "Instructor": "Mr. Test",
            # "day_en": MISSING intentionally
        }
    }]
    
    # Scenario 2: Unassigned, Date exists in top-level
    unassigned = [{
        "student": "Studio",
        "inst": "Mr. Test",
        "date": "2026-04-01", # Wednesday
        "day": 2,
        "raw_row": {
            "Instructor": "Mr. Test",
            "Class Time": "10:00-11:00"
            # Date might not be in raw_row or might be in obscure col
        }
    }]
    
    from modules.scheduler.logic.export_generator import build_export_dataframe
    df = build_export_dataframe(bookings, unassigned, student_map, valid_instructors)
    
    # Check Scenario 1
    row_sched = df[df["Room"] == "Room 101"].iloc[0]
    assert row_sched["Date"] == "2026-03-30"
    assert row_sched["Day"] == "Monday", f"Failed to derive Day from Date. Got: {row_sched['Day']}"
    
    # Check Scenario 2
    row_unassigned = df[df["Room"] == "Unassigned"].iloc[0]
    assert row_unassigned["Date"] == "2026-04-01", f"Unassigned Studio missing Date. Got: {row_unassigned['Date']}"
    # Day should probably come from 'day' int or raw_row fallback, or derived from Date
    # optimize.py passes 'day' (int) or 'Day of Week' in raw. 
    # But if we have Date, we should ensure Day matches it.
    assert row_unassigned["Day"] in ["Wednesday", "Wed"], f"Unassigned Studio missing/wrong Day. Got: {row_unassigned['Day']}"

if __name__ == "__main__":
    pass
