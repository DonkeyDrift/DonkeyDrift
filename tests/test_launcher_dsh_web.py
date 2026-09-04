# -*- coding: utf-8 -*-
"""Launcher「打开 DeepSeek Harness」（dsh_web.py，issue #164）与端点的单元测试。

测试覆盖 donkeycar.launcher.dsh_web：
- _write_patch_file：webserver 补丁层内容（host=0.0.0.0 + port 表达式）
- _patch_privileged_methods：特权方法栅栏自愈补丁（/api 的
  PRIVILEGED_METHODS 空信任表放宽为 trustedHosts，见 _PATCH_FENCE_*）
- _patch_client_uuid_polyfill：client.js 顶部注入 crypto.randomUUID 兜底
  （非安全上下文下 RFC4122 v4，见 _PATCH_UUID_*）
- _probe_dsh_fixed_port：固定端口特征探测（200 且响应体含
  __DSH_BOOT__ 才视为 dsh；无标记/连接失败返回 None）
- launch_dsh_web：存活实例复用（不起子进程）、冷启动拉起
  ``dsh web --patch … --port 58641 --trusted-host …``（固定专属端口
  DSH_WEB_PORT；_FakeProc 脚本化管道输出）成功抓 banner URL 且改写为
  局域网入口（mDNS 主机名优先，其次局域网 IP）、cwd 透传、cwd 非法
  直接报错、未安装 dsh、banner 超时杀进程、进程提前退出报错、冷启动
  失败后固定端口兜底复用
- _SPAWNED 登记：死进程剔除、探测失败剔除后走冷启动；登记为空
  （模拟 launcher 重启）时经固定端口特征探测复用存活实例
以及 POST /api/launch/dsh 端点：路由、参数校验、CORS 头（DC 从
ESP32 origin 跨域调用依赖它）。不起真实 dsh。
"""

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from donkeycar.launcher import dsh_web
from donkeycar.launcher import kimi_web
from donkeycar.launcher.dsh_web import launch_dsh_web
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


class _FakeHttpResponse:
    """urllib.request.urlopen 替身：固定 status/body 的上下文管理器响应。"""

    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self, _size=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# dsh web 就绪 banner（一行，回环 URL 在前、LAN 在后）；固定专属端口
# 后 banner 端口恒为 DSH_WEB_PORT
_DSH_BANNER = (b"\x1b[?1049hdsh web: http://127.0.0.1:58641 "
               b"(LAN: http://192.168.3.57:58641)\r\n")


@pytest.fixture(autouse=True)
def _clean_spawned():
    """每个测试后清掉 _SPAWNED，避免跨测试污染。"""
    yield
    dsh_web._SPAWNED.clear()


# 真实 _probe_dsh_fixed_port 的引用：下面的 autouse fixture 默认把它钉成
# 返回 None，需要真实探测行为的用例先恢复它再 mock urlopen
_REAL_PROBE_DSH_FIXED_PORT = dsh_web._probe_dsh_fixed_port


@pytest.fixture(autouse=True)
def _no_fixed_port_dsh(monkeypatch):
    """默认固定端口上没有存活 dsh，隔离真实端口探测。

    _live_spawned_url 在 _SPAWNED 无存活条目后会探测固定端口
    （_probe_dsh_fixed_port 真实 urlopen 127.0.0.1:DSH_WEB_PORT），结果随
    本机端口占用漂移；默认钉死为 None。要覆盖固定端口行为的用例先
    monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
    _REAL_PROBE_DSH_FIXED_PORT) 恢复真实函数，再 mock urlopen。
    """
    monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port", lambda: None)


@pytest.fixture(autouse=True)
def _fake_lan_ip(monkeypatch):
    """固定本机局域网 IP，隔离真实网络探测。

    _lan_url 定义在 kimi_web 里、运行时查 kimi_web 自己的 _lan_ip 与
    _mdns_hostname（_entry_host 现在 mDNS 优先），所以这里必须把两者都
    patch 到 kimi_web 命名空间（不是 dsh_web 的重导出名），否则
    _entry_host() 会真去解析 mDNS、结果随本机网络漂移。dsh_web 另用
    ``_mdns_hostname`` 派生 trusted-host，同样默认关掉 mDNS（返回 None），
    需要覆盖时由用例显式传 ``mdns_fn=``。
    """
    monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")
    monkeypatch.setattr(kimi_web, "_mdns_hostname", lambda: None)
    monkeypatch.setattr(dsh_web, "_mdns_hostname", lambda: None)


