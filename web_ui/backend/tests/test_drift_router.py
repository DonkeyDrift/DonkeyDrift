# -*- coding: utf-8 -*-
"""drift 编排层（routers/drift.py + drift_engine.py）契约测试。

注入 FakeCamera/FakeDetector/捕获 send_to_car，不起真相机、不连真车。
覆盖：API 状态机联动、标定守卫、AUTO 接管流程、看门狗安全路径、参数更新。
"""
import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import routers.drive as drive_mod
from routers.drift import drift_engine, router


@pytest.fixture
def client(tmp_path, monkeypatch):
    """独立 app + 重置引擎 + 假标定文件。"""
    app = FastAPI()
    app.include_router(router, prefix="/api/drift")
    drift_engine.reset(calibration_file=str(tmp_path / "calib.npz"), tub_base_dir=str(tmp_path))
    (tmp_path / "calib.npz").write_bytes(b"")  # 标定文件存在
    return TestClient(app)


def feed_beta_sequence(beta_deg, t_s):
    """直接调用引擎帧处理（绕过相机线程），喂合成 β。"""
    drift_engine.process_fake_frame(beta_deg=beta_deg, t_s=t_s)


class TestStateApi:
    def test_initial_state_is_idle(self, client):
        r = client.get("/api/drift/state")
        assert r.status_code == 200
        assert r.json()["state"] == "idle"

    def test_record_requires_calibration_file(self, client, monkeypatch):
        drift_engine._calibration_file = "/nonexistent/calib.npz"
        r = client.post("/api/drift/session/start", json={"mode": "record"})
        assert r.status_code == 409

    def test_record_round_trip(self, client):
        r = client.post("/api/drift/session/start", json={"mode": "record"})
        assert r.status_code == 200
        assert client.get("/api/drift/state").json()["state"] == "record"
        r = client.post("/api/drift/session/stop")
        assert r.status_code == 200
        assert client.get("/api/drift/state").json()["state"] == "idle"

    def test_invalid_mode_rejected(self, client):
        r = client.post("/api/drift/session/start", json={"mode": "banana"})
        assert r.status_code == 422


class TestAutoFlow:
    def test_auto_observe_then_engage(self, client):
        captured = []
        drift_engine.send_sink = captured.append
        r = client.post("/api/drift/session/start", json={"mode": "auto"})
        assert r.status_code == 200
        assert client.get("/api/drift/state").json()["state"] == "auto_observe"
        for i in range(13):  # 0.6s，|β|=20 持续超 500ms
            feed_beta_sequence(20.0 if i else 20.0, t_s=0.05 * i)
        state = client.get("/api/drift/state").json()
        assert state["state"] == "auto_engaged"
        # 接管后必须已下发 MODE 2
        modes = [m.get("car_mode") for m in captured if m.get("car_mode") is not None]
        assert 2 in modes

    def test_watchdog_sends_mode0_and_park(self, client):
        captured = []
        drift_engine.send_sink = captured.append
        client.post("/api/drift/session/start", json={"mode": "auto"})
        for i in range(13):
            feed_beta_sequence(20.0, t_s=0.05 * i)
        assert client.get("/api/drift/state").json()["state"] == "auto_engaged"
        drift_engine.trigger_watchdog("测试：相机丢帧")
        assert client.get("/api/drift/state").json()["state"] == "idle"
        modes = [m.get("car_mode") for m in captured if m.get("car_mode") is not None]
        assert 0 in modes, "看门狗必须下发 MODE 0 交还人工"
        zeroes = [m for m in captured if m.get("car_mode") == 0]
        assert zeroes[-1].get("throttle") == 0, "交还人工时应带零油门"

    def test_observe_phase_does_not_send_control(self, client):
        captured = []
        drift_engine.send_sink = captured.append
        client.post("/api/drift/session/start", json={"mode": "auto"})
        for i in range(5):  # β 未稳定
            feed_beta_sequence(20.0 if i % 2 else 5.0, t_s=0.05 * i)
        assert client.get("/api/drift/state").json()["state"] == "auto_observe"
        offending = [m for m in captured if "angle" in m or "throttle" in m]
        assert offending == [], "观察期不得下发任何转向/油门控制（人 RC 在开）"


