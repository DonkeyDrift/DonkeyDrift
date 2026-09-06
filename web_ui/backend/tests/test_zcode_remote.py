"""ZCode 远控链接端点（routers/zcode_remote.py）的契约测试。

覆盖：凭证解密（与桌面端 createCredentialCipherProvider 同构的
aes-256-gcm/enc:v1 格式）、本地凭证现拼链接、t 刷新、端点编排
（CDP 优先、拉起桌面端、凭证兜底、无凭证 409）。
"""

import base64
import hashlib
import importlib
import json
import time
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
