"""TDD for Step 4 workflow service commit semantics."""

from modules.shared.save_outcome import SaveOutcome
from modules.scheduler.logic.workflow_service import commit_current_round


class DummyLoader:
    def __init__(self, bookings):
        self._bookings = bookings
        self.saved = None

    def load_bookings(self):
        return self._bookings

    def save_bookings(self, payload):
        self.saved = payload


class DummySessionManager:
    def __init__(self):
        self.saved = None

    def save_session(self, payload):
        self.saved = payload


class TestCommitNoMutation:
    def test_commit_does_not_mutate_generated_assignments(self):
        loader = DummyLoader(
            [{"id": "legacy_weekly", "type": "weekly_lesson", "committed": True, "resourceId": "R1"}]
        )
        session_mgr = DummySessionManager()
        generated = [
            {
                "id": "wk_1",
                "type": "weekly_lesson",
                "title": "n/a studio",
                "resourceId": "R2",
                "extendedProps": {"Student Name": "n/a studio"},
            }
        ]
        state = {
            "generated_assignments": generated,
            "override_history": [],
            "redo_stack": [],
            "unassigned_lessons": [],
            "round_committed": False,
        }

        final = commit_current_round(loader, session_mgr, state)

        assert generated[0]["type"] == "weekly_lesson"
        assert final[-1]["type"] == "weekly_lesson"
        assert loader.saved[-1]["type"] == "weekly_lesson"

    def test_commit_normalizes_explicit_studio_artifacts_without_mutating_generated_assignments(self):
        loader = DummyLoader(
            [{"id": "legacy_weekly", "type": "weekly_lesson", "committed": True, "resourceId": "R1"}]
        )
        session_mgr = DummySessionManager()
        generated = [
            {
                "id": "stu_failed_1",
                "type": "weekly_lesson",
                "title": "👤 N/A (Studio) (Piano)",
                "resourceId": "R2",
                "extendedProps": {"Student Name": "N/A (Studio)", "Course Code": "STU"},
            }
        ]
        state = {
            "generated_assignments": generated,
            "override_history": [],
            "redo_stack": [],
            "unassigned_lessons": [],
            "round_committed": False,
        }

        final = commit_current_round(loader, session_mgr, state)

        assert generated[0]["type"] == "weekly_lesson"
        assert final[-1]["type"] == "studio_class"
        assert loader.saved[-1]["type"] == "studio_class"

    def test_commit_marks_only_current_round_items_as_committed(self):
        loader = DummyLoader(
            [
                {"id": "legacy_weekly", "type": "weekly_lesson", "committed": True, "resourceId": "R1"},
                {"id": "keep_other", "type": "lecture", "resourceId": "R9"},
            ]
        )
        session_mgr = DummySessionManager()
        state = {
            "generated_assignments": [
                {"id": "wk_1", "type": "weekly_lesson", "resourceId": "R2", "extendedProps": {}},
                {"id": "stu_1", "type": "studio_class", "resourceId": "R3", "extendedProps": {}},
            ],
            "override_history": [],
            "redo_stack": [],
            "unassigned_lessons": [],
            "round_committed": False,
        }

        final = commit_current_round(loader, session_mgr, state)
        committed_by_id = {evt["id"]: evt.get("committed") for evt in final}

        assert committed_by_id["wk_1"] is True
        assert committed_by_id["stu_1"] is True
        assert committed_by_id["legacy_weekly"] is True
        assert committed_by_id["keep_other"] is None
        assert state["round_committed"] is True
        assert session_mgr.saved["round_committed"] is True

    def test_commit_shadow_save_does_not_mark_round_committed_or_clear_draft(self):
        class ShadowLoader(DummyLoader):
            def save_bookings(self, payload):
                self.saved = payload
                return SaveOutcome(
                    status="shadow",
                    path="/tmp/shadow/bookings.json",
                    warning="Primary save failed for bookings.json; wrote fallback shadow copy.",
                )

        loader = ShadowLoader([])
        session_mgr = DummySessionManager()
        state = {
            "step4_edit_session": {
                "assignments": [{"id": "wk_1", "type": "weekly_lesson", "resourceId": "R2", "extendedProps": {}}],
                "unassigned_lessons": [],
                "history": [{"action": "move"}],
                "redo_stack": [],
                "dirty": True,
                "last_save_outcome": None,
            },
            "round_committed": False,
        }

        try:
            commit_current_round(loader, session_mgr, state)
            raise AssertionError("expected degraded shadow save to fail commit")
        except RuntimeError as exc:
            assert "shadow copy" in str(exc)

        assert state["round_committed"] is False
        assert state["step4_edit_session"]["dirty"] is True
        assert session_mgr.saved is None
