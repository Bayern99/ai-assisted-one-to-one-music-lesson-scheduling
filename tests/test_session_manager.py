import unittest
import os
import shutil
import json
import time
import pandas as pd
from unittest.mock import patch, MagicMock

# This import will fail initially (RED Phase)
try:
    from modules.shared.session_manager import SessionManager
except ImportError:
    SessionManager = None

class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = "data_test_session"
        if not os.path.exists(self.test_dir):
            os.makedirs(self.test_dir)
            
    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            
    def test_00_class_exists(self):
        """CRITICAL: Test that SessionManager class is implemented"""
        self.assertIsNotNone(SessionManager, "SessionManager class not found! (RED Phase confirmed)")

    def test_01_save_and_load(self):
        """Test basic save and restore"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir)
        test_data = {"step": 2, "config": {"algo": "csp"}}
        
        # Save
        manager.save_session(test_data)
        
        # Verify file exists
        files = os.listdir(self.test_dir)
        self.assertIn("session_cache.json", files)
        
        # Load
        loaded = manager.load_session()
        self.assertEqual(loaded['step'], 2)
        self.assertEqual(loaded['config']['algo'], "csp")

    def test_02_expiration(self):
        """Test that old sessions are ignored (TTL)"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir, ttl_seconds=3600)
        test_data = {"step": 1}
        manager.save_session(test_data)
        
        # Manually backdate the file by 2 hours
        cache_path = os.path.join(self.test_dir, "session_cache.json")
        past_time = time.time() - 7200 
        os.utime(cache_path, (past_time, past_time))
        
        # Load should return None (Expired)
        loaded = manager.load_session()
        self.assertIsNone(loaded, "Expired session should return None")

    def test_02b_default_manager_restores_weekend_old_draft(self):
        if not SessionManager: return

        manager = SessionManager(base_dir=self.test_dir)
        manager.save_session({"step4_edit_session": {"assignments": [{"id": "wk-1"}]}})
        cache_path = os.path.join(self.test_dir, "session_cache.json")
        past_time = time.time() - (3 * 86400)
        os.utime(cache_path, (past_time, past_time))

        loaded = manager.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["step4_edit_session"]["assignments"][0]["id"], "wk-1")

    def test_03_empty_state_handling(self):
        """Test loading when no session exists"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir)
        loaded = manager.load_session()
        self.assertIsNone(loaded)

    def test_04_pandas_serialization(self):
        """Test that Pandas DataFrames are serialized correctly"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir)
        df = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
        test_data = {"my_df": df, "normal": 123}
        
        # Save (This should fail if not handled)
        try:
            manager.save_session(test_data)
        except TypeError:
            self.fail("SessionManager failed to serialize Pandas DataFrame!")
            
        # Load and verify reconstruction
        loaded = manager.load_session()
        self.assertIn("my_df", loaded)
        
        # Check if it came back as a dict (JSON default) or reconstructed (Advanced)
        # For now, just ensuring it saves without crashing is Step 1.
        # Ideally we want it back as DataFrame or list of records.
        # Let's say we expect it to be handled gracefully (e.g. converted to records).
        reloaded_df = pd.DataFrame(loaded['my_df'])
        pd.testing.assert_frame_equal(df, reloaded_df)

    def test_05_scheduler_structure(self):
        """Test exact structure used in Scheduler page"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir)
        
        # Simulate Scheduler State
        wk_df = pd.DataFrame({"Room": ["A", "B"]})
        stu_df = pd.DataFrame({"Student": ["X", "Y"]})
        assignments = {"A": ["X"], "B": ["Y"]}
        logs = ["Log 1", "Log 2"]
        
        session_data = {
            "wk_df": wk_df,
            "stu_df": stu_df,
            "generated_assignments": assignments,
            "opt_logs": logs
        }
        
        # This should succeed with our SessionEncoder
        manager.save_session(session_data)
        
        loaded = manager.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded['opt_logs']), 2)
        # Verify DataFrame conversion (it becomes list of dicts)
        self.assertIsInstance(loaded['wk_df'], list)


    def test_06_clear_session(self):
        """Test that clear_session physically removes the cache file"""
        if not SessionManager: return
        
        manager = SessionManager(base_dir=self.test_dir)
        
        # 1. Create a dummy session
        manager.save_session({"state": "dirty"})
        cache_path = os.path.join(self.test_dir, "session_cache.json")
        self.assertTrue(os.path.exists(cache_path), "Setup failed: Cache file not created")
        
        # 2. Clear it
        manager.clear_session()
        
        # 3. Verify deletion
        self.assertFalse(os.path.exists(cache_path), "clear_session failed to remove file")
        
        # 4. Idempotency Check (Should not crash if called again)
        try:
            manager.clear_session()
        except Exception as e:
            self.fail(f"clear_session raised exception on second call: {e}")

if __name__ == '__main__':
    unittest.main()
