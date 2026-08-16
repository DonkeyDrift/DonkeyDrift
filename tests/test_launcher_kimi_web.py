# -*- coding: utf-8 -*-
"""Launcher「打开 Kimi Code Web」（kimi_web.py，kimi ≥ 0.36 版）与端点的单元测试。

测试覆盖 donkeycar.launcher.kimi_web：
- strip_ansi：CSI/OSC/alternate-screen 等 ANSI 转义序列剥离
- extract_web_url：Session 深链优先、Local/URL/Network 标签次序、
  任意 URL 兜底、尾部句读剥离、无 URL 返回 None
- _is_loopback_host / _lan_url（issue #125）：回环/通配 host 识别、
  URL 改写为局域网 IP（保留端口与 #token=）、远程 host 与无局域网
  IP 时不改写
- _live_instance_url：实例登记目录扫描（心跳新鲜度、pid 存活、探测
  结果三级过滤）与 #token= 入口 URL 组装
- launch_kimi_code_web：存活实例复用（不起子进程）、冷启动拉起
  kimi web --no-open --host（_FakeProc 脚本化管道输出）成功抓 URL 且进程
  保持存活、cwd 透传、cwd 非法直接报错、未安装 kimi、冷启动失败后
  兜底复用、banner 超时杀进程、进程提前退出报错
以及 POST /api/launch/kimi-code-web 端点：路由、参数校验、CORS 头
（DC 从 ESP32 origin 跨域调用依赖它）。不起真实 kimi。
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from donkeycar.launcher import kimi_web
from donkeycar.launcher.kimi_web import (
    extract_web_url,
    launch_kimi_code_web,
    strip_ansi,
)
from donkeycar.launcher import server as launcher_server


# ===========================================================================
# 工具
# ===========================================================================
class _FakeProc:
    """subprocess.Popen 替身：脚本化 stdout（真实管道，reader 线程行为与
    真实进程一致）；hold=True 时保持静默不退出（用于超时路径）。"""

    def __init__(self, payload=b"", exit_code=0, hold=False):
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "r", encoding="utf-8", errors="replace")
        self._w = w
        self.returncode = None
        self.pid = 9876
        self.killed = False

        def _feed():
            try:
                if payload:
                    os.write(w, payload)
                if hold:
                    return  # 管道保持打开、进程"活着"，等 kill
                self._finish(exit_code)
            except OSError:
                pass

        threading.Thread(target=_feed, daemon=True).start()

    def _finish(self, code):
        if self.returncode is not None:
            return
        self.returncode = code
        try:
            os.close(self._w)
        except OSError:
            pass

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self._finish(-9)


def _make_popen(procs):
    """返回 popen_fn：逐个弹出预置的 _FakeProc 并记录调用参数。"""

    def _popen(args, **kwargs):
        proc = procs.pop(0)
        proc.args_seen = args
        proc.kwargs_seen = kwargs
        return proc

    return _popen


# kimi web 0.36 ready banner（token 在 # 片段里）
_WEB_BANNER = (b"\n  Kimi server ready  0.36.0\n\n"
               b"  Local:    http://127.0.0.1:58627/#token=t0k123\n"
               b"  Network:  off  use --host to enable\n")


@pytest.fixture(autouse=True)
def _clean_spawned():
    """每个测试后清掉 _SPAWNED_PROCS，避免跨测试污染。"""
    yield
    kimi_web._SPAWNED_PROCS.clear()


@pytest.fixture(autouse=True)
def _fake_lan_ip(monkeypatch):
    """固定本机局域网 IP，隔离真实网络探测（issue #125 的 URL 改写）。"""
    monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")


