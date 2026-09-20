import json
import logging
import os
import tempfile
import shutil
import time
import hashlib
from datetime import datetime, timedelta

from modules.shared.atomic_json_io import atomic_write_json
from modules.shared.save_outcome import SaveOutcome
from modules.shared.time_parser import TimeParser

logger = logging.getLogger(__name__)

class DataCorruptionError(Exception):
    """Raised when data file is corrupted/invalid JSON."""
    pass

class DataLoader:
    def __init__(self, base_dir="data", backup_corrupt_reads: bool = True):
        self.base_dir = os.path.abspath(base_dir)
        self.backup_corrupt_reads = backup_corrupt_reads
        shadow_key = hashlib.sha1(self.base_dir.encode("utf-8")).hexdigest()[:16]
        project_shadow = os.path.join(os.path.dirname(self.base_dir), ".runtime_shadow_data")
        temp_shadow = os.path.join(tempfile.gettempdir(), "music_lesson_scheduler_shadow", shadow_key)
        self.shadow_dirs = []
        for candidate in [project_shadow, temp_shadow]:
            try:
                os.makedirs(candidate, exist_ok=True)
                self.shadow_dirs.append(candidate)
            except Exception:
                logger.warning("Failed to create shadow dir: %s", candidate, exc_info=True)
        self._last_io_metadata = {}
        self.ensure_dirs()
        
    def ensure_dirs(self):
        if not os.path.exists(self.base_dir):
            try:
                os.makedirs(self.base_dir)
            except Exception:
                logger.warning("Failed to create base data dir: %s", self.base_dir, exc_info=True)

        # Ensure backup dir exists
        backup_dir = os.path.join(self.base_dir, "corrupted_backups")
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except Exception:
                logger.warning("Failed to create backup dir: %s", backup_dir, exc_info=True)

        # Keep fallback shadow dirs available.
        for shadow_dir in self.shadow_dirs:
            try:
                os.makedirs(shadow_dir, exist_ok=True)
            except Exception:
                pass

    def _atomic_save(self, path, data, preserve_existing=True):
        """Write to temp file then atomic rename to prevent corruption on crash."""
        atomic_write_json(path, data, preserve_existing=preserve_existing)

    def _safe_load(self, path, default_value=None):
        """Load JSON safely. If corrupted, backup and RAISE error (Fail Fast)."""
        if default_value is None: default_value = []
        
        if not os.path.exists(path):
            return default_value
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # CRITICAL: File exists but is corrupted.
            filename = os.path.basename(path)
            backup_message = "Corruption backup disabled for this read."
            if self.backup_corrupt_reads:
                # Backup the scene of the crime for legacy callers.
                timestamp = int(time.time())
                backup_path = os.path.join(
                    self.base_dir,
                    "corrupted_backups",
                    f"{filename}_{timestamp}.bak",
                )
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(path, backup_path)
                backup_message = f"Backup saved to: {backup_path}"
            
            # Raise specialized error to stop the app.
            raise DataCorruptionError(
                f"🔥 FATAL: Data file '{filename}' is corrupted! \n"
                f"{backup_message}\n"
                f"Error: {str(e)}"
            )
        except Exception as e:
            # Propagate other errors (permission, etc)
            raise e

    def _shadow_paths(self, name):
        return [os.path.join(d, name) for d in self.shadow_dirs]

    def _shadow_path(self, name):
        paths = self._shadow_paths(name)
        if paths:
            return paths[0]
        return os.path.join(tempfile.gettempdir(), name)

    def _invoke_atomic_save(self, path, data, preserve_existing):
        try:
            return self._atomic_save(path, data, preserve_existing=preserve_existing)
        except TypeError as exc:
            if "unexpected keyword argument 'preserve_existing'" not in str(exc):
                raise
            return self._atomic_save(path, data)

    def _record_io_metadata(self, name, source, selected_path, warnings=None):
        self._last_io_metadata[name] = {
            "source": source,
            "selected_path": selected_path,
            "warnings": list(warnings or []),
        }

    def get_last_io_metadata(self, name=None):
        if name is None:
            return dict(self._last_io_metadata)
        return dict(self._last_io_metadata.get(name, {}))

    def _preferred_path_for_read(self, name):
        """Pick primary or shadow file (prefer newer one)."""
        primary = os.path.join(self.base_dir, name)
        candidates = []
        if os.path.exists(primary):
            candidates.append(primary)
        for shadow in self._shadow_paths(name):
            if os.path.exists(shadow):
                candidates.append(shadow)
        if not candidates:
            self._record_io_metadata(name, "primary", primary, warnings=[])
            return primary
        def _mtime(path):
            try:
                return os.path.getmtime(path)
            except Exception:
                return 0
        selected = max(candidates, key=_mtime)
        source = "primary"
        warnings = []
        if selected != primary:
            source = "shadow"
            warnings.append(
                f"Using shadow file for {name} because it is newer or primary is unavailable."
            )
        self._record_io_metadata(name, source, selected, warnings=warnings)
        return selected

    def preferred_data_path(self, name):
        return self._preferred_path_for_read(name)

    def load_json_data(self, name, default_value=None):
        path = self.preferred_data_path(name)
        try:
            return self._safe_load(path, default_value=default_value)
        except PermissionError:
            for shadow in self._shadow_paths(name):
                if path == shadow or not os.path.exists(shadow):
                    continue
                try:
                    return self._safe_load(shadow, default_value=default_value)
                except PermissionError:
                    continue
            raise

    # ==========================
    # Core Data Access
    # ==========================
    @staticmethod
    def _normalize_booking_occupancy(evt):
        interval = TimeParser.board_event_occupancy(evt)
        if interval is None:
            return evt
        start_minute, end_minute = interval
        start_norm = TimeParser.minute_to_clock(start_minute)
        end_norm = TimeParser.minute_to_clock(end_minute)
        props = evt.get("extendedProps")
        if not isinstance(props, dict) and evt.get("type") not in {"lecture", "locked_lecture"}:
            props = {}
            evt["extendedProps"] = props
        if start_norm and end_norm and evt.get("type") not in {"lecture", "locked_lecture"}:
            if not isinstance(props, dict):
                props = {}
                evt["extendedProps"] = props
            props["Class Time"] = f"{start_norm}-{end_norm}"

        if evt.get("daysOfWeek") is not None or evt.get("startTime") is not None:
            if start_norm and end_norm:
                evt["startTime"] = f"{start_norm}:00"
                evt["endTime"] = f"{end_norm}:00"
            return evt

        start_value = evt.get("start")
        end_value = evt.get("end")
        try:
            start_dt = datetime.fromisoformat(
                str(start_value).replace("Z", "+00:00")
            )
            end_dt = datetime.fromisoformat(
                str(end_value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return evt
        normalized_start = start_dt.replace(
            hour=start_minute // 60,
            minute=start_minute % 60,
            second=0,
            microsecond=0,
        )
        normalized_end = start_dt.replace(
            hour=end_minute // 60 if end_minute < 24 * 60 else 0,
            minute=end_minute % 60,
            second=0,
            microsecond=0,
        )
        if end_minute >= 24 * 60:
            normalized_end = normalized_end + timedelta(days=1)
        if end_dt.tzinfo is not None and normalized_end.tzinfo is None:
            normalized_end = normalized_end.replace(tzinfo=end_dt.tzinfo)
        evt["start"] = normalized_start.isoformat()
        evt["end"] = normalized_end.isoformat()
        return evt

    def _normalize_booking_event(self, item):
        """
        Normalize legacy booking variants into the current canonical schema.
        Keeps backward compatibility with historical saved data.
        """
        if not isinstance(item, dict):
            return item

        evt = dict(item)
        evt_type = evt.get("type")

        # Backward compatibility for multi-round locked types.
        if evt_type == "committed_weekly":
            evt["type"] = "weekly_lesson"
            evt["committed"] = True
        elif evt_type == "committed_studio":
            evt["type"] = "studio_class"
            evt["committed"] = True

        # Normalize older committed studio variant.
        if evt.get("committed") and evt.get("type") == "studio":
            evt["type"] = "studio_class"

        return self._normalize_booking_occupancy(evt)

    def load_bookings(self):
        """Load and DEDUPLICATE bookings"""
        path = self._preferred_path_for_read("bookings.json")
        try:
            data = self._safe_load(path, default_value=[])
            
            seen = set()
            unique_data = []
            for item in data:
                item = self._normalize_booking_event(item)
                # Create a signature
                sig = f"{item.get('id')}|{item.get('start')}|{item.get('startTime')}|{item.get('resourceId')}"
                if sig not in seen:
                    unique_data.append(item)
                    seen.add(sig)
            
            return unique_data
        except DataCorruptionError:
            raise # Let UI handle the crash screen
        except Exception:
            fallback_path = self._preferred_path_for_read("bookings.json")
            self._record_io_metadata(
                "bookings.json",
                "fallback",
                fallback_path,
                warnings=["Unknown bookings load error. Returned empty list fallback."],
            )
            return [] # Fallback for unknown non-critical errors (or raise?)

    def save_bookings(self, events):
        """Save bookings"""
        return self._save_data_with_outcome("bookings.json", events)

    def get_data(self, name):
        """Generic get"""
        return self.load_json_data(name, default_value=[])
    
    def save_data(self, name, data):
        """Generic save"""
        return self._save_data_with_outcome(name, data).path

    def _save_data_with_outcome(self, name, data):
        """Generic save with explicit degraded-success semantics."""
        path = os.path.join(self.base_dir, name)
        try:
            self._invoke_atomic_save(path, data, preserve_existing=True)
            self._record_io_metadata(name, "primary", path, warnings=[])
            return SaveOutcome(status="primary", path=path)
        except Exception as primary_err:
            for shadow in self._shadow_paths(name):
                try:
                    self._invoke_atomic_save(shadow, data, preserve_existing=False)
                    warning = f"Primary save failed for {name}; wrote fallback shadow copy."
                    self._record_io_metadata(
                        name,
                        "shadow",
                        shadow,
                        warnings=[warning],
                    )
                    return SaveOutcome(status="shadow", path=shadow, warning=warning)
                except Exception:
                    continue
            raise primary_err

    def load_rules(self):
        """Load scheduling rules"""
        # Return default structure if missing
        default_rules = {
            "priorities": {},
            "constraints": {
                "time_range": {"start": "08:00", "end": "23:00"},
                "min_break_between_lessons": 0,
                "enforce_instructor_blocks": True
            },
            "room_types": {}
        }
        rules = self._safe_load(
            self.preferred_data_path("scheduling_rules.json"),
            default_value=default_rules
        )
        return rules if isinstance(rules, dict) else default_rules

    def load_rooms(self):
        """Load rooms configuration"""
        return self.get_data("rooms.json")

    # ==========================
    # Workflow & Config
    # ==========================
    def load_workflow_state(self):
        return self.load_json_data("workflow_state.json", default_value={})

    def save_workflow_state(self, state):
        self.save_data("workflow_state.json", state)

    def load_deadline_config(self):
        try:
            conf = self.load_json_data("deadline_config.json", default_value={})
            return conf if isinstance(conf, dict) else {}
        except Exception:
            return {}
            
    def load_semester_config(self):
        try:
            conf = self.load_json_data("semester_config.json", default_value={})
            if not isinstance(conf, dict):
                conf = {}
            # Normalize legacy key variants so all consumers see stable keys.
            if conf.get("start") and not conf.get("start_date"):
                conf["start_date"] = conf["start"]
            if conf.get("end") and not conf.get("end_date"):
                conf["end_date"] = conf["end"]
            if conf.get("last_day") and not conf.get("end_date"):
                conf["end_date"] = conf["last_day"]
            if conf.get("end_date") and not conf.get("last_day"):
                conf["last_day"] = conf["end_date"]
            return conf
        except Exception:
            return {
                "start_date": "2026-02-24", # Updated default
                "end_date": "2026-06-30",
                "last_day": "2026-06-30",
                "due_date": "2026-07-05"
            }

    def save_semester_config(self, config):
        self.save_data("semester_config.json", config)

    # ==========================
    # Import Methods
    # ==========================
    def load_excel_sheets(self, file_buffer):
        from modules.shared.import_service import load_excel_sheets

        return load_excel_sheets(file_buffer)

    def import_rooms_from_excel(self, file):
        from modules.shared.import_service import import_rooms_from_excel

        return import_rooms_from_excel(self, file)

    def import_student_roster(self, file):
        from modules.shared.import_service import import_student_roster

        return import_student_roster(self, file)

    def import_students_from_excel(self, file):
        from modules.shared.import_service import import_students_from_excel

        return import_students_from_excel(self, file)
    # ==========================
    # Logic: Auto-Schedule (Legacy Wrapper)
    # ==========================
    def auto_schedule(self, rules, clear_existing=False):
        from modules.shared.legacy_csp_service import run_legacy_auto_schedule

        return run_legacy_auto_schedule(self, rules, clear_existing=clear_existing)
