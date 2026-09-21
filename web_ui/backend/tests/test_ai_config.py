"""AI 配置（#403）后端路由契约测试。"""
import base64
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routers import ai_config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把配置持久化重定向到临时目录，避免写进真实 ~/.donkeycar。"""
    monkeypatch.setattr(ai_config, "_config_path", lambda: str(tmp_path / "ai_config.json"))
    ai_config._pending_device_codes.clear()
    app = FastAPI()
    app.include_router(ai_config.router, prefix="/api/ai-config")
    return TestClient(app)


def _raw_state(tmp_path):
    with open(tmp_path / "ai_config.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_config_path_is_local_only_home_dir():
    path = ai_config._config_path()
    assert path == os.path.join(os.path.expanduser("~"), ".donkeycar", "ai_config.json")
    # 绝不写入仓库目录
    assert not os.path.abspath(path).startswith(str(BACKEND_DIR) + os.sep)


def test_save_state_creates_directory(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "ai_config.json"
    monkeypatch.setattr(ai_config, "_config_path", lambda: str(nested))
    ai_config._save_state(ai_config._default_state())
    assert nested.exists()


def test_list_providers_returns_presets(client):
    resp = client.get("/api/ai-config/providers")
    assert resp.status_code == 200
    payload = resp.json()
    providers = {p["id"]: p for p in payload["providers"]}
    assert set(providers.keys()) == {"zhipu", "codex", "anthropic", "moonshot", "qwen", "deepseek"}
    assert providers["zhipu"]["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert providers["deepseek"]["base_url"] == "https://api.deepseek.com/v1"
    assert providers["codex"]["oauth"] is True
    assert providers["anthropic"]["api_format"] == "anthropic"
    assert payload["active_provider"] is None


def test_upsert_account_creates_and_masks_key(client, tmp_path):
    secret = "sk-abcdefghijklmnop1234567890"
    resp = client.post("/api/ai-config/providers/deepseek", json={"name": "我的 Key", "api_key": secret})
    assert resp.status_code == 200
    account = resp.json()["account"]
    assert account["has_api_key"] is True
    assert account["api_key_masked"] == "sk-***7890"
    assert secret not in json.dumps(resp.json())

    # 列表接口同样只返回掩码，绝不含明文
    listing = client.get("/api/ai-config/providers").json()
    assert secret not in json.dumps(listing)
    deepseek = next(p for p in listing["providers"] if p["id"] == "deepseek")
    assert deepseek["accounts"][0]["api_key_masked"] == "sk-***7890"
    assert deepseek["accounts"][0]["has_api_key"] is True

    # 落盘文件确实保存了明文（本地-only，绝不入库），且目录结构正确
    raw = _raw_state(tmp_path)
    assert raw["accounts"]["deepseek"][0]["api_key"] == secret


def test_upsert_account_updates_and_clears(client):
    created = client.post("/api/ai-config/providers/zhipu", json={"name": "A", "api_key": "sk-abcdefgh1234"}).json()["account"]
    account_id = created["id"]

    updated = client.post("/api/ai-config/providers/zhipu", json={"account_id": account_id, "name": "B", "api_key": ""})
    assert updated.status_code == 200
    account = updated.json()["account"]
    assert account["name"] == "B"
    assert account["has_api_key"] is False
    assert account["api_key_masked"] is None


def test_set_active_switches_provider(client):
    client.post("/api/ai-config/providers/deepseek", json={"name": "d", "api_key": "sk-abcdefgh1234"})
    resp = client.post("/api/ai-config/providers/deepseek/active", json={})
    assert resp.status_code == 200
    assert resp.json()["active_provider"] == "deepseek"
    assert resp.json()["configured"] is True

    active = client.get("/api/ai-config/active").json()
    assert active["active_provider"] == "deepseek"
    assert active["model"] == "deepseek-chat"
    assert active["configured"] is True

    # 未配置凭据时 configured=False
    client.post("/api/ai-config/providers/qwen/active", json={})
    active = client.get("/api/ai-config/active").json()
    assert active["active_provider"] == "qwen"
    assert active["configured"] is False


def test_custom_provider_crud(client):
    resp = client.post("/api/ai-config/custom", json={"name": "本地 Ollama", "base_url": "http://127.0.0.1:11434/v1", "models": ["llama3"]})
    assert resp.status_code == 200
    provider_id = resp.json()["provider_id"]
    assert provider_id == "ollama"

    listing = client.get("/api/ai-config/providers").json()
    custom = next(p for p in listing["providers"] if p["id"] == provider_id)
    assert custom["custom"] is True
    assert custom["base_url"] == "http://127.0.0.1:11434/v1"
    assert custom["default_models"] == ["llama3"]

    deleted = client.delete(f"/api/ai-config/custom/{provider_id}")
    assert deleted.status_code == 200
    listing = client.get("/api/ai-config/providers").json()
    assert all(p["id"] != provider_id for p in listing["providers"])


def test_multi_account_and_delete_account(client):
    a1 = client.post("/api/ai-config/providers/deepseek", json={"name": "一号", "api_key": "sk-aaaaaaaaaaaa1111"}).json()["account"]
    a2 = client.post("/api/ai-config/providers/deepseek", json={"name": "二号", "api_key": "sk-bbbbbbbbbbbb2222"}).json()["account"]
    assert a1["id"] != a2["id"]

    listing = client.get("/api/ai-config/providers").json()
    deepseek = next(p for p in listing["providers"] if p["id"] == "deepseek")
    assert len(deepseek["accounts"]) == 2

    # 删除后剩余一个
    client.delete(f"/api/ai-config/providers/deepseek/accounts/{a1['id']}")
    listing = client.get("/api/ai-config/providers").json()
    deepseek = next(p for p in listing["providers"] if p["id"] == "deepseek")
    assert len(deepseek["accounts"]) == 1
    assert deepseek["accounts"][0]["id"] == a2["id"]


def test_oauth_device_code_flow(client, monkeypatch, tmp_path):
    """Codex 设备码登录：发起 -> 轮询 -> 换 token -> 保存账号（token 不进响应）。"""
    def fake_json_post(url, data, headers, timeout):
        if "usercode" in url:
            return 200, {"device_auth_id": "dev-1", "user_code": "ABCD-1234", "expires_in": 900, "interval": 5}
        if "deviceauth/token" in url:
            return 200, {"authorization_code": "authcode-1", "code_verifier": "verifier-1"}
        raise AssertionError(f"unexpected url {url}")

    def fake_form_post(url, form, headers, timeout):
        assert url.endswith("/oauth/token")
        payload = {"chatgpt_account_id": "acc-123"}
        id_token = "h." + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=") + ".sig"
        return 200, {"access_token": "at-secret", "refresh_token": "rt-secret", "id_token": id_token}

    monkeypatch.setattr(ai_config, "_http_json_post", fake_json_post)
    monkeypatch.setattr(ai_config, "_http_form_post", fake_form_post)

    start = client.post("/api/ai-config/oauth/device-code", json={"provider_id": "codex"})
    assert start.status_code == 200
    assert start.json()["user_code"] == "ABCD-1234"
    assert start.json()["verification_uri"] == "https://auth.openai.com/codex/device"
    device_code = start.json()["device_code"]

    poll = client.post("/api/ai-config/oauth/poll", json={"device_code": device_code})
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "success"
    assert body["account"]["oauth_connected"] is True
    assert "rt-secret" not in json.dumps(body)
    assert "at-secret" not in json.dumps(body)

    # 持久化的账号 token 只在本地文件里
    raw = _raw_state(tmp_path)
    codex_account = raw["accounts"]["codex"][0]
    assert codex_account["refresh_token"] == "rt-secret"
    assert codex_account["access_token"] == "at-secret"
    assert codex_account["id"] == "acc-123"
    assert raw["active_provider"] == "codex"


def test_oauth_device_code_pending(client, monkeypatch):
    """用户尚未完成授权（403）时返回 pending。"""
    def fake_json_post(url, data, headers, timeout):
        if "usercode" in url:
            return 200, {"device_auth_id": "dev-2", "user_code": "WXYZ-9876", "expires_in": 900, "interval": 5}
        if "deviceauth/token" in url:
            return 403, {}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(ai_config, "_http_json_post", fake_json_post)

    start = client.post("/api/ai-config/oauth/device-code", json={"provider_id": "codex"}).json()
    poll = client.post("/api/ai-config/oauth/poll", json={"device_code": start["device_code"]})
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending"


def test_oauth_only_codex_supported(client):
    resp = client.post("/api/ai-config/oauth/device-code", json={"provider_id": "deepseek"})
    assert resp.status_code == 400


def test_test_endpoint_uses_active_credentials(client, monkeypatch):
    client.post("/api/ai-config/providers/deepseek", json={"name": "d", "api_key": "sk-abcdefgh1234"})
    client.post("/api/ai-config/providers/deepseek/active", json={})

    captured = {}

    def fake_json_post(url, data, headers, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return 200, {"choices": []}

    monkeypatch.setattr(ai_config, "_http_json_post", fake_json_post)
    resp = client.post("/api/ai-config/test", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-abcdefgh1234"
    assert captured["data"]["model"] == "deepseek-chat"

