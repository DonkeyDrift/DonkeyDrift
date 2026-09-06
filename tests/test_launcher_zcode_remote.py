# -*- coding: utf-8 -*-
"""Launcher「ZCode 远程控制唤醒」端点（POST /api/launch/zcode-remote）的单元测试。

端点职责：DC/DD 的「ZCode」按钮点击时调用，确保 Z Code 桌面端进程在线
（远控链接只有桌面端 Web 远控会话在线才有效，否则 z.ai 页面显示
"手机连接已失效"；桌面端 App 启动时会恢复上次开启的远控会话）。
覆盖：已在运行直接 ok 不重复拉起、未运行则 Popen 拉起（detached）、
二进制不存在 400、拉起 OSError 500；路径动态推导不硬编码本机路径。
"""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from donkeycar.launcher import server as launcher_server


@pytest.fixture()
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), launcher_server.LauncherHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    thread.join(timeout=2)


def _post(url, body: bytes = b""):
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_already_running_skips_launch(http_server, monkeypatch):
    monkeypatch.setattr(launcher_server, "_zcode_desktop_running", lambda: True)
    called = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: called.append((a, k)) or None)
    code, headers, payload = _post(http_server + "/api/launch/zcode-remote")
    assert code == 200
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"
    body = json.loads(payload)
    assert body == {"status": "ok", "running": True, "started": False}
    assert called == []  # 已在运行：不重复拉起


def test_not_running_launches_detached(http_server, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_server, "_zcode_desktop_running", lambda: False)
    fake_bin = tmp_path / "zcode"
    fake_bin.touch()
    monkeypatch.setattr(launcher_server, "_ZCODE_DESKTOP_BIN", fake_bin)
    calls = []

    class _FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    code, headers, payload = _post(http_server + "/api/launch/zcode-remote", b"{}")
    assert code == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    body = json.loads(payload)
    assert body == {"status": "ok", "running": False, "started": True}
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == [str(fake_bin)]
    assert kwargs["start_new_session"] is True  # detached，不随 launcher 退出
    assert kwargs["env"]["DISPLAY"]  # 图形会话 DISPLAY 已兜底


def test_missing_binary_returns_400(http_server, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_server, "_zcode_desktop_running", lambda: False)
    monkeypatch.setattr(
        launcher_server, "_ZCODE_DESKTOP_BIN", tmp_path / "no-such-zcode")
    code, _headers, payload = _post(http_server + "/api/launch/zcode-remote")
    assert code == 400
    assert "不存在" in json.loads(payload)["error"]


def test_launch_oserror_returns_500(http_server, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_server, "_zcode_desktop_running", lambda: False)
    fake_bin = tmp_path / "zcode"
    fake_bin.touch()
    monkeypatch.setattr(launcher_server, "_ZCODE_DESKTOP_BIN", fake_bin)

    def _boom(*a, **k):
        raise OSError("exec format error")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    code, _headers, payload = _post(http_server + "/api/launch/zcode-remote")
    assert code == 500
    assert "拉起 Z Code 桌面端失败" in json.loads(payload)["error"]


def test_desktop_bin_path_is_dynamic_home():
    # 缺省路径动态取 Path.home()（防硬编码本机路径入库泄露的回归栅栏）
    assert launcher_server._ZCODE_DESKTOP_BIN == (
        Path.home() / ".zcode-app" / "zcode")
