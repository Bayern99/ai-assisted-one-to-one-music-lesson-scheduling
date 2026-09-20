import pytest
from modules.scheduler.logic.manual_override_legacy import ManualOverrider
from modules.scheduler.logic.conflict_validator import ConflictValidator

# Dummy Data
@pytest.fixture
def override_setup():
    data = {
        "assignments": [
            {
                "id": "wk_101",
                "resourceId": "R101",
                "daysOfWeek": [1],
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "type": "weekly_lesson",
                "extendedProps": {"Instructor": "Instructor 0001", "Instrument": "Piano"}
            }
        ],
        "lectures": [],
        "rules": {"room_types": {"R105": ["Piano"]}},
        "unassigned_lessons": [] # Support for tracking unassigned
    }
    validator = ConflictValidator(data)
    overrider = ManualOverrider(data, validator)
    return overrider, data

def test_unassign_slot(override_setup):
    """Test removing a slot (Unassign)"""
    overrider, data = override_setup
    
    # Unassign
    res = overrider.unassign_slot("wk_101")
    assert res is True
    
    # Check removed from assignments
    in_assignments = any(a['id'] == "wk_101" for a in data['assignments'])
    assert not in_assignments
    
    # Check added to unassigned
    in_unassigned = any(a['id'] == "wk_101" for a in data['unassigned_lessons'])
    assert in_unassigned

def test_undo_unassign(override_setup):
    """Test undoing an unassign action"""
    overrider, data = override_setup
    
    # 1. Unassign
    overrider.unassign_slot("wk_101")
    assert len(data['assignments']) == 0
    assert len(data['unassigned_lessons']) == 1
    
    # 2. Undo
    overrider.undo()
    
    # Verify Restored
    assert len(data['assignments']) == 1
    assert len(data['unassigned_lessons']) == 0
    assert data['assignments'][0]['id'] == "wk_101"

def test_move_weekly_to_empty_slot(override_setup):
    """Test standard move of a Weekly lesson"""
    overrider, data = override_setup
    
    # Move wk_101 to R105 - Mon 14:00 (Same time, diff room)
    result = overrider.move_slot(
        slot_id="wk_101",
        new_room_id="R105",
        new_day_idx=1,
        new_start_str="14:00:00", 
        new_end_str="15:00:00"
    )
    
    assert result['success'] is True
    
    # Check Data
    evt = next(e for e in data['assignments'] if e['id'] == "wk_101")
    assert evt['resourceId'] == "R105"
    assert evt['pinned'] is True # MUST be pinned

def test_move_fails_with_conflict(override_setup):
    """Test move rejected by validator"""
    overrider, data = override_setup
    
    # Clog R105 with a blocker
    data['assignments'].append({
        "id": "blocker", "resourceId": "R105", "daysOfWeek": [1], 
        "startTime": "14:00:00", "endTime": "15:00:00", "type": "weekly_lesson"
    })
    
    # Try move wk_101 to R105 (Occupied)
    result = overrider.move_slot(
        slot_id="wk_101", 
        new_room_id="R105",
        new_day_idx=1, 
        new_start_str="14:00:00", 
        new_end_str="15:00:00"
    )
    
    assert result['success'] is False
    assert "Conflict" in result['message']
    
    # Check Data (Unchanged)
    evt = next(e for e in data['assignments'] if e['id'] == "wk_101")
    assert evt['resourceId'] == "R101"

def test_granular_move_split_block(override_setup):
    """Test moving only PART of a block (Granularity)"""
    # TODO: This requires splitting logic. 
    # For MVP Phase 2, we assume 'Whole Slot' move first.
    # Granular test will be added in Phase 2.5
    pass

def test_audit_log_created(override_setup):
    """Test that a record is added to history"""
    overrider, data = override_setup
    
    overrider.move_slot("wk_101", "R105", 1, "14:00:00", "15:00:00")
    
    assert len(overrider.history) == 1
    assert overrider.history[0]['action'] == 'move'
    assert overrider.history[0]['slot_id'] == 'wk_101'

def test_unlock_slot(override_setup):
    """Test Unlocking a pinned slot"""
    overrider, data = override_setup
    
    # 1. Pin it
    overrider.move_slot("wk_101", "R105", 1, "14:00:00", "15:00:00")
    assert data['assignments'][0]['pinned'] is True
    
    # 2. Unlock
    overrider.unlock_slot("wk_101")
    assert data['assignments'][0].get('pinned') is False
