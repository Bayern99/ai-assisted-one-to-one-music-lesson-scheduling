import sys
import os
import unittest
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.scheduler.logic.optimizer import RoomAllocator

class TestCourseCodePropagation(unittest.TestCase):
    def test_course_code_passthrough(self):
        """
        PASS-THROUGH MODEL TEST:
        Input has 'Course Code ' header (with space).
        After cleaning, 'Course Code' should be in raw_row.
        After assignment, 'Course Code' should be in extendedProps.
        """
        # 1. Mock DataFrame with problematic header
        data = {
            'Instructor': ['Dr. Test'],
            'Day of Week': ['Monday'],
            'Class Time': ['10:00-11:00'],
            'Student Name': ['Test Student'],
            'Student No': ['12345'],
            'Course Code ': ['MUS123'],  # Note space - simulates user CSV issue
            'Study Year': ['2'],
            'Preferred Venue': ['CC105']
        }
        df = pd.DataFrame(data)
        
        # 2. Init Allocator
        allocator = RoomAllocator([], [], [], {})
        
        # 3. Test Block Splicing
        blocks = allocator._splice_into_blocks(df)
        
        self.assertTrue(blocks, "No blocks spliced")
        lesson = blocks[0]['lessons'][0]
        
        # 4. Verify raw_row contains original data (header cleaned to 'Course Code')
        raw = lesson.get('raw_row', {})
        # After column stripping, key is 'Course Code' (no space)
        self.assertIn('Course Code', raw, f"raw_row missing 'Course Code'. Keys: {raw.keys()}")
        self.assertEqual(raw['Course Code'], 'MUS123', f"Wrong value: {raw['Course Code']}")
        
        # 5. Verify Output Assignment
        allocator._create_assignment(lesson, "CC105")
        evt = allocator.assignments[0]
        
        props = evt.get('extendedProps', {})
        # Pass-through means the original column name is the key
        self.assertEqual(props.get('Course Code'), 'MUS123', f"extendedProps: {props}")
        
        # Also verify Student Name, Study Year are passed through
        self.assertEqual(props.get('Student Name'), 'Test Student')
        self.assertEqual(props.get('Study Year'), '2')
        
        print("\n✅ Pass-Through Verified: Input = Output + Room")

if __name__ == '__main__':
    unittest.main()
