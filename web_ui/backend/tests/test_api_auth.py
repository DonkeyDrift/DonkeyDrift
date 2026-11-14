# -*- coding: utf-8 -*-
"""Web 后端访问控制（P0 安全补强，2026-10-12）测试。

覆盖 web_ui/backend/auth.py 策略、main.py 鉴权中间件与 routers/drive.py
的 WS 握手门：
- 令牌生命周期：DRIVE_API_TOKEN 优先、0600 落盘、幂等复用
- 判定矩阵：TestClient/回环免令牌、跨站 Origin 拒绝、DNS rebinding
  （Host 钳制）、显式令牌与 Cookie 通行规则、DRIVE_API_AUTH=off 全放行
- HTTP 层：远程样式 401（JSON / HTML，不回显候选令牌）、页面 GET
  ?token= 种 Cookie + 302 去查询串、/api/* 不跳转保 curl、OPTIONS 放行
- WS 层：远程无令牌握手被拒（close 先于 accept）、带 ?token= 通过

令牌读写打桩到 tmp_path，不触碰真实 ~/.donkeycar/drive_api.token。
"""

import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import auth as web_auth
import main


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture()
def isolated_token(monkeypatch, tmp_path):
    """令牌文件/环境打桩：文件指向 tmp_path，清掉环境开关。"""
    monkeypatch.delenv(web_auth.TOKEN_ENV, raising=False)
    monkeypatch.delenv(web_auth.AUTH_ENV, raising=False)
    token_file = tmp_path / "drive_api.token"
    monkeypatch.setattr(web_auth, "TOKEN_FILE", token_file)
    return token_file


def _as_remote(monkeypatch):
    """把 TCP 对端判定打成远程设备（TestClient 本身呈现 testclient 回环）。"""
    monkeypatch.setattr(web_auth, "is_local_client", lambda addr: False)


class TestTokenLifecycle:
    def test_env_wins_and_no_file_written(self, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "env-token-123")
        assert web_auth.load_or_create_token() == "env-token-123"
        assert not isolated_token.exists()

    def test_generates_persists_0600_and_idempotent(self, isolated_token):
        token = web_auth.load_or_create_token()
        assert len(token) >= 20
        assert isolated_token.exists()
        assert stat.S_IMODE(isolated_token.stat().st_mode) == 0o600
        assert web_auth.load_or_create_token() == token

    def test_kill_switch_values(self, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.AUTH_ENV, "off")
        assert not web_auth.auth_enabled()

    def test_enabled_by_default(self, isolated_token):
        assert web_auth.auth_enabled()


