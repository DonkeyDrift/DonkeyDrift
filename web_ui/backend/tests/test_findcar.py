"""findcar 一键找车模块测试：配置接口、心跳上报、心跳循环与路由契约。

去 token 公开上报版：配置不再有 token 字段，上报 body 也不带 token。
"""
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
    assert cfg["enabled"] is False
    assert cfg["interval_seconds"] == 150
    # 去 token 后不再有任何 token 字段
    assert "token" not in cfg


def test_config_round_trip_without_token(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/findcar/config",
        json={
            "url": "https://find-dkc.pages.dev/",
            "enabled": True,
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 200
    cfg = response.json()["config"]
    assert cfg["url"] == "https://find-dkc.pages.dev/"
    assert cfg["enabled"] is True
    assert cfg["interval_seconds"] == 60
    assert "token" not in cfg

    raw = json.loads((tmp_path / "findcar.json").read_text(encoding="utf-8"))
    assert "token" not in raw


def test_post_without_interval_keeps_existing(monkeypatch, tmp_path):
    client, _, _ = make_client(monkeypatch, tmp_path)

    client.post(
        "/api/findcar/config",
        json={"url": "https://find-dkc.pages.dev/", "enabled": True, "interval_seconds": 90},
    )
    response = client.post(
        "/api/findcar/config",
        json={"url": "https://find-dkc.pages.dev/", "enabled": True},
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
        "enabled": False,
        "interval_seconds": 150,
    }


def test_legacy_token_field_is_ignored_on_load(monkeypatch, tmp_path):
    """旧配置里可能残留 token 字段，加载时应被忽略且不影响解析。"""
    client, findcar_mod, _ = make_client(monkeypatch, tmp_path)
    (tmp_path / "findcar.json").write_text(
        json.dumps(
            {
                "url": "https://find-dkc.pages.dev/",
                "token": "legacy-secret",
                "enabled": True,
                "interval_seconds": 120,
            }
        ),
        encoding="utf-8",
    )

    cfg = findcar_mod.load_config()
    assert cfg.url == "https://find-dkc.pages.dev/"
    assert cfg.enabled is True
    assert cfg.interval_seconds == 120
    assert not hasattr(cfg, "token")

    response = client.get("/api/findcar/config")
    assert response.status_code == 200
    assert "token" not in response.json()["config"]


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
        url="https://find-dkc.pages.dev/", enabled=True
    )
    result = findcar_mod.report_once(cfg)

    assert result is True
    req = captured["req"]
    assert req.full_url == "https://find-dkc.pages.dev/report"
    assert req.get_method() == "POST"
    assert captured["timeout"] == 8
    content_type = next(
        (value for key, value in req.headers.items() if key.lower() == "content-type"),
        None,
    )
    assert content_type == "application/json"

    body = json.loads(req.data.decode("utf-8"))
    hostname = socket.gethostname()
    assert body["device_id"] == hostname
    assert body["type"] == "dd"
    assert body["lan_ip"] == "192.168.3.10"
    assert body["port"] == os.environ.get("DRIVE_WEB_PORT", "8000")
    assert body["hostname"] == hostname
    assert body["version"] == getattr(findcar_mod.donkeycar, "__version__", "")
    # 默认心跳显式带上在线状态；离线标记由 report_offline 发
    assert body["state"] == "online"
    # 主机身份字段：网页「类型」列显示型号、悬停显示系统
    assert "model" in body and "os" in body
    # 去 token：body 不含 token
    assert "token" not in body
    # 协议要求字段全为字符串
    assert all(isinstance(value, str) for value in body.values())


def test_report_once_returns_false_on_urlerror(monkeypatch, caplog):
    import findcar as findcar_mod

    def raise_urlopen(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(findcar_mod.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setattr(findcar_mod, "detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar_mod.FindCarConfig(
        url="https://find-dkc.pages.dev/", enabled=True
    )
    with caplog.at_level(logging.WARNING, logger="findcar"):
        result = findcar_mod.report_once(cfg)

    assert result is False


def test_report_once_empty_url_returns_false(monkeypatch, caplog):
    import findcar as findcar_mod

    result = findcar_mod.report_once(
        findcar_mod.FindCarConfig(url="", enabled=True)
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
        url="https://find-dkc.pages.dev/", enabled=True, interval_seconds=1
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
        url="https://find-dkc.pages.dev/", enabled=True, interval_seconds=1
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

    cfg = findcar_mod.FindCarConfig(url="", enabled=False, interval_seconds=1)
    asyncio.run(findcar_mod.heartbeat_loop(cfg))

    assert reported == []


# ---------------------------------------------------------------------------
# start_heartbeat
# ---------------------------------------------------------------------------


def test_start_heartbeat_returns_none_when_not_configured(monkeypatch, tmp_path):
    import findcar as findcar_mod

    monkeypatch.setattr(findcar_mod, "CONFIG_PATH", tmp_path / "nonexistent.json")

    assert findcar_mod.start_heartbeat() is None


def test_start_heartbeat_returns_none_when_disabled(monkeypatch, tmp_path):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "load_config",
        lambda: findcar_mod.FindCarConfig(
            url="https://find-dkc.pages.dev/", enabled=False
        ),
    )

    assert findcar_mod.start_heartbeat() is None


def test_start_heartbeat_returns_none_when_url_missing(monkeypatch, tmp_path):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "load_config",
        lambda: findcar_mod.FindCarConfig(url="", enabled=True),
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
            url="https://find-dkc.pages.dev/", enabled=True, interval_seconds=300
        ),
    )

    async def run():
        task = findcar_mod.start_heartbeat()
        assert isinstance(task, asyncio.Task)
        await asyncio.gather(task)
        return task

    task = asyncio.run(run())
    assert task.done()


# ---------------------------------------------------------------------------
# 主机身份（型号 / 系统）——网页「类型」列显示用
# ---------------------------------------------------------------------------


def test_machine_model_uses_dmi_product_name(monkeypatch):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "_read_dmi",
        lambda field: {
            "product_name": "ADL-N",
            "sys_vendor": "",
            "board_name": "ADL-N",
        }.get(field, ""),
    )

    assert findcar_mod._machine_model() == "ADL-N"


