# -*- coding: utf-8 -*-
"""DriveApiBridge 访问令牌注入（P0 安全补强，2026-10-12）单元测试。

车端桥接连回 Web 后端须携带令牌（后端对外监听时鉴权门要求）：
- _load_api_token：DRIVE_API_TOKEN 环境变量 > ~/.donkeycar/drive_api.token，
  两者皆无返回 ""（只读绝不生成——令牌由后端生成落盘，防两进程竞态）
- _with_token：令牌拼进 WS URL 查询串并 URL 编码；空令牌原样返回
- _auth_headers：HTTP 调用的 X-Donkey-Token 头
- __init__ 组合形态：server_url 带 ?role=...&token=...，http_api_base 不带
  令牌（令牌走请求头，不进基础 URL）
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from donkeycar.parts.drive_api_bridge import DriveApiBridge


@pytest.fixture()
def token_file(monkeypatch, tmp_path):
    monkeypatch.delenv(DriveApiBridge.API_TOKEN_ENV, raising=False)
    path = tmp_path / "drive_api.token"
    monkeypatch.setattr(DriveApiBridge, "API_TOKEN_FILE", path)
    return path


class TestLoadApiToken:
    def test_env_wins(self, token_file, monkeypatch):
        monkeypatch.setenv(DriveApiBridge.API_TOKEN_ENV, "env-tok")
        token_file.write_text("file-tok", encoding="utf-8")
        assert DriveApiBridge._load_api_token() == "env-tok"

    def test_file_fallback(self, token_file):
        token_file.write_text("file-tok\n", encoding="utf-8")
        assert DriveApiBridge._load_api_token() == "file-tok"

    def test_missing_returns_empty_and_creates_nothing(self, token_file):
        assert DriveApiBridge._load_api_token() == ""
        assert not token_file.exists()


class TestWithToken:
    def test_appends_query_token(self):
        url = DriveApiBridge._with_token("ws://h:8000/api/drive/ws", "tok-1")
        assert parse_qs(urlsplit(url).query)["token"] == ["tok-1"]

    def test_token_url_encoded(self):
        url = DriveApiBridge._with_token("ws://h:8000/api/drive/ws", "a b/c&d")
        assert parse_qs(urlsplit(url).query)["token"] == ["a b/c&d"]

    def test_empty_token_keeps_url(self):
        assert DriveApiBridge._with_token("ws://h/ws?x=1", "") == "ws://h/ws?x=1"

    def test_appends_with_ampersand_when_query_exists(self):
        url = DriveApiBridge._with_token("ws://h/ws?role=car", "tok-1")
        assert urlsplit(url).query == "role=car&token=tok-1"


class TestAuthHeaders:
    def test_headers_present_with_token(self):
        bridge = SimpleNamespace(api_token="tok-1")
        assert DriveApiBridge._auth_headers(bridge) == \
            {"X-Donkey-Token": "tok-1"}

    def test_headers_empty_without_token(self):
        bridge = SimpleNamespace(api_token="")
        assert DriveApiBridge._auth_headers(bridge) == {}


class TestInitWiring:
    def test_server_url_carries_role_and_token(self, token_file, monkeypatch):
        monkeypatch.setenv(DriveApiBridge.API_TOKEN_ENV, "tok-1")
        bridge = DriveApiBridge(
            server_url="ws://192.168.1.10:8000/api/drive/ws",
            role="car", auto_start=False, webrtc_enabled=False)
        query = parse_qs(urlsplit(bridge.server_url).query)
        assert query["role"] == ["car"]
        assert query["token"] == ["tok-1"]
        # HTTP API 基址不带查询串令牌（令牌走 X-Donkey-Token 请求头）
        base_parts = urlsplit(bridge.http_api_base)
        assert "token" not in parse_qs(base_parts.query)
        assert bridge._auth_headers() == {"X-Donkey-Token": "tok-1"}

    def test_server_url_without_token_keeps_clean_query(
            self, token_file, monkeypatch):
        bridge = DriveApiBridge(
            server_url="ws://127.0.0.1:8000/api/drive/ws",
            role="client", auto_start=False, webrtc_enabled=False)
        assert urlsplit(bridge.server_url).query == "role=client"
        assert bridge._auth_headers() == {}
