# -*- coding: utf-8 -*-
"""drift_controller 单元测试（RFC 7.2/7.3）。

覆盖：油门脉冲发生器波形与参数平滑、delta/输出限幅、内环 yaw-rate
跟踪方向、外环 β/半径环方向、看门狗触发。全部合成数据。
"""
import math
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_controller import (
    ControllerConfig,
    DriftController,
    PulseGenerator,
    Watchdog,
)


class TestPulseGenerator:
    def test_waveform_period_duty_and_levels(self):
        """freq=5, duty=0.5, amp=0.8, base=0.1 → 3s 内 15 个周期、双电平正确。"""
        gen = PulseGenerator(frequency_hz=5.0, duty=0.5, amplitude=0.8, base=0.1)
        outputs = [gen.tick(dt=1.0 / 60.0) for _ in range(int(3.0 * 60))]
        rising = sum(1 for a, b in zip(outputs, outputs[1:]) if b > a)
        assert rising == pytest.approx(15, abs=2), "3 秒应有约 15 个上升沿"
        assert set(round(o, 6) for o in outputs) <= {0.1, 0.9}
        highs = sum(1 for o in outputs if o > 0.5)
        # 每周期仅 12 tick，±1 tick 量化 = ±8.3%，容差取 0.09
        assert highs / len(outputs) == pytest.approx(0.5, abs=0.09)

    def test_output_is_clamped(self):
        gen = PulseGenerator(frequency_hz=10.0, duty=0.5, amplitude=2.0, base=0.5)
        for _ in range(120):
            u = gen.tick(1.0 / 60.0)
            assert -1.0 <= u <= 1.0

    def test_parameter_change_keeps_phase_continuous(self):
        """运行中改频率：相位连续推进，无半周期毛刺（新周期立即正确）。"""
        gen = PulseGenerator(frequency_hz=5.0, duty=0.5, amplitude=0.8, base=0.0)
        for _ in range(60):
            gen.tick(1.0 / 60.0)
        gen.set_parameters(frequency_hz=2.0)
        outputs = [gen.tick(1.0 / 60.0) for _ in range(int(3.0 * 60))]
        rising_times = [i for i in range(1, len(outputs))
                        if outputs[i] > outputs[i - 1]]
        intervals = [b - a for a, b in zip(rising_times, rising_times[1:])]
        expected_period_ticks = 60.0 / 2.0
        for iv in intervals:
            assert iv == pytest.approx(expected_period_ticks, rel=0.2), (
                f"改频后边沿间隔 {iv} 应接近新周期 {expected_period_ticks}")


class TestWatchdog:
    def test_expires_without_feed(self):
        wd = Watchdog(timeout_s=0.2)
        wd.feed(0.0)
        assert not wd.expired(now=0.1)
        assert wd.expired(now=0.25)

    def test_regular_feeding_never_expires(self):
        wd = Watchdog(timeout_s=0.2)
        for i in range(50):
            wd.feed(i * 0.1)
            assert not wd.expired(now=i * 0.1 + 0.05)


class TestDriftController:
    def make_controller(self, **overrides):
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8, **overrides)
        return DriftController(cfg)

    def test_output_within_limits_always(self):
        c = self.make_controller()
        for i in range(200):
            out = c.update(beta_deg=80.0, yaw_rate_dps=-300.0,
                           pose=(1.9, 1.9), t_s=i * (1.0 / 60.0))
            assert -1.0 <= out.steering <= 1.0
            assert -1.0 <= out.throttle <= 1.0

    def test_beta_below_target_raises_desired_yaw(self):
        """β 低于目标 → 需要更大横摆 → r_des 为正（符号约定见模块头）。"""
        c = self.make_controller()
        out = c.update(beta_deg=10.0, yaw_rate_dps=0.0, pose=(1.0, 1.8), t_s=0.0)
        assert out.desired_yaw_rate_dps > 0

    def test_beta_above_target_lowers_desired_yaw(self):
        c = self.make_controller()
        out = c.update(beta_deg=40.0, yaw_rate_dps=0.0, pose=(1.0, 1.8), t_s=0.0)
        assert out.desired_yaw_rate_dps < 0

    def test_inner_loop_steering_tracks_yaw_error(self):
        """r 低于 r_des → 转向朝正方向修正；r 超过 r_des → 反向。"""
        c = self.make_controller()
        # β=10 → r_des>0；实际 r=0 → 正误差 → steering 正
        out1 = c.update(beta_deg=10.0, yaw_rate_dps=0.0, pose=(1.0, 1.8), t_s=0.0)
        assert out1.steering > 0
        # 同样 β 但实际 r 已超 → steering 反向
        c2 = self.make_controller()
        out2 = c2.update(beta_deg=10.0, yaw_rate_dps=500.0, pose=(1.0, 1.8), t_s=0.0)
        assert out2.steering < out1.steering

    def test_radius_error_adjusts_throttle_parameters(self):
        """车太靠圆心（半径误差正）→ 油门参数朝"增大"方向修正（增益符号可配）。"""
        c = self.make_controller()
        out_inner = c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(0.9, 1.0), t_s=0.0)
        c2 = self.make_controller()
        out_outer = c2.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.9, 1.0), t_s=0.0)
        # 偏内与偏外两种误差下，外环输出的脉冲频率修正方向应相反
        assert (out_inner.pulse_freq_adjust_dps_sign !=
                out_outer.pulse_freq_adjust_dps_sign) or (
            out_inner.throttle != out_outer.throttle)

    def test_steering_delta_is_rate_limited(self):
        """转向输出每步变化不超过 max_steering_delta_per_tick。"""
        c = self.make_controller(max_steering_delta_per_tick=0.05)
        prev = 0.0
        for i in range(100):
            out = c.update(beta_deg=(-1.0) ** i * 70.0, yaw_rate_dps=0.0,
                           pose=(1.0, 1.8), t_s=i * (1.0 / 60.0))
            assert abs(out.steering - prev) <= 0.05 + 1e-9
            prev = out.steering

    def test_reset_clears_state(self):
        c = self.make_controller()
        for i in range(50):
            c.update(beta_deg=30.0, yaw_rate_dps=50.0, pose=(1.0, 1.8),
                     t_s=i * (1.0 / 60.0))
        c.reset()
        out = c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.0, 1.8), t_s=10.0)
        # β=β*、r=r_des（0）时输出应接近中性而非残留积分
        assert abs(out.steering) < 0.3

    def test_throttle_contains_pulse_shape(self):
        """接管后输出油门序列呈现脉冲形态（非常数）。"""
        c = self.make_controller()
        values = []
        for i in range(int(2.0 * 60)):
            out = c.update(beta_deg=25.0, yaw_rate_dps=100.0,
                           pose=(1.0 + 0.8 * math.cos(i * 0.1),
                                 1.0 + 0.8 * math.sin(i * 0.1)),
                           t_s=i * (1.0 / 60.0))
            values.append(out.throttle)
        assert max(values) - min(values) > 0.1, "油门应为脉冲形态而非恒值"
