
import pytest
from datetime import datetime
import sys
import os

sys.path.append(os.getcwd())

from modules.scheduler.logic.manual_override_legacy import ManualOverrider
from modules.scheduler.logic.conflict_validator import ConflictValidator

def mock_data_no_self():
    return {
        'assignments': [
            # Only the OBSTACLE (Studio Class)
            # The "Moving Event" is phantom (parameters passed to check_conflict)
            {
                'id': 'studio_1',
                'type': 'studio_class',
                'resourceId': 'R103',
                'start': '2026-05-04T10:30:00', # Mon May 4th
                'end': '2026-05-04T11:30:00',
                'title': 'Studio Class'
            }
        ],
        'lectures': [],
        'rules': {}
    }

def test_conflict_weekly_vs_specific_date():
    data = mock_data_no_self()
    validator = ConflictValidator(data)
    
    # Move a hypothetical Weekly Lesson to Mon 10:00-11:00
    # Should conflict with Studio (Mon 10:30-11:30)
    conflict = validator.check_conflict(
        room_id='R103',
        day_idx=1, # Mon
        start_min=600, # 10:00
        end_min=660,   # 11:00
        specific_date=None # Weekly
    )
    
    assert conflict is not None, "Weekly move MUST detect conflict with future Studio date"
    assert conflict['id'] == 'studio_1'

def test_undo_granularity():
    # ... (Keep existing passing test)
    data = {
        'assignments': [
            {'id':'w1', 'resourceId':'R1', 'type':'weekly_lesson', 'daysOfWeek':[1], 'startTime':'10:00','endTime':'11:00'}
        ],
        'rules': {}
    }
    overrider = ManualOverrider(data)
    w1 = data['assignments'][0]
    
    overrider.move_slot('w1', 'R2', 1, '10:00', '11:00')
    assert w1['resourceId'] == 'R2'
    
    overrider.move_slot('w1', 'R3', 1, '10:00', '11:00')
    assert w1['resourceId'] == 'R3'
    
    overrider.undo()
    assert w1['resourceId'] == 'R2' # Granular Undo
    
    overrider.undo()
    assert w1['resourceId'] == 'R1' # Back to start
