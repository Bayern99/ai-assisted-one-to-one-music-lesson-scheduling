from modules.scheduler.logic.provenance import build_step3_provenance_status


def test_build_step3_provenance_status_warns_on_digest_drift_and_shadow_paths():
    status = build_step3_provenance_status(
        {
            "uploads": {
                "weekly": {"filename": "current.xlsx", "digest": "new-digest"},
                "studio": {"filename": "current.xlsx", "digest": "new-digest"},
            },
            "master_data_sync": {
                "rooms": {
                    "status": "synced",
                    "workbook_filename": "old.xlsx",
                    "workbook_digest": "old-digest",
                    "save_source": "shadow",
                    "save_target_path": "/tmp/shadow/rooms.json",
                    "verified": True,
                },
                "students": {
                    "status": "synced",
                    "workbook_filename": "current.xlsx",
                    "workbook_digest": "new-digest",
                    "save_source": "primary",
                    "save_target_path": "/tmp/data/students.json",
                    "verified": True,
                },
                "instructors": {
                    "status": "synced",
                    "workbook_filename": "current.xlsx",
                    "workbook_digest": "new-digest",
                    "save_source": "primary",
                    "save_target_path": "/tmp/data/instructors.json",
                    "verified": True,
                },
                "courses": {
                    "status": "synced",
                    "workbook_filename": "current.xlsx",
                    "workbook_digest": "new-digest",
                    "save_source": "primary",
                    "save_target_path": "/tmp/data/courses.json",
                    "verified": True,
                },
            },
        },
        {"room_types": {}},
    )

    warning_text = "\n".join(status["warnings"])
    summary_text = "\n".join(status["summary"])
    assert "does not match the active upload digest" in warning_text
    assert "shadow save path" in warning_text
    assert "rooms synced from `old.xlsx`" in summary_text
    assert "students synced from `current.xlsx`" in summary_text
    assert "instructors synced from `current.xlsx`" in summary_text
    assert "courses synced from `current.xlsx`" in summary_text


def test_build_step3_provenance_status_flags_manual_room_type_overrides():
    status = build_step3_provenance_status(
        {"uploads": {}, "master_data_sync": {}},
        {"room_types": {"R103": ["Piano"]}},
    )

    assert any("Manual room-type overrides are active" in item for item in status["warnings"])
