import copy
import os
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from modules.scheduler.logic.optimizer import RoomAllocator
from modules.scheduler.logic.rules_schema import (
    DEFAULT_RULES,
    canonicalize_rules_for_save,
    normalize_rules,
    validate_rules_payload,
)
from modules.shared.data_loader import DataLoader
from modules.shared.session_manager import SessionManager


@dataclass
class SchedulerContext:
    loader: DataLoader
    session_manager: SessionManager
    rules_path: str
    default_rules: dict
    mutation_lock: Any = field(default_factory=Lock)

    def load_rules(self):
        source_path = self.loader.preferred_data_path("scheduling_rules.json")
        try:
            raw_rules = self.loader.load_rules()
        except Exception:
            raw_rules = {}
        return normalize_rules(raw_rules, self.default_rules, source_path=source_path)

    def save_rules(self, rules):
        errors = validate_rules_payload(rules)
        if errors:
            raise ValueError("; ".join(errors))
        source_path = self.loader.preferred_data_path("scheduling_rules.json")
        canonical = canonicalize_rules_for_save(
            rules,
            default_rules=self.default_rules,
            source_path=source_path,
        )
        saved_path = self.loader.save_data("scheduling_rules.json", canonical)
        if os.path.abspath(saved_path) != os.path.abspath(source_path):
            canonical = canonicalize_rules_for_save(
                rules,
                default_rules=self.default_rules,
                source_path=saved_path,
            )
            saved_path = self.loader.save_data("scheduling_rules.json", canonical)
        return canonical, saved_path

    def make_optimizer(self, students, rooms, locked, rules=None):
        run_rules = copy.deepcopy(rules if rules is not None else self.load_rules())
        return RoomAllocator(
            students,
            rooms,
            locked,
            run_rules,
            rules_source_path=self.loader.preferred_data_path("scheduling_rules.json"),
        )


def build_scheduler_context(base_dir="data", default_rules=None, loader=None, session_manager=None):
    scheduler_loader = loader or DataLoader(base_dir=base_dir)
    scheduler_session_manager = session_manager or SessionManager(base_dir=base_dir)
    return SchedulerContext(
        loader=scheduler_loader,
        session_manager=scheduler_session_manager,
        rules_path=os.path.join(scheduler_loader.base_dir, "scheduling_rules.json"),
        default_rules=copy.deepcopy(default_rules if isinstance(default_rules, dict) else DEFAULT_RULES),
    )
