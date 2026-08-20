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
  结果三级过滤）与 #token= 入口 URL 组装；cwd 给定时按
  /proc/<pid>/cwd 校验实例运行目录（issue #168：匹配复用、不匹配跳过、
  读不到视为不匹配）
- launch_kimi_code_web：存活实例复用（不起子进程、复用探测带 cwd）、
  冷启动拉起 kimi web --no-open --host --port <固定端口>（_FakeProc
  脚本化管道输出）成功抓 URL 且进程保持存活、cwd 透传、cwd 非法直接
  报错、未安装 kimi、冷启动失败后兜底复用、banner 超时杀进程、进程
  提前退出报错
以及 POST /api/launch/kimi-code-web 端点：路由、参数校验、缺省 cwd
  为 Projects 工作区（issue #168）、CORS 头（DC 从 ESP32 origin 跨域
  调用依赖它）。不起真实 kimi。
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


# 原始 _mdns_hostname 函数引用：autouse fixture（_fake_lan_ip）会把它
# monkeypatch 成 None；需要直接验证其真实逻辑（主机名小写化）时用它调用，
# 绕开 autouse 的覆盖（只 patch socket 与 _lan_ip，函数体内其余逻辑仍真实执行）。
_ORIGINAL_MDNS_HOSTNAME = kimi_web._mdns_hostname


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
    """固定本机局域网 IP，隔离真实网络探测（issue #125 的 URL 改写）。

    同时把 mDNS 主机名探测钉为 None——默认走 IP 入口路径，保持既有断言
    稳定；mDNS 兜底路径由专门测试用 monkeypatch 覆盖验证。
    """
    monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")
    monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: None)


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

    def test_lan_ip_preferred_over_mdns_for_loopback(self, monkeypatch):
        # issue #168 后续：入口 host 回退为局域网 IP 优先，老 origin 偏好恢复
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "TONY007.local")
        assert kimi_web._lan_url(
            "http://127.0.0.1:58627/#token=t0k123") == \
            "http://192.168.3.10:58627/#token=t0k123"

    def test_lan_ip_preferred_over_mdns_for_lan_host(self, monkeypatch):
        # banner 的 Network 行给的是本机局域网 IP，入口 host 仍用 IP（不换 mDNS）
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "TONY007.local")
        assert kimi_web._lan_url(
            "http://192.168.3.10:58627/#token=t0k123") == \
            "http://192.168.3.10:58627/#token=t0k123"

    def test_mdns_fallback_when_no_lan_ip(self, monkeypatch):
        # IP 探测不到时兜底 mDNS 主机名，入口仍可达
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: None)
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "tony007.local")
        assert kimi_web._lan_url(
            "http://127.0.0.1:58627/#token=t0k123") == \
            "http://tony007.local:58627/#token=t0k123"

    def test_mdns_hostname_keeps_foreign_host(self, monkeypatch):
        # 其它远程 host（非本机 IP）不受 mDNS 改写影响
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "TONY007.local")
        url = "http://192.168.3.41:58627/#token=t0k123"
        assert kimi_web._lan_url(url) == url


# ===========================================================================
# _mdns_hostname / _allowed_host_values（issue #168 后续：DNS-rebinding 栅栏）
# ===========================================================================
class TestMdnsHostnameAndAllowedHosts:
    def test_mdns_hostname_lowercases(self, monkeypatch):
        # 浏览器把 URL host 小写化后放进 Host 头；mDNS 名小写化后 URL、
        # Host 头与 --allowed-host 三者一致，避免大小写不一致被 40301 拦下
        monkeypatch.setattr(kimi_web.socket, "gethostname", lambda: "TONY007")
        monkeypatch.setattr(
            kimi_web.socket, "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("192.168.3.10", 0))])
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")
        assert _ORIGINAL_MDNS_HOSTNAME() == "tony007.local"

    def test_allowed_host_values_mdns_plus_lan(self, monkeypatch):
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "tony007.local")
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")
        assert kimi_web._allowed_host_values() == [
            "tony007.local", "192.168.3.10"]

    def test_allowed_host_values_lan_only_when_no_mdns(self, monkeypatch):
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: None)
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")
        assert kimi_web._allowed_host_values() == ["192.168.3.10"]

    def test_allowed_host_values_empty(self, monkeypatch):
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: None)
        monkeypatch.setattr(kimi_web, "_lan_ip", lambda: None)
        assert kimi_web._allowed_host_values() == []


