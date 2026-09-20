"""Legacy/experimental CSP adapter.

This path is kept for backward compatibility and diagnostics only.
"""

from modules.shared.csp_scheduler import CSPScheduler


def run_legacy_auto_schedule(loader, rules, clear_existing=False):
    warnings = [
        "Legacy CSP path is experimental and not the mainline scheduler.",
        "Use RoomAllocator-based scheduling for supported workflows.",
    ]
    try:
        students = loader.get_data("students.json")
        rooms = loader.get_data("rooms.json")
        existing = loader.load_bookings()
        if clear_existing:
            existing = [e for e in existing if not e.get("extendedProps", {}).get("auto_generated")]

        solver = CSPScheduler(students, rooms, existing)
        result = {
            "mode": "legacy_csp",
            "is_legacy": True,
            "is_experimental": True,
            "warnings": warnings,
        }

        if not solver.solve():
            result.update({"status": "error", "message": "❌ Legacy experimental CSP found no solution."})
            return result

        new_assignments = []
        for sid, (rid, day, hour) in solver.assignments.items():
            student = next((x for x in students if x["student_id"] == sid), {})
            new_assignments.append(
                {
                    "id": f"auto_{sid}",
                    "title": f"👤 {student.get('name_en')} (Auto)",
                    "resourceId": rid,
                    "startTime": f"{hour:02d}:00:00",
                    "endTime": f"{hour+1:02d}:00:00",
                    "daysOfWeek": [day],
                    "type": "weekly_lesson",
                    "extendedProps": {
                        "auto_generated": True,
                        "generator": "legacy_csp",
                        "instructor": student.get("instructor"),
                    },
                }
            )

        loader.save_bookings(existing + new_assignments)
        result.update(
            {
                "status": "success",
                "message": f"✅ Legacy experimental CSP produced {len(new_assignments)} lessons.",
            }
        )
        return result
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Legacy experimental CSP error: {exc}",
            "mode": "legacy_csp",
            "is_legacy": True,
            "is_experimental": True,
            "warnings": warnings,
        }
