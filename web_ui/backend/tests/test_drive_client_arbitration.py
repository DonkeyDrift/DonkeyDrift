# -*- coding: utf-8 -*-
"""多客户端驾驶仲裁测试（Drive 页键盘/摇杆输入被挂机页签覆盖问题）。

问题：后端原本把所有客户端的控制消息原样转发车端，无任何仲裁。
挂机的后台页签（输入源默认摇杆、无人操作）会持续 60Hz 发
{angle:0, throttle:0}，把正在驾驶页签的键盘输入几乎全部覆盖——
车端表现为「输入有显示但车辆不动」。门禁行为：
- 同一时刻唯一「驾驶客户端」（driver）的控制可下发车端；
- 非 driver 的纯空闲 0 流被丢弃，限频回 control_rejected(not_driver)；
- 非零/变化的控制量可抢占驾驶权；
- driver 断开或停发超时后释放身份。
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_engine import drift_engine


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """独立 app + 引擎复位（假标定文件）+ 捕获 send_to_car。"""
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)
    app = FastAPI()
    app.include_router(drive.router, prefix="/api/drive")
    drift_engine.reset(calibration_file=str(tmp_path / "calib.npz"),
                       tub_base_dir=str(tmp_path))
    (tmp_path / "calib.npz").write_bytes(b"")
    sent_to_car = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)
    yield drive, TestClient(app), sent_to_car
    drift_engine.reset()  # 单例复位，避免状态泄漏到其他测试文件


def _drain_initial(ws):
    """连接后服务端先推 car_connection + car_state 两条初始消息。"""
    assert ws.receive_json()["type"] == "car_connection"
    assert ws.receive_json()["type"] == "car_state"


def _recv_until(ws, msg_type: str, max_messages: int = 8):
    """依次收消息直到目标类型（跳过广播类消息），防止广播顺序不确定。"""
    for _ in range(max_messages):
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"连续 {max_messages} 条消息中未见 {msg_type}")


def test_single_client_idle_stream_forwards(rig):
    """回归保护：唯一客户端的空闲 0 流照常转发（首个发送者成为 driver）。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=a") as ws:
        _drain_initial(ws)
        ws.send_json({"angle": 0.0, "throttle": 0.0, "drive_mode": "user"})
        ws.receive_json()  # car_state 广播或本条直接吞掉均可
        assert drive.drive_state.driver_client_id == "a"
        assert any(m.get("angle") == 0.0 for m in sent_to_car)


def test_idle_tab_cannot_override_driver(rig):
    """核心场景：driver 在驾驶时，另一页签的空闲 0 流不得覆盖。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=driver") as ws_d, \
         client.websocket_connect("/api/drive/ws?role=client&client_id=ghost") as ws_g:
        _drain_initial(ws_d)
        _drain_initial(ws_g)
        # driver 先建立身份并发非零值
        ws_d.send_json({"angle": 0.4, "throttle": 0.0, "drive_mode": "user"})
        ws_d.receive_json()  # car_state echo
        # ghost 随后发 0：必须被拒绝（先跳过 driver 触发的 car_state 广播）
        ws_g.send_json({"angle": 0.0, "throttle": 0.0, "drive_mode": "user"})
        reply = _recv_until(ws_g, "control_rejected")
        assert reply["reason"] == "not_driver"
    # 车端最后收到的仍是 driver 的 0.4，不是 ghost 的 0
    assert sent_to_car, "driver 的控制应已转发"
    assert sent_to_car[-1].get("angle") == 0.4
    assert drive.drive_state.angle == 0.4


def test_nonzero_steals_drivership(rig):
    """非零控制量可抢占驾驶权；被抢后原 driver 的 0 流反被拒绝。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=tab1") as ws1, \
         client.websocket_connect("/api/drive/ws?role=client&client_id=tab2") as ws2:
        _drain_initial(ws1)
        _drain_initial(ws2)
        ws1.send_json({"angle": 0.0, "throttle": 0.0, "drive_mode": "user"})
        ws1.receive_json()  # 首条控制触发 car_state 回声（确定性）
        # tab2 键盘按下：非零抢占，并附带 drive_mode 变化以获得确定性回声
        ws2.send_json({"angle": 0.6, "throttle": 0.2, "drive_mode": "local_angle"})
        assert ws2.receive_json()["type"] == "car_state"  # 回声 ⇒ 抢占已处理
        assert drive.drive_state.driver_client_id == "tab2"
        assert drive.drive_state.angle == 0.6
        # tab1 恢复发 0：现在它是非 driver，被拒
        ws1.send_json({"angle": 0.0, "throttle": 0.0, "drive_mode": "local_angle"})
        reply = _recv_until(ws1, "control_rejected")
        assert reply["reason"] == "not_driver"
    assert sent_to_car[-1].get("angle") == 0.6