# ===========================================================================
# _write_patch_file（webserver 补丁层）
# ===========================================================================
def test_patch_file_content():
    path = dsh_web._write_patch_file()
    content = open(path, encoding="utf-8").read()
    # host 必须 0.0.0.0（局域网可达）；port 不能省（配置校验要求有值），
    # 用表达式跟随 --port 参数
    assert "host: 0.0.0.0" in content
    assert "port: !!js ctx.webStartup.port ?? 3080" in content
    assert content.startswith("- id: webserver")


# ===========================================================================
# launch_dsh_web
# ===========================================================================
class TestLaunchDshWeb:
    def test_reuses_live_spawned_instance_without_spawning(self, monkeypatch):
        # _live_spawned_url 的契约：返回前已把回环改写为局域网 IP
        monkeypatch.setattr(dsh_web, "_live_spawned_url",
                            lambda: "http://192.168.3.10:58641/")
        spawned = []
        result = launch_dsh_web(
            cwd=None, timeout_s=5.0,
            popen_fn=_make_popen(spawned))
        assert result == {"status": "ok",
                         "url": "http://192.168.3.10:58641/?dsh_new_session=1"}
        assert spawned == []  # 复用路径不起子进程

    def test_spawn_success_captures_url_and_keeps_proc(self):
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        # banner 里的 127.0.0.1 被改写为局域网 IP（issue #125 同款）
        assert result["url"] == "http://192.168.3.10:58641?dsh_new_session=1"
        # 成功时子进程保持存活（杀它即关 web 服务），句柄被模块留住
        assert proc.killed is False
        assert proc in [e["proc"] for e in dsh_web._SPAWNED]
        assert dsh_web._SPAWNED[0]["port"] == 58641
        # 启动命令：web 子命令 + --patch 绕 host 限制 + 固定专属端口 +
        # trusted-host 放行局域网 API 栅栏
        args = proc.args_seen
        assert args[0].endswith("dsh")
        assert args[1] == "web"
        assert "--patch" in args
        assert args[args.index("--port") + 1] == "58641"
        assert args[args.index("--trusted-host") + 1] == "192.168.3.10"

    def test_spawn_url_prefers_mdns_host(self, monkeypatch):
        # 入口 URL 的 host mDNS 优先（回归覆盖）：_lan_url 查的是
        # kimi_web 模块级 _mdns_hostname（autouse fixture 已钉 None，这里
        # 解除钉死）；launch_dsh_web 的 mdns_fn 参数只影响
        # --trusted-host，与本断言无关。mDNS 还要过 _entry_host 的
        # avahi AAAA 防护才生效，一并钉为不发布
        monkeypatch.setattr(kimi_web, "_mdns_hostname",
                            lambda: "tony007.local")
        monkeypatch.setattr(kimi_web, "_avahi_publishes_ipv6", lambda: False)
        proc = _FakeProc(payload=b"dsh web: http://127.0.0.1:58641/\r\n",
                         hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert result["url"] == "http://tony007.local:58641/?dsh_new_session=1"

    def test_reuse_url_prefers_mdns_host(self, monkeypatch):
        # 复用路径（_live_spawned_url 命中 _SPAWNED）同样 mDNS 优先；
        # 同上需钉 _avahi_publishes_ipv6 为不发布，mDNS 才成为入口 host
        monkeypatch.setattr(kimi_web, "_mdns_hostname",
                            lambda: "tony007.local")
        monkeypatch.setattr(kimi_web, "_avahi_publishes_ipv6", lambda: False)
        proc = _FakeProc(hold=True)
        dsh_web._SPAWNED.append({"proc": proc, "port": 58641})
        monkeypatch.setattr(dsh_web, "_probe_root", lambda *a: True)
        spawned = []
        result = launch_dsh_web(cwd=None, popen_fn=_make_popen(spawned))
        assert result == {"status": "ok",
                          "url": "http://tony007.local:58641/?dsh_new_session=1"}
        assert spawned == []

    def test_spawn_skips_trusted_host_without_lan_ip(self):
        # 无局域网 IP（如离线）时不传 --trusted-host，其余照常
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            lan_ip_fn=lambda: None,
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert "--trusted-host" not in proc.args_seen

    def test_spawn_adds_mdns_host_to_trusted_host(self):
        # 入口 URL 用 mDNS 主机名（_lan_url 优先），--trusted-host 必须
        # 同时声明局域网 IP 与 mDNS 名，否则浏览器以 mDNS 名访问时会被
        # /api 通用信任栅栏 403（issue #164）。
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            mdns_fn=lambda: "TONY007.local",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        args = proc.args_seen
        idx = args.index("--trusted-host")
        assert args[idx + 1] == "192.168.3.10"
        assert args[idx + 2] == "--trusted-host"
        assert args[idx + 3] == "TONY007.local"

    def test_spawn_passes_cwd_through(self, tmp_path):
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=str(tmp_path), timeout_s=10.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert proc.kwargs_seen["cwd"] == str(tmp_path)

    def test_invalid_cwd_errors_without_spawning(self):
        spawned = []
        result = launch_dsh_web(
            cwd="/nonexistent/definitely-not-a-dir", timeout_s=1.0,
            popen_fn=_make_popen(spawned))
        assert result["status"] == "error"
        assert "不存在" in result["error"]
        assert spawned == []

    def test_dsh_binary_missing(self):
        result = launch_dsh_web(
            cwd=None, timeout_s=1.0,
            resolve_binary_fn=lambda: None)
        assert result["status"] == "error"
        assert "未找到 dsh" in result["error"]

    def test_spawn_banner_timeout_kills_proc(self):
        proc = _FakeProc(hold=True)  # 一直不出 URL 也不退出
        result = launch_dsh_web(
            cwd=None, timeout_s=1.5,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "error"
        assert "超时" in result["error"]
        assert proc.killed is True
        assert dsh_web._SPAWNED == []

    def test_spawn_exit_without_url_reports_tail(self):
        proc = _FakeProc(payload=b"Error: config invalid\r\n", exit_code=2)
        result = launch_dsh_web(
            cwd=None, timeout_s=5.0,
            resolve_binary_fn=lambda: "/home/u/env/bin/dsh",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "error"
        assert "提前退出" in result["error"]
        assert "config invalid" in result["error"]
        assert proc.killed is True


# ===========================================================================
# _SPAWNED 登记的复用与清理
# ===========================================================================
class TestSpawnedRegistry:
    def test_live_entry_probed_and_rewritten(self, monkeypatch):
        proc = _FakeProc(hold=True)
        dsh_web._SPAWNED.append({"proc": proc, "port": 58641})
        probed = []
        monkeypatch.setattr(
            dsh_web, "_probe_root",
            lambda host, port: probed.append((host, port)) or True)
        spawned = []
        result = launch_dsh_web(cwd=None, popen_fn=_make_popen(spawned))
        # dsh 固定绑 0.0.0.0，复用探测走回环
        assert probed == [("127.0.0.1", 58641)]
        assert result == {"status": "ok",
                          "url": "http://192.168.3.10:58641/?dsh_new_session=1"}
        assert spawned == []

    def test_dead_entry_removed(self, monkeypatch):
        proc = _FakeProc(hold=True)
        proc._finish(0)  # 已退出
        dsh_web._SPAWNED.append({"proc": proc, "port": 58641})
        fresh = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/x/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([fresh]))
        # 死条目剔除后走冷启动（固定端口探测被 autouse fixture 钉为 None）
        assert dsh_web._SPAWNED == [{"proc": fresh, "port": 58641}]
        assert result["status"] == "ok"

    def test_probe_failure_removed_then_cold_start(self, monkeypatch):
        proc = _FakeProc(hold=True)  # 活着但端口僵死
        dsh_web._SPAWNED.append({"proc": proc, "port": 58641})
        monkeypatch.setattr(dsh_web, "_probe_root", lambda *a: False)
        procs = [_FakeProc(payload=_DSH_BANNER, hold=True)]
        fresh = procs[0]
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/x/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen(procs))
        assert result["status"] == "ok"
        # 僵死条目被清掉，换上冷启动的新实例
        assert [e["proc"] for e in dsh_web._SPAWNED] == [fresh]


# ===========================================================================
# _probe_dsh_fixed_port（固定端口特征探测）与跨 launcher 重启的复用
# ===========================================================================
# dsh web 根 HTML 里的特征标记（window.__DSH_BOOT__）
_DSH_BOOT_HTML = b"<html><script>window.__DSH_BOOT__={};</script></html>"


class TestProbeDshFixedPort:
    def test_hit_returns_lan_entry_url(self, monkeypatch):
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)
        seen = []

        def fake_urlopen(url, timeout=None):
            seen.append(url)
            return _FakeHttpResponse(200, _DSH_BOOT_HTML)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert dsh_web._probe_dsh_fixed_port() == \
            "http://192.168.3.10:58641/"
        # 探测走回环固定端口，返回前才改写为局域网入口
        assert seen == ["http://127.0.0.1:58641/"]

    def test_200_without_boot_marker_returns_none(self, monkeypatch):
        # 200 但无 __DSH_BOOT__ 特征：是占用该端口的外部服务，不能当 dsh
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda url, timeout=None: _FakeHttpResponse(200,
                                                        b"<html>v</html>"))
        assert dsh_web._probe_dsh_fixed_port() is None

    def test_connection_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)

        def fake_urlopen(url, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert dsh_web._probe_dsh_fixed_port() is None


class TestFixedPortReuse:
    """launcher 重启后 _SPAWNED 丢失，固定端口探测通道的复用/穿透/兜底。"""

    def test_empty_registry_reuses_live_dsh_on_fixed_port(self, monkeypatch):
        # _SPAWNED 为空（模拟 launcher 重启）但固定端口上有存活 dsh：
        # 直接复用，不冷启动
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda url, timeout=None: _FakeHttpResponse(200, _DSH_BOOT_HTML))
        spawned = []
        result = launch_dsh_web(cwd=None, popen_fn=_make_popen(spawned))
        assert result == {"status": "ok",
                          "url": "http://192.168.3.10:58641/?dsh_new_session=1"}
        assert spawned == []  # 复用路径不起子进程
        # 实例非本进程拉起，没有 proc 可登记
        assert dsh_web._SPAWNED == []

    def test_200_without_boot_marker_falls_through_to_cold_start(
            self, monkeypatch):
        # 固定端口被外部服务占用（200 但无特征标记）：不复用，走冷启动
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda url, timeout=None: _FakeHttpResponse(200,
                                                        b"<html>v</html>"))
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/x/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        args = proc.args_seen
        assert args[args.index("--port") + 1] == "58641"

    def test_spawn_failure_falls_back_to_fixed_port_probe(self, monkeypatch):
        # 冷启动失败兜底（对齐 kimi_web 语义）：第一次探测时实例尚未就绪
        # （连接拒绝），spawn 失败后第二次探测已就绪 → 复用
        monkeypatch.setattr(dsh_web, "_probe_dsh_fixed_port",
                            _REAL_PROBE_DSH_FIXED_PORT)
        calls = []

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            if len(calls) == 1:
                raise urllib.error.URLError("connection refused")
            return _FakeHttpResponse(200, _DSH_BOOT_HTML)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        proc = _FakeProc(payload=b"Error: address already in use\r\n",
                         exit_code=2)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/x/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result == {"status": "ok",
                         "url": "http://192.168.3.10:58641/?dsh_new_session=1"}
        assert proc.killed is True  # 冷启动失败路径杀净
        # 冷启动前一次 + 失败后兜底一次，都探回环固定端口
        assert calls == ["http://127.0.0.1:58641/"] * 2


