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


class TestTagHitCounters:
    """检测命中率计数：把"丢检测"变成可量化指标（M0 验收 tag_hits/frames <5% 丢失）。"""

    def test_snapshot_exposes_hit_counters(self):
        from drift_engine import DriftEngine
        snap = DriftEngine().snapshot()
        assert snap["frames_total"] == 0 and snap["tag_hits"] == 0

    def test_loop_counts_frames_and_hits(self):
        import numpy as np
        from drift_vision import (FakeCamera, FakeTagDetector, FieldHomography,
                                  TagDetection)
        from drift_engine import DriftEngine

        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        corners = np.array([[300, 200], [340, 200], [340, 240], [300, 240]],
                           dtype=np.float32)
        det = FakeTagDetector([TagDetection(tag_id=0, corners=corners)])
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(), det, homography, tag_id=0)
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and engine.snapshot()["frames_total"] < 5:
                time.sleep(0.02)
            snap = engine.snapshot()
            assert snap["frames_total"] >= 5
            assert snap["tag_hits"] == snap["frames_total"], \
                "每帧都命中时 tag_hits 应等于 frames_total"
        finally:
            engine.stop_camera_loop()


class TestDisplayFrameFreshness:
    def test_display_frame_advances_without_detection(self):
        """检测失败帧不得冻结预览：显示帧必须跟随最新采集帧推进。

        运动模糊导致间歇性检测丢失时，若只在检测成功时更新显示帧，
        推流会持续发旧画面（实车现象：慢推流畅、快推卡顿）。"""
        import numpy as np
        from drift_vision import FakeTagDetector, FieldHomography
        from drift_engine import DriftEngine

        class SeqCamera:
            """每帧像素值递增的合成相机（可区分新旧帧）。"""
            def __init__(self):
                self._n = 0

            def read(self):
                self._n += 1
                return (np.full((480, 640, 3), self._n % 251, np.uint8),
                        time.monotonic())

            def close(self):
                pass

        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(SeqCamera(), FakeTagDetector(),
                                 homography, tag_id=0)
        try:
            samples = []
            for _ in range(3):
                time.sleep(0.2)
                f = engine.display_frame
                samples.append(None if f is None else int(f[0, 0, 0]))
            assert all(s is not None for s in samples), \
                "无检测时预览不得为空"
            assert len(set(samples)) > 1, \
                "检测失败时预览帧也必须推进，不得冻结旧帧"
        finally:
            engine.stop_camera_loop()


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
            # 宽限 10s：FakeCamera 泵自由空转吃满单核，重负载机器（如视频会议
            # 中）消费者线程调度延迟可超 3s；宽限只影响等待上限，不改变验证内容。
            deadline = time.time() + 10.0
            while time.time() < deadline and engine.camera_fps <= 0:
                time.sleep(0.05)
            assert engine.camera_fps > 0, "处理循环应推进"
            assert engine.read_ema_ms >= 0.0 and engine.detect_ema_ms >= 0.0
        finally:
            engine.stop_camera_loop()
