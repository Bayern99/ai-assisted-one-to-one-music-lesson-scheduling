import sys
import os

# 1. Modify Path BEFORE any other imports
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..'))
if root_dir not in sys.path:
    # PREPEND to ensure precedence over other paths
    sys.path.insert(0, root_dir)

import pytest
import pandas as pd
from datetime import datetime

# 2. DEBUG: Import module object first
try:
    import modules.scheduler.logic.export_generator as mod
    print(f"DEBUG: Loaded module from {mod.__file__}")
    print(f"DEBUG: Has function? {hasattr(mod, '_build_studio_date_lookup')}")
    from modules.scheduler.logic.export_generator import build_export_dataframe, _build_studio_date_lookup
except ImportError as e:
    print(f"DEBUG: Import failed: {e}")
    # Fallback for analysis - re-raise
    raise

class TestExportDateLookup:
    
    @pytest.fixture
    def mock_uploaded_studio(self):
        """Mock Step 1 uploaded DataFrame with Chinese dates"""
        data = {
            "Instructor": ["Instructor 0002", "Instructor 0001", "Instructor 0003"],
            "Instruments": ["Piano", "Piano", "Piano"],
            "Preferred Venue": ["R104", "R101", "R104"],
            # Studio 1
            "Studio 1 Date": ["2026年5月18日 星期一", "2026年3月30日 星期一", "2026年3月19日 星期四"],
            "Studio 1 Time": ["18:00-21:00", "18:00-21:00", "12:00-13:00"],
            # Studio 2 - Testing multi-date same time
            "Studio 2 Date": ["", "2026年5月18日 星期一", "2026年3月26日 星期四"],
            "Studio 2 Time": ["", "18:00-21:00", "12:00-13:00"],
            # Studio 3
            "Studio 3 Date": ["", "", "2026年4月16日 星期四"],
            "Studio 3 Time": ["", "", "12:00-13:00"]
        }
        return pd.DataFrame(data)

    def test_build_lookup_from_studio_df(self, mock_uploaded_studio):
        """Test 1: Verify lookup table is built correctly from DataFrame"""
        valid_instructors = ["Instructor 0002", "Instructor 0001", "Instructor 0003"]
        
        lookup = _build_studio_date_lookup(mock_uploaded_studio, valid_instructors)
        
        # InstructorTwo Mon 18:00 -> 2026-05-18
        key_instructor_0002 = ("Instructor 0002", 1, 18)
        assert key_instructor_0002 in lookup
        assert "2026-05-18" in lookup[key_instructor_0002]

        # Instructor 0001 Mon 18:00 -> should have 2 dates sorted
        key_instructor_0001 = ("Instructor 0001", 1, 18)
        assert key_instructor_0001 in lookup
        dates = lookup[key_instructor_0001]
        assert "2026-03-30" in dates
        assert "2026-05-18" in dates
        assert len(dates) == 2

    def test_lookup_date_matches_weekday(self, mock_uploaded_studio):
        """Test 2: Calendar Verification - Dates must match the Day Index"""
        valid_instructors = ["Instructor 0002"]
        lookup = _build_studio_date_lookup(mock_uploaded_studio, valid_instructors)
        
        for (inst, day_idx, hour), dates in lookup.items():
            for date_str in dates:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                # Our schema: 1=Mon...6=Sat, 0=Sun. Python: 0=Mon.
                iso_dow = dt.weekday()
                our_dow_map = {0:1, 1:2, 2:3, 3:4, 4:5, 5:6, 6:0}
                assert our_dow_map[iso_dow] == day_idx

    def test_export_replaces_dates_from_lookup(self, mock_uploaded_studio):
        """Test 3: Verify export actually replaces the date"""
        valid_instructors = ["Instructor 0002"]
        
        bookings = [{
            "type": "studio_class",
            "title": "Instructor 0002",
            "extendedProps": {
                "Instructor": "Instructor 0002",
                "day_en": "Monday",
                "Instrument": "Piano"
            },
            "startTime": "18:00:00", 
            "endTime": "19:00:00",
            "daysOfWeek": [1] # Monday
        }]
        
        df = build_export_dataframe(
            bookings, [], {}, valid_instructors, 
            uploaded_studio_df=mock_uploaded_studio
        )
        
        assert len(df) == 1
        row = df.iloc[0]
        assert row["Date"] == "2026-05-18"

    def test_export_cross_check_validation(self, mock_uploaded_studio):
        """Test 4: Cross-check - if lookup date doesn't match booking day, DO NOT usage"""
        valid_instructors = ["Instructor 0002"]
        
        # Booking says Tuesday (2), but lookup has Monday date
        bookings = [{
            "type": "studio_class",
            "title": "Instructor 0002",
            "extendedProps": {"Instructor": "Instructor 0002", "day_en": "Tuesday"},
            "startTime": "18:00:00",
            "daysOfWeek": [2] # Tuesday
        }]
        
        df = build_export_dataframe(
            bookings, [], {}, valid_instructors, 
            uploaded_studio_df=mock_uploaded_studio
        )
        
        # Should NOT use the Monday date
        assert df.iloc[0]["Date"] != "2026-05-18"

    def test_no_upload_graceful_fallback(self):
        """Test 5: Graceful degradation if no upload data"""
        valid_instructors = ["Instructor 0002"]
        bookings = [{
            "type": "studio_class",
            "title": "Dr. InstructorTwo",
            "extendedProps": {"Instructor": "Instructor 0002", "day_en": "Monday"},
            "startTime": "18:00:00",
            "daysOfWeek": [1]
        }]
        
        df = build_export_dataframe(bookings, [], {}, valid_instructors, uploaded_studio_df=None)
        
        assert len(df) == 1
        # Should not crash

    def test_consume_lookup_dates_sequentially(self, mock_uploaded_studio):
        """Test 6: One-to-many consumption - multiple bookings consume dates in order"""
        valid_instructors = ["Instructor 0001"]
        
        bookings = [
            {"type": "studio_class", "extendedProps": {"Instructor": "Instructor 0001", "day_en": "Monday"}, "startTime": "18:00:00", "daysOfWeek": [1]},
            {"type": "studio_class", "extendedProps": {"Instructor": "Instructor 0001", "day_en": "Monday"}, "startTime": "18:00:00", "daysOfWeek": [1]}
        ]
        
        df = build_export_dataframe(
            bookings, [], {}, valid_instructors, 
            uploaded_studio_df=mock_uploaded_studio
        )
        
        dates = sorted(df["Date"].tolist())
        assert dates == ["2026-03-30", "2026-05-18"]