# ===========================================================================
# _patch_privileged_methods（特权方法栅栏自愈补丁）
# ===========================================================================
# rc.6 实测的栅栏源码片段（dsh-client-connection/lib/index.js）：
_FENCE_SNIPPET = (
    "function apply(ctx, config) {\n"
    "\tconst trustedHosts = config?.trustedHosts ?? [];\n"
    "\tif (method !== void 0 && PRIVILEGED_METHODS.has(method) && "
    "!isTrustedApiRequest(request, [])) return new Response(\"forbidden\", "
    "{ status: 403 });\n"
    "}\n"
)


def _make_dsh_tree(tmp_path, fence_text):
    """搭假 dsh 安装树：<pkg>/lib/bin.js + dsh-client-connection，返回 bin 路径。"""
    pkg = tmp_path / "dsh"
    (pkg / "lib").mkdir(parents=True)
    (pkg / "lib" / "bin.js").write_text("#!/usr/bin/env node\n",
                                        encoding="utf-8")
    cc = (pkg / "node_modules" / "@deepseek-ai"
          / "dsh-client-connection" / "lib")
    cc.mkdir(parents=True)
    (cc / "index.js").write_text(fence_text, encoding="utf-8")
    return pkg / "lib" / "bin.js"


class TestPatchPrivilegedMethods:
    def test_patches_empty_trust_list_to_trusted_hosts(self, tmp_path):
        binary = _make_dsh_tree(tmp_path, _FENCE_SNIPPET)
        dsh_web._patch_privileged_methods(str(binary))
        text = ((tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                 / "dsh-client-connection" / "lib" / "index.js")
                .read_text(encoding="utf-8"))
        assert dsh_web._PATCH_FENCE_NEW in text
        assert dsh_web._PATCH_FENCE_OLD not in text

    def test_idempotent_second_call_is_noop(self, tmp_path):
        binary = _make_dsh_tree(tmp_path, _FENCE_SNIPPET)
        dsh_web._patch_privileged_methods(str(binary))
        target = (tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                  / "dsh-client-connection" / "lib" / "index.js")
        patched = target.read_text(encoding="utf-8")
        dsh_web._patch_privileged_methods(str(binary))
        assert target.read_text(encoding="utf-8") == patched

    def test_unexpected_source_skips_silently(self, tmp_path):
        # dsh 升级后代码段变了：不命中就不动文件
        binary = _make_dsh_tree(tmp_path, "const x = 1;\n")
        dsh_web._patch_privileged_methods(str(binary))
        target = (tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                  / "dsh-client-connection" / "lib" / "index.js")
        assert target.read_text(encoding="utf-8") == "const x = 1;\n"

    def test_missing_connection_package_skips_silently(self, tmp_path):
        # rc.7 起的 pnpm 布局：dsh 包下没有 node_modules/<cc>
        pkg = tmp_path / "dsh"
        (pkg / "lib").mkdir(parents=True)
        (pkg / "lib" / "bin.js").write_text("", encoding="utf-8")
        # 不抛异常即通过
        dsh_web._patch_privileged_methods(str(pkg / "lib" / "bin.js"))

    def test_launch_patches_before_spawn(self, tmp_path, monkeypatch):
        # launch_dsh_web 冷启动路径会先打栅栏补丁再拉子进程
        binary = _make_dsh_tree(tmp_path, _FENCE_SNIPPET)
        calls = []

        def fake_patch(b):
            calls.append(b)

        monkeypatch.setattr(dsh_web, "_patch_privileged_methods", fake_patch)
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: str(binary),
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert calls == [str(binary)]


