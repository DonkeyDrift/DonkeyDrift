"""Harness 下载与一键更新路由（routers/harness_updater.py）的契约测试（issue #404）。

覆盖：路由注册、目录构建、版本解析/比较、下载 URL 解析（mock 网络）、
masked 存储、更新检查逻辑（mock gh/pip/npm）、安装路由分发、OTA 上传构造。
所有网络/子进程依赖均被 monkeypatch 隔离，测试不触网。
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import collect_route_paths

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def hu(monkeypatch, tmp_path):
    """导入模块并把本地-only 目录 / 状态路径重定向到临时目录。"""
    mod = importlib.import_module("routers.harness_updater")
    mod = importlib.reload(mod)
    monkeypatch.setattr(mod, "DOWNLOAD_DIR", tmp_path / "downloads")
    monkeypatch.setattr(mod, "STATE_PATH", tmp_path / "harness_updater.json")
    return mod


def _client(hu):
    app = FastAPI()
    app.include_router(hu.router, prefix="/api/harness")
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────────────────────────────────

def test_main_registers_harness_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/harness/catalog" in routes
    assert "/api/harness/check" in routes
    assert "/api/harness/status" in routes
    assert "/api/harness/ota/flash" in routes


# ─────────────────────────────────────────────────────────────────────────
# 版本解析 / 比较
# ─────────────────────────────────────────────────────────────────────────

def test_parse_version_variants(hu):
    assert hu.parse_version("v1.8.74") == "1.8.74"
    assert hu.parse_version("0.2.3 (Claude Code)") == "0.2.3"
    assert hu.parse_version("codex 0.5.1\n") == "0.5.1"
    assert hu.parse_version("\x1b[31m1.0.0-rc.1\x1b[0m") == "1.0.0-rc.1"
    assert hu.parse_version("no version here") is None
    assert hu.parse_version(None) is None


def test_is_newer_semver(hu):
    assert hu.is_newer("1.0.0", "0.9.9") is True
    assert hu.is_newer("0.1.2", "0.1.1-rc.2") is True
    assert hu.is_newer("0.1.1", "0.1.2") is False
    assert hu.is_newer(None, "1.0") is False
    assert hu.is_newer("1.0", None) is False
    assert hu.is_newer("garbage", "0.1") is False  # 无法比较 → 保守 False


# ─────────────────────────────────────────────────────────────────────────
# 目录构建（检测结构）
# ─────────────────────────────────────────────────────────────────────────

def test_catalog_has_four_harnesses(hu):
    cat = hu._catalog_status()
    ids = [h["id"] for h in cat]
    assert ids == ["codex", "claude", "deepseek", "zcode"]
    # 每项含 components，且含 install 结构
    for h in cat:
        assert isinstance(h["components"], list) and h["components"]
        for c in h["components"]:
            assert "installed" in c and "version" in c
            assert c["install"]["type"] in ("npm", "url")


def test_catalog_endpoint_returns_harnesses(hu):
    client = _client(hu)
    resp = client.get("/api/harness/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["harnesses"]) == 4


# ─────────────────────────────────────────────────────────────────────────
# 下载 URL 解析（mock 网络）
# ─────────────────────────────────────────────────────────────────────────

def test_filename_from_url_and_disposition(hu):
    assert hu._filename_from_url("https://x.com/a/Claude.deb", "") == "Claude.deb"
    assert (
        hu._filename_from_url(
            "https://x.com/download",
            'attachment; filename="MUS4_FW.ino.bin"',
        )
        == "MUS4_FW.ino.bin"
    )
    assert hu._filename_from_url("https://x.com/", "") == "installer"


class _FakeResp:
    def __init__(self, data, headers=None, status=200):
        self._data = data
        self.headers = headers or {}
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_url_to_dir(hu, monkeypatch, tmp_path):
    monkeypatch.setattr(hu, "DOWNLOAD_DIR", tmp_path / "downloads")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _FakeResp(b"fake-deb-bytes", {"Content-Disposition": 'attachment; filename="pkg.deb"'})

    monkeypatch.setattr(hu.urllib.request, "urlopen", fake_urlopen)
    result = hu._download_url_to_dir("https://example.com/pkg.deb", {"doc_url": "https://example.com"})
    assert result["status"] == "ok"
    assert result["path"].endswith("pkg.deb")
    assert captured["url"] == "https://example.com/pkg.deb"
    assert Path(result["path"]).read_bytes() == b"fake-deb-bytes"


# ─────────────────────────────────────────────────────────────────────────
# masked 存储
# ─────────────────────────────────────────────────────────────────────────

def test_mask_sensitive_recursive(hu):
    data = {
        "name": "ok",
        "api_key": "secret-value",
        "nested": {"token": "x", "list": [{"password": "y"}, {"safe": "z"}]},
    }
    masked = hu.mask_sensitive(data)
    assert masked["api_key"] == "***"
    assert masked["nested"]["token"] == "***"
    assert masked["nested"]["list"][0]["password"] == "***"
    assert masked["nested"]["list"][1]["safe"] == "z"
    assert masked["name"] == "ok"


def test_save_state_masks_sensitive(hu, monkeypatch, tmp_path):
    monkeypatch.setattr(hu, "STATE_PATH", tmp_path / "state.json")
    hu.save_state({"last_check_at": "2026-01-01", "api_token": "real-token"})
    raw = json.loads(Path(tmp_path / "state.json").read_text())
    assert raw["api_token"] == "***"


# ─────────────────────────────────────────────────────────────────────────
# 更新检查逻辑（mock gh/pip/npm）
# ─────────────────────────────────────────────────────────────────────────

def test_check_project_update(hu, monkeypatch):
    monkeypatch.setattr(hu, "_current_donkeydrifter_version", lambda: "0.1.2")
    monkeypatch.setattr(
        hu, "github_latest_release", lambda repo: {"tag": "v0.2.0", "assets": []}
    )
    item = hu.check_project_update()
    assert item["kind"] == "project"
    assert item["installed_version"] == "0.1.2"
    assert item["latest_version"] == "0.2.0"
    assert item["updateable"] is True


def test_check_donkeycar_update(hu, monkeypatch):
    monkeypatch.setattr(hu, "_current_donkeycar_version", lambda: "5.1.0")
    monkeypatch.setattr(hu, "pypi_latest_version", lambda pkg: "5.2.0")
    item = hu.check_donkeycar_update()
    assert item["kind"] == "component"
    assert item["updateable"] is True


def test_check_firmware_update_no_release(hu, monkeypatch):
    monkeypatch.setattr(hu, "github_latest_release", lambda repo: None)
    monkeypatch.setattr(hu, "_firmware_vehicle_ip", lambda: None)
    monkeypatch.setattr(hu, "_firmware_current_version", lambda ip: None)
    item = hu.check_firmware_update()
    assert item["kind"] == "firmware"
    assert item["updateable"] is False
    assert "暂无 release" in item["note"]


def test_check_firmware_update_with_asset(hu, monkeypatch, tmp_path):
    monkeypatch.setattr(hu, "github_latest_release", lambda repo: {
        "tag": "v1.8.75",
        "assets": [{"name": "MUS4_FW.ino.bin", "browser_download_url": "https://example.com/fw.bin"}],
    })
    monkeypatch.setattr(hu, "_firmware_vehicle_ip", lambda: "192.168.4.1")
    monkeypatch.setattr(hu, "_firmware_current_version", lambda ip: "v1.8.74")
    monkeypatch.setattr(hu, "_download_firmware_asset", lambda asset: "/tmp/fw.bin")
    item = hu.check_firmware_update()
    assert item["latest_version"] == "1.8.75"
    assert item["installed_version"] == "v1.8.74"
    assert item["updateable"] is True
    assert item["asset"] == "/tmp/fw.bin"


def test_run_update_check_aggregates(hu, monkeypatch):
    monkeypatch.setattr(hu, "check_harness_updates", lambda: [{"updateable": True}])
    monkeypatch.setattr(hu, "check_project_update", lambda: {"updateable": True})
    monkeypatch.setattr(hu, "check_donkeycar_update", lambda: {"updateable": False})
    monkeypatch.setattr(hu, "check_firmware_update", lambda: {"updateable": False})
    result = hu.run_update_check()
    assert result["ok"] is True
    assert result["updateable_count"] == 2
    assert len(result["updates"]) == 4


# ─────────────────────────────────────────────────────────────────────────
# 安装路由分发
# ─────────────────────────────────────────────────────────────────────────

def test_install_update_component(hu, monkeypatch):
    captured = {}

    def fake_run(argv, timeout=None):
        captured["argv"] = argv
        return 0, ""

    monkeypatch.setattr(hu, "_run_capture", fake_run)
    result = hu.install_update("component", "donkeycar")
    assert result["status"] == "ok"
    assert captured["argv"][:2] == ["pip", "install"]


def test_install_update_project_is_manual(hu):
    result = hu.install_update("project", "donkeydrift")
    assert result["status"] == "manual"


def test_install_update_unknown_harness_component(hu):
    result = hu.install_update("harness", "codex/does-not-exist")
    assert result["status"] == "error"


# ─────────────────────────────────────────────────────────────────────────
# OTA 上传构造
# ─────────────────────────────────────────────────────────────────────────

def test_post_multipart_file_body(hu, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        captured["headers"] = req.headers
        return _FakeResp(b"ACK:UPDATE_OK")

    monkeypatch.setattr(hu.urllib.request, "urlopen", fake_urlopen)
    status, body = hu._post_multipart_file("http://1.2.3.4/update", "update", "fw.bin", b"BIN", 10.0)
    assert status == 200
    assert b'name="update"' in captured["body"]
    assert b'filename="fw.bin"' in captured["body"]
    assert b"BIN" in captured["body"]
    content_type = next(v for k, v in captured["headers"].items() if k.lower() == "content-type")
    assert "multipart/form-data" in content_type


def test_ota_flash_rejects_public_ip(hu):
    result = hu.ota_flash("8.8.8.8")
    assert result["status"] == "error"
    assert "非法" in result["message"]
