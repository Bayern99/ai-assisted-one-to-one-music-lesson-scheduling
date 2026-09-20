import copy
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.shared.data_loader import DataLoader
    from modules.shared.session_manager import SessionManager

from modules.scheduler.logic import (
    manual_override_primitives,
    unresolved_assignment_primitives,
)
from modules.scheduler.logic.conflict_validator import ConflictValidator
from modules.scheduler.logic.finalize_validation import collect_finalize_conflicts
from modules.scheduler.logic.reconciliation_checker import verify_candidate_state
from modules.scheduler.logic.provenance import (
    SCHEDULER_PROVENANCE_KEY,
    active_workbook_provenance,
)
from modules.scheduler.logic.rules_schema import get_rules_trace
from modules.scheduler.logic.step4_resolution_actions import Step4ResolutionActionsMixin
from modules.scheduler.logic.session_state import (
    SCHEDULER_SAVE_WARNING_KEY,
    SCHEDULER_SESSION_REVISION_KEY,
    SNAPSHOT_DF_CACHE_KEY,
    STEP4_EDIT_SESSION_KEY,
    collect_scheduler_warning_messages,
    ensure_step4_edit_session,
    persist_step4_draft,
    sync_optimizer_intervention_recovery,
    trim_undo_history,
)
from modules.scheduler.logic.stage_service import replay_stage_record, revert_stage_record
from modules.scheduler.logic.validation_authority import (
    authority_assignments,
    build_occupancy_assignments,
    is_finalize_ready,
    mark_validation_unsealed,
    merge_committed_bookings_into_l1,
    seed_validation_authority,
)
from modules.scheduler.logic.workflow_service import (
    SchedulerSessionConflict,
    commit_current_round,
)


@dataclass
class ActionResult:
    status: str
    message: str
    warnings: list = field(default_factory=list)
    draft_dirty: bool = False
    persistence_outcome: object = None
    # Canonical mutation records written by a compound command, when available.
    records: list = field(default_factory=list)

    @property
    def success(self):
        return self.status == "success"


@dataclass
class FinalizeResult:
    status: str
    conflicts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    save_warnings: list = field(default_factory=list)
    error: str = None
    final: object = None


@dataclass
class Step4Runtime:
    loader: "DataLoader"
    session_mgr: "SessionManager"
    booked_lectures: list
    locked_context_assignments: list
    edit_session: dict
    normalized_rules: dict
    rules_trace: dict
    rooms_cache: list
    validator: ConflictValidator
    draft_controller: "Step4DraftController"


