# -*- coding: utf-8 -*-
"""漂移引擎相机循环安全测试：异常护栏、ENGAGED 期看门狗、重入守卫。

安全模型（RFC）：异常一律看门狗触发 → car_mode 0 + 零油门交还人工
（RC 遥控器始终可物理夺回）。覆盖：
- E1 相机循环核心链路（检测/位姿/β/录盘）异常 → 看门狗 + 循环干净退出
  + 帧源停止（DirectShow 句柄不泄漏）；
- E2 ENGAGED 期逐帧看门狗：检测丢失超时 / 遥测停滞 / 控制下发连续失败；
  非 AUTO 状态触发看门狗只记事件，不得下发车控；
- E3 start_camera_loop 重入：先幂等停旧循环（释放旧相机）再启新循环。
"""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_engine import DriftEngine  # noqa: E402
from drift_session import DriftSessionState  # noqa: E402


def _homography():
    from drift_vision import FieldHomography
    img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
    field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
    return FieldHomography.from_correspondences(img, field)


def _engine(tmp_path):
    """带假标定文件的独立引擎（可进 AUTO）。"""
    engine = DriftEngine(tub_base_dir=str(tmp_path))
    (tmp_path / "calib.npz").write_bytes(b"")
    engine._calibration_file = str(tmp_path / "calib.npz")
    return engine


