"""
TDD Test: Export Logic — Correct Studio Detection and Data Completeness

Tests that build_export_dataframe() correctly:
1. Detects Studio events even when mislabeled as 'weekly_lesson'
2. Extracts Time from ISO format as fallback
3. Includes Instrument for Studio events
4. Correctly separates Weekly and Studio in filtered exports
"""

import pytest
import pandas as pd
from modules.scheduler.logic.export_generator import build_export_dataframe


@pytest.fixture
def mixed_bookings():
    """Realistic bookings data including misclassified Studio events."""
    return [
        # Normal Weekly
        {
            "id": "wk_student1",
            "type": "weekly_lesson",
            "resourceId": "R101",
            "title": "👤 Student 0001 (Piano)",
            "startTime": "14:00:00",
            "endTime": "15:00:00",
            "daysOfWeek": [3],
            "extendedProps": {
                "Instructor": "Instructor 0001",
                "Student Name": "Student 0001",
                "Student No": "S001",
                "Instrument": "Piano",
                "Study Year": "2",
                "Course Code": "MUSC1001",
                "day_en": "Wednesday"
            }
        },
        # Normal Studio
        {
            "id": "stu_drA_1_0_opt",
            "type": "studio_class",
            "resourceId": "R101",
            "title": "🎹 Studio: Instructor 0001",
            "start": "2026-03-04T18:00:00",
            "end": "2026-03-04T19:00:00",
            "extendedProps": {
                "Instructor": "Instructor 0001",
                "is_studio": True,
                "Class Time": "18:00-19:00"
            }
        },
        # MISCLASSIFIED Studio (has type=weekly_lesson but is actually Studio)
        {
            "id": "manual_N/A_(Studio)_8",
            "type": "weekly_lesson",
            "resourceId": "R104",
            "title": "👤 N/A (Studio) (Piano)",
            "startTime": "12:00:00",
            "endTime": "13:00:00",
            "daysOfWeek": [1],
            "extendedProps": {
                "Instructor": "Instructor 0002",
                "Student Name": "N/A (Studio)",
                "Instrument": "Piano",
                "day_en": "Monday"
            }
        },
        # Another misclassified Studio
        {
            "id": "manual_N/A_(Studio)_4",
            "type": "weekly_lesson",
            "resourceId": "R105",
            "title": "👤 N/A (Studio) (Piano)",
            "startTime": "18:00:00",
            "endTime": "19:00:00",
            "daysOfWeek": [3],
            "extendedProps": {
                "Instructor": "Instructor 0001",
                "Student Name": "N/A (Studio)",
                "Instrument": "Piano",
                "day_en": "Wednesday"
            }
        },
    ]


class TestExportTypeDetection:
    """Export should detect Studio events regardless of 'type' field."""

    def test_weekly_only_excludes_misclassified_studio(self, mixed_bookings):
        """
        When filtering for 'weekly_lesson', events with 'Studio' in title
        should NOT appear.
        """
        weekly = [b for b in mixed_bookings if b.get('type') == 'weekly_lesson']
        df = build_export_dataframe(weekly, [], {}, [])
        
        # Should only have real weekly lessons (Student 0001), not Studio
        studio_rows = df[df['Event Type'] == 'Studio Class']
        weekly_rows = df[df['Event Type'] == 'Weekly Lesson']
        
        assert len(studio_rows) >= 2, (
            f"Expected at least 2 Studio rows (the misclassified ones) but got {len(studio_rows)}"
        )
        assert len(weekly_rows) == 1, (
            f"Expected 1 real Weekly row but got {len(weekly_rows)}"
        )

    def test_studio_only_includes_misclassified_studio(self, mixed_bookings):
        """
        Studio export should include both properly typed and misclassified Studio.
        """
        # In the real app, the filtering happens BEFORE build_export_dataframe
        # But build_export_dataframe should recognize misclassified ones
        df = build_export_dataframe(mixed_bookings, [], {}, [])
        studio_rows = df[df['Event Type'] == 'Studio Class']
        
        # Normal studio + 2 misclassified = at least 3
        assert len(studio_rows) >= 3

    def test_studio_has_time(self, mixed_bookings):
        """All Studio events should have Time filled in."""
        df = build_export_dataframe(mixed_bookings, [], {}, [])
        studio_rows = df[df['Event Type'] == 'Studio Class']
        
        for _, row in studio_rows.iterrows():
            assert row['Time'] and str(row['Time']).strip(), (
                f"Studio row for {row['Instructor']} has empty Time"
            )

    def test_studio_has_instrument(self, mixed_bookings):
        """Studio Instrument should not be empty when available in props."""
        df = build_export_dataframe(mixed_bookings, [], {}, [])
        studio_rows = df[df['Event Type'] == 'Studio Class']
        
        # The misclassified studios have 'Piano' in props
        for _, row in studio_rows.iterrows():
            if row['Instructor'] in ['Instructor 0002', 'Instructor 0001']:
                assert row['Instrument'] == 'Piano', (
                    f"Studio for {row['Instructor']} should have Instrument=Piano"
                )

    def test_studio_has_day(self, mixed_bookings):
        """All Studio events should have Day filled in."""
        df = build_export_dataframe(mixed_bookings, [], {}, [])
        studio_rows = df[df['Event Type'] == 'Studio Class']
        
        for _, row in studio_rows.iterrows():
            assert row['Day'] and str(row['Day']).strip(), (
                f"Studio row for {row['Instructor']} has empty Day"
            )
