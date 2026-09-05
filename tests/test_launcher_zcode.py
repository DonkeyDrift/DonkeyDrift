# -*- coding: utf-8 -*-
"""Launcher「打开 ZCode 网页终端」端点（POST /api/launch/zcode）的单元测试。

zcode 端点不启动子进程：仅校验可选 cwd、拼 ``cd <cwd> && zcode`` 命令，
返回 launcher 自身的 /terminal?cmd=...&title=ZCode&icon=zcode.png URL，
由浏览器侧 xterm.js 打开并自动执行。覆盖：happy path URL 形态（含
shlex.quote 防注入与 CORS 头）、cwd 不存在 400 绝不回退、缺省 cwd
动态取 Path.home()（而非硬编码本机路径入库）、非 JSON 请求体 400。
测试里的 IP 一律用 TEST-NET-1（192.0.2.x，RFC 5737）占位。
"""

import json
import shlex
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from donkeycar.launcher import server as launcher_server


@pytest.fixture()
def http_server(monkeypatch):
    """内存 HTTP 服务器；入口 host 钉为 192.0.2.10，隔离真实网络探测
    （_entry_host 真实实现会查局域网 IP / mDNS，结果随本机漂移）。"""
    monkeypatch.setattr(launcher_server, "_entry_host", lambda: "192.0.2.10")
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


def test_endpoint_happy_path_url_shape(http_server, tmp_path):
    # cwd 含空格：命令必须经 shlex.quote 防注入，quote 后的单引号/空格
    # 在 URL 里应呈百分号编码形态，而不是裸拼进 cmd
    cwd = str(tmp_path / "my proj")
    Path(cwd).mkdir()
    code, headers, payload = _post(
        http_server + "/api/launch/zcode",
        json.dumps({"cwd": cwd}).encode())
    assert code == 200
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"
    url = json.loads(payload)["url"]
    assert url.startswith("http://192.0.2.10:8090/terminal?cmd=")
    assert url.endswith("&title=ZCode&icon=zcode.png")
    cmd = f"cd {shlex.quote(cwd)} && zcode"
    assert quote(cmd, safe="") in url


def test_endpoint_rejects_nonexistent_cwd(http_server):
    # cwd 不存在：400 报错，绝不回退到其它目录
    code, _headers, payload = _post(
        http_server + "/api/launch/zcode",
        json.dumps({"cwd": "/nonexistent/definitely-not-a-dir"}).encode())
    assert code == 400
    assert "不存在" in json.loads(payload)["error"]


def test_endpoint_default_cwd_is_dynamic_home(http_server):
    # 不传 cwd：缺省动态取 Path.home()，URL 里 cmd 的 cd 目标应与
    # Path.home() 完全一致（防硬编码本机路径入库泄露的回归栅栏）
    code, _headers, payload = _post(http_server + "/api/launch/zcode", b"{}")
    assert code == 200
    url = json.loads(payload)["url"]
    cmd = f"cd {shlex.quote(str(Path.home()))} && zcode"
    assert quote(cmd, safe="") in url


def test_endpoint_rejects_non_json_with_cors(http_server):
    code, headers, payload = _post(
        http_server + "/api/launch/zcode", b"not-json")
    assert code == 400
    assert json.loads(payload)["status"] == "error"
    assert headers.get("Access-Control-Allow-Origin") == "*"