# ===========================================================================
# _is_loopback_host / _lan_url（issue #125：URL 必须局域网可达）
# ===========================================================================
class TestLanUrl:
    def test_loopback_hosts_recognized(self):
        for host in ("localhost", "LOCALHOST", "127.0.0.1", "127.1.2.3",
                     "[::1]", "0.0.0.0"):
            assert kimi_web._is_loopback_host(host) is True

    def test_remote_hosts_not_loopback(self):
        for host in ("192.168.3.10", "example.com", "[::ffff:1.2.3.4]",
                     None, ""):
            assert kimi_web._is_loopback_host(host) is False

    def test_rewrites_loopback_host_keeps_port_and_token(self):
        assert kimi_web._lan_url(
            "http://127.0.0.1:58627/#token=t0k123") == \
            "http://192.168.3.10:58627/#token=t0k123"

    def test_rewrites_localhost_without_port(self):
        assert kimi_web._lan_url("http://localhost/x?a=1") == \
            "http://192.168.3.10/x?a=1"

    def test_keeps_lan_host_untouched(self):
        url = "http://192.168.3.41:58627/#token=t0k123"
        assert kimi_web._lan_url(url) == url

    def test_no_lan_ip_returns_unchanged(self, monkeypatch):
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: None)
        url = "http://127.0.0.1:58627/#token=t0k123"
        assert kimi_web._lan_url(url) == url


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
# _live_instance_url（实例复用）
# ===========================================================================
def _write_instance(d, pid, port=58627, heartbeat_age_ms=0, host="127.0.0.1"):
    d.mkdir(parents=True, exist_ok=True)
    (d / "01TEST.json").write_text(json.dumps({
        "server_id": "01TEST",
        "pid": pid,
        "host": host,
        "port": port,
        "started_at": 1,
        "heartbeat_at": int(time.time() * 1000) - heartbeat_age_ms,
        "host_version": "0.36.0",
    }), encoding="utf-8")


