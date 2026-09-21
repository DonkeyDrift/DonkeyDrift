"""ZCode 远控链接端点（routers/zcode_remote.py）的契约测试。

覆盖：凭证解密（与桌面端 createCredentialCipherProvider 同构的
aes-256-gcm/enc:v1 格式）、本地凭证现拼链接、t 刷新、端点编排
（CDP 优先、拉起桌面端、凭证兜底、无凭证 409）。
"""

import asyncio
import base64
import hashlib
import importlib
import json
import sys
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from conftest import collect_route_paths

TEST_SECRET = "test-credential-secret"
TEST_SID = "d_testsid123"
TEST_PASS_HASH = base64.b64encode(b"fake-pass-hash").decode()


def _encrypt(secret: str, plaintext: str) -> str:
    """按桌面端格式加密：enc:v1:<b64u(iv)>.<b64u(tag)>.<b64u(ct)>。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.sha256(secret.encode()).digest()
    iv = b"\x01" * 12
    ct_and_tag = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    ct, tag = ct_and_tag[:-16], ct_and_tag[-16:]
    b64u = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"enc:v1:{b64u(iv)}.{b64u(tag)}.{b64u(ct)}"


@pytest.fixture()
def zcode_store(tmp_path, monkeypatch):
    """搭一套临时 ZCode 数据目录并写入加密凭证，返回目录路径。"""
    monkeypatch.setenv("ZCODE_DATA_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("ZCODE_CREDENTIAL_SECRET", TEST_SECRET)
    v2 = tmp_path / ".zcode" / "v2"
    v2.mkdir(parents=True)
    (v2 / "setting.json").write_text(
        json.dumps({"webRemoteControlExternalRelayDevice": {"deviceSid": TEST_SID}}),
        encoding="utf-8",
    )
    (v2 / "credentials.json").write_text(
        json.dumps({"web-remote-control:external-relay:pass_hash": _encrypt(TEST_SECRET, TEST_PASS_HASH)}),
        encoding="utf-8",
    )
    (v2 / "telemetry-state.json").write_text(
        json.dumps({"deviceMid": "mid-123"}), encoding="utf-8"
    )
    return tmp_path


def test_main_registers_zcode_remote_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/zcode-remote/link" in routes


def test_decrypt_credential_roundtrip(monkeypatch):
    monkeypatch.setenv("ZCODE_CREDENTIAL_SECRET", TEST_SECRET)
    zr = importlib.import_module("routers.zcode_remote")
    assert zr._decrypt_credential(_encrypt(TEST_SECRET, "hello")) == "hello"
    # 非 enc:v1: 前缀按明文原样返回（桌面端 decrypt 同款行为）
    assert zr._decrypt_credential("plain-text") == "plain-text"


def test_refresh_t_replaces_timestamp_and_drops_fragment():
    zr = importlib.import_module("routers.zcode_remote")
    url = "https://zcode.z.ai/remote/v4?sid=S&hash=H&t=1&mid=M#frag"
    out = zr._refresh_t(url)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(out).query)
    assert q["sid"] == ["S"] and q["hash"] == ["H"] and q["mid"] == ["M"]
    assert int(q["t"][0]) > 1_000_000_000_000  # 全新毫秒戳
    assert "#" not in out


def test_mint_link_from_store(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")
    monkeypatch.setattr(zr, "_app_version", lambda: "9.9.9")
    url = zr._mint_link_from_store()
    assert url is not None
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == zr.REMOTE_PAGE_BASE
    assert q["sid"] == [TEST_SID]
    assert q["hash"] == [TEST_PASS_HASH]
    assert q["mid"] == ["mid-123"]
    assert q["app_version"] == ["9.9.9"]
    assert abs(int(q["t"][0]) - int(time.time() * 1000)) < 60_000


def test_mint_link_from_store_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ZCODE_DATA_BASE_DIR", str(tmp_path))
    zr = importlib.import_module("routers.zcode_remote")
    assert zr._mint_link_from_store() is None


def _client():
    main = importlib.import_module("main")
    return TestClient(main.app)


def test_link_endpoint_prefers_cdp_url(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")
    cdp_url = "https://zcode.z.ai/remote/v4?sid=S&hash=H&t=123"

    async def fake_cdp():
        return cdp_url

    monkeypatch.setattr(zr, "_cdp_remote_url", fake_cdp)
    resp = _client().post("/api/zcode-remote/link")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "url": cdp_url}


def test_link_endpoint_store_fallback_when_cdp_down(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")

    async def fake_cdp():
        return None

    monkeypatch.setattr(zr, "_cdp_remote_url", fake_cdp)
    monkeypatch.setattr(zr, "_app_running", lambda: True)  # 不触发拉起
    monkeypatch.setattr(zr, "_app_version", lambda: "")
    resp = _client().post("/api/zcode-remote/link")
    assert resp.status_code == 200
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(resp.json()["url"]).query)
    assert q["sid"] == [TEST_SID]
    assert q["hash"] == [TEST_PASS_HASH]


def test_link_endpoint_409_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setenv("ZCODE_DATA_BASE_DIR", str(tmp_path))
    zr = importlib.import_module("routers.zcode_remote")

    async def fake_cdp():
        return None

    monkeypatch.setattr(zr, "_cdp_remote_url", fake_cdp)
    monkeypatch.setattr(zr, "_app_running", lambda: True)
    resp = _client().post("/api/zcode-remote/link")
    assert resp.status_code == 409
    assert resp.json()["status"] == "error"


# --- CDP 端口选择与持久化（2026-09-08：9222 被外部进程占用导致取不到活链）---


def test_cdp_port_file_roundtrip(zcode_store):
    zr = importlib.import_module("routers.zcode_remote")
    assert zr._stored_cdp_port() is None
    zr._write_cdp_port(9334)
    assert zr._stored_cdp_port() == 9334


def test_cdp_port_file_corrupt_returns_none(zcode_store):
    zr = importlib.import_module("routers.zcode_remote")
    zr._cdp_port_file().write_text("not-json{{{", encoding="utf-8")
    assert zr._stored_cdp_port() is None


def test_current_cdp_port_requires_zcode_ownership(zcode_store, monkeypatch):
    # 端口文件写了 9333，但 9333 被外部进程（如普通 Chrome）占用 → 不认领
    zr = importlib.import_module("routers.zcode_remote")
    zr._write_cdp_port(9333)
    monkeypatch.setattr(zr, "_cdp_port_owned_by_zcode", lambda port: port == 9336)
    assert zr._current_cdp_port() is None


def test_current_cdp_port_falls_back_to_legacy_9222(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")
    monkeypatch.setattr(zr, "_cdp_port_owned_by_zcode", lambda port: port == 9222)
    assert zr._current_cdp_port() == 9222


def test_current_cdp_port_prefers_port_file(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")
    zr._write_cdp_port(9333)
    monkeypatch.setattr(
        zr, "_cdp_port_owned_by_zcode", lambda port: port in (9222, 9333)
    )
    assert zr._current_cdp_port() == 9333


def test_pick_free_cdp_port_skips_busy(zcode_store, monkeypatch):
    zr = importlib.import_module("routers.zcode_remote")
    busy = {9333, 9334}
    monkeypatch.setattr(zr, "_port_bindable", lambda port: port not in busy)
    assert zr._pick_free_cdp_port() == 9335


def test_launch_app_uses_free_port_and_persists(monkeypatch, tmp_path):
    zr = importlib.import_module("routers.zcode_remote")
    monkeypatch.setenv("ZCODE_DATA_BASE_DIR", str(tmp_path))
    calls = []

    class _FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(zr.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(zr, "_pick_free_cdp_port", lambda: 9334)
    zr._launch_app()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == [
        str(zr.ZCODE_APP_BIN),
        "--no-sandbox",
        "--remote-debugging-port=9334",
    ]
    assert kwargs["start_new_session"] is True
    assert zr._stored_cdp_port() == 9334


# --- 会话复用与重启保护（2026-09-08：status="active" 被误判未运行导致强制重启，
# --- 已连接的手机/浏览器端被踢成「桌面端已离线」）---


class _FakeWS:
    """按序回放 CDP evaluate 结果的假 WebSocket。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        reply = self._replies.pop(0)
        return json.dumps(
            {"id": self.sent[-1]["id"], "result": {"result": {"value": reply}}}
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_cdp_env(monkeypatch, replies):
    """注入假 websockets 模块与 CDP 目标页，返回记录了发送内容的 _FakeWS。"""
    zr = importlib.import_module("routers.zcode_remote")
    ws = _FakeWS(replies)
    fake_module = types.SimpleNamespace(connect=lambda url, open_timeout=None: ws)
    monkeypatch.setitem(sys.modules, "websockets", fake_module)
    monkeypatch.setattr(zr, "_current_cdp_port", lambda: 9333)
    monkeypatch.setattr(
        zr,
        "_http_json",
        lambda url, timeout=2.0: [
            {
                "type": "page",
                "url": "file:///zcode-app/renderer/index.html",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9333/dev/page",
            }
        ],
    )
    return zr, ws


def test_cdp_reuses_active_session_without_restart(zcode_store, monkeypatch):
    # v3.8.1 实测：远控在线时 getWebRemoteControlStatus 返回 status="active" + connectUrl。
    # 必须直接复用，绝不能再调 startWebRemoteControl（会把已连接端踢成「桌面端已离线」）
    zr, ws = _fake_cdp_env(
        monkeypatch,
        [
            {
                "status": "active",
                "connectUrl": "https://zcode.z.ai/remote/v4?sid=S&hash=H&t=1",
            }
        ],
    )
    url = asyncio.run(zr._cdp_remote_url())
    assert url is not None
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert q["sid"] == ["S"] and q["hash"] == ["H"]
    assert int(q["t"][0]) > 1  # t 已刷新
    # 只发了 1 条 status 查询，没有 startWebRemoteControl
    assert len(ws.sent) == 1
    assert "startWebRemoteControl" not in ws.sent[0]["params"]["expression"]


def test_cdp_reuses_legacy_running_status(zcode_store, monkeypatch):
    # 旧版桌面端的 status 词表是 "running"，同样按已有会话复用
    zr, ws = _fake_cdp_env(
        monkeypatch,
        [
            {
                "status": "running",
                "connectUrl": "https://zcode.z.ai/remote/v4?sid=S&hash=H&t=1",
            }
        ],
    )
    assert asyncio.run(zr._cdp_remote_url()) is not None
    assert len(ws.sent) == 1


def test_cdp_starts_remote_when_no_connect_url(zcode_store, monkeypatch):
    # 远控确实没开（status dict 但无 connectUrl）才允许 start
    zr, ws = _fake_cdp_env(
        monkeypatch,
        [
            {"status": "disabled"},
            {
                "status": "active",
                "connectUrl": "https://zcode.z.ai/remote/v4?sid=S2&hash=H2&t=2",
            },
        ],
    )
    url = asyncio.run(zr._cdp_remote_url())
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert q["sid"] == ["S2"]
    assert len(ws.sent) == 2
    assert "startWebRemoteControl" in ws.sent[1]["params"]["expression"]


def test_cdp_returns_none_when_status_not_dict(zcode_store, monkeypatch):
    # status 偶发返回 null（如会话启动瞬态）：不得 start，返回 None 走兜底
    zr, ws = _fake_cdp_env(monkeypatch, [None])
    assert asyncio.run(zr._cdp_remote_url()) is None
    assert len(ws.sent) == 1
