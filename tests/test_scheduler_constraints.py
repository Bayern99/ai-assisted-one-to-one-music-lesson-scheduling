import sys
import os
import unittest
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.scheduler.logic.optimizer import RoomAllocator

class TestSchedulerConstraints(unittest.TestCase):
    def test_piano_rejected_from_percussion_room(self):
        """
        Scenario: 
        - Student: Piano
        - Time: Mon 10-11
        - Available Rooms: ONLY CC105 (Percussion)
        - Expected: Unassigned (Fail) - Should NOT put Piano in Percussion room.
        """
        
        # 1. Setup Data
        students = [{'student_id': '1999', 'name': 'Piano Boi', 'instrument': 'Piano'}]
        rooms = [
            {'id': 'CC105', 'type': 'Percussion', 'name': 'Percussion Room'}, 
            # Note: No Piano rooms available!
        ]
        bookings = [] # Time is free
        rules = {'priorities': {'Piano': {'Piano': 10}, 'Percussion': {'Percussion': 10}}}
        
        # 2. Mock Input DF
        df = pd.DataFrame([{
            'Student Name': 'Piano Boi',
            'Student No': '1999',
            'Instructor': 'Dr. Test',
            'Day of Week': 'Monday',
            'Class Time': '10:00-11:00',
            'Course Code': 'MUS1263 - Demo Course I (Piano)',
            'Preferred Venue': ''
        }])
        
        # 3. Optimize
        allocator = RoomAllocator(students, rooms, bookings, rules)
        allocator.optimize(df)
        
        # 4. Verify Failure
        # Should be unassigned because CC105 is strictly Percussion
        assigned_ids = [a['id'] for a in allocator.assignments]
        unassigned_names = [u['student'] for u in allocator.unassigned]
        
        self.assertEqual(len(allocator.assignments), 0, f"Should NOT assign. Assigned to: {assigned_ids}")
        self.assertIn('Piano Boi', unassigned_names, "Student should be in Unassigned list")
        
        print("\n✅ Validated: Student 0007 correctly REJECTED Percussion room.")

    def test_piano_accepted_in_piano_room(self):
        """
        Scenario: Same as above but with a Piano room available.
        """
        students = [{'student_id': '1999', 'name': 'Piano Boi', 'instrument': 'Piano'}]
        rooms = [{'id': 'R101', 'type': 'Piano', 'name': 'Piano Room'}]
        bookings = [] 
        rules = {'priorities': {'Piano': {'Piano': 10}}}
        
        df = pd.DataFrame([{
            'Student Name': 'Piano Boi',
            'Student No': '1999',
            'Instructor': 'Dr. Test',
            'Day of Week': 'Monday',
            'Class Time': '10:00-11:00',
            'Course Code': 'MUS1263 - Demo Course I (Piano)',
        }])

        allocator = RoomAllocator(students, rooms, bookings, rules)
        allocator.optimize(df)

        self.assertEqual(len(allocator.assignments), 1, "Should assign to Piano room")
        self.assertEqual(allocator.assignments[0]['resourceId'], 'R101')
        print("\n✅ Validated: Student 0007 ACCEPTED in Piano room.")

if __name__ == '__main__':
    unittest.main()
