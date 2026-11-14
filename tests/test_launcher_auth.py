# -*- coding: utf-8 -*-
"""Launcher 访问控制（P0 安全补强，2026-10-12）单元测试。

覆盖 donkeycar.launcher.auth 策略与 launcher/server 的鉴权门：
- 令牌生命周期：环境变量优先、0600 落盘、幂等复用、常数时间比对
- 判定矩阵：回环免令牌、跨站 Origin 拒绝、DNS rebinding（Host 钳制）、
  显式令牌与 Cookie 的通行规则、DONKEY_LAUNCHER_AUTH=off 全放行
- HTTP 层：远程样式 401（JSON / HTML / WS 握手）、页面 GET ?token=
  种 Cookie + 302 去查询串、/api/* 不跳转保 curl、本机访问不生成令牌
  文件（防测试副作用）
- resolve_bind_host：默认 127.0.0.1，显式参数 > 环境变量 > 默认

全部令牌读写打桩到 tmp_path，不触碰真实 ~/.donkeycar/launcher.token。
"""

import http.client
import json
import stat
import threading
from http.server import ThreadingHTTPServer

import pytest

from donkeycar.launcher import auth as launch_auth
from donkeycar.launcher.server import LauncherHandler, resolve_bind_host


REMOTE = ("192.168.1.7", 50000)  # 模拟局域网设备的 TCP 对端


@pytest.fixture()
def isolated_token(monkeypatch, tmp_path):
    """令牌文件/环境打桩：文件指向 tmp_path，清掉环境开关。"""
    monkeypatch.delenv(launch_auth.TOKEN_ENV, raising=False)
    monkeypatch.delenv(launch_auth.AUTH_ENV, raising=False)
    monkeypatch.delenv(launch_auth.HOST_ENV, raising=False)
    token_file = tmp_path / "launcher.token"
    monkeypatch.setattr(launch_auth, "TOKEN_FILE", token_file)
    return token_file


@pytest.fixture()
def http_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), LauncherHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    thread.join(timeout=2)


