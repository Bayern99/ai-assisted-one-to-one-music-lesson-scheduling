"""Resolution-specific Step 4 commands kept outside the core draft service."""

import copy

from modules.scheduler.logic import unresolved_assignment_primitives
from modules.scheduler.logic.resolution_package import (
    PackageRejected,
    apply_piano_leverage_package,
    apply_reconciliation_package,
)
from modules.scheduler.logic.resolution_simulation import (
    execute_intervention_actions,
    simulate_assignment_plan,
    simulate_intervention_plan,
)
from modules.scheduler.logic.schedule_change_policy import attach_teacher_confirmation
from modules.scheduler.logic.session_state import trim_undo_history
from modules.shared.time_parser import TimeParser


class Step4ResolutionActionsMixin:
    """Assignment and move commands layered onto ``Step4DraftController``."""

    def simulate_assignment_plan(self, actions):
        return simulate_assignment_plan(self, actions)

    def simulate_intervention_plan(self, actions):
        return simulate_intervention_plan(self, actions)

    def simulate_reconciliation_package(self, changes, *, keep_state=False):
        """Evaluate a declarative final-state package without persistence."""
        from modules.scheduler.logic.resolution_package import evaluate_reconciliation_package

        return evaluate_reconciliation_package(
            self,
            changes,
            confirmed_teachers=(),
            commit=False,
            keep_state=keep_state,
        )

    def apply_reconciliation_package(
        self,
        state,
        changes,
        *,
        confirmed_teachers=(),
        confirmation_note="",
        decision_note="",
        authorized_sacrifice_subject_ids=(),
    ):
        """Apply one validated package as a single canonical mutation."""
        snapshot = self._snapshot_mutation_state(state)
        result = apply_reconciliation_package(
            self,
            state,
            changes,
            confirmed_teachers=confirmed_teachers,
            decision_note=decision_note,
            authorized_sacrifice_subject_ids=authorized_sacrifice_subject_ids,
        )
        if not result.get("feasible") or result.get("status") != "feasible":
            self._restore_mutation_state(state, snapshot)
            return self._action_result(
                status="failed",
                message=(result.get("failure_codes") or [
                    "The reconciliation package is not ready to apply."
                ])[0],
                warnings=list(result.get("warnings") or []),
            )
        records = copy.deepcopy(result.get("records") or [])
        confirmation_text = str(confirmation_note or "").strip() or "Confirmed for this reconciliation package."
        confirmed = {
            str(name or "").strip().casefold() for name in confirmed_teachers if str(name or "").strip()
        }
        for record in records:
            new_state = record.get("new_state")
            # Only a lesson whose time actually changed carries a time-change
            # confirmation, and only for the teacher who gave it.
            if not isinstance(new_state, dict) or not record.get("time_changed"):
                continue
            props = new_state.get("extendedProps") or {}
            instructor = str(
                record.get("teacher")
                or props.get("Instructor")
                or new_state.get("instructor")
                or ""
            ).strip()
            if not instructor or instructor.casefold() not in confirmed:
                continue
            attach_teacher_confirmation(
                new_state,
                instructor=instructor,
                note=confirmation_text,
            )
            record["new_state"] = copy.deepcopy(new_state)
            target = self._find_slot(self._assignments, record.get("slot_id"))
            if target:
                target.clear()
                target.update(copy.deepcopy(new_state))
        self._history = trim_undo_history(self._history)
        compound = {
            "action": "compound",
            "label": "reconciliation_package",
            "records": [self._stamp_intervention(record) for record in records],
            "package_hash": result.get("package_hash"),
            "metrics": copy.deepcopy(result.get("metrics") or {}),
        }
        if str(decision_note or "").strip():
            compound["decision_note"] = str(decision_note).strip()
        self._history.append(compound)
        self._redo_stack.clear()
        outcome = self._persist_mutation(
            state,
            snapshot,
            "Applied reconciliation package.",
            warnings=list(result.get("warnings") or []),
        )
        if outcome.success:
            outcome.records = records
        return outcome

    def apply_intervention_plan(
        self,
        state,
        actions,
        *,
        confirmed_action_ids=None,
        plan_package_id="",
        profile="",
        decision_note="",
    ):
        """Apply a verified heterogeneous plan as one canonical mutation."""
        snapshot = self._snapshot_mutation_state(state)
        try:
            execution = execute_intervention_actions(
                self,
                actions,
                confirmed_action_ids=confirmed_action_ids,
                apply=True,
            )
            if not execution.get("feasible"):
                self._restore_mutation_state(state, snapshot)
                failed = next(
                    (
                        item
                        for item in execution.get("actions") or []
                        if not item.get("success")
                    ),
                    None,
                )
                return self._action_result(
                    status="failed",
                    message=(
                        (failed or {}).get("message")
                        or "Plan failed canonical revalidation."
                    ),
                )

            records = []
            for record in execution.get("history_records") or []:
                child = copy.deepcopy(record)
                child.setdefault("pi_plan_package_id", plan_package_id or None)
                child.setdefault("pi_plan_profile", profile or None)
                records.append(self._stamp_intervention(child))
            parent = self._stamp_intervention(
                {
                    "action": "compound",
                    "label": "pi_plan",
                    "pi_plan_package_id": plan_package_id or None,
                    "pi_plan_profile": profile or None,
                    "decision_note": str(decision_note or "").strip(),
                    "pi_plan_action_ids": [
                        str(action.get("action_id") or "") for action in actions or []
                    ],
                    "pi_plan_outcome": "applied",
                    "pi_plan_revalidation": {
                        "status": execution.get("status"),
                        "feasible": execution.get("feasible"),
                        "resolved_now": execution.get("resolved_now", 0),
                        "conditionally_resolvable": execution.get(
                            "conditionally_resolvable", 0
                        ),
                        "confirmations_required": execution.get(
                            "confirmations_required", 0
                        ),
                        "actions": copy.deepcopy(execution.get("actions") or []),
                    },
                    "records": records,
                }
            )
            self._history.append(parent)
            self._redo_stack.clear()
            result = self._persist_mutation(
                state,
                snapshot,
                "Applied verified Pi intervention plan.",
            )
            if not result.success:
                self._restore_mutation_state(state, snapshot)
                return result
            return result
        except PackageRejected as exc:
            self._restore_mutation_state(state, snapshot)
            return self._action_result(status="failed", message=str(exc))
        except Exception:
            self._restore_mutation_state(state, snapshot)
            raise

    def validate_assignment(
        self,
        issue_id,
        new_room,
        day,
        new_start,
        new_end,
        *,
        teacher_confirmed=None,
    ):
        unresolved = self._find_unresolved(issue_id)
        if not unresolved:
            return {
                "success": False,
                "message": f"Issue {issue_id} not found.",
            }
        return unresolved_assignment_primitives.validate(
            self.validator,
            unresolved,
            new_room,
            day,
            new_start,
            new_end,
            teacher_confirmed=teacher_confirmed,
        )

    def move(
        self,
        state,
        event_id,
        new_room,
        day,
        new_start,
        new_end,
        *,
        teacher_confirmed=False,
        confirmation_note="",
        decision_note="",
    ):
        new_room = self._normalize_room_id(new_room)
        slot = self._find_slot(self._assignments, event_id)
        if not slot:
            return self._action_result(
                status="failed",
                message=f"Slot {event_id} not found.",
            )

        validation = self._validate_move(
            slot,
            new_room,
            day,
            new_start,
            new_end,
            teacher_confirmed=teacher_confirmed,
        )
        if not validation["success"]:
            return self._action_result(status="failed", message=validation["message"])

        snapshot = self._snapshot_mutation_state(state)
        previous = copy.deepcopy(slot)
        current = self._apply_move(
            slot,
            new_room,
            day,
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
            current = copy.deepcopy(slot)
        self._history = trim_undo_history(self._history)
        record = {
            "action": "move",
            "slot_id": event_id,
            "prev_state": previous,
            "new_state": current,
        }
        if str(decision_note or "").strip():
            record["decision_note"] = str(decision_note).strip()
        self._history.append(self._stamp_intervention(record))
        self._redo_stack.clear()
        return self._persist_mutation(
            state,
            snapshot,
            "Moved!",
            warnings=validation.get("warnings", []),
        )

    def assign(
        self,
        state,
        issue_id,
        new_room,
        day,
        new_start,
        new_end,
        *,
        teacher_confirmed=False,
        confirmation_note="",
        decision_note="",
        pi_proposal_id=None,
    ):
        unresolved = self._find_unresolved(issue_id)
        if not unresolved:
            return self._action_result(
                status="failed",
                message=f"Issue {issue_id} not found.",
            )

        validation = self.validate_assignment(
            issue_id,
            new_room,
            day,
            new_start,
            new_end,
            teacher_confirmed=teacher_confirmed,
        )
        if not validation["success"]:
            return self._action_result(
                status="failed",
                message=validation["message"],
                warnings=list(validation.get("warnings", []) or []),
            )

        snapshot = self._snapshot_mutation_state(state)
        context = unresolved_assignment_primitives.build_context(unresolved)
        if validation.get("requires_teacher_confirmation"):
            attach_teacher_confirmation(
                validation["assignment"],
                instructor=context.get("instructor"),
                note=confirmation_note,
            )
        record = unresolved_assignment_primitives.apply(
            self._assignments,
            self._unassigned_lessons,
            unresolved,
            validation["assignment"],
        )
        if str(decision_note or "").strip():
            record["decision_note"] = str(decision_note).strip()
        if str(pi_proposal_id or "").strip():
            record["pi_proposal_id"] = str(pi_proposal_id).strip()
        self._history = trim_undo_history(self._history)
        self._history.append(self._stamp_intervention(record))
        self._redo_stack.clear()
        label = context.get("student_name") or context.get("instructor") or issue_id
        return self._persist_mutation(
            state,
            snapshot,
            f"Assigned {label} to {new_room}",
            warnings=validation.get("warnings", []),
        )

    def apply_piano_leverage(
        self,
        state,
        proposal,
        *,
        teacher_confirmed=False,
        confirmation_note="",
    ):
        if not teacher_confirmed:
            return self._action_result(
                status="failed",
                message=(
                    "Teacher confirmation is required before applying a Piano "
                    "leverage package."
                ),
            )
        snapshot = self._snapshot_mutation_state(state)
        try:
            records = apply_piano_leverage_package(
                self,
                proposal,
                confirmation_note=confirmation_note,
            )
        except PackageRejected as exc:
            self._restore_mutation_state(state, snapshot)
            return self._action_result(status="failed", message=str(exc))
        except Exception:
            self._restore_mutation_state(state, snapshot)
            raise
        self._history = trim_undo_history(self._history)
        self._history.append(
            self._stamp_intervention(
                {
                    "action": "compound",
                    "label": "piano_leverage",
                    "records": records,
                }
            )
        )
        self._redo_stack.clear()
        return self._persist_mutation(
            state,
            snapshot,
            f"Applied Piano leverage: +{len(proposal.get('fills', []))} resolved",
        )

    def assign_failed(self, state, failed_item, index, view_model, new_room):
        if index < 0 or index >= len(self._unassigned_lessons):
            raise IndexError("failed_index out of range")
        start = view_model.get("start_clock")
        end = view_model.get("end_clock")
        if not start or not end:
            start, end = TimeParser.parse_time_range(view_model.get("requested_time"))
        unresolved = self._unassigned_lessons[index]
        return self.assign(
            state,
            unresolved_assignment_primitives.issue_id(unresolved),
            new_room,
            view_model["detected_day"],
            start,
            end,
        )