# ===========================================================================
# _patch_client_uuid_polyfill（client.js crypto.randomUUID 兜底补丁）
# ===========================================================================
# rc.6 实测的 client.js 顶部片段（factory 作用域内 CommonJS 桩）：
_UUID_SNIPPET = (
    "window.__ModuleLoader__.load({\n"
    "\tid: \"@deepseek-ai/dsh-client-connection\",\n"
    "\tfactory: (require) => {\n"
    "\t\tvar module = { exports: {} };\n"
    "\t\tvar exports = module.exports;\n"
    "\t\tObject.defineProperty(exports, Symbol.toStringTag, { value: \"Module\" });\n"
    "\t\t//#region lib/types/client/connection.js\n"
    "\t\tconst CONNECTION_DEFAULTS = {}\n"
    "\t};\n"
    "});\n"
)


def _make_dsh_client_tree(tmp_path, client_text):
    """搭假 dsh 安装树：<pkg>/lib/bin.js + dsh-client-connection/client.js。"""
    pkg = tmp_path / "dsh"
    (pkg / "lib").mkdir(parents=True)
    (pkg / "lib" / "bin.js").write_text("#!/usr/bin/env node\n",
                                        encoding="utf-8")
    cc = (pkg / "node_modules" / "@deepseek-ai"
          / "dsh-client-connection" / "lib")
    cc.mkdir(parents=True)
    (cc / "client.js").write_text(client_text, encoding="utf-8")
    return pkg / "lib" / "bin.js"


