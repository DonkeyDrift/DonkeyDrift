"""findcar 一键找车模块测试：配置接口、心跳上报、心跳循环与路由契约。"""
import importlib
import json
import logging
import os
import socket
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import collect_route_paths

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client(monkeypatch, tmp_path):
    import findcar as findcar_mod
    import routers.findcar as router_mod

    monkeypatch.setattr(findcar_mod, "CONFIG_PATH", tmp_path / "findcar.json")
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api/findcar")
    return TestClient(app), findcar_mod, router_mod


def _token_masked(token: str) -> str:
    return token[:2] + "*" * (len(token) - 4) + token[-2:]


# ---------------------------------------------------------------------------
# 路由契约
# ---------------------------------------------------------------------------


def test_main_registers_findcar_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/findcar/config" in routes


# ---------------------------------------------------------------------------
# 配置接口
# ---------------------------------------------------------------------------


def test_get_config_returns_defaults(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)

    response = client.get("/api/findcar/config")

    assert response.status_code == 200
    cfg = response.json()["config"]
    assert cfg["url"] == ""
    assert cfg["token"] == ""
    assert cfg["enabled"] is False
    assert cfg["interval_seconds"] == 300


def test_config_round_trip_masks_token(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)
    token = "secret-token-123"

    response = client.post(
        "/api/findcar/config",
        json={
            "url": "https://worker.example.com/",
            "token": token,
            "enabled": True,
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 200
    cfg = response.json()["config"]
    assert cfg["url"] == "https://worker.example.com/"
    assert cfg["token"] == _token_masked(token)
    assert cfg["enabled"] is True
    assert cfg["interval_seconds"] == 60

    # 配置文件里保存的是完整 token（脱敏只发生在 API 返回层）
    raw = json.loads((tmp_path / "findcar.json").read_text(encoding="utf-8"))
    assert raw["token"] == token

    # GET 同样返回脱敏值，绝不回传完整 token
    loaded = client.get("/api/findcar/config").json()["config"]
    assert loaded["token"] == cfg["token"]
    assert token not in loaded["token"]


def test_post_without_interval_keeps_existing(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)

    client.post(
        "/api/findcar/config",
        json={"url": "https://w/", "token": "tok12345", "enabled": True, "interval_seconds": 90},
    )
    response = client.post(
        "/api/findcar/config",
        json={"url": "https://w2/", "token": "tok12345", "enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["config"]["interval_seconds"] == 90


def test_corrupted_config_file_falls_back_to_defaults(monkeypatch, tmp_path):
    client, findcar_mod, _ = make_client(monkeypatch, tmp_path)
    (tmp_path / "findcar.json").write_text("{bad json", encoding="utf-8")

    response = client.get("/api/findcar/config")

    assert response.status_code == 200
    assert response.json()["config"] == {
        "url": "",
        "token": "",
        "enabled": False,
        "interval_seconds": 300,
    }


# ---------------------------------------------------------------------------
# mask_token
# ---------------------------------------------------------------------------


def test_mask_token():
    import findcar as findcar_mod

    assert findcar_mod.mask_token("") == ""
    assert findcar_mod.mask_token("ab") == "**"
    assert findcar_mod.mask_token("abc") == "***"
    assert findcar_mod.mask_token("abcd") == "****"
    assert findcar_mod.mask_token("secret-token-123") == _token_masked("secret-token-123")


# ---------------------------------------------------------------------------
# report_once
# ---------------------------------------------------------------------------


class _FakeResponse:
    def read(self):
        return b"ok"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_report_once_posts_json_and_returns_true(monkeypatch):
    import findcar as findcar_mod

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(findcar_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(findcar_mod, "detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar_mod.FindCarConfig(
        url="https://worker.example.com/", token="secret-token-123", enabled=True
    )
    result = findcar_mod.report_once(cfg)

    assert result is True
    req = captured["req"]
    assert req.full_url == "https://worker.example.com/report"
    assert req.get_method() == "POST"
    assert captured["timeout"] == 8
    content_type = next(
        (value for key, value in req.headers.items() if key.lower() == "content-type"),
        None,
    )
    assert content_type == "application/json"

    body = json.loads(req.data.decode("utf-8"))
    hostname = socket.gethostname()
    assert body["token"] == "secret-token-123"
    assert body["device_id"] == hostname
    assert body["type"] == "dd"
    assert body["lan_ip"] == "192.168.3.10"
    assert body["port"] == os.environ.get("DRIVE_WEB_PORT", "8000")
    assert body["hostname"] == hostname
    assert body["version"] == getattr(findcar_mod.donkeycar, "__version__", "")
    # 协议要求字段全为字符串
    assert all(isinstance(value, str) for value in body.values())


def test_report_once_returns_false_and_never_logs_token(monkeypatch, caplog):
    import findcar as findcar_mod

    def raise_urlopen(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(findcar_mod.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setattr(findcar_mod, "detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar_mod.FindCarConfig(
        url="https://worker.example.com/", token="secret-token-123", enabled=True
    )
    with caplog.at_level(logging.WARNING, logger="findcar"):
        result = findcar_mod.report_once(cfg)

    assert result is False
    assert "secret-token-123" not in caplog.text


def test_report_once_empty_url_returns_false(monkeypatch, caplog):
    import findcar as findcar_mod

    result = findcar_mod.report_once(
        findcar_mod.FindCarConfig(url="", token="t", enabled=True)
    )

    assert result is False


# ---------------------------------------------------------------------------
# heartbeat_loop
# ---------------------------------------------------------------------------


class _StopLoop(Exception):
    pass


def test_heartbeat_loop_reports_repeatedly(monkeypatch):
    import asyncio

    import findcar as findcar_mod

    calls = []

    def fake_report_once(cfg):
        calls.append(cfg)
        return True

    monkeypatch.setattr(findcar_mod, "report_once", fake_report_once)

    sleeps = 0

    async def fake_sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 3:
            raise _StopLoop()

    monkeypatch.setattr(findcar_mod.asyncio, "sleep", fake_sleep)

    cfg = findcar_mod.FindCarConfig(
        url="https://worker.example.com/", token="t", enabled=True, interval_seconds=1
    )

    with pytest.raises(_StopLoop):
        asyncio.run(findcar_mod.heartbeat_loop(cfg))

    assert len(calls) == 3
    assert sleeps == 3


def test_heartbeat_loop_survives_report_exception(monkeypatch):
    import asyncio

    import findcar as findcar_mod

    calls = []

    def flaky_report(cfg):
        calls.append(cfg)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(findcar_mod, "report_once", flaky_report)

    sleeps = 0

    async def fake_sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise _StopLoop()

    monkeypatch.setattr(findcar_mod.asyncio, "sleep", fake_sleep)

    cfg = findcar_mod.FindCarConfig(
        url="https://worker.example.com/", token="t", enabled=True, interval_seconds=1
    )

    with pytest.raises(_StopLoop):
        asyncio.run(findcar_mod.heartbeat_loop(cfg))

    # 首轮抛异常未中断循环，第二轮仍继续上报
    assert len(calls) == 2


def test_heartbeat_loop_disabled_returns_immediately(monkeypatch):
    import asyncio

    import findcar as findcar_mod

    reported = []
    monkeypatch.setattr(
        findcar_mod,
        "report_once",
        lambda cfg: reported.append(cfg) or True,
    )

    cfg = findcar_mod.FindCarConfig(url="", token="", enabled=False, interval_seconds=1)
    asyncio.run(findcar_mod.heartbeat_loop(cfg))

    assert reported == []


# ---------------------------------------------------------------------------
# start_heartbeat
# ---------------------------------------------------------------------------


def test_start_heartbeat_returns_none_when_not_configured(monkeypatch, tmp_path):
    import findcar as findcar_mod

    monkeypatch.setattr(findcar_mod, "CONFIG_PATH", tmp_path / "nonexistent.json")

    assert findcar_mod.start_heartbeat() is None


def test_start_heartbeat_returns_none_when_token_missing(monkeypatch, tmp_path):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "load_config",
        lambda: findcar_mod.FindCarConfig(
            url="https://worker.example.com/", token="", enabled=True
        ),
    )

    assert findcar_mod.start_heartbeat() is None


def test_start_heartbeat_returns_task_when_configured(monkeypatch, tmp_path):
    import asyncio

    import findcar as findcar_mod

    async def fake_loop(cfg):
        return None

    monkeypatch.setattr(findcar_mod, "heartbeat_loop", fake_loop)
    monkeypatch.setattr(
        findcar_mod,
        "load_config",
        lambda: findcar_mod.FindCarConfig(
            url="https://worker.example.com/", token="t", enabled=True, interval_seconds=300
        ),
    )

    async def run():
        task = findcar_mod.start_heartbeat()
        assert isinstance(task, asyncio.Task)
        await asyncio.gather(task)
        return task

    task = asyncio.run(run())
    assert task.done()
