"""DriveApiBridge 遥测采集与发送的单测。

覆盖 RFC telemetry-chart-migration.md 改动1 的断点：
- 输入遥测 -> 发出 type=telemetry 消息
- 全部遥测为 None -> 不发 telemetry 消息，不报错
- 100Hz（10ms）节流：节流窗口内多次调用只发一次
- 旧调用方不传遥测参数 -> 向后兼容，不报错
"""
import time

import numpy as np

from donkeycar.parts.drive_api_bridge import DriveApiBridge


def _make_bridge(connected: bool = True) -> DriveApiBridge:
    """构造一个不自动启动、标记为已连接的 bridge，便于单测。"""
    bridge = DriveApiBridge(auto_start=False)
    bridge.connected = connected
    return bridge


def test_run_threaded_accepts_telemetry_kwargs_and_sends_message(monkeypatch):
    """输入遥测 -> 发出 type=telemetry 消息，字段与入参一致。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run_threaded(
        img_arr=None,
        imu_gz=0.12,
        imu_gx=-0.05,
        imu_gy=0.03,
        imu_ax=0.1,
        imu_ay=-0.2,
        imu_az=9.8,
        steering=0.0,
        throttle=0.35,
        pilot_angle=0.1,
        pilot_throttle=0.4,
        rc_steering=-0.3,
        rc_throttle=0.6,
        rc_mode=0,
        rc_park=1,
    )

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1
    msg = telemetry_msgs[0]
    assert msg["gz"] == 0.12
    assert msg["ax"] == 0.1
    assert msg["az"] == 9.8
    assert msg["steering"] == 0.0
    assert msg["throttle"] == 0.35
    assert msg["pilot_angle"] == 0.1
    assert msg["pilot_throttle"] == 0.4
    assert msg["rc_steering"] == -0.3
    assert msg["rc_throttle"] == 0.6
    assert msg["rc_mode"] == 0
    assert msg["rc_park"] == 1
    assert "t" in msg  # 必须带时间戳


def test_run_threaded_without_telemetry_sends_no_telemetry_message(monkeypatch):
    """所有遥测入参为 None -> 不发 telemetry 消息，且不报错。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    # 不传任何遥测参数（等价于旧调用方）
    bridge.run_threaded(img_arr=None)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert telemetry_msgs == []


def test_telemetry_throttled_to_100hz(monkeypatch):
    """100Hz（10ms）节流：节流窗口内多次调用只发一次 telemetry 消息。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    # 用固定时间序列，避免依赖真实墙钟：首次发送后，同时刻再调不应重复发
    monkeypatch.setattr(time, "time", lambda: 1000.0)

    bridge.run_threaded(img_arr=None, imu_gz=0.1)
    # 同一时刻再次调用，应被节流
    bridge.run_threaded(img_arr=None, imu_gz=0.2)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1

    # 推进时间超过 10ms（100Hz 窗口）后，应再次发送
    monkeypatch.setattr(time, "time", lambda: 1000.011)
    bridge.run_threaded(img_arr=None, imu_gz=0.3)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 2


def test_telemetry_omits_none_fields(monkeypatch):
    """部分遥测为 None -> None 字段不写入消息，其余字段照常发送。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run_threaded(img_arr=None, imu_gz=0.12, steering=0.0)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1
    msg = telemetry_msgs[0]
    assert msg["gz"] == 0.12
    assert msg["steering"] == 0.0
    # 未提供的字段不应出现在消息中
    assert "ax" not in msg
    assert "throttle" not in msg
    assert "pilot_angle" not in msg
    assert "rc_steering" not in msg
    assert "rc_throttle" not in msg
    assert "rc_mode" not in msg
    assert "rc_park" not in msg


def test_telemetry_not_sent_when_disconnected(monkeypatch):
    """未连接时不应发送 telemetry 消息（与 frame/car_state 一致）。"""
    bridge = _make_bridge(connected=False)
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run_threaded(img_arr=None, imu_gz=0.12)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert telemetry_msgs == []


def test_run_delegates_telemetry_kwargs(monkeypatch):
    """run() 应透传遥测参数到 run_threaded。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run(img_arr=None, imu_gz=0.5, throttle=0.2)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1
    assert telemetry_msgs[0]["gz"] == 0.5
    assert telemetry_msgs[0]["throttle"] == 0.2


def test_car_mode_command_is_sticky_and_returned():
    """car_mode 命令应作为第 7 个返回值传出，且粘滞（无新命令时仍保持）。"""
    bridge = _make_bridge()
    bridge._handle_message({"car_mode": 2})

    outputs = bridge.run_threaded(img_arr=None)
    assert outputs[6] == 2

    # 粘滞：下一次调用仍返回最后一次命令值，避免主循环漏读单次 latch
    outputs = bridge.run_threaded(img_arr=None)
    assert outputs[6] == 2


def test_car_mode_command_rejects_invalid_values():
    """非法 car_mode（非 0/1/2 或非数字）不改变命令值。"""
    bridge = _make_bridge()
    bridge._handle_message({"car_mode": 3})
    bridge._handle_message({"car_mode": "x"})

    assert bridge.car_mode is None
    outputs = bridge.run_threaded(img_arr=None)
    assert outputs[6] is None



def test_sim_connected_included_in_telemetry(monkeypatch):
    """sim_connected=False 应写入 telemetry 消息（False 不是 None，不可省略）。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run_threaded(img_arr=None, sim_connected=False)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1
    assert telemetry_msgs[0]["sim_connected"] is False


def test_sim_connected_omitted_when_none(monkeypatch):
    """未接 sim_connected 输入（如实车模板）时不应在消息中出现该字段。"""
    bridge = _make_bridge()
    sent = []
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge.run_threaded(img_arr=None, throttle=0.2)

    telemetry_msgs = [m for m in sent if m.get("type") == "telemetry"]
    assert len(telemetry_msgs) == 1
    assert "sim_connected" not in telemetry_msgs[0]
