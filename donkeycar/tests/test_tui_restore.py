import os
import shutil
import tempfile
import unittest
import tarfile
from pathlib import Path
# Assuming the file structure allows this import. 
# Since we are running from project root, we might need to adjust python path or import.
# I will assume 'donkeycar' is in python path.
from donkeycar.management.tui import _get_data_cache_dir, _list_backup_archives, _is_valid_archive

class TestRestoreData(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.data_cache = Path("data_cache")
        self.data_cache.mkdir()

    def tearDown(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def test_get_data_cache_dir(self):
        # This expects the function to return the local data_cache
        expected = Path(self.test_dir) / "data_cache"
        self.assertEqual(_get_data_cache_dir(), expected)

    def test_list_backup_archives(self):
        # Create standard file
        (self.data_cache / "data-231001-001.tar.gz").touch()
        # Create non-standard file
        (self.data_cache / "data0205.tar.gz").touch()
        # Create irrelevant file
        (self.data_cache / "invalid.txt").touch()
        
        archives = _list_backup_archives(self.data_cache)
        self.assertEqual(len(archives), 2)
        
        # Verify standard file
        standard = next(a for a in archives if "data-231001-001" in a["path"].name)
        self.assertEqual(standard['seq'], '001')
        
        # Verify non-standard file
        non_standard = next(a for a in archives if "data0205" in a["path"].name)
        self.assertEqual(non_standard['seq'], 'N/A')

    def test_is_valid_archive(self):
        # 1. Test missing file
        missing_file = self.data_cache / "missing.tar.gz"
        self.assertFalse(_is_valid_archive(missing_file))

        # 2. Test directory (should be false)
        dir_path = self.data_cache / "some_dir"
        dir_path.mkdir()
        self.assertFalse(_is_valid_archive(dir_path))

        # 3. Test invalid content
        invalid_file = self.data_cache / "invalid.tar.gz"
        with open(invalid_file, "wb") as f:
            f.write(b"not a tar file")
        self.assertFalse(_is_valid_archive(invalid_file))

        # 4. Test valid tar.gz
        valid_file = self.data_cache / "valid.tar.gz"
        with tarfile.open(valid_file, "w:gz") as tar:
            # Create a dummy file to add
            dummy = self.test_dir + "/dummy.txt"
            with open(dummy, "w") as f:
                f.write("content")
            tar.add(dummy, arcname="dummy.txt")
        
        self.assertTrue(_is_valid_archive(valid_file))

if __name__ == '__main__':
    unittest.main()
