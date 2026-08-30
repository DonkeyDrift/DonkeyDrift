# -*- coding: utf-8 -*-
"""drift_engine 层单元测试：相机循环的帧率计量。"""
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_engine import FpsMeter  # noqa: E402


class TestFpsMeter:
    def test_steady_rate(self):
        """0.05s 间隔的稳定流应量出 20fps。"""
        meter = FpsMeter(window_s=2.0)
        fps = 0.0
        for i in range(21):
            fps = meter.tick(t_s=0.05 * i)
        assert fps == pytest.approx(20.0, rel=0.05)

    def test_single_tick_returns_zero(self):
        """单帧不足以计算帧率，返回 0 而非除零。"""
        assert FpsMeter().tick(t_s=1.0) == 0.0

    def test_old_stamps_slide_out(self):
        """窗口外的旧时戳滑出：停流 2s 后再 tick，不应用陈旧帧算出虚高 fps。"""
        meter = FpsMeter(window_s=1.0)
        for i in range(10):  # 0.00~0.45s
            meter.tick(t_s=0.05 * i)
        assert meter.tick(t_s=2.5) == 0.0  # 窗内只剩单帧

    def test_snapshot_exposes_camera_fps(self):
        """状态快照应包含 camera_fps 字段（前端诊断显示）。"""
        from drift_engine import DriftEngine
        snap = DriftEngine().snapshot()
        assert "camera_fps" in snap and snap["camera_fps"] == 0.0


class TestCameraLoopSmoke:
    def test_loop_runs_and_reports_stage_timing(self):
        """泵+处理循环真线程冒烟：fps 与分段耗时被统计，停止干净。"""
        import numpy as np
        from drift_vision import FakeCamera, FakeTagDetector, FieldHomography
        from drift_engine import DriftEngine

        img = np.float32([[0, 1], [1, 2], [2, 0], [0, 0]])  # 任意非退化四点
        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(shape=(480, 640, 3)),
                                  FakeTagDetector(), homography, tag_id=0)
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and engine.camera_fps <= 0:
                time.sleep(0.05)
            assert engine.camera_fps > 0, "处理循环应推进"
            assert engine.read_ema_ms >= 0.0 and engine.detect_ema_ms >= 0.0
        finally:
            engine.stop_camera_loop()
