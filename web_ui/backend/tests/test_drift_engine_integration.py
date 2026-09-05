# -*- coding: utf-8 -*-
"""集成协调点回归测试（2026-09-01 夜间审计修复汇总）：

- 位姿解算抛 ValueError / PoseSolver 拒收（返回 None）→ 按丢帧处理，
  循环不死、不误触发看门狗、不下发控制（区别于"循环异常"级故障）。
- /config 白名单收纳控制器新键 max_steering_rate_per_s / radius_freq_sign，
  展示侧给出 max_steering_rate_per_s 的生效值（旧字段 ×60 映射）而非 None。
- FrameSource.read_ema_ms 首样本直接赋值（不从 0 冷启动收敛）。
- DriftSession.events 有界（watchdog 反复触发不再无界增长）。
- 泵线程卡死（DSHOW 僵尸句柄阻塞 read）时 stop 跳过 camera.close()
  （与在途 read 并发 release 是未定义行为；泄漏给 OS 回收更安全）。
"""
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import drift_engine  # noqa: E402
from drift_engine import DriftEngine  # noqa: E402


def _homography():
    import numpy as np
    from drift_vision import FieldHomography
    img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
    field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
    return FieldHomography.from_correspondences(img, field)


class TestSolverFailureTreatedAsMiss:
    def test_solve_exception_does_not_kill_loop(self, monkeypatch):
        """检测命中但位姿解算抛 ValueError（退化投影/坏单应）时按丢帧处理：
        循环继续推进、不下发控制。"""
        import numpy as np
        import drift_vision
        from drift_vision import FakeCamera, FakeTagDetector, TagDetection

        def _boom(*args, **kwargs):
            raise ValueError("退化投影（过地平线）")

        # 引擎在 start_camera_loop 内局部 import，补丁打在源模块上
        monkeypatch.setattr(drift_vision, "solve_tag_pose", _boom)
        corners = np.array([[300, 200], [340, 200], [340, 240], [300, 240]],
                           dtype=np.float32)
        det = FakeTagDetector([TagDetection(tag_id=0, corners=corners)])
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(), det, _homography(), tag_id=0)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and engine.snapshot()["frames_total"] < 5:
                time.sleep(0.02)
            assert engine.snapshot()["frames_total"] >= 5, \
                "解算异常应按丢帧处理，不得杀死相机循环"
            assert all("angle" not in m and "throttle" not in m
                       for m in engine.sent_messages), "解算失败不得下发控制"
        finally:
            engine.stop_camera_loop()

    def test_solver_returns_none_treated_as_miss(self, monkeypatch):
        """PoseSolver 拒收（首帧即 NaN 等历史为空情形）返回 None → 同样按丢帧。"""
        import numpy as np
        import drift_vision
        from drift_vision import FakeCamera, FakeTagDetector, TagDetection

        # 引擎在 start_camera_loop 内局部 import，补丁打在源模块类上
        monkeypatch.setattr(drift_vision.PoseSolver, "push",
                            lambda self, pose: None)
        corners = np.array([[300, 200], [340, 200], [340, 240], [300, 240]],
                           dtype=np.float32)
        det = FakeTagDetector([TagDetection(tag_id=0, corners=corners)])
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(), det, _homography(), tag_id=0)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and engine.snapshot()["frames_total"] < 5:
                time.sleep(0.02)
            assert engine.snapshot()["frames_total"] >= 5, \
                "PoseSolver 拒收应按丢帧处理，不得 AttributeError 杀死循环"
        finally:
            engine.stop_camera_loop()


class TestConfigNewControllerKeys:
    def test_new_keys_accepted(self):
        engine = DriftEngine(tub_base_dir=None)
        engine.update_config({"max_steering_rate_per_s": 2.5,
                              "radius_freq_sign": 1.0})
        assert engine.config.max_steering_rate_per_s == 2.5
        assert engine.config.radius_freq_sign == 1.0

    def test_rate_negative_rejected(self):
        engine = DriftEngine(tub_base_dir=None)
        with pytest.raises(ValueError):
            engine.update_config({"max_steering_rate_per_s": -1.0})

    def test_config_dict_shows_effective_rate(self):
        """未显式设置新键时展示生效值（旧 delta_per_tick × 60 映射），不为 None。"""
        engine = DriftEngine(tub_base_dir=None)
        shown = drift_engine._config_as_dict(engine.config)
        assert shown["max_steering_rate_per_s"] == pytest.approx(3.0)
        engine.update_config({"max_steering_rate_per_s": 4.0})
        shown = drift_engine._config_as_dict(engine.config)
        assert shown["max_steering_rate_per_s"] == pytest.approx(4.0)


class TestFrameSourceEmaColdStart:
    def test_read_ema_first_sample_direct(self):
        """read_ema_ms 首样本直接赋值：FakeCamera 60fps 节拍首帧 ≥10ms，
        从 0 冷启动的 EMA 仅 ~1.6ms（可区分断言）。"""
        from drift_vision import FakeCamera, FrameSource
        src = FrameSource(FakeCamera())
        src.start()
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and src.latest() is None:
                time.sleep(0.01)
            assert src.latest() is not None
            assert src.read_ema_ms > 5.0, "首样本应直接赋值而非从 0 收敛"
        finally:
            src.stop()


class TestEventsBounded:
    def test_session_events_capped(self):
        """events 有界（500 上限）：watchdog 反复触发不再无界增长。"""
        from drift_session import DriftSession
        s = DriftSession()
        for i in range(600):
            s._record("watchdog", reason=f"第{i}次")
        assert len(s.events) <= 500


class _StuckCamera:
    """模拟 DSHOW 僵尸句柄下无限阻塞的 read()。"""

    def __init__(self):
        self.close_called = False
        self._release = threading.Event()

    def read(self):
        import numpy as np
        self._release.wait(timeout=10.0)
        return np.zeros((480, 640, 3), dtype=np.uint8), time.monotonic()

    def close(self):
        self.close_called = True


class TestStopWithStuckPumpSkipsClose:
    def test_stop_skips_close_when_pump_stuck(self):
        """泵线程堵在 read() 时，stop 不与之并发 close（未定义行为），
        泄漏给 OS 回收；整个过程有界（不超过 join 宽限）。"""
        from drift_vision import FakeTagDetector
        cam = _StuckCamera()
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(cam, FakeTagDetector([]), _homography(), tag_id=0)
        t0 = time.monotonic()
        engine.stop_camera_loop()
        elapsed = time.monotonic() - t0
        try:
            assert not cam.close_called, \
                "泵线程仍存活时不应并发 close（泄漏给 OS 回收）"
            assert elapsed < 8.0, "stop 必须有界"
        finally:
            cam._release.set()  # 释放卡死泵线程，清理测试现场
