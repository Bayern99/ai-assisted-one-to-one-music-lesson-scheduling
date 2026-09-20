"""
Diagnostic Script: Detect Ghost Lessons in Conflict Validator

Purpose: Identify why validator reports conflicts with non-existent lessons

Usage:
1. Call dump_validator_state() before conflict check
2. Analyze output to find ghost lessons
3. Identify root cause of stale data
"""

import json
from datetime import datetime

def dump_validator_state(validator, room_id=None, day_idx=None):
    """
    Dump complete state of ConflictValidator for debugging
    
    Args:
        validator: ConflictValidator instance
        room_id: Optional - filter to specific room
        day_idx: Optional - filter to specific day
    """
    print(f"\n{'='*80}")
    print(f"[DIAGNOSTIC] ConflictValidator State Dump - {datetime.now().isoformat()}")
    print(f"{'='*80}\n")
    
    print(f"Total Assignments in Memory: {len(validator.assignments)}")
    print(f"Total Lectures in Memory: {len(validator.lectures)}")
    
    print(f"\n--- ASSIGNMENTS ---")
    for idx, a in enumerate(validator.assignments):
        # Filter if requested
        if room_id and a.get('resourceId') != room_id:
            continue
        if day_idx is not None and day_idx not in a.get('daysOfWeek', []):
            continue
            
        print(f"\n{idx}. ID: {a.get('id')}")
        print(f"   Room: {a.get('resourceId')}")
        print(f"   Days: {a.get('daysOfWeek')} (0=Sun JS convention)")
        print(f"   Time: {a.get('startTime')} - {a.get('endTime')}")
        print(f"   Title: {a.get('title')}")
        
        # Check for possible stale data
        props = a.get('extendedProps', {})
        instructor = props.get('Instructor', 'Unknown')
        print(f"   Instructor: {instructor}")
        
        # Flag potential ghosts
        if 'pinned' in a and not a['pinned']:
            print(f"   ⚠️  UNPINNED (might be stale)")
        if props.get('auto_generated'):
            print(f"   🤖 AUTO-GENERATED")
    
    print(f"\n--- LECTURES (Locked) ---")
    for idx, lec in enumerate(validator.lectures):
        if room_id and lec.get('resourceId') != room_id:
            continue
        if day_idx is not None and day_idx not in lec.get('daysOfWeek', []):
            continue
            
        print(f"\n{idx}. ID: {lec.get('id')}")
        print(f"   Room: {lec.get('resourceId')}")
        print(f"   Days: {lec.get('daysOfWeek')}")
        print(f"   Time: {lec.get('startTime')} - {lec.get('endTime')}")
        print(f"   Title: {lec.get('title')}")
    
    print(f"\n{'='*80}\n")

def verify_instructor_schedule(validator, instructor_name, day_idx):
    """
    Verify what lessons an instructor actually has on a specific day
    """
    print(f"\n[VERIFY] Lessons for {instructor_name} on Day {day_idx}")
    print(f"=" * 80)
    
    found_lessons = []
    
    for a in validator.assignments:
        props = a.get('extendedProps', {})
        if props.get('Instructor') == instructor_name:
            if day_idx in a.get('daysOfWeek', []):
                found_lessons.append(a)
                print(f"  ✓ {a.get('startTime')} - {a.get('endTime')} at {a.get('resourceId')}")
    
    if not found_lessons:
        print(f"  ❌ NO LESSONS FOUND")
        print(f"  → If conflict reported, this is a GHOST LESSON BUG")
    else:
        print(f"\n  Total: {len(found_lessons)} lessons")
    
    return found_lessons

# HOW TO USE IN scheduling.py:
"""
# Import at top:
from tests.diagnostic_validator_dump import dump_validator_state, verify_instructor_schedule

# Before conflict check:
print("\\n[DEBUG] About to check conflict:")
print(f"  Room: {new_room}")
print(f"  Day: {detected_day} (0=Sun JS)")
print(f"  Time: {f_start}-{f_end}")

# Dump validator state filtered to this room+day:
dump_validator_state(validator, room_id=new_room, day_idx=detected_day)

# If conflict reported, verify instructor schedule:
if conflict:
    instructor = conflict.get('extendedProps', {}).get('Instructor')
    if instructor:
        verify_instructor_schedule(validator, instructor, detected_day)
"""