def _request(hostport, method, path, headers=None, body=None):
    """原始 HTTP 请求（不跟随重定向，保留 302/401 原样）。"""
    conn = http.client.HTTPConnection(hostport, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, resp, data
    finally:
        conn.close()


class TestTokenLifecycle:
    def test_env_wins_and_no_file_written(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "env-token-123")
        assert launch_auth.load_or_create_token() == "env-token-123"
        assert not isolated_token.exists()

    def test_generates_persists_0600_and_idempotent(self, isolated_token):
        token = launch_auth.load_or_create_token()
        assert len(token) >= 20
        assert isolated_token.exists()
        assert stat.S_IMODE(isolated_token.stat().st_mode) == 0o600
        assert launch_auth.load_or_create_token() == token

    def test_empty_file_falls_through_to_generate(self, isolated_token):
        isolated_token.parent.mkdir(parents=True, exist_ok=True)
        isolated_token.write_text("", encoding="utf-8")
        token = launch_auth.load_or_create_token()
        assert token
        assert launch_auth.load_or_create_token() == token

    def test_token_matches_exact_only(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-abc")
        assert launch_auth.token_matches("tok-abc")
        assert not launch_auth.token_matches("tok-ABC")
        assert not launch_auth.token_matches("tok-ab")
        assert not launch_auth.token_matches("")
        assert not launch_auth.token_matches(None)


class TestAuthSwitch:
    def test_enabled_by_default(self, isolated_token):
        assert launch_auth.auth_enabled()

    @pytest.mark.parametrize("raw", ["off", "0", "false", "no", "OFF", " Off "])
    def test_kill_switch_values(self, raw, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.AUTH_ENV, raw)
        assert not launch_auth.auth_enabled()

    def test_off_opens_everything(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.AUTH_ENV, "off")
        headers = {"Origin": "http://evil.example", "Host": "car.evil:8090"}
        assert launch_auth.is_authorized(headers, {}, REMOTE)


class TestClientAndOrigin:
    @pytest.mark.parametrize("addr", [
        ("127.0.0.1", 50000), ("::1", 50000), ("127.5.5.5", 1),
        ("::ffff:127.0.0.1", 2), ("testclient", 50000),
    ])
    def test_local_clients(self, addr):
        assert launch_auth.is_local_client(addr)

    @pytest.mark.parametrize("addr", [
        ("192.168.1.7", 50000), ("10.0.0.2", 80), ("172.16.0.9", 1),
        ("", 0), None,
    ])
    def test_remote_clients(self, addr):
        assert not launch_auth.is_local_client(addr)

    def test_local_plain_allowed(self, isolated_token):
        headers = {"Host": "127.0.0.1:8090"}
        assert launch_auth.is_authorized(headers, {}, ("127.0.0.1", 50000))

    def test_missing_host_denied(self, isolated_token):
        # HTTP/1.0 可以不带 Host；缺 Host 无法做 rebinding 判定，从严拒绝
        assert not launch_auth.is_authorized({}, {}, ("127.0.0.1", 50000))

    def test_local_same_origin_allowed(self, isolated_token):
        headers = {"Host": "127.0.0.1:8090",
                   "Origin": "http://127.0.0.1:8090"}
        assert launch_auth.is_authorized(headers, {}, ("127.0.0.1", 50000))

    def test_local_cross_origin_denied(self, isolated_token):
        headers = {"Host": "127.0.0.1:8090",
                   "Origin": "http://evil.example"}
        assert not launch_auth.is_authorized(
            headers, {}, ("127.0.0.1", 50000))

    def test_dns_rebinding_denied_even_on_loopback(self, isolated_token):
        # 恶意域名解析到车机：Origin/Host 同为攻击者域名也过不了 Host 钳制
        headers = {"Host": "car.evil:8090",
                   "Origin": "http://car.evil:8090"}
        assert not launch_auth.is_authorized(
            headers, {}, ("127.0.0.1", 50000))

    def test_host_self_names(self, isolated_token):
        for host in ("127.0.0.1:8090", "localhost:8090", "[::1]:8090",
                     "127.0.0.1"):
            assert launch_auth._host_is_self({"Host": host}), host
        for host in ("car.evil:8090", "evil.example", ""):
            assert not launch_auth._host_is_self({"Host": host}), host


class TestTokenPassage:
    def test_explicit_token_paths(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        cases = [
            {"Authorization": "Bearer tok-xyz"},
            {"X-Donkey-Token": "tok-xyz"},
        ]
        for headers in cases:
            assert launch_auth.is_authorized(headers, {}, REMOTE), headers
        assert launch_auth.is_authorized({}, {"token": ["tok-xyz"]}, REMOTE)

    def test_cookie_passage_requires_clean_origin(
            self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        cookie = {"Cookie": f"{launch_auth.COOKIE_NAME}=tok-xyz",
                  "Host": "127.0.0.1:8090"}
        assert launch_auth.is_authorized(cookie, {}, REMOTE)
        hostile = dict(cookie, Origin="http://evil.example")
        assert not launch_auth.is_authorized(hostile, {}, REMOTE)

    def test_wrong_token_denied(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        headers = {"Authorization": "Bearer wrong"}
        assert not launch_auth.is_authorized(headers, {}, REMOTE)

    def test_extract_token_precedence(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        headers = {
            "Authorization": "Bearer from-bearer",
            "X-Donkey-Token": "from-header",
            "Cookie": f"{launch_auth.COOKIE_NAME}=from-cookie",
        }
        assert launch_auth.extract_token(headers, {"token": ["from-query"]}) \
            == "from-bearer"
        assert launch_auth.extract_token({}, {"token": ["from-query"]}) \
            == "from-query"
        assert launch_auth.extract_token(
            {"Cookie": f"{launch_auth.COOKIE_NAME}=from-cookie"}, {}) \
            == "from-cookie"

    def test_query_token_valid(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        assert launch_auth.query_token_valid({"token": ["tok-xyz"]})
        assert not launch_auth.query_token_valid({"token": ["nope"]})
        assert not launch_auth.query_token_valid({})
        assert not launch_auth.query_token_valid({"token": [""]})


class TestResolveBindHost:
    def test_default_loopback(self, isolated_token):
        assert resolve_bind_host() == "127.0.0.1"
        assert resolve_bind_host(None) == "127.0.0.1"

    def test_env_beats_default(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.HOST_ENV, "0.0.0.0")
        assert resolve_bind_host() == "0.0.0.0"

    def test_explicit_beats_env(self, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.HOST_ENV, "0.0.0.0")
        assert resolve_bind_host("192.168.1.10") == "192.168.1.10"


class TestHttpGate:
    """HTTP 层集成：真实 ThreadingHTTPServer + 鉴权门。"""

    def test_local_api_passes_without_side_effects(
            self, http_server, isolated_token):
        code, _, data = _request(http_server, "GET", "/api/status")
        assert code == 200
        assert json.loads(data)
        # 本机流量不得触发令牌生成（否则测试/日常运行污染家目录）
        assert not isolated_token.exists()

    def test_local_host_pinning_blocks_rebinding_host(
            self, http_server, isolated_token):
        code, _, _ = _request(
            http_server, "GET", "/api/status",
            headers={"Host": "car.evil:8090"})
        assert code == 401

    def test_local_cross_origin_post_denied(
            self, http_server, isolated_token):
        code, _, _ = _request(
            http_server, "POST", "/api/launch/drive",
            headers={"Host": "127.0.0.1", "Origin": "http://evil.example"})
        assert code == 401

    def test_remote_without_token_gets_json_401(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, _, data = _request(
            http_server, "GET", "/api/status",
            headers={"Host": "127.0.0.1"})
        assert code == 401
        assert json.loads(data)["error"] == "unauthorized"

    def test_remote_page_gets_html_401_without_echoing_token(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, resp, data = _request(
            http_server, "GET", "/?token=guess-me",
            headers={"Host": "127.0.0.1"})
        assert code == 401
        assert "text/html" in (resp.getheader("Content-Type") or "")
        assert b"guess-me" not in data  # 未授权页不得回显任何候选令牌

    def test_remote_ws_handshake_denied(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, _, _ = _request(
            http_server, "GET", "/terminal/ws",
            headers={"Host": "127.0.0.1", "Upgrade": "websocket",
                     "Connection": "Upgrade"})
        assert code == 401

    def test_page_get_with_valid_token_sets_cookie_and_strips_query(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        code, resp, _ = _request(
            http_server, "GET", "/?token=tok-xyz&cmd=ls",
            headers={"Host": "127.0.0.1"})
        assert code == 302
        assert resp.getheader("Location") == "/?cmd=ls"
        cookie = resp.getheader("Set-Cookie") or ""
        assert f"{launch_auth.COOKIE_NAME}=tok-xyz" in cookie
        assert "HttpOnly" in cookie

    def test_api_get_with_valid_token_does_not_redirect(
            self, http_server, isolated_token, monkeypatch):
        # curl ?token= 直接取数据的用法保持不变（/api/* 不做 302）
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        code, resp, _ = _request(
            http_server, "GET", "/api/status?token=tok-xyz",
            headers={"Host": "127.0.0.1"})
        assert code == 200
        assert resp.getheader("Location") is None

    def test_remote_cookie_followup_passes(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, _, _ = _request(
            http_server, "GET", "/api/status",
            headers={"Host": "127.0.0.1",
                     "Cookie": f"{launch_auth.COOKIE_NAME}=tok-xyz"})
        assert code == 200

    def test_remote_cookie_with_hostile_origin_denied(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.TOKEN_ENV, "tok-xyz")
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, _, _ = _request(
            http_server, "GET", "/api/status",
            headers={"Host": "127.0.0.1", "Origin": "http://evil.example",
                     "Cookie": f"{launch_auth.COOKIE_NAME}=tok-xyz"})
        assert code == 401

    def test_auth_off_opens_remote(
            self, http_server, isolated_token, monkeypatch):
        monkeypatch.setenv(launch_auth.AUTH_ENV, "off")
        monkeypatch.setattr(launch_auth, "is_local_client", lambda addr: False)
        code, _, _ = _request(
            http_server, "GET", "/api/status", headers={"Host": "127.0.0.1"})
        assert code == 200
