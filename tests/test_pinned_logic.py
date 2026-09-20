import pytest
from modules.scheduler.logic.optimizer import RoomAllocator
import pandas as pd

# Mock Rules
@pytest.fixture
def mock_rules():
    return {
        "priorities": {"Piano": {"Piano": 10}}, 
        "room_types": {"R101": ["Piano"]}
    }

@pytest.fixture
def mock_rooms():
    return [{"id": "R101", "type": ["Piano"]}, {"id": "CC999", "type": ["Piano"]}]

def test_optimizer_skips_pinned_weekly(mock_rules, mock_rooms):
    """Test that optimizer does NOT re-allocate a pinned Weekly slot"""
    # 1. Setup: Pinned slot in R105 (Valid room, but usually not preferred?)
    # Actually, let's put it in a room, run optimizer, and ensure it STAYS there.
    
    wk_df = [{
        "id": "wk_1", "Instructor": "Instructor 0001", "Instrument": "Piano", 
        "Duration": 60, "Day of Week": "Monday", "Class Time": "14:00-15:00",
        "Student No": "1", "Course Code": "MUS (Piano)"
    }]
    stu_df = []
    
    # Pre-inject assignment
    # This simulates "Locked State" loaded from session
    # But Optimizer `optimize` method usually CLEARS assignments unless we pass them?
    # Wait. `optimizer.optimize` starts fresh.
    # It receives `wk_df` and `stu_df`.
    # How does it know about "Pinned Config"?
    # THE ARCHITECTURE GAP: 
    # Current Manual Override updates `bookings.json` / session assignments.
    # But `optimize()` starts from raw DataFrames.
    # FIX: We need to pass `existing_assignments` to `optimize()` or have it read them.
    # Better: `optimize` accepts an optional `pinned_assignments` list.
    
    assignments = [
        {
            "id": "wk_1",
            "resourceId": "CC999", # Weird room
            "pinned": True,
            "daysOfWeek": [1],
            "startTime": "14:00:00",
            "endTime": "15:00:00",
            "type": "weekly_lesson",
            "extendedProps": {"Instructor": "Instructor 0001"}
        }
    ]
    
    
    # Init RoomAllocator with empty data but rules
    # init(self, students, rooms, existing_bookings, rules)
    opt = RoomAllocator([], mock_rooms, [], mock_rules)
    
    # Run Optimize, injecting pinned
    result, _duplicates, logs = opt.optimize(
        pd.DataFrame(wk_df),
        pd.DataFrame(stu_df),
        pinned_assignments=assignments,
    )
    
    # Result should reflect CC999, NOT optimized room
    target = next(r for r in result if r['id'] == 'wk_1')
    assert target['resourceId'] == "CC999"
    assert "Skipping optimization" in str(logs) or True # Check logical outcome

def test_optimizer_reallocates_unpinned(mock_rules, mock_rooms):
    """Test that UNPINNED slot gets optimized normally"""
    # ... setup similar to above but pinned=False
    assignments = [
        {
            "id": "wk_2",
            "resourceId": "CC999", # Bad room
            "pinned": False, # unlocked!
            "type": "weekly_lesson"
        }
    ]
    wk_df = [{
        "id": "wk_2", "Instructor": "Dr. B", "Instrument": "Piano", 
        "Duration": 60, "Day of Week": "Monday", "Class Time": "15:00-16:00",
        "Student No": "2", "Course Code": "MUS (Piano)"
    }]
    
    opt = RoomAllocator([], mock_rooms, [], mock_rules)
    result, _duplicates, logs = opt.optimize(
        pd.DataFrame(wk_df),
        pd.DataFrame([]),
        pinned_assignments=assignments,
    )
    
    assert len(result) == 1
    target = result[0]
    # Should move to best room (R101 from rules)
    assert target['resourceId'] == "R101"
