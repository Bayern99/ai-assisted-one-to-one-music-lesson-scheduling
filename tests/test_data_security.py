import unittest
import os
import json
import shutil
import time
from modules.shared.data_loader import DataLoader, DataCorruptionError

class TestDataSecurity(unittest.TestCase):
    def setUp(self):
        self.loader = DataLoader("data_test")
        self.loader.ensure_dirs()
        self.test_file = "test_corrupt.json"
        
    def tearDown(self):
        if os.path.exists("data_test"):
            shutil.rmtree("data_test")

    def test_atomic_write(self):
        """Test that save_data writes correct JSON"""
        data = {"key": "value", "id": 123}
        self.loader.save_data("atomic_test.json", data)
        
        path = os.path.join("data_test", "atomic_test.json")
        self.assertTrue(os.path.exists(path))
        with open(path, 'r') as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_corruption_handling(self):
        """Test that loading corrupted JSON raises error and creates backup"""
        # 1. Create corrupted file
        path = os.path.join("data_test", self.test_file)
        with open(path, 'w') as f:
            f.write("{ invalid json : [ broken }")
            
        # 2. Assert Error Raised
        with self.assertRaises(DataCorruptionError):
            self.loader.get_data(self.test_file)
            
        # 3. Assert Backup Created
        backup_dir = os.path.join("data_test", "corrupted_backups")
        self.assertTrue(os.path.exists(backup_dir))
        backups = os.listdir(backup_dir)
        self.assertTrue(len(backups) > 0)
        print(f"Backup created: {backups[0]}")

if __name__ == '__main__':
    unittest.main()