def test_machine_model_prefixes_vendor_when_not_in_product(monkeypatch):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "_read_dmi",
        lambda field: {"product_name": "82RN", "sys_vendor": "LENOVO"}.get(field, ""),
    )

    assert findcar_mod._machine_model() == "LENOVO 82RN"


def test_machine_model_keeps_product_when_vendor_already_included(monkeypatch):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "_read_dmi",
        lambda field: {
            "product_name": "LENOVO ThinkPad X1",
            "sys_vendor": "LENOVO",
        }.get(field, ""),
    )

    assert findcar_mod._machine_model() == "LENOVO ThinkPad X1"


def test_machine_model_falls_back_to_board_name(monkeypatch):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "_read_dmi",
        lambda field: {"board_name": "ADL-N"}.get(field, ""),
    )

    assert findcar_mod._machine_model() == "ADL-N"


def test_machine_model_empty_when_dmi_unavailable(monkeypatch):
    """DMI 读不到（非 x86 / 无权限）时不抛异常，返回空串，网页再退回主机名。"""
    import findcar as findcar_mod

    monkeypatch.setattr(findcar_mod, "_read_dmi", lambda field: "")

    assert findcar_mod._machine_model() == ""


def test_os_name_reads_pretty_name(monkeypatch, tmp_path):
    import findcar as findcar_mod

    os_release = tmp_path / "os-release"
    os_release.write_text(
        'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04 LTS"\nVERSION_ID="26.04"\n',
        encoding="utf-8",
    )

    assert findcar_mod._os_name(str(os_release)) == "Ubuntu 26.04 LTS"


def test_os_name_missing_file_returns_empty(tmp_path):
    import findcar as findcar_mod

    assert findcar_mod._os_name(str(tmp_path / "nope")) == ""


# ---------------------------------------------------------------------------
# 下线标记（优雅退出时立即显示「离线」）
# ---------------------------------------------------------------------------


def test_report_offline_posts_offline_state_with_short_timeout(monkeypatch):
    import findcar as findcar_mod

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(findcar_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(findcar_mod, "detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar_mod.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)

    assert findcar_mod.report_offline(cfg) is True
    assert captured["body"]["state"] == "offline"
    assert captured["timeout"] == findcar_mod.OFFLINE_TIMEOUT_SECONDS


def test_report_offline_returns_false_when_not_configured(monkeypatch):
    import findcar as findcar_mod

    def fail_urlopen(req, timeout=None):  # pragma: no cover - 不应被调用
        raise AssertionError("未配置时不应发起请求")

    monkeypatch.setattr(findcar_mod.urllib.request, "urlopen", fail_urlopen)

    assert findcar_mod.report_offline(findcar_mod.FindCarConfig(url="", enabled=False)) is False


def test_report_offline_swallows_errors(monkeypatch):
    import findcar as findcar_mod

    monkeypatch.setattr(
        findcar_mod,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert findcar_mod.report_offline() is False


def test_stop_heartbeat_sends_offline_marker(monkeypatch):
    import asyncio

    import findcar as findcar_mod

    calls = []
    monkeypatch.setattr(findcar_mod, "report_offline", lambda: calls.append(1) or True)

    asyncio.run(findcar_mod.stop_heartbeat())

    assert calls == [1]


def test_stop_heartbeat_swallows_errors(monkeypatch):
    import asyncio

    import findcar as findcar_mod

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(findcar_mod, "report_offline", boom)

    asyncio.run(findcar_mod.stop_heartbeat())  # 不抛异常


def test_main_lifespan_wires_findcar_offline_marker():
    """Starlette 1.x 下 on_event 不再触发，下线标记必须挂在 lifespan 里。"""
    source = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")

    assert "findcar.stop_heartbeat()" in source
