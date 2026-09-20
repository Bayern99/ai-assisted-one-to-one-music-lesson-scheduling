def test_conflict_validator_with_full_duration():
    from modules.scheduler.logic.conflict_validator import ConflictValidator

    existing = [{
        "resourceId": "R101",
        "daysOfWeek": [1],
        "startTime": "14:00:00",
        "endTime": "16:00:00",
        "type": "weekly_lesson",
        "title": "Existing 2H"
    }]

    validator = ConflictValidator({'assignments': existing, 'lectures': [], 'rules': {}})
    conflict = validator.check_conflict("R101", 1, 900, 960)
    assert conflict is not None
    assert conflict['title'] == "Existing 2H"

    clean = validator.check_conflict("R101", 1, 960, 1020)
    assert clean is None
