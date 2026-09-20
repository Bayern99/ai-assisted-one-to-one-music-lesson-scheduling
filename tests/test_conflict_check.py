import pytest
from datetime import datetime
from modules.scheduler.logic.conflict_validator import ConflictValidator

# Dummy Scheduler Data for Testing
@pytest.fixture
def mock_scheduler_data():
    return {
        "assignments": [
            {
                "id": "existing_1",
                "resourceId": "R101",
                "startTime": "14:00:00",
                "endTime": "15:00:00",
                "daysOfWeek": [1], # Monday
                "type": "weekly_lesson"
            },
            {
                "id": "existing_2",
                "resourceId": "R105",
                "start": "2026-03-04T10:00:00",
                "end": "2026-03-04T12:00:00",
                "type": "studio_class"
            }
        ],
        "lectures": [
            {
                "resourceId": "R101",
                "daysOfWeek": [2], # Tuesday
                "startTime": "09:00:00",
                "endTime": "11:00:00",
                "title": "LOCKED LECTURE"
            }
        ],
        "rules": {
            "room_types": {
                "R101": ["Piano", "Voice"], # Piano Only
                "R105": ["Instrumental", "Percussion"] # Non-Piano
            }
        }
    }

def test_detect_weekly_overlap(mock_scheduler_data):
    """Test detecting overlap with a Weekly lesson"""
    validator = ConflictValidator(mock_scheduler_data)
    
    # Try to move here: Mon 14:00-15:00 R101 (Occupied by existing_1)
    conflict = validator.check_conflict(
        room_id="R101",
        day_idx=1, # Mon
        start_min=14*60, # 14:00
        end_min=15*60,
        specific_date=None
    )
    
    assert conflict is not None
    assert conflict['type'] == 'weekly_lesson'
    assert conflict['id'] == 'existing_1'

def test_detect_studio_overlap(mock_scheduler_data):
    """Test detecting overlap with a Studio class (Specific Date)"""
    validator = ConflictValidator(mock_scheduler_data)
    
    # Try to move roughly Wed Mar 4 10:30 (Inside existing_2)
    # 2026-03-04 is a Wednesday (day_idx=2 for Py, but let's assume validator handles date check properly)
    
    conflict = validator.check_conflict(
        room_id="R105",
        day_idx=2, # Wed
        start_min=10*60 + 30, # 10:30
        end_min=11*60,
        specific_date="2026-03-04"
    )
    
    assert conflict is not None
    assert conflict['type'] == 'studio_class'
    assert conflict['id'] == 'existing_2'

def test_detect_lecture_overlap(mock_scheduler_data):
    """Test detecting overlap with a Locked Lecture"""
    validator = ConflictValidator(mock_scheduler_data)
    
    # Try to move Tue 09:30 R101
    conflict = validator.check_conflict(
        room_id="R101",
        day_idx=2, 
        start_min=9*60 + 30,
        end_min=10*60,
        specific_date=None
    )
    
    assert conflict is not None
    assert conflict['is_locked_lecture'] == True

def test_valid_slot_no_conflict(mock_scheduler_data):
    """Test a perfectly valid empty slot"""
    validator = ConflictValidator(mock_scheduler_data)
    
    # Mon 08:00 R101 (Empty)
    conflict = validator.check_conflict(
        room_id="R101",
        day_idx=1,
        start_min=8*60,
        end_min=9*60,
        specific_date=None
    )
    
    assert conflict is None

def test_room_type_rules(mock_scheduler_data):
    """Test validating instrument vs room type"""
    validator = ConflictValidator(mock_scheduler_data)
    
    # Piano into Piano Room -> OK
    valid = validator.validate_rules(
        room_id="R101", 
        instrument="Piano"
    )
    assert valid["allowed"] is True
    
    # Tuba into Piano Room -> Warn/Fail
    invalid = validator.validate_rules(
        room_id="R101",
        instrument="Tuba"
    )
    assert invalid["allowed"] is False
    assert "Room Type Mismatch" in invalid["reason"]


def test_room_type_rules_treats_missing_instrument_as_generic_instrumental(mock_scheduler_data):
    validator = ConflictValidator(mock_scheduler_data)

    invalid = validator.validate_rules(
        room_id="R101",
        instrument=None,
    )

    assert invalid["allowed"] is False
    assert "Instrumental" in invalid["reason"]


def test_check_conflict_exclude_id_skips_the_event_itself(mock_scheduler_data):
    """Moving an event onto its own current slot must not conflict with itself."""
    validator = ConflictValidator(mock_scheduler_data)

    conflict = validator.check_conflict(
        room_id="R101",
        day_idx=1,
        start_min=14 * 60,
        end_min=15 * 60,
        specific_date=None,
        exclude_id="existing_1",
    )

    assert conflict is None


def test_check_conflict_exclude_id_still_detects_other_events(mock_scheduler_data):
    other = {
        "id": "existing_3",
        "resourceId": "R101",
        "startTime": "14:30:00",
        "endTime": "15:30:00",
        "daysOfWeek": [1],
        "type": "weekly_lesson",
    }
    data = dict(mock_scheduler_data)
    data["assignments"] = list(mock_scheduler_data["assignments"]) + [other]
    validator = ConflictValidator(data)

    conflict = validator.check_conflict(
        room_id="R101",
        day_idx=1,
        start_min=14 * 60,
        end_min=15 * 60,
        specific_date=None,
        exclude_id="existing_1",
    )

    assert conflict is not None
    assert conflict["id"] == "existing_3"


def test_malformed_existing_assignment_time_blocks_manual_override_fail_closed(mock_scheduler_data):
    bad_data = dict(mock_scheduler_data)
    bad_data["assignments"] = list(mock_scheduler_data["assignments"]) + [
        {
            "id": "broken_evt",
            "resourceId": "CC322",
            "startTime": "bad",
            "endTime": "15:00:00",
            "daysOfWeek": [1],
            "type": "weekly_lesson",
            "title": "Broken Event",
        }
    ]

    validator = ConflictValidator(bad_data)
    conflict = validator.check_conflict(
        room_id="CC322",
        day_idx=1,
        start_min=14 * 60,
        end_min=15 * 60,
        specific_date=None,
    )

    assert conflict is not None
    assert conflict.get("is_malformed_time") is True
    assert conflict.get("id") == "broken_evt"
