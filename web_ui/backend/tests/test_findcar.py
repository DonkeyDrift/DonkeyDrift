"""findcar 一键找车配置接口测试：路由契约与配置读写。

主机心跳上报已迁至常驻 launcher（donkeycar/findcar.py +
donkeycar/launcher/server.py，测试在 tests/test_findcar.py 与
tests/test_launcher_findcar.py）；本文件只覆盖 web 后端保留的配置接口
（/api/findcar/config，读写 ~/.donkeycar_findcar.json，与 launcher 共用）。
去 token 公开上报版：配置不再有 token 字段。
"""
import importlib
import json
import sys
from pathlib import Path

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


def test_main_lifespan_no_longer_wires_findcar_heartbeat():
    """主机心跳由常驻 launcher 上报；后端 lifespan 不再挂 findcar 心跳/下线钩子。"""
    source = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")

    assert "start_heartbeat" not in source
    assert "stop_heartbeat" not in source


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
