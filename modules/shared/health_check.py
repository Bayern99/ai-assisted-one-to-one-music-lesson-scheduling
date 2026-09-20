"""
Startup health check for AI-Assisted One-to-One Music Lesson Scheduling.
Runs at app startup to verify system readiness for low-frequency users.
"""
import os
import logging

logger = logging.getLogger(__name__)

CRITICAL_IMPORTS = [
    ("pandas", "Data processing"),
    ("fastapi", "Local API framework"),
    ("openpyxl", "Excel reading"),
    ("xlsxwriter", "Excel writing"),
]

RECOMMENDED_FILES = [
    "rooms.json",
    "workflow_state.json",
]


def run_health_check(base_dir="data"):
    """Run system health check. Returns {status, checks, recommendations}."""

    checks = []
    recommendations = []

    # 1. Data directory exists and is writable
    data_ok = os.path.isdir(base_dir) and os.access(base_dir, os.W_OK)
    checks.append({
        "name": "Data Directory",
        "status": "ok" if data_ok else "error",
        "detail": f"data/ {'exists and writable' if data_ok else 'missing or not writable'}"
    })
    if not data_ok:
        recommendations.append("Data directory missing. Check project setup.")

    # 2. Critical Python imports
    for mod_name, desc in CRITICAL_IMPORTS:
        try:
            __import__(mod_name)
            checks.append({"name": f"Import: {desc}", "status": "ok",
                           "detail": f"{mod_name} available"})
        except ImportError:
            checks.append({"name": f"Import: {desc}", "status": "error",
                           "detail": f"{mod_name} not installed"})
            recommendations.append(f"Missing dependency: {mod_name}. Run: pip install {mod_name}")

    # 3. Check for shadow-as-primary situation
    abs_base = os.path.abspath(base_dir)
    shadow_dir = os.path.join(os.path.dirname(abs_base), ".runtime_shadow_data")

    data_entries = []
    data_probe_error = False
    if data_ok:
        try:
            data_entries = os.listdir(base_dir)
        except OSError:
            data_probe_error = True

    shadow_entries = []
    shadow_probe_error = False
    if os.path.isdir(shadow_dir):
        try:
            shadow_entries = os.listdir(shadow_dir)
        except OSError:
            shadow_probe_error = True

    has_data_files = any(
        f.endswith('.json')
        for f in data_entries
        if f.startswith(('bookings', 'students', 'rooms'))
    )
    has_shadow_files = any(f.endswith('.json') for f in shadow_entries)

    if data_probe_error:
        checks.append({
            "name": "Data Files Location",
            "status": "error",
            "detail": "Could not inspect data directory"
        })
        recommendations.append("Check data directory read permissions.")
    elif has_shadow_files and not has_data_files:
        checks.append({
            "name": "Shadow as Primary",
            "status": "warning",
            "detail": "Data files found only in .runtime_shadow_data/, not data/. "
                      "This may indicate a previous write failure."
        })
        recommendations.append(
            "Your data is stored in the shadow directory (.runtime_shadow_data/). "
            "Consider checking if the main data/ directory is writable."
        )
    else:
        checks.append({
            "name": "Data Files Location",
            "status": "ok" if has_data_files else "warning",
            "detail": "Data files in expected location" if has_data_files else "No data files found yet (normal for first run)"
        })

    if shadow_probe_error:
        checks.append({
            "name": "Shadow Data Location",
            "status": "error",
            "detail": "Could not inspect shadow data directory"
        })
        recommendations.append("Check shadow data directory read permissions.")

    # 4. Check for temp file leaks
    if data_ok and not data_probe_error:
        leaked = [f for f in data_entries if f.startswith('tmp')]
        if leaked:
            checks.append({
                "name": "Temp File Leaks",
                "status": "warning",
                "detail": f"Found {len(leaked)} orphaned temp files in data/"
            })
            recommendations.append(f"Clean up {len(leaked)} temp files in data/ directory.")
        else:
            checks.append({
                "name": "Temp File Leaks",
                "status": "ok",
                "detail": "No orphaned temp files"
            })

    # Determine overall status
    statuses = [c["status"] for c in checks]
    if "error" in statuses:
        overall = "error"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"

    return {
        "status": overall,
        "checks": checks,
        "recommendations": recommendations,
    }
