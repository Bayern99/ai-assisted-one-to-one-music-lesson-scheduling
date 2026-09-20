"""
TDD: Reconciliation Logic (正本清源)
Goal: Verify detection of Phantom Lessons (Optimization Artifacts) and Missing Lessons.

Scenario:
- Raw Data: Instructor 0011 has lessons at 11:00, 13:00 (Gap at 12:00-13:00).
- Assignment Data: Optimizer bridges gap -> 11:00-14:00 (Includes 12:00-13:00 Phantom).
- Checker MUST flag 12:00-13:00 as 'Phantom'.
"""

import sys
import os
import pandas as pd
import unittest
from datetime import datetime

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Logic to test (will be implemented later)
# from modules.scheduler.logic.reconciliation_checker import reconcile_assignments

class TestReconciliation(unittest.TestCase):
    
    def setUp(self):
        # 1. Mock Raw Spreadsheet Data (Instructor 0011's Schedule)
        # 11:00-12:00, Gap, 13:00-14:00
        self.raw_df = pd.DataFrame([
            {
                'Student Name': 'S1', 'Student No': '101', 'Instructor': 'Instructor 0011',
                'Class Time': '11:00-12:00', 'Day of Week': 'Thursday',
                'Course Code': 'STU'
            },
            {
                'Student Name': 'S2', 'Student No': '102', 'Instructor': 'Instructor 0011',
                'Class Time': '13:00-14:00', 'Day of Week': 'Thursday',
                'Course Code': 'STU'
            }
        ])
        
        # 2. Mock Optimized Assignments (Bridged Gap)
        # Optimizer outputs 3 atomic 1-hour blocks because of bridge logic 
        # (assuming Atomic Fix is active, splitting won't happen, but bridge creates the extra hour)
        # Wait - if Atomic Fix is active, optimizer outputs BLOCKS.
        # But `_create_assignment` happens per LESSON in the block.
        # If the gap was bridged, did it create a fake lesson object?
        # NO. `_splice_into_blocks` creates a BLOCK of lessons.
        # `_finalize_block` sums duration.
        # But `optimize` loop iterates `block['lessons']`.
        # The phantom hour exists only if `lessons` list contains it?
        # AHH. If spreadsheet doesn't have the row, `lessons` won't have it.
        # So where does the phantom 12:00 come from?
        #
        # Re-reading Optimizer:
        # `_splice_into_blocks` groups EXISTING lessons.
        # It does NOT inject new lessons into `block['lessons']`.
        # It just says "This group of lessons is one block".
        #
        # SO: If 12:00-13:00 row is MISSING in spreadsheet, `optimizer` does NOT create it.
        # THEN WHY did user report Instructor 0011 has 12:00-13:00 in output?
        #
        # Hypothesis:
        # 1. User Spreadsheet actually HAS 12:00 but user thinks not?
        # 2. Or `_create_assignment` uses `block.start` / `block.end` to overwrite lesson times?
        # Let's check `_create_assignment`.
        # It uses `lesson['start']` and `lesson['end']`.
        #
        # Wait, if `_solve_fragmented_block_min_switches` or fallback determines splitting...
        #
        # Let's look at `_finalize_studio_merge` (PRE-FIX) -> It DID create merged slots.
        # The User said "Instructor 0011... 11-12, 13-14... middle no 12-13. System fill in."
        #
        # If the system FILLED IN a slot, it must have INSTANTIATED an event object.
        # WHERE?
        #
        # Maybe `_expand_weekly_slots`? 
        # Or maybe the user input actually implies it?
        #
        # Let's assume for this TDD that we HAVE a Phantom Assignment (id='phantom_12')
        # regardless of how it got there. The Checker must catch it.
        
        self.assignments = [
            # Real 11:00
            {
                'id': 'real_11',
                'title': '👤 S1 (Instructor 0011)',
                'startTime': '11:00:00', # Weekly format
                'type': 'weekly_lesson',
                'extendedProps': {
                    'source_request_id': 'weekly:0',
                    'Student No': '101', 'Class Time': '11:00-12:00', 'Instructor': 'Instructor 0011', 
                    'Day of Week': 'Thursday'
                }
            },
            # PHANTOM 12:00 (The Bug)
            {
                'id': 'phantom_12',
                'title': '👤 Phantom (Instructor 0011)',
                'startTime': '12:00:00',
                'type': 'weekly_lesson',
                'extendedProps': {
                    # Phantom might carry copied props or be empty/auto-gen
                    'source_request_id': 'weekly:phantom',
                    'Student No': '101', # Maybe copied?
                    'Class Time': '12:00-13:00', # Generated time?
                    'Instructor': 'Instructor 0011',
                    'Day of Week': 'Thursday',
                    'auto_generated': True
                }
            },
            # Real 13:00
            {
                'id': 'real_13',
                'title': '👤 S2 (Instructor 0011)',
                'startTime': '13:00:00',
                'type': 'weekly_lesson',
                'extendedProps': {
                    'source_request_id': 'weekly:1',
                    'Student No': '102', 'Class Time': '13:00-14:00', 'Instructor': 'Instructor 0011',
                    'Day of Week': 'Thursday'
                }
            }
        ]

    def test_phantom_detection(self):
        # Import target (simulated failure first)
        try:
            from modules.scheduler.logic.reconciliation_checker import reconcile_assignments
        except ImportError:
            self.fail("Implementation module not found (Expected for TDD Step 1)")
            
        report = reconcile_assignments(self.raw_df, self.assignments)
        
        # Expectation:
        # 1. real_11 -> Match
        # 2. real_13 -> Match
        # 3. phantom_12 -> PHANTOM
        
        phantoms = report["phantom"]
        matches = report["matches"]

        self.assertEqual(len(matches), 2, "Should match 2 real lessons")
        self.assertEqual(len(phantoms), 1, "Should detect 1 phantom lesson")
        self.assertEqual(phantoms[0]['assignment_id'], 'phantom_12')
        self.assertFalse(report["is_valid"])
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["phantom_count"], 1)
        self.assertEqual(report["blocking_reason_codes"], ["phantom_result"])
        print("✅ Phantom Detection Verified")

if __name__ == '__main__':
    unittest.main()