# ===========================================================================
# _mark_onboarded（issue #168 后续：跳过首次语言/主题欢迎页）
# ===========================================================================
class TestMarkOnboarded:
    def test_adds_param_keeps_token_fragment(self):
        url = "http://192.168.3.10:58627/#token=t0k123"
        assert kimi_web._mark_onboarded(url) == \
            "http://192.168.3.10:58627/?kimi_onboarded=1#token=t0k123"

    def test_preserves_existing_query(self):
        url = "http://tony007.local:58640/session/abc?foo=bar#token=t0k"
        assert kimi_web._mark_onboarded(url) == \
            "http://tony007.local:58640/session/abc?foo=bar&kimi_onboarded=1#token=t0k"

    def test_does_not_duplicate_existing_param(self):
        url = "http://tony007.local:58640/?kimi_onboarded=1#token=t0k"
        assert kimi_web._mark_onboarded(url) == url


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

    def test_cwd_matching_instance_reused(self, tmp_path, monkeypatch):
        # issue #168：cwd 给定时只复用运行目录一致的实例
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        token_file = tmp_path / "server.token"
        token_file.write_text("tok-xyz\n", encoding="utf-8")
        monkeypatch.setattr(kimi_web, "_proc_cwd", lambda pid: "/home/dkc/projects")
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        url = kimi_web._live_instance_url(inst_dir, token_file,
                                          cwd="/home/dkc/projects")
        assert url == "http://192.168.3.10:58627/#token=tok-xyz"

    def test_lan_ip_preferred_for_local_instance(self, tmp_path, monkeypatch):
        # issue #168 后续：本机实例（登记 0.0.0.0/回环）复用后入口 host 用
        # 局域网 IP（老 origin），置顶/模式偏好直接恢复
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        token_file = tmp_path / "server.token"
        token_file.write_text("tok-xyz\n", encoding="utf-8")
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "TONY007.local")
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        url = kimi_web._live_instance_url(inst_dir, token_file)
        assert url == "http://192.168.3.10:58627/#token=tok-xyz"

    def test_cwd_mismatching_instance_skipped(self, tmp_path, monkeypatch):
        # 实例跑在别的目录（如 mycar 里的 TUI 内嵌 server）时不复用，
        # 由调用方在目标目录另起（issue #168）
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        monkeypatch.setattr(kimi_web, "_proc_cwd", lambda pid: "/home/dkc/projects/mycar")
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        assert kimi_web._live_instance_url(
            inst_dir, tmp_path / "tk", cwd="/home/dkc/projects") is None

    def test_cwd_proc_gone_treated_as_mismatch(self, tmp_path, monkeypatch):
        # /proc 读不到（进程刚消失/无权限）时按不匹配处理，不误复用
        inst_dir = tmp_path / "instances"
        _write_instance(inst_dir, pid=os.getpid())
        monkeypatch.setattr(kimi_web, "_proc_cwd", lambda pid: None)
        monkeypatch.setattr(kimi_web, "_probe_server", lambda *a, **k: True)
        assert kimi_web._live_instance_url(
            inst_dir, tmp_path / "tk", cwd="/home/dkc/projects") is None

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
        seen = {}

        def _live(**kw):
            # 只收关键字参数：live_url_fn 若按位置传参会 TypeError，
            # 防止 cwd 被误绑到 _live_instance_url 的 instances_dir 上
            seen.update(kw)
            return "http://127.0.0.1:58627/#token=t0k"

        result = launch_kimi_code_web(
            cwd="/home/dkc/projects", timeout_s=5.0,
            live_url_fn=_live,
            popen_fn=_make_popen(spawned))
        assert result == {"status": "ok",
                          "url": "http://192.168.3.10:58627/?kimi_onboarded=1#token=t0k"}
        assert spawned == []  # 复用路径不起子进程
        # 复用探测带上了请求的 cwd（issue #168）
        assert seen["cwd"] == "/home/dkc/projects"

    def test_spawn_success_captures_url_and_keeps_proc(self):
        proc = _FakeProc(payload=_WEB_BANNER, hold=True)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=10.0,
            live_url_fn=lambda cwd=None: None,
            resolve_binary_fn=lambda: "/home/u/.kimi-code/bin/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        # banner 里的 127.0.0.1 被改写为局域网 IP（issue #125）
        assert result["url"] == "http://192.168.3.10:58627/?kimi_onboarded=1#token=t0k123"
        # 成功时子进程保持存活（杀它即关 web 服务），句柄被模块留住
        assert proc.killed is False
        assert proc in kimi_web._SPAWNED_PROCS
        # 启动命令是官方子命令，绑 0.0.0.0 供局域网访问，不开浏览器，
        # 且绑固定专属端口（origin 稳定，issue #168）；并带 --allowed-host
        # 放行局域网 IP（autouse 把 mDNS 钉为 None，回退 IP）
        args = proc.args_seen
        assert args[:2] == ["/home/u/.kimi-code/bin/kimi", "web"]
        assert "--no-open" in args and "--host" in args
        assert args[args.index("--port") + 1] == str(kimi_web.KIMI_WEB_PORT)
        assert "--allowed-host" in args
        assert args[args.index("--allowed-host") + 1] == "192.168.3.10"

    def test_spawn_passes_mdns_and_lan_allowed_hosts(self, monkeypatch):
        # issue #168 后续：mDNS 可用时，--allowed-host 同时放行 mDNS 主机名
        # 与局域网 IP（后者是 mDNS 解析不到时 URL 的回退入口）
        monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: "tony007.local")
        proc = _FakeProc(payload=_WEB_BANNER, hold=True)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=10.0,
            live_url_fn=lambda cwd=None: None,
            resolve_binary_fn=lambda: "/home/u/.kimi-code/bin/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        args = proc.args_seen
        assert args[args.index("--allowed-host") + 1] == "tony007.local"
        assert "192.168.3.10" in args

    def test_spawn_passes_cwd_through(self, tmp_path):
        proc = _FakeProc(payload=_WEB_BANNER, hold=True)
        result = launch_kimi_code_web(
            cwd=str(tmp_path), timeout_s=10.0,
            live_url_fn=lambda cwd=None: None,
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert proc.kwargs_seen["cwd"] == str(tmp_path)

    def test_invalid_cwd_errors_without_spawning(self):
        spawned = []
        result = launch_kimi_code_web(
            cwd="/nonexistent/definitely-not-a-dir", timeout_s=1.0,
            live_url_fn=lambda cwd=None: None,
            popen_fn=_make_popen(spawned))
        assert result["status"] == "error"
        assert "不存在" in result["error"]
        assert spawned == []

    def test_kimi_binary_missing(self):
        result = launch_kimi_code_web(
            cwd=None, timeout_s=1.0,
            live_url_fn=lambda cwd=None: None,
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
            live_url_fn=lambda cwd=None: next(live_calls),
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert result["url"] == "http://192.168.3.10:58627/?kimi_onboarded=1#token=t0k"
        assert proc.killed is True  # 失败的子进程被杀净

    def test_spawn_banner_timeout_kills_proc(self):
        proc = _FakeProc(hold=True)  # 一直不出 URL 也不退出
        result = launch_kimi_code_web(
            cwd=None, timeout_s=1.5,
            live_url_fn=lambda cwd=None: None,
            resolve_binary_fn=lambda: "/x/kimi",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "error"
        assert "超时" in result["error"]
        assert proc.killed is True

    def test_spawn_exit_without_url_reports_tail(self):
        proc = _FakeProc(payload=b"boom: something broke\r\n", exit_code=2)
        result = launch_kimi_code_web(
            cwd=None, timeout_s=5.0,
            live_url_fn=lambda cwd=None: None,
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
    state = {"cwd": "unset"}

    def fake(cwd=None):
        state["cwd"] = cwd
        return {"status": "ok", "url": "https://kimi.example/w"}

    monkeypatch.setattr(launcher_server, "launch_kimi_code_web", fake)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), launcher_server.LauncherHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", state
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
    base, state = http_server
    code, headers, payload = _post(
        base + "/api/launch/kimi-code-web", b"{}")
    assert code == 200
    assert json.loads(payload) == {"status": "ok",
                                   "url": "https://kimi.example/w"}
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"
    # 缺省 cwd 是 Projects 工作区，不再落用户主目录（issue #168）
    assert state["cwd"] == "/home/dkc/projects"


def test_endpoint_explicit_cwd_wins(http_server):
    base, state = http_server
    code, _headers, _payload = _post(
        base + "/api/launch/kimi-code-web",
        json.dumps({"cwd": "/tmp"}).encode())
    assert code == 200
    assert state["cwd"] == "/tmp"


def test_endpoint_empty_body_uses_projects_default(http_server):
    base, state = http_server
    code, _headers, _payload = _post(
        base + "/api/launch/kimi-code-web", b"")
    # DC 按钮的空体 POST（Content-Length=0）也落到 Projects（issue #168）
    assert code == 200
    assert state["cwd"] == "/home/dkc/projects"


def test_endpoint_rejects_non_json_with_cors(http_server):
    base, _state = http_server
    code, headers, payload = _post(
        base + "/api/launch/kimi-code-web", b"not-json")
    assert code == 400
    assert json.loads(payload)["status"] == "error"
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_string_cwd(http_server):
    base, _state = http_server
    code, _headers, payload = _post(
        base + "/api/launch/kimi-code-web",
        json.dumps({"cwd": 123}).encode())
    assert code == 400
    assert "cwd" in json.loads(payload)["error"]


def test_endpoint_error_from_automation_is_500(http_server, monkeypatch):
    base, _state = http_server
    monkeypatch.setattr(
        launcher_server, "launch_kimi_code_web",
        lambda cwd=None: {"status": "error", "error": "boom"})
    code, headers, payload = _post(
        base + "/api/launch/kimi-code-web", b"{}")
    assert code == 500
    assert json.loads(payload)["error"] == "boom"
    assert headers.get("Access-Control-Allow-Origin") == "*"