class TestConfigApi:
    def test_beta_target_update(self, client):
        r = client.post("/api/drift/config", json={"beta_target_deg": 30.0})
        assert r.status_code == 200
        assert client.get("/api/drift/state").json()["config"]["beta_target_deg"] == 30.0

    def test_unknown_config_key_rejected(self, client):
        r = client.post("/api/drift/config", json={"nonsense_key": 1})
        assert r.status_code == 422


class TestCameraStartApi:
    """camera/start 契约：曝光等参数透传到 USBCamera 构造。"""

    @staticmethod
    def _patch_camera_deps(monkeypatch, captured):
        import drift_engine as engine_mod
        import drift_vision
        from types import SimpleNamespace

        class FakeUSBCamera:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                pass

        monkeypatch.setattr(drift_vision, "USBCamera", FakeUSBCamera)
        monkeypatch.setattr(drift_vision, "FieldHomography",
                            SimpleNamespace(from_file=lambda p: object()))
        monkeypatch.setattr(drift_vision, "AprilTagDetector",
                            lambda downscale: object())
        monkeypatch.setattr(engine_mod.drift_engine, "start_camera_loop",
                            lambda *a, **k: None)

    def test_exposure_passthrough(self, client, monkeypatch):
        captured = {}
        self._patch_camera_deps(monkeypatch, captured)
        r = client.post("/api/drift/camera/start", json={
            "camera_index": 1, "tag_id": 0,
            "calibration_file": "whatever.npz", "exposure": -7.0})
        assert r.status_code == 200
        assert captured["index"] == 1
        assert captured["exposure"] == -7.0, "曝光参数必须透传到 USBCamera"

    def test_exposure_default_is_none(self, client, monkeypatch):
        """不传曝光字段时以 None 透传（USBCamera 保持自动曝光）。"""
        captured = {}
        self._patch_camera_deps(monkeypatch, captured)
        r = client.post("/api/drift/camera/start", json={
            "camera_index": 1, "tag_id": 0, "calibration_file": "whatever.npz"})
        assert r.status_code == 200
        assert captured.get("exposure") is None


class TestTelemetryHook:
    def test_telemetry_push_reaches_recorder(self, client):
        client.post("/api/drift/session/start", json={"mode": "record"})
        drift_engine.on_telemetry(t_s=0.0, fields={"rc/throttle": 0.5, "imu/gyr_z": 0.1})
        assert drift_engine.telemetry_count >= 1


class TestMjpegStream:
    def test_frame_mjpg_returns_multipart_stream(self):
        """预览 MJPEG 端点应返回 multipart/x-mixed-replace 流式响应。"""
        from routers.drift import overhead_frame_mjpg

        resp = asyncio.run(overhead_frame_mjpg())
        assert resp.status_code == 200
        assert resp.media_type.startswith("multipart/x-mixed-replace")


class TestWebrtcOffer:
    """WebRTC 预览信令：浏览器 offer → 后端 answer。"""

    def test_offer_returns_answer(self, client):
        aiortc = pytest.importorskip("aiortc")

        async def _make_offer():
            pc = aiortc.RTCPeerConnection()
            pc.addTransceiver("video", direction="recvonly")
            offer = await pc.createOffer()
            await pc.close()
            return offer

        offer = asyncio.run(_make_offer())
        r = client.post("/api/drift/webrtc/offer",
                        json={"sdp": offer.sdp, "type": offer.type})
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "answer" and "sdp" in body

    def test_garbage_sdp_rejected(self, client):
        pytest.importorskip("aiortc")
        import drift_webrtc
        before = len(drift_webrtc._pcs)
        for _ in range(3):
            r = client.post("/api/drift/webrtc/offer",
                            json={"sdp": "not-a-valid-sdp", "type": "offer"})
            assert r.status_code == 400
        # 协商失败的 RTCPeerConnection 必须 close 并移出 _pcs：
        # 失败路径泄漏会让 pc 随垃圾请求数无界堆积
        assert len(drift_webrtc._pcs) == before, (
            "垃圾 SDP 协商失败后 pc 不得残留在 _pcs（泄漏）")


