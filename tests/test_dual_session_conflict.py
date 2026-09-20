"""TDD: detect cross-session write conflicts at the session root boundary."""
import os
import threading
import tempfile
import time
import unittest
import shutil
from unittest.mock import patch

from modules.shared.session_manager import SessionManager


class TestDualSessionConflict(unittest.TestCase):
    def setUp(self):
        self.test_dir = "data_test_dual_session"
        os.makedirs(self.test_dir, exist_ok=True)
        SessionManager(base_dir=self.test_dir).clear_session()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_second_writer_gets_conflict_when_mtime_changes(self):
        writer_a = SessionManager(base_dir=self.test_dir)
        writer_b = SessionManager(base_dir=self.test_dir)

        first_mtime = writer_a.get_session_mtime()
        writer_a.save_session({"step": 1}, expected_mtime=first_mtime)
        observed_mtime = writer_a.get_session_mtime()
        self.assertIsNotNone(observed_mtime)

        time.sleep(0.01)
        writer_b.save_session({"step": 2}, expected_mtime=None)

        outcome = writer_a.save_session({"step": 3}, expected_mtime=observed_mtime)
        self.assertEqual(outcome.status, "conflict")
        self.assertIn("another", outcome.warning.lower())

    def test_primary_revision_rejects_stale_writer(self):
        writer_a = SessionManager(base_dir=self.test_dir)
        writer_b = SessionManager(base_dir=self.test_dir)
        writer_a.save_session({"writer": "initial"})
        revision = writer_a.get_session_revision()

        writer_b.save_session({"writer": "external"})
        outcome = writer_a.save_session(
            {"writer": "stale"}, expected_mtime=revision
        )

        self.assertEqual(outcome.status, "conflict")
        self.assertEqual(writer_a.load_session(), {"writer": "external"})

    def test_newer_shadow_revision_rejects_stale_writer(self):
        writer_a = SessionManager(base_dir=self.test_dir)
        writer_b = SessionManager(base_dir=self.test_dir)
        writer_a.save_session({"writer": "primary"})
        primary = writer_a._get_path()
        shadow = writer_a._get_shadow_paths()[0]
        writer_a._atomic_write(shadow, {"writer": "shadow-initial"})
        future_ns = os.stat(primary).st_mtime_ns + 2_000_000_000
        os.utime(shadow, ns=(future_ns, future_ns))
        revision = writer_a.get_session_revision()
        self.assertEqual(revision.source, os.path.abspath(shadow))

        original_write = writer_b._atomic_write

        def shadow_only(path, payload, preserve_existing=True):
            if path == primary:
                raise PermissionError("primary unavailable")
            original_write(path, payload, preserve_existing=preserve_existing)
            newer_ns = future_ns + 2_000_000_000
            os.utime(path, ns=(newer_ns, newer_ns))

        with patch.object(writer_b, "_atomic_write", side_effect=shadow_only):
            outcome = writer_b.save_session({"writer": "external"})
        self.assertEqual(outcome.status, "shadow")

        stale = writer_a.save_session(
            {"writer": "stale"}, expected_mtime=revision
        )

        self.assertEqual(stale.status, "conflict")
        self.assertEqual(writer_a.load_session(), {"writer": "external"})

    def test_source_switch_conflicts_even_when_mtime_ns_matches(self):
        manager = SessionManager(base_dir=self.test_dir)
        manager.save_session({"source": "primary"})
        primary_revision = manager.get_session_revision()
        primary = manager._get_path()
        shadow = manager._get_shadow_paths()[0]

        manager._atomic_write(shadow, {"source": "shadow"})
        os.utime(
            shadow,
            ns=(primary_revision.mtime_ns, primary_revision.mtime_ns),
        )
        os.remove(primary)

        outcome = manager.save_session(
            {"source": "stale-primary"}, expected_mtime=primary_revision
        )

        self.assertEqual(outcome.status, "conflict")
        self.assertEqual(manager.load_session(), {"source": "shadow"})

        shadow_revision = manager.get_session_revision()
        manager._atomic_write(primary, {"source": "new-primary"})
        os.utime(
            primary,
            ns=(shadow_revision.mtime_ns, shadow_revision.mtime_ns),
        )
        os.remove(shadow)

        outcome = manager.save_session(
            {"source": "stale-shadow"}, expected_mtime=shadow_revision
        )

        self.assertEqual(outcome.status, "conflict")
        self.assertEqual(manager.load_session(), {"source": "new-primary"})

    def test_file_lock_closes_check_then_write_race(self):
        writer_a = SessionManager(base_dir=self.test_dir)
        writer_b = SessionManager(base_dir=self.test_dir)
        writer_a.save_session({"writer": "initial"})
        revision = writer_a.get_session_revision()
        original_write = writer_a._atomic_write
        first_checked = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()
        outcomes = {}

        def paused_write(path, payload, preserve_existing=True):
            first_checked.set()
            self.assertTrue(release_first.wait(timeout=2))
            original_write(path, payload, preserve_existing=preserve_existing)
            changed_ns = revision.mtime_ns + 2_000_000_000
            os.utime(path, ns=(changed_ns, changed_ns))

        def first_save():
            with patch.object(writer_a, "_atomic_write", side_effect=paused_write):
                outcomes["first"] = writer_a.save_session(
                    {"writer": "first"}, expected_mtime=revision
                )

        def second_save():
            second_started.set()
            outcomes["second"] = writer_b.save_session(
                {"writer": "second"}, expected_mtime=revision
            )
            second_finished.set()

        first = threading.Thread(target=first_save)
        second = threading.Thread(target=second_save)
        first.start()
        self.assertTrue(first_checked.wait(timeout=2))
        second.start()
        self.assertTrue(second_started.wait(timeout=2))
        self.assertFalse(second_finished.wait(timeout=0.05))
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(outcomes["first"].status, "primary")
        self.assertEqual(outcomes["second"].status, "conflict")
        self.assertEqual(writer_a.load_session(), {"writer": "first"})

    def test_symlink_aliases_share_shadow_revision_and_cas(self):
        with tempfile.TemporaryDirectory() as root:
            real_dir = os.path.join(root, "real-data")
            alias_dir = os.path.join(root, "alias-data")
            os.makedirs(real_dir)
            os.symlink(real_dir, alias_dir)
            real_writer = SessionManager(base_dir=real_dir)
            alias_writer = SessionManager(base_dir=alias_dir)
            stale_revision = alias_writer.get_session_revision()

            self.assertEqual(real_writer._get_lock_path(), alias_writer._get_lock_path())
            self.assertEqual(real_writer._get_shadow_paths(), alias_writer._get_shadow_paths())

            def force_shadow(manager):
                original_write = manager._atomic_write

                def shadow_only(path, payload, preserve_existing=True):
                    if os.path.realpath(path) == os.path.realpath(manager._get_path()):
                        raise PermissionError("primary session is read-only")
                    return original_write(
                        path,
                        payload,
                        preserve_existing=preserve_existing,
                    )

                return shadow_only

            with patch.object(
                real_writer,
                "_atomic_write",
                side_effect=force_shadow(real_writer),
            ):
                external = real_writer.save_session({"writer": "external"})

            self.assertEqual(external.status, "shadow")
            self.assertEqual(alias_writer.load_session(), {"writer": "external"})
            with patch.object(
                alias_writer,
                "_atomic_write",
                side_effect=force_shadow(alias_writer),
            ):
                stale = alias_writer.save_session(
                    {"writer": "stale"},
                    expected_mtime=stale_revision,
                )

            self.assertEqual(stale.status, "conflict")
            self.assertEqual(real_writer.load_session(), {"writer": "external"})
            self.assertEqual(alias_writer.load_session(), {"writer": "external"})