class TestJudgementMatrix:
    def test_local_plain_allowed(self, isolated_token):
        headers = {"Host": "testserver"}
        assert web_auth.is_authorized(headers, {}, ("127.0.0.1", 50000))

    def test_local_cross_origin_denied(self, isolated_token):
        headers = {"Host": "testserver", "Origin": "http://evil.example"}
        assert not web_auth.is_authorized(
            headers, {}, ("127.0.0.1", 50000))

    def test_dns_rebinding_denied_even_on_loopback(self, isolated_token):
        # 恶意域名解析到车机：Origin/Host 同为攻击者域名也过不了 Host 钳制
        headers = {"Host": "car.evil:8090", "Origin": "http://car.evil:8090"}
        assert not web_auth.is_authorized(
            headers, {}, ("127.0.0.1", 50000))

    def test_explicit_token_paths(self, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        remote = ("192.168.1.7", 50000)
        for headers in ({"Authorization": "Bearer tok-xyz"},
                        {"X-Donkey-Token": "tok-xyz"}):
            assert web_auth.is_authorized(headers, {}, remote), headers
        assert web_auth.is_authorized({}, {"token": ["tok-xyz"]}, remote)

    def test_cookie_passage_requires_clean_origin(
            self, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        cookie = {"Cookie": f"{web_auth.COOKIE_NAME}=tok-xyz",
                  "Host": "testserver"}
        assert web_auth.is_authorized(cookie, {}, ("192.168.1.7", 50000))
        hostile = dict(cookie, Origin="http://evil.example")
        assert not web_auth.is_authorized(
            hostile, {}, ("192.168.1.7", 50000))


class TestHttpGate:
    def test_local_request_passes(self, client, isolated_token):
        # TestClient（testclient/testserver）走免令牌路径：可达路由而非 401
        resp = client.get("/api/config/version")
        assert resp.status_code != 401

    def test_local_request_has_no_token_file_side_effect(
            self, client, isolated_token):
        client.get("/api/config/version")
        assert not isolated_token.exists()

    def test_remote_api_without_token_gets_json_401(
            self, client, isolated_token, monkeypatch):
        _as_remote(monkeypatch)
        resp = client.get("/api/config/version")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_remote_page_gets_html_401_without_echoing_token(
            self, client, isolated_token, monkeypatch):
        _as_remote(monkeypatch)
        resp = client.get("/?token=guess-me")
        assert resp.status_code == 401
        assert "text/html" in resp.headers.get("content-type", "")
        assert "guess-me" not in resp.text  # 未授权页不得回显任何候选令牌

    def test_page_get_with_valid_token_sets_cookie_and_strips_query(
            self, client, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        resp = client.get("/?token=tok-xyz&cmd=ls", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/?cmd=ls"
        cookie = resp.headers.get("set-cookie", "")
        assert f"{web_auth.COOKIE_NAME}=tok-xyz" in cookie
        assert "HttpOnly" in cookie

    def test_api_get_with_valid_token_does_not_redirect(
            self, client, isolated_token, monkeypatch):
        # curl ?token= 直接取数据的用法保持不变（/api/* 不做 302）
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        resp = client.get("/api/config/version?token=tok-xyz",
                          follow_redirects=False)
        assert resp.status_code != 302
        assert "location" not in resp.headers

    def test_remote_cookie_followup_passes(
            self, client, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        _as_remote(monkeypatch)
        resp = client.get(
            "/api/config/version",
            headers={"Cookie": f"{web_auth.COOKIE_NAME}=tok-xyz"},
            follow_redirects=False)
        assert resp.status_code != 401

    def test_remote_cookie_with_hostile_origin_denied(
            self, client, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        _as_remote(monkeypatch)
        resp = client.get(
            "/api/config/version",
            headers={"Cookie": f"{web_auth.COOKIE_NAME}=tok-xyz",
                     "Origin": "http://evil.example"})
        assert resp.status_code == 401

    def test_options_preflight_passes(self, client, isolated_token,
                                      monkeypatch):
        # CORS 预检不携带凭据/自定义头，卡它只会断跨域调试链路
        _as_remote(monkeypatch)
        resp = client.options("/api/config/version")
        assert resp.status_code != 401

    def test_auth_off_opens_remote(self, client, isolated_token,
                                   monkeypatch):
        monkeypatch.setenv(web_auth.AUTH_ENV, "off")
        _as_remote(monkeypatch)
        resp = client.get("/api/config/version")
        assert resp.status_code != 401


class TestDriveWsGate:
    def test_remote_ws_rejected_without_token(
            self, client, isolated_token, monkeypatch):
        _as_remote(monkeypatch)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/drive/ws?role=client"):
                pass

    def test_remote_ws_passes_with_query_token(
            self, client, isolated_token, monkeypatch):
        monkeypatch.setenv(web_auth.TOKEN_ENV, "tok-xyz")
        _as_remote(monkeypatch)
        with client.websocket_connect(
                "/api/drive/ws?role=client&token=tok-xyz") as ws:
            assert ws is not None

    def test_local_ws_passes_without_token(self, client, isolated_token):
        with client.websocket_connect("/api/drive/ws?role=client") as ws:
            assert ws is not None
