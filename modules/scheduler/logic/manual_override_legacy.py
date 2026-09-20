import copy

from modules.scheduler.logic import manual_override_primitives as primitives
from modules.scheduler.logic.schedule_change_policy import attach_teacher_confirmation


class ManualOverrider:
    """
    Legacy compatibility adapter around `manual_override_primitives`.

    The Step 4 runtime should prefer `manual_override_primitives` directly through
    `Step4DraftController`, which owns runtime history and redo semantics.

    The legacy stateful wrappers (`move_slot`, `unassign_slot`, `undo`, `redo`,
    `unlock_slot`) are retained only for compatibility with older tests/tools.
    """

    def __init__(self, scheduler_data, validator=None, history=None, redo_stack=None):
        self.data = scheduler_data
        if validator is None:
            from modules.scheduler.logic.conflict_validator import ConflictValidator

            self.validator = ConflictValidator(scheduler_data)
        else:
            self.validator = validator

        # Compatibility only: controller-owned history/redo no longer flows through
        # these lists in the Step 4 runtime path.
        self.history = history if history is not None else []
        self.redo_stack = redo_stack if redo_stack is not None else []

    def _legacy_assignments(self):
        return self.data.setdefault("assignments", [])

    def _legacy_unassigned_lessons(self):
        return self.data.setdefault("unassigned_lessons", [])

    def _record_legacy_action(self, record):
        self.history.append(record)
        self.redo_stack.clear()

    def find_slot(self, assignments, slot_id):
        return primitives.find_slot(assignments, slot_id)

    def resolve_specific_date(self, slot):
        return primitives.resolve_specific_date(slot)

    def validate_move(
        self,
        slot,
        new_room_id,
        new_day_idx,
        new_start_str,
        new_end_str,
        *,
        teacher_confirmed=None,
    ):
        return primitives.validate_move(
            self.validator,
            slot,
            new_room_id,
            new_day_idx,
            new_start_str,
            new_end_str,
            teacher_confirmed=teacher_confirmed,
        )

    def apply_move(self, slot, new_room_id, new_day_idx, start_norm, end_norm, specific_date=None):
        return primitives.apply_move(slot, new_room_id, new_day_idx, start_norm, end_norm, specific_date)

    def apply_unassign(self, assignments, unassigned, slot):
        return primitives.apply_unassign(assignments, unassigned, slot)

    def revert_record(self, assignments, unassigned, record):
        return primitives.revert_record(assignments, unassigned, record)

    def replay_record(self, assignments, unassigned, record):
        return primitives.replay_record(assignments, unassigned, record)

    def move_slot(
        self,
        slot_id,
        new_room_id,
        new_day_idx,
        new_start_str,
        new_end_str,
        *,
        teacher_confirmed=False,
        confirmation_note="",
    ):
        """Legacy compatibility wrapper around the primitive move helpers."""
        assignments = self._legacy_assignments()
        slot = self.find_slot(assignments, slot_id)
        if not slot:
            return {"success": False, "message": f"Slot {slot_id} not found."}

        validation = self.validate_move(
            slot,
            new_room_id,
            new_day_idx,
            new_start_str,
            new_end_str,
            teacher_confirmed=teacher_confirmed,
        )
        if not validation["success"]:
            return validation

        prev_state = copy.deepcopy(slot)
        new_state = self.apply_move(
            slot,
            new_room_id,
            new_day_idx,
            validation["start_norm"],
            validation["end_norm"],
            validation["specific_date"],
        )
        if validation.get("requires_teacher_confirmation"):
            props = slot.get("extendedProps") or {}
            attach_teacher_confirmation(
                slot,
                instructor=props.get("Instructor") or slot.get("instructor"),
                note=confirmation_note,
            )
            new_state = copy.deepcopy(slot)
        self._record_legacy_action(
            {
                "action": "move",
                "slot_id": slot_id,
                "prev_state": prev_state,
                "new_state": new_state,
            }
        )
        return {"success": True, "message": "Moved successfully."}

    def unlock_slot(self, slot_id):
        assignments = self._legacy_assignments()
        slot = self.find_slot(assignments, slot_id)
        if slot:
            slot["pinned"] = False
            return True
        return False

    def unassign_slot(self, slot_id):
        """Legacy compatibility wrapper around the primitive unassign helpers."""
        assignments = self._legacy_assignments()
        unassigned = self._legacy_unassigned_lessons()
        slot = self.find_slot(assignments, slot_id)
        if not slot:
            return False

        prev_state = copy.deepcopy(slot)
        new_state = self.apply_unassign(assignments, unassigned, slot)
        self._record_legacy_action(
            {
                "action": "unassign",
                "slot_id": slot_id,
                "prev_state": prev_state,
                "new_state": new_state,
            }
        )
        return True

    def undo(self):
        if not self.history:
            return False
        record = self.history.pop()
        self.redo_stack.append(record)
        return self.revert_record(
            self._legacy_assignments(),
            self._legacy_unassigned_lessons(),
            record,
        )

    def redo(self):
        if not self.redo_stack:
            return False
        record = self.redo_stack.pop()
        self.history.append(record)
        return self.replay_record(
            self._legacy_assignments(),
            self._legacy_unassigned_lessons(),
            record,
        )
