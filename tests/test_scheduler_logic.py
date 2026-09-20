import unittest
import pandas as pd
from modules.scheduler.logic.optimizer import RoomAllocator

class TestSchedulerLogicBaseline(unittest.TestCase):
    """
    Regression Safety Net for Scheduler.
    Verifies constraints and basic allocation logic.
    """
    
    def setUp(self):
        # Mock Data
        self.rooms = [
            {"id": "RoomA", "types": ["Piano"], "capacity": 10},
            {"id": "RoomB", "types": ["Voice"], "capacity": 10}
        ]
        self.students = [
            {"student_id": "S1", "name": "Student 0001", "instrument": "Piano"},
            {"student_id": "S2", "name": "Student 0002", "instrument": "Voice"}
        ]
        self.rules = {
            "priorities": {
                "Piano": {"Piano": 10, "Voice": 0},
                "Voice": {"Voice": 10, "Piano": 0}
            },
            "constraints": {
                "time_range": {"start": "08:00", "end": "22:00"},
                "min_break_between_lessons": 0
            }
        }
    
    def test_basic_allocation_match(self):
        """Test ideal scenario: Student 0007 gets Piano room"""
        # Weekly DF Mock
        wk_df = pd.DataFrame([
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
                "Student No": "S1",
                "Student Name": "Student 0001",
                "Course Code": "MUS1263 - Demo Course I (Piano)",
            }
        ])

        optimizer = RoomAllocator(self.students, self.rooms, [], self.rules)
        assignments, _, logs = optimizer.optimize(wk_df)
        
        if len(assignments) != 1:
            print("\nDEBUG LOGS:")
            for l in logs: print(l)
        
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]['resourceId'], "RoomA") # S1 is Piano -> RoomA

    def test_conflict_detection(self):
        """Test that locked slots prevent assignment"""
        # Lock RoomA at 10-11
        locked_booking = [{
            "resourceId": "RoomA",
            "daysOfWeek": [1], # Monday
            "startTime": "10:00:00",
            "endTime": "11:00:00",
            "locked": True
        }]
        
        wk_df = pd.DataFrame([
            {
                "Instructor": "Instructor 0001",
                "Day of Week": "Monday",
                "Class Time": "10:00-11:00",
                "Student No": "S1", # Student 0007
                "Student Name": "Student 0001"
            }
        ])
        
        # RoomA is locked. RoomB is Voice (Score 0). S1 should fail or go to fallback?
        # Score 0 means Forbidden. So should be unassigned.
        
        optimizer = RoomAllocator(self.students, self.rooms, locked_booking, self.rules)
        assignments, _, logs = optimizer.optimize(wk_df)
        
        # Should be unassigned
        assigned_ids = [a['id'] for a in assignments]
        self.assertFalse(assigned_ids, "Should not assign to locked room or wrong type")
        self.assertEqual(len(optimizer.unassigned), 1)

if __name__ == '__main__':
    unittest.main()