class TestPatchClientUuidPolyfill:
    def test_patches_random_uuid_polyfill_into_client(self, tmp_path):
        binary = _make_dsh_client_tree(tmp_path, _UUID_SNIPPET)
        dsh_web._patch_client_uuid_polyfill(str(binary))
        text = ((tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                 / "dsh-client-connection" / "lib" / "client.js")
                .read_text(encoding="utf-8"))
        assert dsh_web._PATCH_UUID_NEW in text
        assert dsh_web._PATCH_UUID_OLD not in text

    def test_idempotent_second_call_is_noop(self, tmp_path):
        binary = _make_dsh_client_tree(tmp_path, _UUID_SNIPPET)
        dsh_web._patch_client_uuid_polyfill(str(binary))
        target = (tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                  / "dsh-client-connection" / "lib" / "client.js")
        patched = target.read_text(encoding="utf-8")
        dsh_web._patch_client_uuid_polyfill(str(binary))
        assert target.read_text(encoding="utf-8") == patched

    def test_unexpected_source_skips_silently(self, tmp_path):
        binary = _make_dsh_client_tree(tmp_path, "const x = 1;\n")
        dsh_web._patch_client_uuid_polyfill(str(binary))
        target = (tmp_path / "dsh" / "node_modules" / "@deepseek-ai"
                  / "dsh-client-connection" / "lib" / "client.js")
        assert target.read_text(encoding="utf-8") == "const x = 1;\n"

    def test_missing_connection_package_skips_silently(self, tmp_path):
        # rc.7 起的 pnpm 布局：dsh 包下没有 node_modules/<cc>
        pkg = tmp_path / "dsh"
        (pkg / "lib").mkdir(parents=True)
        (pkg / "lib" / "bin.js").write_text("", encoding="utf-8")
        # 不抛异常即通过
        dsh_web._patch_client_uuid_polyfill(str(pkg / "lib" / "bin.js"))

    def test_launch_patches_uuid_before_spawn(self, tmp_path, monkeypatch):
        # launch_dsh_web 冷启动路径会先打 UUID 补丁再拉子进程
        binary = _make_dsh_client_tree(tmp_path, _UUID_SNIPPET)
        calls = []

        def fake_patch(b):
            calls.append(b)

        monkeypatch.setattr(dsh_web, "_patch_client_uuid_polyfill", fake_patch)
        # 该树没有 index.js，真实 _patch_privileged_methods 会跳过；这里置空
        # 只聚焦验证 UUID 补丁的调用时机
        monkeypatch.setattr(dsh_web, "_patch_privileged_methods",
                            lambda b: None)
        proc = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: str(binary),
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([proc]))
        assert result["status"] == "ok"
        assert calls == [str(binary)]


