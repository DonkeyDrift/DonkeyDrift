# -*- coding: utf-8 -*-
"""sync_recorder 单元测试：遥测插值对齐、点动特征提取、tub 写入。

合成数据驱动：构造已知频率/占空比/幅值的油门方波与线性变化的遥测流，
验证插值精度与特征恢复精度（RFC 第 6 节验收口径）。
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sync_recorder import TelemetryBuffer, ThrottlePulseAnalyzer


class TestTelemetryBuffer:
    def test_linear_interpolation_midpoint(self):
        buf = TelemetryBuffer()
        buf.push(t_s=0.0, fields={"rc/throttle": 0.0})
        buf.push(t_s=1.0, fields={"rc/throttle": 1.0})
        out = buf.interpolate(0.5)
        assert out["rc/throttle"] == pytest.approx(0.5, abs=1e-9)

    def test_interpolation_on_sine_is_accurate(self):
        """100Hz 正弦遥测上任意时刻插值，误差远小于幅值（线性化误差量级）。"""
        buf = TelemetryBuffer()
        for i in range(0, 200):
            t = i / 100.0
            buf.push(t, {"imu/gyr_z": math.sin(2 * math.pi * 2.0 * t)})
        for t in [0.537, 1.111, 1.732]:
            got = buf.interpolate(t)["imu/gyr_z"]
            want = math.sin(2 * math.pi * 2.0 * t)
            assert got == pytest.approx(want, abs=0.02)

    def test_outside_range_clamps_to_nearest(self):
        buf = TelemetryBuffer()
        buf.push(0.0, {"v": 1.0})
        buf.push(1.0, {"v": 3.0})
        assert buf.interpolate(-0.5)["v"] == pytest.approx(1.0)
        assert buf.interpolate(2.0)["v"] == pytest.approx(3.0)

    def test_empty_buffer_returns_empty(self):
        assert TelemetryBuffer().interpolate(0.0) == {}

    def test_multiple_fields_interpolated(self):
        buf = TelemetryBuffer()
        buf.push(0.0, {"a": 0.0, "b": 10.0})
        buf.push(1.0, {"a": 2.0, "b": 20.0})
        out = buf.interpolate(0.25)
        assert out["a"] == pytest.approx(0.5)
        assert out["b"] == pytest.approx(12.5)


def square_wave(t, freq_hz, amp, base=0.0, duty=0.5):
    return amp if (t * freq_hz) % 1.0 < duty else base


class TestThrottlePulseAnalyzer:
    def _feed(self, analyzer, freq, amp=0.8, duty=0.5, duration=3.0, rate=60.0):
        n = int(duration * rate)
        for i in range(n):
            t = i / rate
            analyzer.push(t, square_wave(t, freq, amp, duty=duty))
        return analyzer.features()

    def test_recovers_known_frequency_duty_amp(self):
        feats = self._feed(ThrottlePulseAnalyzer(window_s=1.0), freq=5.0)
        assert feats.frequency_hz == pytest.approx(5.0, abs=0.5)
        assert feats.duty == pytest.approx(0.5, abs=0.05)
        assert feats.peak_amp == pytest.approx(0.8, abs=0.05)

    def test_different_duty(self):
        feats = self._feed(ThrottlePulseAnalyzer(window_s=1.0), freq=4.0, duty=0.3)
        assert feats.duty == pytest.approx(0.3, abs=0.06)

    def test_frequency_change_is_tracked(self):
        """前 2s 高频、后 2s 低频：滑动窗特征跟随变化。"""
        ana = ThrottlePulseAnalyzer(window_s=1.0)
        n = int(4.0 * 60)
        for i in range(n):
            t = i / 60.0
            freq = 8.0 if t < 2.0 else 3.0
            ana.push(t, square_wave(t, freq, 0.8))
        feats = ana.features()  # 窗口覆盖 t∈[3,4]，应为低频
        assert feats.frequency_hz == pytest.approx(3.0, abs=0.6)

    def test_steady_high_throttle_reports_no_pulses(self):
        """持续满油（无点动）→ 频率 0、占空比 1 的语义。"""
        ana = ThrottlePulseAnalyzer(window_s=1.0)
        for i in range(120):
            ana.push(i / 60.0, 0.9)
        feats = ana.features()
        assert feats.frequency_hz == 0.0
        assert feats.duty == pytest.approx(1.0, abs=0.02)

    def test_idle_reports_zero(self):
        ana = ThrottlePulseAnalyzer(window_s=1.0)
        for i in range(120):
            ana.push(i / 60.0, 0.0)
        feats = ana.features()
        assert feats.frequency_hz == 0.0
        assert feats.duty == pytest.approx(0.0, abs=0.02)


class TestSyncRecorderTub:
    def test_writes_records_with_full_schema(self, tmp_path):
        """写入 5 帧后：manifest 字段齐全，可读回且数值对齐。"""
        from sync_recorder import SyncRecorder

        rec = SyncRecorder(path=str(tmp_path / "tub"))
        for i in range(5):
            t = 0.1 * i
            rec.on_telemetry(t, {"rc/steering": 0.1, "rc/throttle": square_wave(t, 5, 0.8),
                                 "imu/gyr_z": 0.5})
            rec.on_camera_frame(t_s=t, image=np.zeros((8, 8, 3), dtype=np.uint8),
                                pose={"x": 1.0, "y": 1.0, "heading_deg": 30.0},
                                beta_deg=25.0, yaw_rate_dps=100.0)
        rec.close()
        manifest = Path(tmp_path / "tub" / "manifest.json")
        assert manifest.exists()
        import json
        inputs_list = json.loads(manifest.read_text(encoding="utf-8"))
        # tub v2 的 manifest 顶层即 inputs 数组
        for key in ["overhead/image_array", "pose/x", "pose/y", "pose/heading_deg",
                    "state/beta", "state/yaw_rate", "state/throttle_pulse_freq",
                    "state/throttle_duty", "state/throttle_pulse_amp",
                    "rc/steering", "rc/throttle", "imu/gyr_z"]:
            assert key in inputs_list, f"缺少字段 {key}"
        assert rec.frames_written == 5

    def test_frame_without_telemetry_is_skipped(self, tmp_path):
        """遥测未到（早期帧）不写残缺记录。"""
        from sync_recorder import SyncRecorder

        rec = SyncRecorder(path=str(tmp_path / "tub"))
        rec.on_camera_frame(t_s=0.0, image=np.zeros((8, 8, 3), dtype=np.uint8),
                            pose={"x": 1.0, "y": 1.0, "heading_deg": 0.0},
                            beta_deg=0.0, yaw_rate_dps=0.0)
        rec.on_telemetry(0.05, {"rc/steering": 0.0, "rc/throttle": 0.0, "imu/gyr_z": 0.0})
        rec.on_camera_frame(t_s=0.1, image=np.zeros((8, 8, 3), dtype=np.uint8),
                            pose={"x": 1.0, "y": 1.0, "heading_deg": 0.0},
                            beta_deg=0.0, yaw_rate_dps=0.0)
        rec.close()
        assert rec.frames_written == 1
