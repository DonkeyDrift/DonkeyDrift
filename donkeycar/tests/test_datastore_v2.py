import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from donkeycar.parts.datastore_v2 import Manifest


class TestDatastore(unittest.TestCase):

    def setUp(self):
        self._path = tempfile.mkdtemp()

    def test_basic_datastore_operations(self):
        # 2 records per catalog entry in the manifest
        manifest = Manifest(self._path, max_len=2)
        count = 10
        for i in range(count):
            manifest.write_record(self._newRecord())

        read_records = 0
        for entry in manifest:
            print('Entry %s' % (entry))
            read_records += 1

        self.assertEqual(count, read_records)

    def test_deletion(self):
        manifest = Manifest(self._path, max_len=2)
        count = 10
        deleted = 5
        for i in range(count):
            manifest.write_record(self._newRecord())

        for i in range(deleted):
            manifest.delete_records(i)

        read_records = 0
        for entry in manifest:
            print(f'Entry {entry}')
            read_records += 1

        self.assertEqual((count - deleted), read_records)

    def test_delete_and_restore_by_set(self):
        manifest = Manifest(self._path, max_len=2)
        count = 10
        deleted = range(3, 7)
        for i in range(count):
            manifest.write_record(self._newRecord())

        manifest.delete_records(deleted)
        read_records = 0
        for entry in manifest:
            print(f'Entry {entry}')
            read_records += 1

        self.assertEqual(count - len(deleted), read_records)

        manifest.restore_records(deleted)
        read_records = 0
        for entry in manifest:
            print(f'Entry {entry}')
            read_records += 1

        self.assertEqual(count, read_records)

    def test_memory_mapped_read(self):
        manifest = Manifest(self._path, max_len=2)
        for i in range(10):
            manifest.write_record(self._newRecord())
        manifest.close()

        manifest_2 = Manifest(self._path, read_only=True)
        read_records = 0
        for _ in manifest_2:
            read_records += 1

        manifest_2.close()

        self.assertEqual(10, read_records)

    def test_read_only_manifest_with_empty_catalog(self):
        # A recording that stops right after a catalog roll-over (or crashes
        # before its first record) leaves a 0-byte catalog registered in the
        # manifest. Opening such a datastore read-only must not crash —
        # mmap of an empty file raises "cannot mmap an empty file".
        manifest = Manifest(self._path, max_len=2)
        for i in range(3):
            manifest.write_record(self._newRecord())
        # Simulate a roll-over where no record lands: the next catalog is
        # created and registered but stays 0-byte.
        manifest._add_catalog()
        manifest.close()

        manifest_2 = Manifest(self._path, read_only=True)
        try:
            read_records = 0
            for _ in manifest_2:
                read_records += 1
        finally:
            manifest_2.close()

        self.assertEqual(3, read_records)

    def tearDown(self):
        shutil.rmtree(self._path)

    def _newRecord(self):
        record = {'at' : time.time()}
        return record


if __name__ == '__main__':
    unittest.main()


def test_manifest_iterator_closes_catalogs(tmp_path, monkeypatch):
    """#501：迭代换 catalog/结束时显式 close，句柄不靠 GC 兜底。"""
    import donkeycar.parts.datastore_v2 as ds

    closed = []
    real_close = ds.Catalog.close

    def spy_close(self):
        closed.append(self.path.name)
        real_close(self)

    monkeypatch.setattr(ds.Catalog, "close", spy_close)

    from donkeycar.parts.tub_v2 import Tub
    import numpy as np

    tub = Tub(str(tmp_path), inputs=['cam/image_array', 'user/angle'],
              types=['image_array', 'float'])
    tub.manifest.max_len = 2  # 每 2 条滚动一个 catalog
    for i in range(5):
        tub.write_record({'user/angle': 0.1 * i,
                          'cam/image_array': np.zeros((4, 4, 3), dtype=np.uint8)})
    tub.close()

    manifest = ds.Manifest(str(tmp_path))
    n = len(list(manifest))  # 全量迭代
    assert n >= 3
    catalog_names = [p for p in manifest.catalog_paths]
    # 迭代中每个访问过的 catalog 都被显式关闭（含最后一个）
    for name in catalog_names:
        assert name in closed, f"{name} 未显式关闭（#501）"
    manifest.close()
