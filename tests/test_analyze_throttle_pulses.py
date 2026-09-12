"""analyze_throttle_pulses 参数健壮性测试（M2 验收工具）。

覆盖 scripts/analyze_throttle_pulses.py 的参数解析错误路径：
--center 缺逗号/非数值、 tub 路径不存在——均应中文提示而非裸 traceback。
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from scripts.analyze_throttle_pulses import main


class ArgumentRobustnessTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pulse_cli_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_main(self, argv):
        with mock.patch.object(sys, "argv", ["analyze_throttle_pulses.py"] + argv):
            return main()

    def test_center_without_comma_is_usage_error(self):
        # "1.0" 缺逗号 → parser.error（SystemExit 2），不裸 traceback
        with self.assertRaises(SystemExit) as cm:
            self._run_main([self.tmp, "--center", "1.0"])
        self.assertEqual(cm.exception.code, 2)

    def test_center_non_numeric_is_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            self._run_main([self.tmp, "--center", "abc"])
        self.assertEqual(cm.exception.code, 2)

    def test_missing_tub_dir_returns_1(self):
        missing = os.path.join(self.tmp, "no_such_tub")
        rc = self._run_main([missing, "--center", "1.0,1.0"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
