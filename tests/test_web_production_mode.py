"""`donkey web` 默认生产模式回归测试（#135）。

根因：donkey web 此前始终用 `npm run dev` 起 Vite dev 服务器给最终用户，
dev 模式跑未优化代码 + React dev 运行时，顶部导航切换实测 ~400-550ms；
生产构建由后端托管时仅 ~43-63ms。issue #135 因此在首轮前端优化后仍被重开。

本测试验证：
1. 默认（不带 --dev）为生产模式：不起 Vite，前端由后端托管，
   frontend_port == backend_port，dist 缺失/过期时先 npm run build。
2. --dev 保留开发模式：起 `npm run dev`，Vite 独立监听 frontend_port。
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

from donkeycar.management.base import Web


def _make_args(**overrides):
    """构造一份与 Web.parse_args 默认值等价的 args。"""
    defaults = dict(
        path='/fake/web_ui',
        frontend_port=5188,
        backend_port=8000,
        backend_host='0.0.0.0',
        install_deps=False,
        open=False,
        route='/',
        dev=False,
        debug=False,
    )
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class _FakeDirs:
    """让 _launch_web_ui 的目录/依赖检查通过。"""

    def setUp(self):
        self._patches = [
            mock.patch.object(Web, '_resolve_web_ui_path', return_value='/fake/web_ui'),
            mock.patch.object(Web, '_check_dependencies_or_warn', lambda *a, **k: None),
            mock.patch('os.path.isdir', return_value=True),
            mock.patch('shutil.which', return_value='/usr/bin/npm'),
            mock.patch.object(Web, '_choose_available_port', side_effect=lambda host, port: port),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()


class TestWebProductionModeDefault(_FakeDirs, unittest.TestCase):
    """默认应为生产模式：SPA 由后端托管，不启动 Vite dev 服务器。"""

    def test_default_builds_dist_and_no_vite(self):
        popen_cmds = []
        run_cmds = []

        def fake_popen(cmd, **kwargs):
            popen_cmds.append(cmd)
            return mock.MagicMock(poll=lambda: None)

        def fake_run(cmd, **kwargs):
            run_cmds.append(cmd)
            return mock.MagicMock(returncode=0)

        with mock.patch.object(Web, '_frontend_needs_build', return_value=True), \
                mock.patch('subprocess.Popen', side_effect=fake_popen), \
                mock.patch('subprocess.run', side_effect=fake_run), \
                mock.patch('os.path.isfile', return_value=True):
            frontend_proc, backend_proc, frontend_port, backend_port, _url = \
                Web()._launch_web_ui(_make_args())

        # 先构建再起后端
        self.assertEqual(run_cmds, [['/usr/bin/npm', 'run', 'build']])
        self.assertEqual(len(popen_cmds), 1, '生产模式只应起后端进程')
        self.assertIn('uvicorn', popen_cmds[0])
        self.assertNotIn('--reload', popen_cmds[0], '生产模式不应开 --reload')
        # 前端由后端托管：frontend_port == backend_port，且无独立前端进程
        self.assertIsNone(frontend_proc)
        self.assertEqual(frontend_port, backend_port)

    def test_fresh_dist_skips_build(self):
        popen_cmds = []
        run_cmds = []

        def fake_popen(cmd, **kwargs):
            popen_cmds.append(cmd)
            return mock.MagicMock(poll=lambda: None)

        with mock.patch.object(Web, '_frontend_needs_build', return_value=False), \
                mock.patch('subprocess.Popen', side_effect=lambda cmd, **k: popen_cmds.append(cmd) or mock.MagicMock(poll=lambda: None)), \
                mock.patch('subprocess.run', side_effect=lambda cmd, **k: run_cmds.append(cmd) or mock.MagicMock(returncode=0)):
            _frontend_proc, _backend_proc, _fp, _bp, _url = \
                Web()._launch_web_ui(_make_args())

        self.assertEqual(run_cmds, [], 'dist 未过期时不应重新构建')
        self.assertEqual(len(popen_cmds), 1)

    def test_build_failure_raises(self):
        def fake_popen(cmd, **kwargs):
            return mock.MagicMock(poll=lambda: None)

        with mock.patch.object(Web, '_frontend_needs_build', return_value=True), \
                mock.patch('subprocess.Popen', side_effect=fake_popen), \
                mock.patch('subprocess.run', return_value=mock.MagicMock(returncode=1)):
            with self.assertRaises(SystemExit):
                Web()._launch_web_ui(_make_args())


class TestWebDevModeOptIn(_FakeDirs, unittest.TestCase):
    """--dev 才起 Vite dev 服务器，行为与旧版一致。"""

    def test_dev_flag_starts_vite(self):
        popen_cmds = []

        def fake_popen(cmd, **kwargs):
            popen_cmds.append(cmd)
            return mock.MagicMock(poll=lambda: None)

        with mock.patch('subprocess.Popen', side_effect=fake_popen):
            frontend_proc, backend_proc, frontend_port, backend_port, _url = \
                Web()._launch_web_ui(_make_args(dev=True))

        self.assertIsNotNone(frontend_proc, '--dev 应启动独立前端进程')
        vite_cmd = popen_cmds[0] if 'npm' in popen_cmds[0] else popen_cmds[1]
        uvicorn_cmd = popen_cmds[1] if 'npm' in popen_cmds[0] else popen_cmds[0]
        self.assertIn('dev', vite_cmd, '应使用 npm run dev')
        self.assertIn('--reload', uvicorn_cmd, '开发模式后端应开 --reload')
        # 开发模式 frontend_port 独立于 backend_port
        self.assertNotEqual(frontend_port, backend_port)
        self.assertEqual(frontend_port, 5188)
        self.assertEqual(backend_port, 8000)


class TestFrontendNeedsBuild(unittest.TestCase):
    """_frontend_needs_build 的判定逻辑。"""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.frontend = os.path.join(self.tmp, 'frontend')
        os.makedirs(os.path.join(self.frontend, 'dist'))
        self.dist_index = os.path.join(self.frontend, 'dist', 'index.html')
        with open(self.dist_index, 'w') as f:
            f.write('<html></html>')
        # dist/index.html 的 mtime 已是"现在"，后续写入的文件只会更新
        os.utime(self.dist_index)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_dist_no_rebuild(self):
        src = os.path.join(self.frontend, 'src')
        os.makedirs(src)
        older = os.path.join(src, 'App.tsx')
        with open(older, 'w') as f:
            f.write('x')
        old_time = os.path.getmtime(self.dist_index) - 100
        os.utime(older, (old_time, old_time))
        self.assertFalse(Web()._frontend_needs_build(self.frontend))

    def test_missing_dist_needs_build(self):
        os.remove(self.dist_index)
        self.assertTrue(Web()._frontend_needs_build(self.frontend))

    def test_newer_source_needs_build(self):
        src = os.path.join(self.frontend, 'src')
        os.makedirs(src)
        newer = os.path.join(src, 'App.tsx')
        with open(newer, 'w') as f:
            f.write('x')
        self.assertTrue(Web()._frontend_needs_build(self.frontend))

    def test_newer_config_needs_build(self):
        cfg = os.path.join(self.frontend, 'vite.config.ts')
        with open(cfg, 'w') as f:
            f.write('x')
        self.assertTrue(Web()._frontend_needs_build(self.frontend))


class TestWebHelpHasDevFlag(unittest.TestCase):
    def test_web_and_drive_accept_dev_flag(self):
        for cls in (Web,):
            args = cls().parse_args([])
            self.assertFalse(args.dev, '默认不开 dev 模式')
            args = cls().parse_args(['--dev'])
            self.assertTrue(args.dev)


if __name__ == '__main__':
    unittest.main()
