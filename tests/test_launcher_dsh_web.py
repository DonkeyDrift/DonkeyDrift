# -*- coding: utf-8 -*-
"""Launcher「打开 DeepSeek Harness」（dsh_web.py，issue #164）与端点的单元测试。

测试覆盖 donkeycar.launcher.dsh_web：
- _write_patch_file：webserver 补丁层内容（host=0.0.0.0 + port 表达式）
- _patch_privileged_methods：特权方法栅栏自愈补丁（/api 的
  PRIVILEGED_METHODS 空信任表放宽为 trustedHosts，见 _PATCH_FENCE_*）
- launch_dsh_web：存活实例复用（不起子进程）、冷启动拉起
  ``dsh web --patch … --port 0 --trusted-host …``（_FakeProc 脚本化管道
  输出）成功抓 banner URL 且改写为局域网 IP、cwd 透传、cwd 非法直接
  报错、未安装 dsh、banner 超时杀进程、进程提前退出报错
- _SPAWNED 登记：死进程剔除、探测失败剔除后走冷启动
以及 POST /api/launch/dsh 端点：路由、参数校验、CORS 头（DC 从
ESP32 origin 跨域调用依赖它）。不起真实 dsh。
"""

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

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


# dsh web 就绪 banner（一行，回环 URL 在前、LAN 在后）
_DSH_BANNER = (b"\x1b[?1049hdsh web: http://127.0.0.1:43749 "
               b"(LAN: http://192.168.3.57:43749)\r\n")


@pytest.fixture(autouse=True)
def _clean_spawned():
    """每个测试后清掉 _SPAWNED，避免跨测试污染。"""
    yield
    dsh_web._SPAWNED.clear()


@pytest.fixture(autouse=True)
def _fake_lan_ip(monkeypatch):
    """固定本机局域网 IP，隔离真实网络探测。

    _lan_url 定义在 kimi_web 里、运行时查 kimi_web 自己的 _lan_ip，
    所以这里必须 patch kimi_web 命名空间（不是 dsh_web 的重导出名）。
    """
    monkeypatch.setattr(kimi_web, "_lan_ip", lambda: "192.168.3.10")


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
                            lambda: "http://192.168.3.10:43749/")
        spawned = []
        result = launch_dsh_web(
            cwd=None, timeout_s=5.0,
            popen_fn=_make_popen(spawned))
        assert result == {"status": "ok", "url": "http://192.168.3.10:43749/"}
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
        assert result["url"] == "http://192.168.3.10:43749"
        # 成功时子进程保持存活（杀它即关 web 服务），句柄被模块留住
        assert proc.killed is False
        assert proc in [e["proc"] for e in dsh_web._SPAWNED]
        assert dsh_web._SPAWNED[0]["port"] == 43749
        # 启动命令：web 子命令 + --patch 绕 host 限制 + 随机端口 +
        # trusted-host 放行局域网 API 栅栏
        args = proc.args_seen
        assert args[0].endswith("dsh")
        assert args[1] == "web"
        assert "--patch" in args
        assert args[args.index("--port") + 1] == "0"
        assert args[args.index("--trusted-host") + 1] == "192.168.3.10"

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
        dsh_web._SPAWNED.append({"proc": proc, "port": 43749})
        probed = []
        monkeypatch.setattr(
            dsh_web, "_probe_root",
            lambda host, port: probed.append((host, port)) or True)
        spawned = []
        result = launch_dsh_web(cwd=None, popen_fn=_make_popen(spawned))
        # dsh 固定绑 0.0.0.0，复用探测走回环
        assert probed == [("127.0.0.1", 43749)]
        assert result == {"status": "ok", "url": "http://192.168.3.10:43749/"}
        assert spawned == []

    def test_dead_entry_removed(self, monkeypatch):
        proc = _FakeProc(hold=True)
        proc._finish(0)  # 已退出
        dsh_web._SPAWNED.append({"proc": proc, "port": 43749})
        fresh = _FakeProc(payload=_DSH_BANNER, hold=True)
        result = launch_dsh_web(
            cwd=None, timeout_s=10.0,
            resolve_binary_fn=lambda: "/x/dsh",
            lan_ip_fn=lambda: "192.168.3.10",
            popen_fn=_make_popen([fresh]))
        # 死条目剔除后走冷启动
        assert dsh_web._SPAWNED == [{"proc": fresh, "port": 43749}]
        assert result["status"] == "ok"

    def test_probe_failure_removed_then_cold_start(self, monkeypatch):
        proc = _FakeProc(hold=True)  # 活着但端口僵死
        dsh_web._SPAWNED.append({"proc": proc, "port": 43749})
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
    # 请求不带 cwd：缺省 /home/dkc/projects（与 kimi-code-web 同目录，
    # dsh 以进程 cwd 作为新会话/工作区默认目录）
    seen = []

    def fake(cwd=None):
        seen.append(cwd)
        return {"status": "ok", "url": "http://dsh.example/w"}

    monkeypatch.setattr(launcher_server, "launch_dsh_web", fake)
    code, _headers, _payload = _post(http_server + "/api/launch/dsh", b"{}")
    assert code == 200
    assert seen == ["/home/dkc/projects"]


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
