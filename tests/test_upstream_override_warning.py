"""上游 donkeycar 包覆盖检测测试。

验证 donkeydrifter 导入时：
- 环境中不存在名为 donkeycar 的发行包（正常 DonkeyDrifter 安装）→ 无警告；
- 存在官方上游 donkeycar 包（误装覆盖）→ stderr 输出修复指引。
"""
import importlib
import importlib.metadata
import importlib.metadata as importlib_metadata_module
import sys
import unittest
from unittest import mock

import donkeydrifter


class _FakeDistribution:
    """模拟官方 donkeycar 发行包元数据。"""

    version = '4.9.2'


class TestUpstreamOverrideWarning(unittest.TestCase):

    def _reload_with(self, distribution_mock):
        """在受控的 distribution() 环境下重新加载 donkeydrifter。

        返回 (module, stdout, stderr)。
        """
        import io
        import contextlib

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(
                importlib_metadata_module, 'distribution',
                distribution_mock), \
                contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            module = importlib.reload(donkeydrifter)
        return module, stdout.getvalue(), stderr.getvalue()

    def test_no_warning_without_upstream_donkeycar(self):
        """正常安装（无 donkeycar 发行包）时导入不应产生任何警告。"""

        def raise_not_found(name):
            raise importlib.metadata.PackageNotFoundError(name)

        _, stdout, stderr = self._reload_with(raise_not_found)
        self.assertEqual(stdout, '')
        self.assertEqual(stderr, '')

    def test_warning_when_upstream_donkeycar_installed(self):
        """误装官方 donkeycar 后导入应输出修复指引到 stderr。"""

        def fake_distribution(name):
            if name == 'donkeycar':
                return _FakeDistribution()
            raise importlib.metadata.PackageNotFoundError(name)

        _, stdout, stderr = self._reload_with(fake_distribution)
        self.assertEqual(stdout, '')
        self.assertIn('WARNING: upstream "donkeycar" package detected', stderr)
        self.assertIn('4.9.2', stderr)
        self.assertIn('pip uninstall -y donkeycar', stderr)
        self.assertIn('donkeydrifter[macos]', stderr)
        self.assertIn('donkeydrifter[pc]', stderr)

    def test_metadata_failure_does_not_break_import(self):
        """元数据解析异常时不应阻塞导入。"""

        def raise_unexpected(name):
            raise RuntimeError('corrupted metadata')

        module, _, _ = self._reload_with(raise_unexpected)
        self.assertTrue(hasattr(module, '__version__'))

    @classmethod
    def tearDownClass(cls):
        # 确保测试结束后模块恢复到无 mock 的正常状态
        importlib.reload(donkeydrifter)


if __name__ == '__main__':
    unittest.main()
