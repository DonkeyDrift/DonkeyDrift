"""后端遥测转发契约测试。

覆盖 RFC telemetry-chart-migration.md 改动3 的断点：
- car 端发 type=telemetry 消息 -> 所有 client 收到原样广播
- 遥测消息不应被当作 car_state 触发状态广播
"""
import importlib
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client():
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)
    app = FastAPI()
    app.include_router(drive.router, prefix="/api/drive")
    return TestClient(app), drive


def make_online_client():
    client, drive = make_client()
    drive.drive_state.car_last_seen = datetime.now()
    return client, drive


def test_car_telemetry_message_is_broadcast_verbatim(monkeypatch):
    """car 端发 telemetry 消息 -> 原样广播给所有客户端。"""
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)

    telemetry_payload = {
        "type": "telemetry",
        "t": 1752300000000,
        "gz": 0.12,
        "gx": -0.05,
        "gy": 0.03,
        "ax": 0.1,
        "ay": -0.2,
        "az": 9.8,
        "steering": 0.0,
        "throttle": 0.35,
        "pilot_angle": 0.1,
        "pilot_throttle": 0.4,
    }

    with client.websocket_connect("/api/drive/ws?role=car") as car_ws:
        car_ws.send_json(telemetry_payload)

    telemetry_messages = [m for m in broadcasted if m.get("type") == "telemetry"]
    assert len(telemetry_messages) == 1
    # 原样转发：字段与车端发送的完全一致
    msg = telemetry_messages[0]
    assert msg["gz"] == 0.12
    assert msg["az"] == 9.8
    assert msg["steering"] == 0.0
    assert msg["throttle"] == 0.35
    assert msg["t"] == 1752300000000


def test_car_telemetry_message_does_not_trigger_car_state_broadcast(monkeypatch):
    """遥测消息不带 num_records/drive_mode/recording，不应触发 car_state 广播。"""
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)

    with client.websocket_connect("/api/drive/ws?role=car") as car_ws:
        car_ws.send_json({"type": "telemetry", "t": 1, "gz": 0.5})

    car_state_messages = [m for m in broadcasted if m.get("type") == "car_state"]
    # 遥测消息本身被广播，但不应额外触发 car_state 状态变更广播
    assert car_state_messages == []
