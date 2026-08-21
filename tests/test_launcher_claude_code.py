# -*- coding: utf-8 -*-
"""POST /api/launch/claude-code 端点（网页终端入口，Claude Code）的单元测试。

Claude Code 没有官方 web UI：端点不启动任何子进程，只回 launcher
自带网页终端的 URL（/terminal?cmd=...，终端页面连上 WebSocket 后把
cmd 作为首行命令执行），claude 在浏览器终端会话里运行。测试覆盖：
路由、参数校验（非法 JSON / 非对象体 / 非字符串 cwd）、cwd 缺省
/home/dkc/projects、cwd 不存在直接报错、URL 形态（/terminal?cmd=
已 URL 编码、cmd 含 cd 与 claude）、CORS 头（DC 从 ESP32 origin
跨域调用依赖它）。_entry_host 固定为固定主机名，隔离真实 mDNS/网络
探测，保证测试稳定。
"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from donkeycar.launcher import server as launcher_server


# ===========================================================================
# POST /api/launch/claude-code 端点（内存 HTTP 服务器）
# ===========================================================================
@pytest.fixture()
def http_server(monkeypatch):
    # 固定入口 host，隔离真实 mDNS/局域网 IP 探测（结果随本机网络漂移）
    monkeypatch.setattr(launcher_server, "_entry_host",
                        lambda: "TONY007.local")
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


def _post_claude_code(http_server, body: bytes):
    return _post(http_server + "/api/launch/claude-code", body)


def test_endpoint_ok_defaults_cwd_to_projects(http_server):
    # 空体/空对象不带 cwd：缺省 /home/dkc/projects（与 kimi-code-web
    # 同目录，不落回用户主目录）
    code, headers, payload = _post_claude_code(http_server, b"{}")
    assert code == 200
    result = json.loads(payload)
    assert result["status"] == "ok"
    # URL 形态：launcher 网页终端 + URL 编码的 cmd 参数
    assert result["url"].startswith(
        "http://TONY007.local:8090/terminal?cmd=")
    cmd = urllib.parse.parse_qs(
        urllib.parse.urlsplit(result["url"]).query)["cmd"][0]
    assert cmd == "cd /home/dkc/projects && claude"
    # DC（ESP32 origin）跨域 fetch 依赖这个头
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_ok_with_explicit_cwd(http_server, tmp_path):
    code, _headers, payload = _post_claude_code(
        http_server, json.dumps({"cwd": str(tmp_path)}).encode())
    assert code == 200
    result = json.loads(payload)
    assert result["status"] == "ok"
    cmd = urllib.parse.parse_qs(
        urllib.parse.urlsplit(result["url"]).query)["cmd"][0]
    assert cmd == f"cd {tmp_path} && claude"


def test_endpoint_quotes_cwd_with_spaces(http_server, tmp_path):
    # cwd 含空格时 shlex.quote 加引号，URL 再做 percent 编码
    spaced = tmp_path / "dir with space"
    spaced.mkdir()
    code, _headers, payload = _post_claude_code(
        http_server, json.dumps({"cwd": str(spaced)}).encode())
    assert code == 200
    result = json.loads(payload)
    assert result["url"].startswith(
        "http://TONY007.local:8090/terminal?cmd=")
    assert " " not in result["url"]  # cmd 已 URL 编码
    cmd = urllib.parse.parse_qs(
        urllib.parse.urlsplit(result["url"]).query)["cmd"][0]
    assert cmd == f"cd '{spaced}' && claude"


def test_endpoint_missing_cwd_is_500_with_cors(http_server):
    # cwd 不存在直接报错（与 kimi-code-web 行为一致），绝不回退
    code, headers, payload = _post_claude_code(
        http_server,
        json.dumps({"cwd": "/nonexistent/definitely-not-a-dir"}).encode())
    assert code == 500
    result = json.loads(payload)
    assert result["status"] == "error"
    assert "不存在" in result["error"]
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_json_with_cors(http_server):
    code, headers, payload = _post_claude_code(http_server, b"not-json")
    assert code == 400
    assert json.loads(payload)["status"] == "error"
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_endpoint_rejects_non_object_body(http_server):
    code, _headers, payload = _post_claude_code(http_server, b"[1,2]")
    assert code == 400
    assert "JSON 对象" in json.loads(payload)["error"]


def test_endpoint_rejects_non_string_cwd(http_server):
    code, _headers, payload = _post_claude_code(
        http_server, json.dumps({"cwd": 123}).encode())
    assert code == 400
    assert "cwd" in json.loads(payload)["error"]