# ===========================================================================
# POST /api/launch/dsh 端点（内存 HTTP 服务器）
# ===========================================================================
@pytest.fixture()
def http_server(monkeypatch):
    fake = lambda cwd=None: {"status": "ok", "url": "http://dsh.example/w"}
    monkeypatch.setattr(launcher_server, "launch_dsh_web", fake)
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
    code, headers, payload = _post(http_server + "/api/launch/dsh", b"{}")
    assert code == 200
    assert json.loads(payload) == {"status": "ok",
                                   "url": "http://dsh.example/w"}
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_passes_cwd_through(http_server, monkeypatch):
    seen = []

    def fake(cwd=None):
        seen.append(cwd)
        return {"status": "ok", "url": "http://dsh.example/w"}

    monkeypatch.setattr(launcher_server, "launch_dsh_web", fake)
    _post(http_server + "/api/launch/dsh",
          json.dumps({"cwd": "/home/dkc/projects"}).encode())
    assert seen == ["/home/dkc/projects"]


def test_endpoint_defaults_cwd_to_projects(http_server, monkeypatch):
    # 请求不带 cwd：缺省动态推导为 Path.home()/"projects"（与
    # kimi-code-web 同目录，非硬编码串；dsh 以进程 cwd 作为新会话/
    # 工作区默认目录）
    seen = []

    def fake(cwd=None):
        seen.append(cwd)
        return {"status": "ok", "url": "http://dsh.example/w"}

    monkeypatch.setattr(launcher_server, "launch_dsh_web", fake)
    code, _headers, _payload = _post(http_server + "/api/launch/dsh", b"{}")
    assert code == 200
    assert seen == [str(Path.home() / "projects")]