def _wait_until(pred, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _force_engaged(engine):
    """测试钩子：绕过视觉喂 β 跨过观察期稳定窗 → AUTO_ENGAGED。"""
    engine.process_fake_frame(beta_deg=20.0, t_s=0.0)
    engine.process_fake_frame(beta_deg=20.0, t_s=0.6)
    assert engine.session.state == DriftSessionState.AUTO_ENGAGED


def _watchdog_reasons(engine):
    return [e.detail.get("reason", "") for e in engine.session.events
            if e.kind == "watchdog"]


def _always_hit_detector():
    from drift_vision import FakeTagDetector, TagDetection
    corners = np.array([[300, 200], [340, 200], [340, 240], [300, 240]],
                       dtype=np.float32)
    return FakeTagDetector([TagDetection(tag_id=0, corners=corners)])


class TestLoopExceptionGuard:
    """E1：核心链路异常不得静默杀掉相机线程。"""

    def test_detector_exception_triggers_watchdog_and_clean_exit(self, tmp_path):
        from drift_vision import FakeCamera

        class _ExplodingDetector:
            """第 4 次 detect 起抛异常（合成核心链路故障）。"""

            def __init__(self):
                self._n = 0

            def detect(self, frame):
                self._n += 1
                if self._n > 3:
                    raise RuntimeError("检测器爆炸（合成）")
                return []

        engine = _engine(tmp_path)
        engine.start("auto")  # OBSERVE：看门狗应把它打回 IDLE
        engine.start_camera_loop(FakeCamera(), _ExplodingDetector(),
                                 _homography(), tag_id=0)
        try:
            assert _wait_until(lambda: not engine._camera_thread.is_alive()), \
                "循环异常后线程应退出"
            assert engine.session.state == DriftSessionState.IDLE, \
                "异常必须触发看门狗把会话打回 IDLE"
            assert any("相机循环异常" in r for r in _watchdog_reasons(engine)), \
                "看门狗事件必须带异常原因"
            assert engine._frame_source is not None
            assert engine._frame_source.alive is False, \
                "循环退出必须停掉帧源（释放采集线程/相机句柄）"
            assert engine.camera_loop_errors == 1, "异常应计数"
        finally:
            engine.stop_camera_loop()


class TestEngagedWatchdogs:
    """E2：ENGAGED 期逐帧安全巡检（按相机帧时戳判定，不按帧数）。"""

    def test_detection_loss_timeout_triggers_watchdog(self, tmp_path):
        """连续无检测超过 0.2s → 看门狗交还人工。"""
        from drift_vision import FakeCamera, FakeTagDetector

        engine = _engine(tmp_path)
        engine.start("auto")
        _force_engaged(engine)  # 先接管，再开永不命中的相机循环
        engine.start_camera_loop(FakeCamera(), FakeTagDetector(),
                                 _homography(), tag_id=0)
        try:
            assert _wait_until(
                lambda: engine.session.state == DriftSessionState.IDLE), \
                "检测丢失超时必须触发看门狗"
            assert any("检测丢失" in r for r in _watchdog_reasons(engine))
        finally:
            engine.stop_camera_loop()

    def test_telemetry_stale_triggers_watchdog(self, tmp_path):
        """遥测停滞 >0.5s 且 ENGAGED → 看门狗（β 在吃陈旧 yaw_rate 积分）。"""
        from drift_vision import FakeCamera

        engine = _engine(tmp_path)
        engine.start("auto")
        _force_engaged(engine)
        engine.on_telemetry(t_s=time.monotonic(),
                            fields={"imu/gyr_z": 10.0})  # 只来一次，随后停滞
        engine.start_camera_loop(FakeCamera(), _always_hit_detector(),
                                 _homography(), tag_id=0)
        try:
            assert _wait_until(
                lambda: engine.session.state == DriftSessionState.IDLE), \
                "遥测停滞必须触发看门狗"
            assert any("遥测" in r for r in _watchdog_reasons(engine))
        finally:
            engine.stop_camera_loop()

    def test_consecutive_send_failures_trigger_watchdog(self, tmp_path):
        """ENGAGED 期间控制下发连续失败 ≥3 次 → 看门狗；累计计数进 snapshot。"""
        from drift_vision import FakeCamera

        engine = _engine(tmp_path)
        engine.start("auto")
        engine.send_sink = lambda msg: False  # 车端链路持续失败
        _force_engaged(engine)
        engine.start_camera_loop(FakeCamera(), _always_hit_detector(),
                                 _homography(), tag_id=0)
        try:
            assert _wait_until(
                lambda: engine.session.state == DriftSessionState.IDLE), \
                "控制下发连续失败必须触发看门狗"
            assert any("下发" in r for r in _watchdog_reasons(engine))
            assert engine.snapshot()["send_failures"] >= 3
        finally:
            engine.stop_camera_loop()


class TestWatchdogAuthority:
    """E2：看门狗的车控权限仅限 AUTO 期间。"""

    def test_watchdog_outside_auto_never_touches_car(self, tmp_path):
        """非 AUTO（IDLE/仅开预览）触发看门狗：只记事件，无权碰车。"""
        engine = _engine(tmp_path)  # IDLE
        captured = []
        engine.send_sink = captured.append
        engine.trigger_watchdog("测试：非 AUTO 触发")
        assert captured == [], "非 AUTO 状态不得下发任何车控"
        assert len(engine.sent_messages) == 0
        assert any("非 AUTO" in r for r in _watchdog_reasons(engine)), \
            "非 AUTO 触发也应记录事件供事后排查"


class TestCameraLoopReentry:
    """E3：start_camera_loop 重入守卫。"""

    def test_second_start_stops_first_loop_and_closes_camera(self, tmp_path):
        from drift_vision import FakeCamera, FakeTagDetector

        class _ClosableCamera(FakeCamera):
            def __init__(self):
                super().__init__()
                self.closed = False

            def close(self):
                self.closed = True

        engine = _engine(tmp_path)
        cam1, cam2 = _ClosableCamera(), _ClosableCamera()
        engine.start_camera_loop(cam1, FakeTagDetector(), _homography(), tag_id=0)
        first_thread = engine._camera_thread
        first_source = engine._frame_source
        engine.start_camera_loop(cam2, FakeTagDetector(), _homography(), tag_id=0)
        try:
            assert cam1.closed, "重入必须先释放旧相机句柄"
            assert first_source is not None and first_source.alive is False, \
                "旧帧源泵线程必须停止"
            assert not first_thread.is_alive(), "旧循环线程必须退出"
            assert engine._camera_thread is not first_thread
            assert engine._camera_thread.is_alive(), "新循环应存活"
            assert engine._camera is cam2, "引擎应持有新相机"
        finally:
            engine.stop_camera_loop()
