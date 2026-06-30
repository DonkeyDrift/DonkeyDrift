"""配网 API 路由契约测试。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def client():
    """创建只包含配网路由的测试客户端。"""
    from routers import provisioning

    app = FastAPI()
    app.include_router(provisioning.router, prefix="/api/provisioning")
    return TestClient(app)


class TestStatusEndpoint:
    """验证 GET /api/provisioning/status 端点。"""

    def test_returns_idle_initially(self, client):
        """初始状态为 idle。"""
        response = client.get("/api/provisioning/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"
        assert "ssid" in data
        assert "ip" in data
        assert "error" in data

    def test_response_has_all_fields(self, client):
        """返回的 JSON 包含所有必要字段。"""
        response = client.get("/api/provisioning/status")
        data = response.json()
        for field in ("status", "ssid", "ip", "error"):
            assert field in data, f"缺少字段: {field}"


class TestConnectEndpoint:
    """验证 POST /api/provisioning/connect 端点。"""

    def test_validates_ssid_required(self, client):
        """缺少 ssid 返回 400。"""
        response = client.post("/api/provisioning/connect", json={"password": "123"})
        assert response.status_code == 400
        # 空字符串 ssid 也会被拒绝
        response2 = client.post("/api/provisioning/connect", json={"ssid": "", "password": "123"})
        assert response2.status_code == 400

    def test_accepts_valid_request(self, client, monkeypatch):
        """正确的请求返回 200 并更新状态为 connecting。"""
        # Mock WifiManager 避免真实的 nmcli 调用
        import routers.provisioning as prov_module
        from unittest.mock import MagicMock

        mock_wm = MagicMock()
        mock_wm.disconnect_ap.return_value = True
        mock_wm.connect.return_value = (True, "192.168.1.100")

        # 在路由模块中替换 WifiManager 类
        monkeypatch.setattr(
            prov_module, "WifiManager",
            lambda *args, **kwargs: mock_wm,
        )

        response = client.post("/api/provisioning/connect",
                               json={"ssid": "TestNet", "password": "secret"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] is True
        assert "开始连接" in data["message"]


class TestScanEndpoint:
    """验证 POST /api/provisioning/scan 端点。"""

    def test_returns_networks_list(self, client, monkeypatch):
        """扫描返回网络列表。"""
        import routers.provisioning as prov_module
        from unittest.mock import MagicMock

        mock_wm = MagicMock()
        mock_wm.scan_networks.return_value = [
            {"ssid": "MyWiFi", "signal": 90, "security": "WPA2"},
            {"ssid": "Guest", "signal": 45, "security": "OPEN"},
        ]
        monkeypatch.setattr(
            prov_module, "WifiManager",
            lambda *args, **kwargs: mock_wm,
        )

        response = client.post("/api/provisioning/scan")

        assert response.status_code == 200
        data = response.json()
        assert "networks" in data
        assert len(data["networks"]) == 2
        assert data["networks"][0]["ssid"] == "MyWiFi"

    def test_scan_empty_on_failure(self, client, monkeypatch):
        """扫描失败时返回空列表。"""
        import routers.provisioning as prov_module
        from unittest.mock import MagicMock

        mock_wm = MagicMock()
        mock_wm.scan_networks.return_value = []
        monkeypatch.setattr(
            prov_module, "WifiManager",
            lambda *args, **kwargs: mock_wm,
        )

        response = client.post("/api/provisioning/scan")
        assert response.status_code == 200
        assert response.json()["networks"] == []


class TestSerialScanEndpoint:
    """验证 GET /api/provisioning/serial/scan 端点。"""

    def test_returns_scan_result_structure(self, client, monkeypatch):
        """返回 found/port/rtt_ms 结构。"""
        import routers.provisioning as prov_module

        monkeypatch.setattr(
            prov_module.ProvisioningPart, "scan_serial_ports",
            staticmethod(lambda **kw: (None, None)),
        )

        response = client.get("/api/provisioning/serial/scan")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["port"] is None
        assert data["rtt_ms"] is None
