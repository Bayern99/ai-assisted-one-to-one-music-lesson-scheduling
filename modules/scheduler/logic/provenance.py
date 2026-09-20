"""Scheduler upload/master-data provenance helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime

SCHEDULER_PROVENANCE_KEY = "scheduler_data_provenance"
ROOM_TYPE_OVERRIDE_WARNING = (
    "Manual room-type overrides in scheduling_rules.json take precedence over imported room types."
)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def build_workbook_digest(file_bytes):
    return hashlib.sha1(file_bytes).hexdigest()


def ensure_scheduler_provenance(provenance=None):
    data = copy.deepcopy(provenance or {})
    data.setdefault("uploads", {})
    data.setdefault("master_data_sync", {})
    return data


def record_uploaded_workbook(provenance, upload_slot, file_name, file_bytes, uploaded_at=None):
    data = ensure_scheduler_provenance(provenance)
    data["uploads"][upload_slot] = {
        "filename": file_name,
        "digest": build_workbook_digest(file_bytes),
        "uploaded_at": uploaded_at or _now_iso(),
    }
    return data


def record_master_data_sync(provenance, target, sync_record):
    data = ensure_scheduler_provenance(provenance)
    data["master_data_sync"][target] = copy.deepcopy(sync_record)
    return data


def active_workbook_provenance(provenance):
    """Return the current upload digests and a stable version for Step 4."""
    data = ensure_scheduler_provenance(provenance)
    digests = {
        str(slot): str(item.get("digest"))
        for slot, item in sorted(data.get("uploads", {}).items())
        if isinstance(item, dict) and item.get("digest")
    }
    if not digests:
        return "", {}
    version = hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return version, digests


def build_step3_provenance_status(provenance, rules):
    data = ensure_scheduler_provenance(provenance)
    uploads = data.get("uploads", {})
    syncs = data.get("master_data_sync", {})

    summary = []
    warnings = []
    active_digests = {
        item.get("digest")
        for item in uploads.values()
        if isinstance(item, dict) and item.get("digest")
    }

    if len(active_digests) > 1:
        warnings.append(
            "Weekly and studio uploads come from different workbook digests. Master-data sync may be stale for one side."
        )

    for slot in ("weekly", "studio"):
        item = uploads.get(slot) or {}
        if item.get("filename"):
            summary.append(
                f"{slot.capitalize()} upload: `{item['filename']}`"
                + (f" ({item.get('uploaded_at')})" if item.get("uploaded_at") else "")
            )

    for target in ("rooms", "students", "instructors", "courses"):
        item = syncs.get(target) or {}
        status = item.get("status", "unknown")
        workbook_name = item.get("workbook_filename") or "unknown workbook"
        save_source = item.get("save_source") or "unknown"
        save_target = item.get("save_target_path") or "unavailable"
        synced_at = item.get("synced_at")

        line = f"{target} synced from `{workbook_name}`: `{status}` via `{save_source}` -> `{save_target}`"
        if synced_at:
            line += f" ({synced_at})"
        summary.append(line)

        if status == "synced" and active_digests and item.get("workbook_digest") not in active_digests:
            warnings.append(
                f"{target.capitalize()} sync does not match the active upload digest. Re-upload or re-sync master data."
            )
        if save_source == "shadow":
            warnings.append(
                f"{target.capitalize()} is currently backed by a shadow save path: `{save_target}`."
            )
        if status == "failed":
            warnings.append(
                f"{target.capitalize()} sync failed: {item.get('message') or 'unknown error'}"
            )

    if (rules or {}).get("room_types"):
        warnings.append(
            "Manual room-type overrides are active in Step 2 and take precedence over imported room types."
        )

    return {
        "summary": summary,
        "warnings": warnings,
        "has_manual_room_type_overrides": bool((rules or {}).get("room_types")),
    }