def test_driver_disconnect_releases_role(rig):
    """driver 页签关闭即释放驾驶权，其它页签的 0 流立即可用。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=d") as ws_d:
        _drain_initial(ws_d)
        ws_d.send_json({"angle": 0.5, "throttle": 0.0})
        ws_d.receive_json()  # 首条控制触发回声
        assert drive.drive_state.driver_client_id == "d"
    # ws_d 关闭（with 退出，服务端处理完毕）→ 驾驶权释放
    assert drive.drive_state.driver_client_id is None
    with client.websocket_connect("/api/drive/ws?role=client&client_id=b") as ws_b:
        _drain_initial(ws_b)
        ws_b.send_json({"angle": 0.0, "throttle": 0.0})
    # b 的 0 流被转发（若驾驶权未释放会被仲裁拒绝），出 with 后身份随断开再次释放
    assert drive.drive_state.driver_client_id is None
    assert any(m.get("angle") == 0.0 for m in sent_to_car)


def test_driver_timeout_releases_role(rig, monkeypatch):
    """driver 停发超时（页面隐藏/挂起）后身份自动释放。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=stale") as ws_s, \
         client.websocket_connect("/api/drive/ws?role=client&client_id=fresh") as ws_f:
        _drain_initial(ws_s)
        _drain_initial(ws_f)
        ws_s.send_json({"angle": 0.3, "throttle": 0.0})
        ws_s.receive_json()  # 首条控制触发回声 ⇒ 身份已建立
        assert drive.drive_state.driver_client_id == "stale"
        # 模拟 stale 停发已超过 DRIVER_RELEASE_TIMEOUT
        monkeypatch.setattr(drive.drive_state, "driver_last_seen",
                            drive.drive_state.driver_last_seen - drive.DRIVER_RELEASE_TIMEOUT - 0.1)
        ws_f.send_json({"angle": 0.0, "throttle": 0.0})
    # fresh 的 0 流被转发（若 stale 未超时释放会被仲裁拒绝）
    assert any(m.get("angle") == 0.0 for m in sent_to_car)


def test_rejected_notice_rate_limited(rig):
    """空闲 0 流的拒绝回执按 2s 限频，不会 60Hz 洪泛（mock ws 确定性驱动）。"""
    import asyncio
    import time as time_mod
    from unittest.mock import AsyncMock

    from fastapi import WebSocket as FWebSocket, WebSocketDisconnect

    drive, _client, sent_to_car = rig
    driver_ws = AsyncMock(spec=FWebSocket)
    drive_state = drive.drive_state
    drive_state.driver_client_id = "driver"
    drive_state.driver_last_seen = time_mod.monotonic()

    ghost_ws = AsyncMock(spec=FWebSocket)
    ghost_ws.accept = AsyncMock()
    ghost_ws.send_text = AsyncMock()
    # 依次喂 3 条 ghost 的空闲 0 流，随后断开
    ghost_ws.receive_text = AsyncMock(side_effect=[
        '{"angle": 0.0, "throttle": 0.0, "drive_mode": "user"}',
        '{"angle": 0.0, "throttle": 0.0, "drive_mode": "user"}',
        '{"angle": 0.0, "throttle": 0.0, "drive_mode": "user"}',
        WebSocketDisconnect(code=1000),
    ])

    async def run():
        # 先注册 mock driver，保证仲裁判定「driver 在线」
        drive_state.client_ws["driver"] = driver_ws
        await drive.drive_ws(ghost_ws, role="client", client_id="ghost")

    asyncio.run(run())

    # ghost 收到的 send_text = 2 条初始状态推送 + 仅 1 条拒绝回执
    assert ghost_ws.send_text.call_count == 3
    rejections = [c for c in ghost_ws.send_text.call_args_list
                  if '"control_rejected"' in c.args[0]]
    assert len(rejections) == 1
    assert '"not_driver"' in rejections[0].args[0]
    # 3 条 ghost 控制全部未到达车端
    assert sent_to_car == []
