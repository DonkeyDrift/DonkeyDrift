# -*- coding: utf-8 -*-
"""Launcher「打开 Kimi Code Web」自动化（kimi_web.py）与端点的单元测试。

测试覆盖 donkeycar.launcher.kimi_web：
- strip_ansi：CSI/OSC/alternate-screen 等 ANSI 转义序列剥离
- extract_web_url：Session 深链优先、Local/URL/Network 标签次序、
  任意 URL 兜底、尾部句读剥离、无 URL 返回 None
- launch_kimi_code_web：用 _FakeSession 脚本化喂 PTY 输出，覆盖成功
  （TUI 就绪→注入 /web→捕获 URL，会话保持存活）、command not found、
  Trust this folder 拦截、No active session、URL 等待超时、cwd 非法
  直接报错且不创建会话
以及 POST /api/launch/kimi-code-web 端点：路由、参数校验、CORS 头
（DC 从 ESP32 origin 跨域调用依赖它）。不起真实 kimi。
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from donkeycar.launcher import kimi_web
from donkeycar.launcher.kimi_web import (
    TerminalSession,
    extract_web_url,
    launch_kimi_code_web,
    strip_ansi,
)
from donkeycar.launcher import server as launcher_server


# ===========================================================================
# 工具
# ===========================================================================
class _FakeSession:
    """TerminalSession 替身：on_input 按脚本异步向 writer 喂 PTY 输出。

    script 形如 {b"kimi\\r": [(延迟秒, 输出字节), ...]}；未匹配的输入忽略。
    接口对齐 TerminalSession（on_input/on_resize/close/pid）。
    """

    def __init__(self, writer, cwd=None, script=None):
        self._writer = writer
        self.cwd = cwd
        self._script = script or {}
        self.closed = False
        self.resized_to = None
        self.inputs = []

    @property
    def pid(self):
        return 4321

    def on_resize(self, cols, rows):
        self.resized_to = (cols, rows)

    def on_input(self, data: bytes):
        self.inputs.append(data)
        steps = self._script.get(data)
        if not steps:
            return

        def _feed():
            for delay, payload in steps:
                time.sleep(delay)
                if self.closed:
                    return
                self._writer.send(payload)

        threading.Thread(target=_feed, daemon=True).start()

    def close(self):
        self.closed = True


def _make_factory(script, sessions):
    """返回 session_factory：记录每次创建的 _FakeSession 供断言。"""

    def _factory(writer, cwd=None):
        session = _FakeSession(writer, cwd=cwd, script=script)
        sessions.append(session)
        return session

    return _factory


# TUI 就绪信号：alternate-screen 进入序列 + 首屏文本，之后保持静默
_TUI_READY = [(0.0, b"\x1b[?1049h\x1b[2J Kimi Code TUI ready\r\n")]
# /web 就绪 banner：Local 裸入口 + Session 深链（token 在 # 片段里）
_WEB_BANNER = [(0.0, b"  Local:   http://127.0.0.1:5123/\r\n"
                     b"  Network: http://192.168.3.41:5123/\r\n"
                     b"  Session: http://127.0.0.1:5123/#token=abc123\r\n")]


# ===========================================================================
# strip_ansi / extract_web_url
# ===========================================================================
class TestStripAnsi:
    def test_strips_csi_osc_and_alt_screen(self):
        raw = ("\x1b[?1049h\x1b[1;31m红色\x1b[0m"
               "\x1b]0;窗口标题\x07纯文本\x1b(B")
        assert strip_ansi(raw) == "红色纯文本"

    def test_keeps_visible_text_and_newlines(self):
        assert strip_ansi("a\r\nb\x1b[2Jc") == "a\r\nbc"


class TestExtractWebUrl:
    def test_prefers_session_deep_link(self):
        text = ("Local:   http://127.0.0.1:5123/\r\n"
                "Session: http://127.0.0.1:5123/#token=abc123\r\n")
        assert extract_web_url(text) == "http://127.0.0.1:5123/#token=abc123"

    def test_falls_back_to_labeled_lines_in_order(self):
        assert extract_web_url("Local: http://127.0.0.1:5123/\n") == \
            "http://127.0.0.1:5123/"
        text = "Network: http://192.168.3.41:5123/\nLocal: http://a/\n"
        # Local 优先级高于 Network（_LABELED_URL_RES 顺序）
        assert extract_web_url(text) == "http://a/"

    def test_falls_back_to_any_url_and_strips_trailing_punct(self):
        assert extract_web_url("打开 http://example.com/x?a=1. 即可") == \
            "http://example.com/x?a=1"

    def test_returns_none_without_url(self):
        assert extract_web_url("没有任何链接") is None

    def test_extracts_from_ansi_laden_banner(self):
        raw = ("\x1b[2K\r\x1b[38;5;111mSession:\x1b[0m "
               "\x1b[4mhttps://kimi.example/web#token=t0k\x1b[24m\r\n")
        assert extract_web_url(strip_ansi(raw)) == \
            "https://kimi.example/web#token=t0k"


# ===========================================================================
# launch_kimi_code_web
# ===========================================================================
class TestLaunchKimiCodeWeb:
    def test_success_captures_session_url_and_keeps_session(self):
        sessions = []
        factory = _make_factory(
            {b"kimi\r": _TUI_READY, b"/web\r": _WEB_BANNER}, sessions)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=10.0, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "ok"
        assert result["url"] == "http://127.0.0.1:5123/#token=abc123"
        # 成功时会话保持存活（kimi web server 挂在这个 PTY 上）
        assert sessions[0].closed is False
        # PTY 加宽（防 URL 折行）+ 两次注入顺序正确
        assert sessions[0].resized_to == (500, 24)
        assert sessions[0].inputs == [b"kimi\r", b"/web\r"]

    def test_passes_cwd_through_to_session(self, tmp_path):
        sessions = []
        factory = _make_factory(
            {b"kimi\r": _TUI_READY, b"/web\r": _WEB_BANNER}, sessions)
        result = launch_kimi_code_web(
            cwd=str(tmp_path), timeout_s=10.0, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "ok"
        assert sessions[0].cwd == str(tmp_path)

    def test_invalid_cwd_errors_without_creating_session(self):
        sessions = []
        factory = _make_factory({}, sessions)
        result = launch_kimi_code_web(
            cwd="/nonexistent/definitely-not-a-dir", timeout_s=1.0,
            session_factory=factory)
        assert result["status"] == "error"
        assert "不存在" in result["error"]
        assert sessions == []

    def test_kimi_command_not_found(self):
        sessions = []
        script = {b"kimi\r": [(0.0, b"bash: kimi: command not found\r\n")]}
        factory = _make_factory(script, sessions)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "error"
        assert "command not found" in result["error"]
        assert sessions[0].closed is True

    def test_trust_folder_prompt_blocks(self):
        sessions = []
        script = {b"kimi\r": [(0.0, b"Trust this folder? (y/N)\r\n")]}
        factory = _make_factory(script, sessions)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "error"
        assert "Trust this folder" in result["error"]
        assert sessions[0].closed is True

    def test_no_active_session_after_web(self):
        sessions = []
        script = {b"kimi\r": _TUI_READY,
                  b"/web\r": [(0.0, b"No active session\r\n")]}
        factory = _make_factory(script, sessions)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "error"
        assert "No active session" in result["error"]
        assert sessions[0].closed is True

    def test_url_wait_timeout_closes_session(self):
        sessions = []
        # TUI 就绪但 /web 之后始终不出 URL
        factory = _make_factory({b"kimi\r": _TUI_READY}, sessions)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=1.5, ready_silence_s=0.05,
            session_factory=factory)
        assert result["status"] == "error"
        assert "超时" in result["error"]
        assert sessions[0].closed is True

    def test_default_session_factory_is_terminal_session(self):
        import inspect
        sig = inspect.signature(launch_kimi_code_web)
        assert sig.parameters["session_factory"].default is TerminalSession


# ===========================================================================
# POST /api/launch/kimi-code-web 端点（内存 HTTP 服务器）
# ===========================================================================
@pytest.fixture()
def http_server(monkeypatch):
    fake = lambda cwd=None: {"status": "ok", "url": "https://kimi.example/w"}
    monkeypatch.setattr(launcher_server, "launch_kimi_code_web", fake)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), launcher_server.LauncherHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    thread.join(timeout=2)


def _post(url, body: bytes):
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_endpoint_ok_with_cors_header(http_server):
    code, headers, payload = _post(
        http_server + "/api/launch/kimi-code-web", b"{}")
    assert code == 200
    assert json.loads(payload) == {"status": "ok",
                                   "url": "https://kimi.example/w"}
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_json_with_cors(http_server):
    code, headers, payload = _post(
        http_server + "/api/launch/kimi-code-web", b"not-json")
    assert code == 400
    assert json.loads(payload)["status"] == "error"
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_string_cwd(http_server):
    code, _headers, payload = _post(
        http_server + "/api/launch/kimi-code-web",
        json.dumps({"cwd": 123}).encode())
    assert code == 400
    assert "cwd" in json.loads(payload)["error"]


def test_endpoint_error_from_automation_is_500(http_server, monkeypatch):
    monkeypatch.setattr(
        launcher_server, "launch_kimi_code_web",
        lambda cwd=None: {"status": "error", "error": "boom"})
    code, headers, payload = _post(
        http_server + "/api/launch/kimi-code-web", b"{}")
    assert code == 500
    assert json.loads(payload)["error"] == "boom"
    assert headers.get("Access-Control-Allow-Origin") == "*"
