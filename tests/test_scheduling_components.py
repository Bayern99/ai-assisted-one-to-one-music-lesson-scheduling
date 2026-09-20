import sys
import os
import pandas as pd
import json
import unittest
from datetime import datetime

# Path Hack to include 'logic'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.shared.models import LessonEvent
from modules.scheduler.logic.optimizer import RoomAllocator

class TestSchedulingComponents(unittest.TestCase):
    
    def test_lesson_model_hash_integrity(self):
        """Verify Source ID generation is deterministic and unique by index/content"""
        row_a = {'col1': 'val1', 'col2': 100}
        row_b = {'col1': 'val1', 'col2': 100} # Identical content
        row_c = {'col1': 'val1', 'col2': 999} # Diff content
        
        # 1. Deterministic
        h1 = LessonEvent.generate_source_id(0, row_a)
        h1_retry = LessonEvent.generate_source_id(0, row_a)
        self.assertEqual(h1, h1_retry, "Hash should be deterministic")
        
        # 2. Unique by Index
        h2 = LessonEvent.generate_source_id(1, row_a)
        self.assertNotEqual(h1, h2, "Different indices should produce different hashes")
        
        # 3. Unique by Content
        h3 = LessonEvent.generate_source_id(0, row_c)
        self.assertNotEqual(h1, h3, "Different content should produce different hashes")
        
    def test_block_splicing_logic(self):
        """Verify instructor blocks splice adjacent and ≤60-minute-gap lessons."""
        # Create Dummy DataFrame
        data = [
            # Block 1
            {"Instructor": "Prof A", "Day of Week": "Monday", "Class Time": "09:00-10:00", "Student No": "S1"},
            {"Instructor": "Prof A", "Day of Week": "Monday", "Class Time": "10:00-11:00", "Student No": "S2"}, # Gap 0
            {"Instructor": "Prof A", "Day of Week": "Monday", "Class Time": "12:00-13:00", "Student No": "S3"}, # Gap 60 (bridge)
            
            # Block 2 (Gap > 60)
            {"Instructor": "Prof A", "Day of Week": "Monday", "Class Time": "15:00-16:00", "Student No": "S4"}, # Gap 120 (Split)
            
            # Block 3 (Different Day)
            {"Instructor": "Prof A", "Day of Week": "Tuesday", "Class Time": "09:00-10:00", "Student No": "S5"},
        ]
        df = pd.DataFrame(data)
        
        # Instantiate Allocator (mocking dependencies)
        allocator = RoomAllocator([], [], [], {})
        
        blocks = allocator._splice_into_blocks(df)
        
        # Sort output to be sure (Alloc doesn't guarantee order of keys, but returns list)
        # We expect 3 blocks: (A, Mon, 9-13), (A, Mon, 15-16), (A, Tue, 9-10).
        
        # Filter for Mon
        mon_blocks = [b for b in blocks if b['day'] == 1]
        tue_blocks = [b for b in blocks if b['day'] == 2]
        
        self.assertEqual(len(mon_blocks), 2, "Monday should have 2 blocks")
        self.assertEqual(len(tue_blocks), 1, "Tuesday should have 1 block")
        
        first_block = next(b for b in mon_blocks if b['start'] == 9)
        self.assertEqual(first_block['end'], 13, "60-minute gap is bridged")
        self.assertEqual(first_block['size'], 3, "Adjacent and 60-minute-gap lessons are linked")
        self.assertEqual(first_block['duration'], 3, "Duration is active hours sum (3h)")
        
    def test_conflict_detection(self):
        """Verify can_assign detects conflicts correctly"""
        existing = [{
            "resourceId": "R1",
            "daysOfWeek": [1],
            "startTime": "10:00",
            "endTime": "12:00",
            "type": "lecture"
        }]
        allocator = RoomAllocator([], [], existing, {})
        
        # 1. Exact Overlap
        self.assertFalse(allocator.can_assign("R1", 1, 10, 11))
        
        # 2. Internal Overlap
        self.assertFalse(allocator.can_assign("R1", 1, 10.5, 11.5))
        
        # 3. Wrapping Overlap
        self.assertFalse(allocator.can_assign("R1", 1, 9, 11))
        
        # 4. Touching Boundaries (Should be Allowed? usually yes if start=end)
        # s_min < b_e and e_min > b_s
        # 9-10: 540-600. b: 600-720. 540 < 720 (T), 600 > 600 (F). -> No Overlap. True.
        self.assertTrue(allocator.can_assign("R1", 1, 9, 10))
        self.assertTrue(allocator.can_assign("R1", 1, 12, 13))
        
        # 5. Different Room
        self.assertTrue(allocator.can_assign("R2", 1, 10, 11))

if __name__ == '__main__':
    unittest.main()
