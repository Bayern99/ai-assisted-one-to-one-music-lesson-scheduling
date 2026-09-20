import unittest
import pytest
import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.scheduler.logic.optimizer import RoomAllocator
from modules.shared.data_loader import DataLoader
from modules.shared.data_validator import DataValidator
from modules.shared.field_schema import WEEKLY_FIELDS

class TestEndToEnd(unittest.TestCase):
    
    def test_full_workflow_weekly(self):
        """
        1. Load weekly.csv
        2. Run optimizer (using new Field Schema)
        3. Verify round-trip (Input Count == Output + Failed)
        4. Verify field integrity (All 8 canonical fields present)
        """
        print("\n🚀 Starting End-to-End Workflow Test...")
        loader = DataLoader()
        validator = DataValidator()
        
        # 1. Load (Mocking file read via DataLoader helper if needed, but direct pandas is cleaner for unit test)
        # We assume Files/weekly.csv exists as per previous context
        file_path = 'Files/weekly.csv'
        if not os.path.exists(file_path):
            pytest.skip(f"Test data file not found: {file_path}")

        df = pd.read_csv(file_path)
        original_count = len(df)
        print(f"📊 Loaded {original_count} input rows.")
        
        # 2. Optimize
        # Mock dependencies
        students = [] # Not used by splicing logic directly (uses DF)
        rooms = [{"id": "R101", "instruments": ["Piano"]}, {"id": "CC105", "types": ["Percussion"]}]
        existing = []
        rules = {
            "instructor_priority": {"Instructor 0001": 10},
            "instructor_preferred_rooms": {"Instructor 0001": ["R101"]},
            "constraints": {"time_range": {"start": "08:00", "end": "22:00"}}
        }
        
        optimizer = RoomAllocator(students, rooms, existing, rules)
        assignments, _, logs = optimizer.optimize(df)
        unassigned = optimizer.unassigned
        
        print(f"✅ Generated {len(assignments)} assignments and {len(unassigned)} unassigned.")
        
        # 3. Round-trip validation
        rt_report = validator.validate_round_trip(
            df, assignments, unassigned
        )
        print("🔍 Round-Trip Report:", rt_report)
        self.assertTrue(rt_report['balanced'], rt_report['messages'])
        
        # 4. Field integrity
        fi_report = validator.validate_field_integrity(assignments)
        print("🔍 Field Integrity Report:", fi_report)
        self.assertEqual(fi_report['status'], 'PASS', fi_report['issues'])
        
        # 5. Verify specifically that extendedProps has correct keys
        if assignments:
            sample = assignments[0]
            props = sample['extendedProps']
            self.assertIn("Student Name", props)
            self.assertIn("Course Code", props)
            self.assertIn("auto_generated", props)
            print("✅ Verified extendedProps schema.")

    def test_studio_format_conversion(self):
        """
        Verify Studio data is converted to Weekly format.
        """
        from modules.shared.field_schema import parse_studio_date, normalize_to_weekly_format
        
        print("\n🧪 Testing Studio Format Conversion...")
        # Parse Chinese date
        date_obj, day_idx, day_en = parse_studio_date("2026年3月30日 星期一")
        self.assertEqual(day_idx, 1)
        self.assertEqual(day_en, "Monday")
        print(f"✅ Date Parse: {date_obj} -> {day_en}")
        
        # Normalize
        raw = {"Instructor": "Dr. Inst", "Instruments": "Piano", "Preferred Venue": "R101"}
        extra = {"day_en": "Monday", "class_time": "18:00-19:00"}
        normalized = normalize_to_weekly_format("studio", raw, extra)
        
        self.assertEqual(normalized["Instructor"], "Dr. Inst")
        self.assertEqual(normalized["Course Code"], "Piano")
        self.assertEqual(normalized["Day of Week"], "Monday")
        self.assertEqual(normalized["Student Name"], "N/A (Studio)")
        print("✅ Normalization Successful.")

    def test_round_trip_accounts_for_duplicate_rows(self):
        """
        Duplicate weekly rows should still be visible in failed accounting
        instead of disappearing from the round-trip totals.
        """
        validator = DataValidator()
        df = pd.DataFrame([
            {
                "Student Name": "Student 0001",
                "Student No": "S1",
                "Instructor": "Instructor 0001",
                "Study Year": "1",
                "Course Code": "MUS101 (Piano)",
                "Day of Week": "Monday",
                "Class Time": "09:00-10:00",
                "Preferred Venue": ""
            },
            {
                "Student Name": "Student 0001 Duplicate",
                "Student No": "S1",
                "Instructor": "Instructor 0001",
                "Study Year": "1",
                "Course Code": "MUS101 (Piano)",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
                "Preferred Venue": ""
            }
        ])

        students = [{"student_id": "S1", "instrument": "Piano"}]
        rooms = [{"id": "R101", "type": "Piano"}]
        rules = {"priorities": {"Piano": {"Piano": 10}}}

        optimizer = RoomAllocator(students, rooms, [], rules)
        assignments, _, _ = optimizer.optimize(df)
        report = validator.validate_round_trip(df, assignments, optimizer.unassigned)

        self.assertTrue(report["balanced"], report["messages"])
        self.assertEqual(len(assignments), 1)
        self.assertEqual(len(optimizer.unassigned), 1)
        self.assertIn("Duplicate", optimizer.unassigned[0].get("reason", ""))

if __name__ == '__main__':
    unittest.main()