def test_endpoint_rejects_non_json_with_cors(http_server):
    code, headers, payload = _post(
        http_server + "/api/launch/dsh", b"not-json")
    assert code == 400
    assert json.loads(payload)["status"] == "error"
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_object_body(http_server):
    code, _headers, payload = _post(
        http_server + "/api/launch/dsh", b"[1,2]")
    assert code == 400
    assert "JSON 对象" in json.loads(payload)["error"]


def test_endpoint_rejects_non_string_cwd(http_server):
    code, _headers, payload = _post(
        http_server + "/api/launch/dsh",
        json.dumps({"cwd": 123}).encode())
    assert code == 400
    assert "cwd" in json.loads(payload)["error"]


def test_endpoint_error_from_automation_is_500(http_server, monkeypatch):
    monkeypatch.setattr(
        launcher_server, "launch_dsh_web",
        lambda cwd=None: {"status": "error", "error": "boom"})
    code, headers, payload = _post(
        http_server + "/api/launch/dsh", b"{}")
    assert code == 500
    assert json.loads(payload)["error"] == "boom"
    assert headers.get("Access-Control-Allow-Origin") == "*"


# ===========================================================================
# _mark_new_session（URL 追加 ?dsh_new_session=1）
# ===========================================================================
def test_mark_new_session_appends_marker_and_is_idempotent():
    """_mark_new_session 给裸 URL 追加 ?dsh_new_session=1，且幂等不重复加。"""
    # 裸 URL（带尾斜杠）→ 追加 marker
    assert dsh_web._mark_new_session(
        "http://192.168.3.10:58641/") == \
        "http://192.168.3.10:58641/?dsh_new_session=1"
    # 裸 URL（不带尾斜杠）→ 追加 marker
    assert dsh_web._mark_new_session(
        "http://192.168.3.10:58641") == \
        "http://192.168.3.10:58641?dsh_new_session=1"
    # 已含 marker → 幂等，不重复追加
    assert dsh_web._mark_new_session(
        "http://192.168.3.10:58641/?dsh_new_session=1") == \
        "http://192.168.3.10:58641/?dsh_new_session=1"
    # 已含 marker（无尾斜杠）→ 幂等
    assert dsh_web._mark_new_session(
        "http://tony007.local:58641?dsh_new_session=1") == \
        "http://tony007.local:58641?dsh_new_session=1"
    # 已有其他 query 参数 → 追加在后面
    assert dsh_web._mark_new_session(
        "http://192.168.3.10:58641/?foo=bar") == \
        "http://192.168.3.10:58641/?foo=bar&dsh_new_session=1"


def test_patch_uuid_new_contains_new_session_marker():
    """_PATCH_UUID_NEW 常量包含 dsh_new_session 清理逻辑的标记文本，
    确保 client.js 补丁注入了新会话清除代码。"""
    assert "dsh_new_session" in dsh_web._PATCH_UUID_NEW
