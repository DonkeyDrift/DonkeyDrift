import shutil
import tempfile
import unittest
from random import randint

from donkeycar.parts.datastore import TubHandler
from donkeycar.parts.tub_v2 import Tub, TubWriter, TubRotator


class TestTub(unittest.TestCase):
    def setUp(self):
        self._path = tempfile.mkdtemp()

    def test_tubwriter_sessions(self):
        # run tubwriter multiple times on the same tub directory
        write_counts = []
        for _ in range(5):
            tub_writer = TubWriter(self._path, inputs=['input'], types=['int'])
            write_count = randint(1, 10)
            for i in range(write_count):
                tub_writer.run(i)
            tub_writer.close()
            write_counts.append(write_count)

        # Check we have good session id for all new records:
        id = 0
        total = 0
        for record in tub_writer.tub:
            print(f'Record: {record}')
            session_number = int(record['_session_id'].split('_')[1])
            self.assertEqual(session_number, id,
                             'Session id not correctly generated')
            total += 1
            if total == write_counts[0]:
                total = 0
                id += 1
                write_counts.pop(0)

    def tearDown(self):
        shutil.rmtree(self._path)


class TestTubRotator(unittest.TestCase):
    def setUp(self):
        self._path = tempfile.mkdtemp()
        self._data_path = tempfile.mkdtemp()

    def _new_writer(self):
        return TubWriter(self._path, inputs=['input'], types=['int'])

    def test_new_tub_resets_count(self):
        tub_writer = self._new_writer()
        tub_writer.run(1)
        tub_writer.run(2)
        self.assertEqual(tub_writer.tub.manifest.current_index, 2)

        new_path = TubHandler(path=self._data_path).create_tub_path()
        tub_writer.new_tub(new_path)
        self.assertEqual(tub_writer.tub.manifest.current_index, 0)
        self.assertEqual(tub_writer.run(42), 1)
        self.assertEqual(tub_writer.tub.base_path, new_path)
        # old tub is untouched after rotation
        old_tub = Tub(self._path, ['input'], ['int'])
        self.assertEqual(old_tub.manifest.current_index, 2)
        old_tub.close()
        tub_writer.close()

    def test_rotates_on_rising_edge_when_tub_has_records(self):
        tub_writer = self._new_writer()
        tub_writer.run(1)
        rotator = TubRotator(tub_writer, self._data_path)

        rotator.run(False)
        self.assertEqual(tub_writer.tub.manifest.current_index, 1)
        rotator.run(True)  # rising edge -> rotate to new tub
        self.assertNotEqual(tub_writer.tub.base_path, self._path)
        self.assertEqual(tub_writer.tub.manifest.current_index, 0)
        first_tub_path = tub_writer.tub.base_path
        tub_writer.run(7)  # record some frames in the new tub
        rotator.run(True)  # staying True -> no further rotation
        self.assertEqual(tub_writer.tub.base_path, first_tub_path)
        rotator.run(False)
        rotator.run(True)  # next rising edge -> rotate again
        self.assertNotEqual(tub_writer.tub.base_path, first_tub_path)
        self.assertEqual(tub_writer.tub.manifest.current_index, 0)
        tub_writer.close()

    def test_no_rotation_when_tub_empty(self):
        tub_writer = self._new_writer()
        rotator = TubRotator(tub_writer, self._data_path)

        rotator.run(True)  # rising edge but tub holds no records
        self.assertEqual(tub_writer.tub.base_path, self._path)
        tub_writer.close()

    def tearDown(self):
        shutil.rmtree(self._path)
        shutil.rmtree(self._data_path)


if __name__ == '__main__':
    unittest.main()
