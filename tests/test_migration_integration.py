
import unittest
import os
import shutil
import tempfile
import sys
from pathlib import Path

# Import migration script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import migrate_model_names

class TestMigration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.models_dir = os.path.join(self.test_dir, "models")
        os.makedirs(self.models_dir)
        
        # Create dummy project folder structure
        # /tmp/xxx/myproject/models
        # So folder name is 'models'? No, logic is dirname(abspath(models_dir/..))
        # Wait, if models_dir is /tmp/xxx/models, then parent is /tmp/xxx.
        # folder_name will be xxx.
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_dummy_file(self, filename):
        path = os.path.join(self.models_dir, filename)
        with open(path, 'w') as f:
            f.write("dummy content")
        return path

    def test_migration_logic(self):
        # Setup files
        # Old format: pilot-231027-001.tflite
        old_file = "pilot-231027-001.tflite"
        self.create_dummy_file(old_file)
        
        # Run migration
        # We need to capture stdout or just check files
        migrate_model_names.migrate_models(self.models_dir, dry_run=False)
        
        # Check results
        files = os.listdir(self.models_dir)
        self.assertEqual(len(files), 1)
        
        new_file = files[0]
        self.assertNotEqual(new_file, old_file)
        
        # Expected format: {folder}-{base}-{date}-{suffix}.tflite
        folder_name = os.path.basename(self.test_dir)
        self.assertTrue(new_file.startswith(f"{folder_name}-pilot-231027-"))
        self.assertTrue(new_file.endswith(".tflite"))
        
        # Check suffix length (4 chars)
        # folder-pilot-231027-XXXX.tflite
        # split by -
        parts = new_file.split('-')
        suffix = parts[-1].replace(".tflite", "")
        self.assertEqual(len(suffix), 4)

if __name__ == '__main__':
    unittest.main()
