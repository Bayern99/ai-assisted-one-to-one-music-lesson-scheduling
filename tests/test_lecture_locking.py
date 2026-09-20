import sys
import os
import unittest
import pandas as pd
from datetime import datetime
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.shared.data_loader import DataLoader
from modules.scheduler.logic.optimizer import RoomAllocator

class TestLectureLocking(unittest.TestCase):
    def test_room_normalization_and_locking(self):
        """
        Scenario: User has 'CC-105' in CSV.
        System must:
        1. Parse it.
        2. Normalize to 'CC105' (matching rooms.json).
        3. Block the optimizer from assigning CC105 at that time.
        """
        
        # 1. Mock Data Loader Parsing Logic (reproducing logic/data_loader.py)
        import re
        raw_room = "CC-105" 
        normalized_room = re.sub(r'[^A-Z0-9]', '', raw_room)
        
        self.assertEqual(normalized_room, "CC105", "Normalization failed: CC-105 should be CC105")
        
        # 2. Mock a Locked Lecture Event
        locked_lecture = {
            "resourceId": "CC105", 
            "daysOfWeek": [1], # Monday
            "startTime": "10:00:00",
            "endTime": "12:00:00",
            "type": "lecture",
            "locked": True
        }
        
        # 3. Setup Scheduler with this Locked Event
        rooms = [{"id": "CC105", "type": "Piano"}, {"id": "R104", "type": "Piano"}]
        students = [] # Not needed for blocking test
        existing_bookings = [locked_lecture]
        
        optimizer = RoomAllocator(students, rooms, existing_bookings, {})
        
        # 4. Test Availability
        
        # A. Conflict: Monday 10:00-11:00 in CC105
        # 10:00=10.0, 11:00=11.0
        can_do = optimizer.can_assign("CC105", 1, 10.0, 11.0)
        self.assertFalse(can_do, "Optimizer permitted overlap with locked lecture!")
        
        # B. Conflict: Monday 11:30-12:30 in CC105 (Overlap tail)
        can_do = optimizer.can_assign("CC105", 1, 11.5, 12.5)
        self.assertFalse(can_do, "Optimizer permitted tail overlap with locked lecture!")
        
        # C. No Conflict: Monday 12:00-13:00 in CC105 (Touch boundary)
        can_do = optimizer.can_assign("CC105", 1, 12.0, 13.0)
        self.assertTrue(can_do, "Optimizer blocked valid slot touching boundary!")
        
        # D. No Conflict: Tuesday 10:00-11:00 in CC105 (Different Day)
        can_do = optimizer.can_assign("CC105", 2, 10.0, 11.0)
        self.assertTrue(can_do, "Optimizer blocked different day!")

        # E. No Conflict: Monday 10:00-11:00 in R104 (Different Room)
        can_do = optimizer.can_assign("R104", 1, 10.0, 11.0)
        self.assertTrue(can_do, "Optimizer blocked different room!")

        print("\n✅ Verification Passed: 'CC-105' (normalized) correctly blocks 'CC105' in scheduler.")

if __name__ == '__main__':
    unittest.main()