class TestDisplayFrameTrack:
    def test_track_downscales_for_encoding(self):
        """推流轨道应输出半分辨率帧：运动画面 H.264 编码 20~35ms 超
        60fps 预算，降分辨率编码是显示链路不掉帧的关键。"""
        aiortc = pytest.importorskip("aiortc")
        import numpy as np
        from drift_webrtc import DisplayFrameTrack

        async def _recv():
            track = DisplayFrameTrack(lambda: np.zeros((720, 1280, 3), np.uint8))
            return await asyncio.wait_for(track.recv(), timeout=2.0)

        vf = asyncio.run(_recv())
        assert vf.width == 640 and vf.height == 360


class TestConfigApiValidation:
    """E8：/config 非法值映射 422（而非裸穿 500 或静默落配置）。"""

    def test_nan_rejected_422(self, client):
        # httpx 的 json= 序列化器拒绝 nan，用原始 body 模拟客户端直发 NaN
        # （服务端 json.loads 默认接受 NaN/Infinity，必须显式门禁）
        r = client.post("/api/drift/config", content=b'{"k_beta": NaN}',
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 422

    def test_inf_rejected_422(self, client):
        r = client.post("/api/drift/config", content=b'{"k_yaw": -Infinity}',
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 422

    def test_negative_duty_rejected_422(self, client):
        """占空比负值无物理意义 → 422。"""
        r = client.post("/api/drift/config", json={"pulse_duty": -0.5})
        assert r.status_code == 422

    def test_non_numeric_rejected_422(self, client):
        r = client.post("/api/drift/config", json={"k_beta": {"x": 1}})
        assert r.status_code == 422

    def test_valid_update_unaffected(self, client):
        r = client.post("/api/drift/config", json={"k_beta": 2.5})
        assert r.status_code == 200
        assert client.get("/api/drift/state").json()["config"]["k_beta"] == 2.5


class TestCameraStartFailure:
    """E8/E3：detector 构造失败必须 close 已打开的相机（DSHOW 句柄不泄漏）。"""

    def test_detector_failure_closes_camera(self, client, monkeypatch):
        import drift_vision
        from types import SimpleNamespace

        closed = []

        class FakeUSBCamera:
            def __init__(self, **kwargs):
                pass

            def close(self):
                closed.append(True)

        def _boom_detector(downscale):
            raise RuntimeError("apriltags 后端缺失（合成）")

        monkeypatch.setattr(drift_vision, "USBCamera", FakeUSBCamera)
        monkeypatch.setattr(drift_vision, "FieldHomography",
                            SimpleNamespace(from_file=lambda p: object()))
        monkeypatch.setattr(drift_vision, "AprilTagDetector", _boom_detector)
        r = client.post("/api/drift/camera/start", json={
            "camera_index": 0, "tag_id": 0, "calibration_file": "x.npz"})
        assert r.status_code == 409
        assert closed, "detector 构造失败时必须 close 已打开的相机"


class TestInstallDriveHooks:
    """E8：install_drive_hooks 幂等——重复调用不得重复 append 遥测 hook。"""

    def test_idempotent_no_duplicate_telemetry_hook(self, monkeypatch):
        import routers.drive as drive_mod
        import routers.drift as drift_mod

        hooks = []
        monkeypatch.setattr(drive_mod.drive_state, "telemetry_hooks", hooks)
        monkeypatch.setattr(drift_mod, "_drive_hooks_installed", False)
        monkeypatch.setattr(asyncio, "get_event_loop", lambda: object())
        drift_mod.install_drive_hooks()
        drift_mod.install_drive_hooks()
        assert len(hooks) == 1, "重复安装不得让遥测翻倍"


class TestAppLifecycle:
    """E4：应用关闭必须释放俯拍相机（DirectShow 句柄）。"""

    def test_shutdown_stops_camera_loop(self, monkeypatch):
        import main as main_mod

        calls = []
        monkeypatch.setattr(main_mod.drift.drift_engine, "stop_camera_loop",
                            lambda: calls.append(True))
        with TestClient(main_mod.app):
            pass
        assert calls, "shutdown 钩子必须调用 drift_engine.stop_camera_loop"
