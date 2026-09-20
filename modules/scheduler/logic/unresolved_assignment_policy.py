"""Hard policy checks for placing an unresolved Step 4 request."""

from modules.scheduler.logic.instructor_time_integrity import instructor_is_available
from modules.scheduler.logic.schedule_change_policy import (
    confirmation_message,
    context_time_changed,
    instructor_allows_time_change,
    time_change_pool_message,
)


def validate_unresolved_policy(
    validator,
    *,
    context,
    room,
    day,
    start_norm,
    end_norm,
    start_min,
    end_min,
    teacher_confirmed,
):
    """Return teacher, room-rule, and confirmation checks for one proposal."""
    instructor = context.get("instructor") or ""
    specific_date = (
        context["original_date"]
        if context["type"] == "studio_class"
        else None
    )
    if not instructor_is_available(
        getattr(validator, "assignments", []),
        instructor=instructor,
        day=day,
        start_min=start_min,
        end_min=end_min,
        specific_date=specific_date,
    ):
        return {
            "success": False,
            "message": (
                f"Instructor time conflict: {instructor} is already teaching "
                "at this time."
            ),
        }

    instrument = context.get("instrument")
    if instrument and hasattr(validator, "validate_rules"):
        rules_check = validator.validate_rules(room, instrument)
        if not rules_check.get("allowed", True):
            return {
                "success": False,
                "message": rules_check.get("reason", "Room type mismatch"),
            }

    requires_confirmation = context_time_changed(
        context,
        day=day,
        start=start_norm,
        end=end_norm,
    )
    if requires_confirmation and not instructor_allows_time_change(
        getattr(validator, "rules", {}),
        instructor,
    ):
        return {
            "success": False,
            "message": time_change_pool_message(instructor),
        }
    teacher_message = confirmation_message(instructor) if requires_confirmation else None
    if requires_confirmation and teacher_confirmed is False:
        return {
            "success": False,
            "message": teacher_message,
            "requires_teacher_confirmation": True,
            "teacher_confirmation_message": teacher_message,
        }

    return {
        "success": True,
        "requires_teacher_confirmation": requires_confirmation,
        "teacher_confirmation_message": teacher_message,
    }