class Step4DraftController(Step4ResolutionActionsMixin):
    """Single command boundary for Step 4 draft mutations and finalize."""

    def __init__(
        self,
        *,
        session_mgr,
        validator,
        overrider=None,
        primitive_ops=None,
        edit_session,
        locked_context_assignments,
        booked_lectures,
        normalized_rules,
        weekly_df=None,
        studio_df=None,
    ):
        self.session_mgr = session_mgr
        self.validator = validator
        self.overrider = overrider
        self.primitive_ops = primitive_ops or overrider or manual_override_primitives
        self.edit_session = edit_session
        self.locked_context_assignments = locked_context_assignments
        self.booked_lectures = booked_lectures
        self.normalized_rules = normalized_rules
        self.weekly_df = weekly_df
        self.studio_df = studio_df
        self.rooms_cache = list(getattr(validator, "rooms", []) or [])
        self._assignments = copy.deepcopy(edit_session.get("assignments", []) or [])
        self._unassigned_lessons = copy.deepcopy(edit_session.get("unassigned_lessons", []) or [])
        self._history = copy.deepcopy(edit_session.get("history", []) or [])
        self._redo_stack = copy.deepcopy(edit_session.get("redo_stack", []) or [])
        self._sync_validator_state()
        self._sync_edit_session_state()

    def _find_slot(self, assignments, event_id):
        return self.primitive_ops.find_slot(assignments, event_id)

    def _find_unresolved(self, issue_id):
        return unresolved_assignment_primitives.find_unresolved(
            self._unassigned_lessons,
            issue_id,
        )

    @staticmethod
    def _normalize_room_id(room):
        return str(room or "").strip()

    @staticmethod
    def _action_result(**kwargs):
        return ActionResult(**kwargs)

    @staticmethod
    def _stamp_intervention(record):
        record.setdefault("intervention_id", uuid.uuid4().hex)
        return record

    def _validate_move(
        self,
        slot,
        new_room,
        day,
        new_start,
        new_end,
        *,
        teacher_confirmed=None,
    ):
        if not new_room:
            return {"success": False, "message": "Room must not be blank."}
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            return {"success": False, "message": "Day must be between 0 and 6."}

        canonical_rooms = getattr(self.validator, "rooms", None)
        if canonical_rooms is not None:
            room_ids = {
                self._normalize_room_id(room.get("id"))
                for room in canonical_rooms
                if isinstance(room, dict) and room.get("id")
            }
            if new_room not in room_ids:
                return {
                    "success": False,
                    "message": f"Unknown room: {new_room}",
                }

        if self.overrider is not None and self.primitive_ops is self.overrider:
            return self.primitive_ops.validate_move(
                slot,
                new_room,
                day,
                new_start,
                new_end,
                teacher_confirmed=teacher_confirmed,
            )
        return self.primitive_ops.validate_move(
            self.validator,
            slot,
            new_room,
            day,
            new_start,
            new_end,
            teacher_confirmed=teacher_confirmed,
        )

    def validate_move(self, event_id, new_room, day, new_start, new_end):
        new_room = self._normalize_room_id(new_room)
        slot = self._find_slot(self._assignments, event_id)
        if not slot:
            return {"success": False, "message": f"Slot {event_id} not found."}
        return self._validate_move(slot, new_room, day, new_start, new_end)

    def _apply_move(self, slot, new_room, day, start_norm, end_norm, specific_date=None):
        return self.primitive_ops.apply_move(slot, new_room, day, start_norm, end_norm, specific_date)

    def _apply_unassign(self, assignments, unassigned, slot):
        return self.primitive_ops.apply_unassign(assignments, unassigned, slot)

    def _revert_record(self, assignments, unassigned, record):
        return self.primitive_ops.revert_record(assignments, unassigned, record)

    def _replay_record(self, assignments, unassigned, record):
        return self.primitive_ops.replay_record(assignments, unassigned, record)

    @property
    def history_count(self):
        return len(self._history)

    @property
    def redo_count(self):
        return len(self._redo_stack)

    @property
    def can_undo(self):
        return self.history_count > 0

    @property
    def can_redo(self):
        return self.redo_count > 0

    def _sync_validator_state(self):
        if hasattr(self.validator, "assignments"):
            l1_assignments = authority_assignments(self.edit_session)
            self.validator.assignments = build_occupancy_assignments(
                l1_assignments,
                self._assignments,
            )

    def _sync_edit_session_state(self):
        self._history = trim_undo_history(self._history)
        self.edit_session["assignments"] = copy.deepcopy(self._assignments)
        self.edit_session["unassigned_lessons"] = copy.deepcopy(self._unassigned_lessons)
        self.edit_session["history"] = copy.deepcopy(self._history)
        self.edit_session["redo_stack"] = copy.deepcopy(self._redo_stack)
        sync_optimizer_intervention_recovery(self.edit_session, self._history, self._redo_stack)

    @staticmethod
    def _persisted_action_result(message, persistence_outcome, warnings=None, draft_dirty=True):
        warnings = list(warnings or [])
        persistence_status = getattr(persistence_outcome, "status", "")
        persistence_warning = getattr(persistence_outcome, "warning", "")
        if persistence_status == "conflict":
            return ActionResult(
                status="conflict",
                message=persistence_warning
                or "Session changed before the scheduler draft could be saved.",
                warnings=warnings,
                draft_dirty=draft_dirty,
                persistence_outcome=persistence_outcome,
            )
        if persistence_warning and persistence_warning not in warnings:
            warnings.append(persistence_warning)
        return ActionResult(
            status="success",
            message=message,
            warnings=warnings,
            draft_dirty=True,
            persistence_outcome=persistence_outcome,
        )

    def _snapshot_mutation_state(self, state):
        state_keys = (
            SNAPSHOT_DF_CACHE_KEY,
            SCHEDULER_SAVE_WARNING_KEY,
            SCHEDULER_SESSION_REVISION_KEY,
            "scheduler_session_mtime",
        )
        return {
            "assignments": copy.deepcopy(self._assignments),
            "unassigned_lessons": copy.deepcopy(self._unassigned_lessons),
            "history": copy.deepcopy(self._history),
            "redo_stack": copy.deepcopy(self._redo_stack),
            "edit_session": copy.deepcopy(self.edit_session),
            "validator_has_assignments": hasattr(self.validator, "assignments"),
            "validator_assignments": copy.deepcopy(getattr(self.validator, "assignments", None)),
            "state_values": {
                key: copy.deepcopy(state[key])
                for key in state_keys
                if key in state
            },
            "state_keys": state_keys,
        }

    def _restore_mutation_state(self, state, snapshot):
        self._assignments = snapshot["assignments"]
        self._unassigned_lessons = snapshot["unassigned_lessons"]
        self._history = snapshot["history"]
        self._redo_stack = snapshot["redo_stack"]
        self.edit_session.clear()
        self.edit_session.update(snapshot["edit_session"])
        state[STEP4_EDIT_SESSION_KEY] = self.edit_session
        for key in snapshot["state_keys"]:
            if key in snapshot["state_values"]:
                state[key] = snapshot["state_values"][key]
            else:
                state.pop(key, None)
        if snapshot["validator_has_assignments"]:
            self.validator.assignments = snapshot["validator_assignments"]

    def _source_integrity_enabled(self):
        for frame in (self.weekly_df, self.studio_df):
            if frame is None:
                continue
            if hasattr(frame, "columns"):
                if len(frame.columns):
                    return True
            elif frame:
                return True
        return False

    def _candidate_integrity(self):
        if not self._source_integrity_enabled():
            return {"is_valid": True, "blocking_reason_codes": [], "validation_errors": []}
        result = verify_candidate_state(
            self.weekly_df,
            self._assignments,
            studio_df=self.studio_df,
            unresolved=self._unassigned_lessons,
            rooms=getattr(self.validator, "rooms", []) or [],
            rules=self.normalized_rules,
            locked_context_assignments=self.locked_context_assignments,
            lectures=self.booked_lectures,
            validator=self.validator,
        )
        active_version, active_digests = active_workbook_provenance(
            getattr(self, "_state_provenance", {})
        )
        saved_version = str(self.edit_session.get("source_workbook_version") or "").strip()
        saved_digests = self.edit_session.get("source_workbook_digests") or {}
        if active_version and (saved_version != active_version or saved_digests != active_digests):
            result["is_valid"] = False
            result["blocking_reason_codes"] = sorted(
                set(result.get("blocking_reason_codes", [])) | {"source_version_mismatch"}
            )
            result.setdefault("validation_errors", []).append(
                {"code": "source_version_mismatch", "collection": "session"}
            )
        return result

    @staticmethod
    def _integrity_conflicts(result):
        conflicts = []
        for error in result.get("validation_errors", []) or []:
            conflicts.append(
                (
                    {"id": error.get("item_id") or error.get("left_id") or "integrity"},
                    {
                        "id": error.get("conflict_id") or "integrity",
                        "message": error.get("code", "integrity_failure"),
                    },
                )
            )
        for code in result.get("blocking_reason_codes", []) or []:
            if not any(pair[1].get("message") == code for pair in conflicts):
                conflicts.append(({}, {"id": "integrity", "message": code}))
        return conflicts

    def _persist_mutation(self, state, snapshot, message, warnings=None, *, keep_sealed=False):
        if not keep_sealed:
            mark_validation_unsealed(self.edit_session)
        self._sync_validator_state()
        self._sync_edit_session_state()
        integrity = self._candidate_integrity()
        if not integrity["is_valid"]:
            self._restore_mutation_state(state, snapshot)
            reasons = ", ".join(integrity.get("blocking_reason_codes", []))
            return ActionResult(
                status="failed",
                message="Scheduler integrity blocked this Step 4 operation"
                + (f": {reasons}" if reasons else "."),
                warnings=list(warnings or []),
                draft_dirty=False,
            )
        try:
            persistence_outcome = persist_step4_draft(self.session_mgr, state)
        except Exception:
            self._restore_mutation_state(state, snapshot)
            raise
        if getattr(persistence_outcome, "status", "") == "conflict":
            self._restore_mutation_state(state, snapshot)
        return self._persisted_action_result(
            message,
            persistence_outcome,
            warnings=warnings,
            draft_dirty=bool(self.edit_session.get("dirty")),
        )

    def finalize(self, state, loader=None):
        if not is_finalize_ready(state, self.edit_session):
            return FinalizeResult(
                status="blocked",
                error="Stage before finalizing.",
                conflicts=[({}, {"id": "stage", "message": "Stage before finalizing."})],
            )
        self._sync_validator_state()
        self._sync_edit_session_state()
        generated_assignments = self._assignments
        self._state_provenance = state.get(SCHEDULER_PROVENANCE_KEY, {})
        integrity = self._candidate_integrity()
        if not integrity["is_valid"]:
            return FinalizeResult(
                status="blocked",
                conflicts=self._integrity_conflicts(integrity),
            )
        conflicts, warnings = collect_finalize_conflicts(self, generated_assignments)

        if conflicts:
            return FinalizeResult(
                status="blocked",
                conflicts=conflicts,
                warnings=warnings,
            )

        self.edit_session["optimizer_finalize_warnings"] = copy.deepcopy(warnings)
        snapshot = self._snapshot_mutation_state(state)
        try:
            final = commit_current_round(loader, self.session_mgr, state)
        except SchedulerSessionConflict as exc:
            self._restore_mutation_state(state, snapshot)
            return FinalizeResult(
                status="conflict",
                warnings=warnings,
                error=str(exc),
            )
        except Exception as exc:
            self._restore_mutation_state(state, snapshot)
            return FinalizeResult(
                status="failed",
                warnings=warnings,
                error=str(exc),
            )

        return FinalizeResult(
            status="committed",
            warnings=warnings,
            save_warnings=collect_scheduler_warning_messages(state),
            final=final,
        )

    def _apply_history_record(self, record, *, reverse: bool):
        action = record.get("action")
        if action == "stage":
            if reverse:
                revert_stage_record(self.edit_session, record)
                self._assignments = copy.deepcopy(self.edit_session.get("assignments", []) or [])
                self._unassigned_lessons = copy.deepcopy(
                    self.edit_session.get("unassigned_lessons", []) or []
                )
            else:
                replay_stage_record(self.edit_session, record)
                self._assignments = copy.deepcopy(self.edit_session.get("assignments", []) or [])
                self._unassigned_lessons = copy.deepcopy(
                    self.edit_session.get("unassigned_lessons", []) or []
                )
            return True
        if reverse:
            self._revert_record(self._assignments, self._unassigned_lessons, record)
        else:
            self._replay_record(self._assignments, self._unassigned_lessons, record)
        return False

    def undo(self, state):
        if not self._history:
            return ActionResult(status="failed", message="Undo failed")

        snapshot = self._snapshot_mutation_state(state)
        record = self._history.pop()
        self._redo_stack.append(copy.deepcopy(record))
        staged = self._apply_history_record(record, reverse=True)
        return self._persist_mutation(
            state,
            snapshot,
            "Undone!",
        )

    def redo(self, state):
        if not self._redo_stack:
            return ActionResult(status="failed", message="Redo failed")

        snapshot = self._snapshot_mutation_state(state)
        record = self._redo_stack.pop()
        self._history = trim_undo_history(self._history)
        self._history.append(copy.deepcopy(record))
        staged = self._apply_history_record(record, reverse=False)
        return self._persist_mutation(
            state,
            snapshot,
            "Redone!",
            keep_sealed=staged,
        )

    def unlock(self, state, event_id):
        slot = self._find_slot(self._assignments, event_id)
        if not slot:
            return ActionResult(status="failed", message="Unlock failed")

        snapshot = self._snapshot_mutation_state(state)
        slot["pinned"] = False
        return self._persist_mutation(
            state,
            snapshot,
            "Unlocked!",
        )

    def unassign(self, state, event_id, label, *, decision_note=""):
        slot = self._find_slot(self._assignments, event_id)
        if not slot:
            return ActionResult(status="failed", message="Failed to unassign")

        snapshot = self._snapshot_mutation_state(state)
        prev_state = copy.deepcopy(slot)
        new_state = self._apply_unassign(self._assignments, self._unassigned_lessons, slot)
        self._history = trim_undo_history(self._history)
        record = {
            "action": "unassign",
            "slot_id": event_id,
            "prev_state": prev_state,
            "new_state": new_state,
        }
        if str(decision_note or "").strip():
            record["decision_note"] = str(decision_note).strip()
        self._history.append(self._stamp_intervention(record))
        self._redo_stack.clear()
        return self._persist_mutation(
            state,
            snapshot,
            f"Unassigned {label}",
        )

    def unassign_block(self, state, event_ids, *, decision_note=""):
        ids = []
        seen = set()
        for raw in event_ids or []:
            event_id = str(raw or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            ids.append(event_id)
        if not ids:
            return ActionResult(status="failed", message="Select a teacher block to unassign.")
        if len(ids) > 24:
            return ActionResult(status="failed", message="Teacher block is too large to unassign at once.")

        for event_id in ids:
            slot = self._find_slot(self._assignments, event_id)
            if not slot:
                return ActionResult(status="failed", message="Failed to unassign")
            slot_type = str(slot.get("type") or "").lower()
            if "lecture" in slot_type or slot.get("locked") is True or slot.get("committed") is True:
                return ActionResult(status="failed", message="Locked lectures cannot be unassigned.")

        snapshot = self._snapshot_mutation_state(state)
        records = []
        note = str(decision_note or "").strip()
        for event_id in ids:
            slot = self._find_slot(self._assignments, event_id)
            if not slot:
                self._restore_mutation_state(state, snapshot)
                return ActionResult(status="failed", message="Failed to unassign")
            prev_state = copy.deepcopy(slot)
            new_state = self._apply_unassign(self._assignments, self._unassigned_lessons, slot)
            child = {
                "action": "unassign",
                "slot_id": event_id,
                "prev_state": prev_state,
                "new_state": new_state,
            }
            if note:
                child["decision_note"] = note
            records.append(self._stamp_intervention(child))

        self._history = trim_undo_history(self._history)
        compound = {
            "action": "compound",
            "label": "unassign_block",
            "records": records,
        }
        if note:
            compound["decision_note"] = note
        self._history.append(self._stamp_intervention(compound))
        self._redo_stack.clear()
        count = len(records)
        return self._persist_mutation(
            state,
            snapshot,
            f"Unassigned {count} lesson{'s' if count != 1 else ''}",
        )

def finalize_step4_round(runtime, state):
    return runtime.draft_controller.finalize(state, loader=runtime.loader)


def apply_undo_action(runtime, state):
    return runtime.draft_controller.undo(state)


def apply_unlock_action(runtime, state, event_id):
    return runtime.draft_controller.unlock(state, event_id)


def apply_unassign_action(runtime, state, event_id, label):
    return runtime.draft_controller.unassign(state, event_id, label)


def apply_move_action(
    runtime,
    state,
    event_id,
    new_room,
    day,
    new_start,
    new_end,
    *,
    teacher_confirmed=False,
    confirmation_note="",
):
    return runtime.draft_controller.move(
        state,
        event_id,
        new_room,
        day,
        new_start,
        new_end,
        teacher_confirmed=teacher_confirmed,
        confirmation_note=confirmation_note,
    )


def assign_failed_lesson(runtime, state, failed_item, index, view_model, new_room):
    return runtime.draft_controller.assign_failed(state, failed_item, index, view_model, new_room)


def build_step4_runtime(context, state, *, bookings=None, rooms=None):
    loader = context.loader
    session_mgr = context.session_manager
    bookings = list(loader.load_bookings() if bookings is None else bookings)
    rooms = list(loader.load_rooms() if rooms is None else rooms)
    rooms_cache = [room for room in rooms if isinstance(room, dict) and room.get("id")]
    if not rooms_cache:
        rooms_cache = [{"id": "R101"}]

    booked_lectures = [
        event for event in bookings
        if event.get("type") in ("lecture", "academic_lecture")
    ]
    edit_session = ensure_step4_edit_session(state)
    l0_assignments = list(edit_session.get("assignments", []) or [])
    l1_assignments = merge_committed_bookings_into_l1(
        authority_assignments(edit_session),
        l0_assignments,
        bookings,
    )
    locked_context_assignments = l1_assignments
    normalized_rules = context.load_rules()
    get_data = getattr(loader, "get_data", None)
    students = get_data("students.json") if callable(get_data) else []
    unresolved_assignment_primitives.enrich_student_instruments(
        edit_session.get("unassigned_lessons", []),
        students,
    )
    validator = ConflictValidator({
        "assignments": build_occupancy_assignments(
            locked_context_assignments,
            list(edit_session.get("assignments", [])),
        ),
        "lectures": booked_lectures,
        "rooms": rooms_cache,
        "rules": normalized_rules,
    })
    controller = Step4DraftController(
        session_mgr=session_mgr,
        validator=validator,
        primitive_ops=manual_override_primitives,
        edit_session=edit_session,
        locked_context_assignments=locked_context_assignments,
        booked_lectures=booked_lectures,
        normalized_rules=normalized_rules,
        weekly_df=state.get("wk_df"),
        studio_df=state.get("stu_df"),
    )
    controller._state_provenance = state.get(SCHEDULER_PROVENANCE_KEY, {})
    return Step4Runtime(
        loader=loader,
        session_mgr=session_mgr,
        booked_lectures=booked_lectures,
        locked_context_assignments=locked_context_assignments,
        edit_session=edit_session,
        normalized_rules=normalized_rules,
        rules_trace=get_rules_trace(normalized_rules),
        rooms_cache=rooms_cache,
        validator=validator,
        draft_controller=controller,
    )
