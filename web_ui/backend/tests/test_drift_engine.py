# -*- coding: utf-8 -*-
"""drift_engine 层单元测试：相机循环的帧率计量。"""
import sys
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
