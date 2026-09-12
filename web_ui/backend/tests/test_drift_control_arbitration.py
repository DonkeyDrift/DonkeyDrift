# -*- coding: utf-8 -*-
"""AUTO 期间服务端多 client 控制仲裁测试（交接文档 §6 遗留项）。

问题：浏览器客户端经 /api/drive/ws 发来的控制字段（angle/throttle/...）
原本无条件转发车端；漂移 AUTO（观察/接管）期间会与 drift_engine
经 send_sink 下发的控制打架（RFC 第 11 节风险表）。门禁行为：
- AUTO_OBSERVE / AUTO_ENGAGED：丢弃浏览器控制，回发 control_rejected；
- IDLE（含停止 AUTO 后）：照常转发，行为与旧版一致；
- 引擎自身 send_sink 下发不经浏览器 ws 通道，不受门禁影响。
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
    """独立 app + 重置引擎（假标定文件）+ 捕获 send_to_car。"""
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)
    app = FastAPI()
    app.include_router(drive.router, prefix="/api/drive")
    drift_engine.reset(calibration_file=str(tmp_path / "calib.npz"),
                       tub_base_dir=str(tmp_path))
    (tmp_path / "calib.npz").write_bytes(b"")  # 标定文件存在
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


def _engage_auto():
    """观察期喂 |β|=20° 跨过 0.5s 稳定窗 → AUTO_ENGAGED。"""
    drift_engine.process_fake_frame(beta_deg=20.0, t_s=0.0)
    drift_engine.process_fake_frame(beta_deg=20.0, t_s=0.6)
    assert drift_engine.session.state.value == "auto_engaged"


def test_idle_forwards_browser_control(rig):
    """回归保护：非 AUTO 时浏览器控制照常转发车端。"""
    drive, client, sent_to_car = rig
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        _drain_initial(ws)
        ws.send_json({"angle": 0.5, "throttle": 0.3})
        assert ws.receive_json()["type"] == "car_state"  # 转发后的常规广播
    assert any(m.get("angle") == 0.5 and m.get("throttle") == 0.3
               for m in sent_to_car)
    assert drive.drive_state.angle == 0.5
    assert drive.drive_state.throttle == 0.3


def test_auto_observe_blocks_browser_control(rig):
    """AUTO 观察期：浏览器控制必须被丢弃，不下发、不污染共享状态。"""
    drive, client, sent_to_car = rig
    drift_engine.start("auto")
    assert drift_engine.session.state.value == "auto_observe"
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        _drain_initial(ws)
        ws.send_json({"angle": 0.7, "throttle": 0.4})
        reply = ws.receive_json()
    assert reply["type"] == "control_rejected"
    assert reply["reason"] == "drift_auto_active"
    assert sent_to_car == [], "AUTO 期间浏览器控制不得到达车端"
    assert drive.drive_state.angle == 0.0, "被拦截的消息不得更新 drive_state"
    assert drive.drive_state.throttle == 0.0


def test_auto_engaged_blocks_browser_control(rig):
    """AUTO 接管期：控制器独占控制权，浏览器控制同样拦截。"""
    drive, client, sent_to_car = rig
    drift_engine.start("auto")
    _engage_auto()
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        _drain_initial(ws)
        ws.send_json({"angle": -0.6, "throttle": 0.9, "car_mode": 0})
        reply = ws.receive_json()
    assert reply["type"] == "control_rejected"
    assert sent_to_car == []
    assert drive.drive_state.angle == 0.0


def test_forwarding_resumes_after_auto_stop(rig):
    """停止 AUTO 回到 IDLE 后，浏览器控制恢复转发。"""
    drive, client, sent_to_car = rig
    drift_engine.start("auto")
    _engage_auto()
    drift_engine.stop()
    assert drift_engine.session.state.value == "idle"
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        _drain_initial(ws)
        ws.send_json({"angle": 0.2, "throttle": 0.1})
        assert ws.receive_json()["type"] == "car_state"
    assert any(m.get("angle") == 0.2 for m in sent_to_car)


def test_engine_sink_unaffected_while_gate_active(rig):
    """引擎自身控制下发（send_sink）不经 ws 门禁，AUTO 期间必须畅通。"""
    _, _, _ = rig
    captured = []
    drift_engine.send_sink = captured.append
    drift_engine.start("auto")
    _engage_auto()
    drift_engine.process_fake_frame(beta_deg=20.0, t_s=0.65)  # 接管后控制输出
    engine_msgs = [m for m in captured
                   if "angle" in m or m.get("car_mode") is not None]
    assert engine_msgs, "AUTO 期间引擎自身下发不得被门禁影响"
