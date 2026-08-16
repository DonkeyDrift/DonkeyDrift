# -*- coding: utf-8 -*-
"""launcher `_launch_web`（D 页菜单 7 号 Web）行为测试。

D 页菜单 7 号 "Web"（启动 Web UI）此前在前端是 notImplemented、后端
也没有对应端点。本功能打通它：POST /api/launch/web，与 6 号 Drive 同
模式——复用存活实例（不互杀、不端口漂移），冷启动时等就绪（issue
#134 的 _wait_for_web_ready）才返回；区别是不起车进程、跳转 DD 主页。

覆盖：
- _launch_web：冷启动起 donkey web → 等就绪 → 回读实际端口、url 指向
  /#/；复用存活实例时不起进程、status=already_running；Popen 失败
  报 error；车进程跟踪字段不被覆盖
- MENU_HTML：7 号按键分发到 launchWeb，前端请求 /api/launch/web
"""

import time
from unittest import mock

import pytest

from donkeycar.launcher import server as launcher_server


class _FakeProc:
    """最小 Popen 替身：poll 恒 None（存活）。"""

    def __init__(self, returncode=None):
        self.pid = 4242
        self._returncode = returncode

    def poll(self):
        return self._returncode


@pytest.fixture(autouse=True)
def _reset_processes():
    """每个测试后还原模块级进程跟踪表。"""
    yield
    launcher_server._processes.update({
        "web": None, "car": None, "backend_port": None,
        "frontend_port": None, "project": None,
    })


def _patches(inst=None, ready=(5189, 8001, None)):
    """公共桩：实例探测/端口预选/就绪等待/项目路径。"""
    return {
        "find": mock.patch.object(launcher_server, "find_live_instance",
                                  return_value=inst),
        "backend_port": mock.patch.object(
            launcher_server, "_choose_available_backend_port",
            side_effect=lambda p: p,
        ),
        "web_ui_path": mock.patch.object(
            launcher_server, "_get_bundled_web_ui_path", return_value=None,
        ),
        "wait": mock.patch.object(launcher_server, "_wait_for_web_ready",
                                  return_value=ready),
        "project": mock.patch.object(
            launcher_server, "_find_mycar_project",
            return_value="/fake/mycar",
        ),
    }


# ===========================================================================
# _launch_web
# ===========================================================================
class TestLaunchWeb:
    def test_cold_start_popen_web_waits_ready(self):
        """冷启动：起 donkey web → 等就绪回读实际端口 → url 指向 /#/，
        不起任何车进程。"""
        p = _patches(inst=None, ready=(5189, 8001, None))
        with mock.patch.object(
            launcher_server.subprocess, "Popen", return_value=_FakeProc(),
        ) as popen:
            with p["find"], p["backend_port"], p["web_ui_path"], \
                 p["wait"] as wait, p["project"]:
                result = launcher_server._launch_web()

        assert result["status"] == "launched"
        assert result["frontend_port"] == 5189
        assert result["backend_port"] == 8001
        assert result["url"] == "http://localhost:5189/#/"
        assert result["warning"] is None
        # 只起了 web（donkey ... web），没有 manage.py drive
        assert popen.call_count == 1
        web_cmd = popen.call_args_list[0].args[0]
        assert web_cmd[0] == "donkey" and web_cmd[1] == "web"
        assert "--backend-port" in web_cmd and "--frontend-port" in web_cmd
        wait.assert_called_once()
        assert launcher_server._processes["car"] is None

    def test_ready_timeout_still_returns_with_warning(self):
        """就绪等待超时：不报 error，照常返回并透出 warning。"""
        p = _patches(inst=None, ready=(5188, 8000, "Web UI 在 90s 内未就绪"))
        with mock.patch.object(
            launcher_server.subprocess, "Popen", return_value=_FakeProc(),
        ):
            with p["find"], p["backend_port"], p["web_ui_path"], \
                 p["wait"], p["project"]:
                result = launcher_server._launch_web()
        assert result["status"] == "launched"
        assert "未就绪" in result["warning"]

    def test_reuse_instance_skips_popen_and_wait(self):
        """复用存活实例：不起进程、不等就绪，status=already_running，
        url 用登记端口。"""
        inst = {"pid": 999, "backend_port": 8000, "frontend_port": 5188,
                "started_at": time.time()}
        p = _patches(inst=inst)
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
        ) as popen:
            with p["find"], p["backend_port"], p["web_ui_path"], \
                 p["wait"] as wait, p["project"]:
                result = launcher_server._launch_web()
        assert result["status"] == "already_running"
        assert result["url"] == "http://localhost:5188/#/"
        assert result["backend_port"] == 8000
        assert result["warning"] is None
        popen.assert_not_called()
        wait.assert_not_called()

    def test_reuse_keeps_tracked_car_process(self):
        """复用实例不覆盖车进程跟踪：launcher 之前跟踪的车进程保留。"""
        inst = {"pid": 999, "backend_port": 8000, "frontend_port": 5188,
                "started_at": time.time()}
        car_proc = _FakeProc()
        launcher_server._processes["car"] = car_proc
        p = _patches(inst=inst)
        with mock.patch.object(launcher_server.subprocess, "Popen"):
            with p["find"], p["backend_port"], p["web_ui_path"], \
                 p["wait"], p["project"]:
                launcher_server._launch_web()
        assert launcher_server._processes["car"] is car_proc

    def test_popen_failure_returns_error(self):
        """donkey 命令缺失：直接报 error。"""
        p = _patches(inst=None)
        with mock.patch.object(
            launcher_server.subprocess, "Popen",
            side_effect=FileNotFoundError("donkey"),
        ) as popen:
            with p["find"], p["backend_port"], p["web_ui_path"], \
                 p["wait"] as wait, p["project"]:
                result = launcher_server._launch_web()
        assert result["status"] == "error"
        assert "donkey" in result["error"]
        popen.assert_called_once()
        wait.assert_not_called()


# ===========================================================================
# MENU_HTML / HTTP 端点接线
# ===========================================================================
class TestMenuHtmlWiring:
    def test_menu_item_7_dispatches_launch_web(self):
        """7 号按键分发到 launchWeb()，不再落入 notImplemented。"""
        source = launcher_server.MENU_HTML
        assert "no === 7" in source
        # no===7 分支调用 launchWeb（而非仅存在同名函数）
        dispatch = source[source.index("function selectItem"):]
        dispatch = dispatch[:dispatch.index("}", dispatch.index("notImplemented"))]
        assert "no === 7" in dispatch and "launchWeb()" in dispatch
        assert "async function launchWeb" in source
        assert "'/api/launch/web'" in source

    def test_post_endpoint_wired(self):
        """do_POST 注册了 /api/launch/web 并调用 _launch_web。"""
        source = open(launcher_server.__file__, encoding="utf-8").read()
        assert 'path == "/api/launch/web"' in source
        assert "_launch_web()" in source