class TestLiveInstanceUrl:
    def test_builds_token_url_for_live_instance(self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        token_file = tmp_path / "server.token"
        token_file.write_text("tok-xyz\n", encoding="utf-8")
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        url = kimi_web._live_instance_url(inst_dir, token_file)
        # 登记的 127.0.0.1 实测监听 0.0.0.0（对局域网 IP 探测通过）时，
        # 返回局域网 host 的 URL（issue #125）
        assert url == "http://192.168.3.10:58627/#token=tok-xyz"

    def test_loopback_instance_not_lan_reachable_skipped(
            self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        probes = []
        monkeypatch.setattr(
            kimi_web, "_probe_server",
            lambda host, port, token: probes.append(host) or False)
        assert kimi_web._live_instance_url(
            inst_dir, tmp_path / "tk") is None
        # 回环实例只对局域网 IP 探测（不对 127.0.0.1 白探）
        assert probes == ["192.168.3.10"]

    def test_no_lan_ip_skips_loopback_instance(self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: None)
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        assert kimi_web._live_instance_url(
            inst_dir, tmp_path / "tk") is None

    def test_lan_host_instance_probed_on_registered_host(
            self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid(), host="192.168.3.41")
        token_file = tmp_path / "server.token"
        token_file.write_text("tok-xyz\n", encoding="utf-8")
        probed = []
        monkeypatch.setattr(
            kimi_web, "_probe_server",
            lambda host, port, token: probed.append(host) or True)
        url = kimi_web._live_instance_url(inst_dir, token_file)
        assert url == "http://192.168.3.41:58627/#token=tok-xyz"
        assert probed == ["192.168.3.41"]

    def test_skips_dead_pid(self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        # 找一个确定不存在的 pid
        dead_pid = 2 ** 22
        while os.path.exists(f"/proc/{dead_pid}"):
            dead_pid += 1
        _write_instance(inst_dir, pid=dead_pid)
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        assert kimi_web._live_instance_url(inst_dir, tmp_path / "tk") is None

    def test_skips_stale_heartbeat(self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid(),
                        heartbeat_age_ms=int(
                            (kimi_web.INSTANCE_HEARTBEAT_MAX_AGE_S + 60) * 1000))
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        assert kimi_web._live_instance_url(inst_dir, tmp_path / "tk") is None

    def test_skips_failed_probe(self, tmp_path, monkeypatch):
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: False)
        assert kimi_web._live_instance_url(inst_dir, tmp_path / "tk") is None

    def test_empty_registry_returns_none(self, tmp_path):
        assert kimi_web._live_instance_url(
            tmp_path / "no-such-dir", tmp_path / "tk") is None


# ===========================================================================
# launch_kimi_code_web
# ===========================================================================
class TestLaunchKimiCodeWeb:
    def test_reuses_live_instance_without_spawning(self):
        spawned = []
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0,
            live_url_fn=lambda: "http://127.0.0.1:58627/#token=t0k",
            popen_fn=_make_popen(spawned))
        assert result == {"status": "ok",
                          "url": "http://192.168.3.10:58627/#token=t0k"}
        assert spawned == []  # 复用路径不起子进程

    def test_spawn_success_captures_url_and_keeps_proc(self):
        proc = _FakeProc(payload=_WEB_BANNER, hold=True)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=10.0,
            live_url_fn=lambda: None,
            resolve_binary_fn=lambda: "/home/u/.kimi-code/bin/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        # banner 里的 127.0.0.1 被改写为局域网 IP（issue #125）
        assert result["url"] == "http://192.168.3.10:58627/#token=t0k123"
        # 成功时子进程保持存活（杀它即关 web 服务），句柄被模块留住
        assert proc.killed is False
        assert proc in kimi_web._SPAWNED_PROCS
        # 启动命令是官方子命令，绑 0.0.0.0 供局域网访问，且不开浏览器
        assert proc.args_seen[-3:] == ["web", "--no-open", "--host"]

    def test_spawn_passes_cwd_through(self, tmp_path):
        proc = _FakeProc(payload=_WEB_BANNER, hold=True)
        result = launch_kimi_code_web(
            cwd=str(tmp_path), timeout_s=10.0,
            live_url_fn=lambda: None,
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert proc.kwargs_seen["cwd"] == str(tmp_path)

    def test_invalid_cwd_errors_without_spawning(self):
        spawned = []
        result = launch_kimi_code_web(
            cwd="/nonexistent/definitely-not-a-dir", timeout_s=1.0,
            live_url_fn=lambda: None,
            popen_fn=_make_popen(spawned))
        assert result["status"] == "error"
        assert "不存在" in result["error"]
        assert spawned == []

    def test_kimi_binary_missing(self):
        result = launch_kimi_code_web(
            cwd=None, timeout_s=1.0,
            live_url_fn=lambda: None,
            resolve_binary_fn=lambda: None)
        assert result["status"] == "error"
        assert "未找到 kimi" in result["error"]

    def test_spawn_failure_falls_back_to_reuse(self):
        # 冷启动失败（进程秒退），第二次复用扫到存活实例（端口占用来源）
        proc = _FakeProc(payload=b"Failed to start server: EADDRINUSE\r\n",
                         exit_code=1)
        live_calls = iter([None, "http://127.0.0.1:58627/#token=t0k"])
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0,
            live_url_fn=lambda: next(live_calls),
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert result["url"] == "http://192.168.3.10:58627/#token=t0k"
        assert proc.killed is True  # 失败的子进程被杀净

    def test_spawn_banner_timeout_kills_proc(self):
        proc = _FakeProc(hold=True)  # 一直不出 URL 也不退出
        result = launch_kimi_code_web(
            cwd=None, timeout_s=1.5,
            live_url_fn=lambda: None,
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "error"
        assert "超时" in result["error"]
        assert proc.killed is True

    def test_spawn_exit_without_url_reports_tail(self):
        proc = _FakeProc(payload=b"boom: something broke\r\n", exit_code=2)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0,
            live_url_fn=lambda: None,
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "error"
        assert "提前退出" in result["error"]
        assert "something broke" in result["error"]
        assert proc.killed is True


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
