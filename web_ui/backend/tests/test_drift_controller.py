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


class TestNanGuards:
    """NaN/inf 防线：控制器不得消化非有限输入（编排层捕获 ValueError
    后走看门狗路径）。"""

    def make_controller(self, **overrides):
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8, **overrides)
        return DriftController(cfg)

    @pytest.mark.parametrize("kwargs", [
        dict(beta_deg=float("nan")),
        dict(beta_deg=float("inf")),
        dict(yaw_rate_dps=float("nan")),
        dict(yaw_rate_dps=float("-inf")),
        dict(pose=(float("nan"), 1.8)),
        dict(pose=(1.0, float("inf"))),
        dict(t_s=float("nan")),
        dict(t_s=float("inf")),
    ])
    def test_nonfinite_inputs_raise_value_error(self, kwargs):
        c = self.make_controller()
        args = dict(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.0, 1.8), t_s=0.0)
        args.update(kwargs)
        with pytest.raises(ValueError):
            c.update(**args)

    def test_controller_usable_after_nan_rejection(self):
        """拒绝 NaN 后控制器状态未被污染，下一拍正常输出。"""
        c = self.make_controller()
        with pytest.raises(ValueError):
            c.update(beta_deg=float("nan"), yaw_rate_dps=0.0,
                     pose=(1.0, 1.8), t_s=0.0)
        out = c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.0, 1.8),
                       t_s=1.0 / 60.0)
        assert math.isfinite(out.steering) and math.isfinite(out.throttle)


class TestSteeringRateLimit:
    """delta 限幅 dt 化：限幅是转向摆速量纲（/s），每步上限 = rate × dt。
    控制节率=相机帧率（20~60fps 可变），按 tick 固定限幅会让摆速随帧率漂移，
    剧烈运动的难帧（20fps）恰好削减转向权限。"""

    def _two_ticks(self, cfg):
        """同一大误差输入打两拍，返回第二拍相对第一拍的转向增量。"""
        c = DriftController(cfg)
        base = dict(beta_deg=-70.0, yaw_rate_dps=0.0, pose=(1.0, 1.8))
        o0 = c.update(t_s=0.0, **base)
        return c, o0

    def test_rate_limit_scales_with_dt(self):
        """默认 rate=3.0/s：60fps 每步 0.05、20fps 每步 0.15。"""
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8)
        c, o0 = self._two_ticks(cfg)
        o1 = c.update(beta_deg=-70.0, yaw_rate_dps=0.0, pose=(1.0, 1.8),
                      t_s=1.0 / 60.0)
        assert o1.steering - o0.steering == pytest.approx(0.05, abs=1e-9)

        c2, o20 = self._two_ticks(ControllerConfig(
            beta_target_deg=25.0, circle_center=(1.0, 1.0), circle_radius=0.8))
        o21 = c2.update(beta_deg=-70.0, yaw_rate_dps=0.0, pose=(1.0, 1.8),
                        t_s=0.05)  # 20fps 步长
        assert o21.steering - o20.steering == pytest.approx(0.15, abs=1e-9), (
            "20fps 下每步限幅应按 dt 放大到 0.15，而非仍按 tick 钉在 0.05")

    def test_legacy_delta_field_maps_to_rate(self):
        """deprecated 兼容：只传旧字段 max_steering_delta_per_tick 时
        映射 rate = 旧值 × 60（保持 60fps 下行为完全一致）。"""
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8, max_steering_delta_per_tick=0.02)
        c, o0 = self._two_ticks(cfg)
        o1 = c.update(beta_deg=-70.0, yaw_rate_dps=0.0, pose=(1.0, 1.8),
                      t_s=1.0 / 60.0)
        assert o1.steering - o0.steering == pytest.approx(0.02, abs=1e-9)

    def test_new_rate_field_overrides_legacy(self):
        """显式传 max_steering_rate_per_s 时旧字段失效。"""
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8,
                               max_steering_delta_per_tick=0.02,
                               max_steering_rate_per_s=6.0)
        c, o0 = self._two_ticks(cfg)
        o1 = c.update(beta_deg=-70.0, yaw_rate_dps=0.0, pose=(1.0, 1.8),
                      t_s=1.0 / 60.0)
        assert o1.steering - o0.steering == pytest.approx(0.1, abs=1e-9)


class TestPulseHotUpdate:
    """脉冲参数热更新：duty/amplitude/base 运行中改 cfg 必须当拍生效
    （PulseGenerator 相位连续，全量 set_parameters 安全）。"""

    def test_duty_amplitude_base_hot_updated(self):
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8)
        c = DriftController(cfg)
        for i in range(30):  # 先按初始参数跑 0.5s
            c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.0, 1.8),
                     t_s=i / 60.0)
        # Web 面板式热改：恒定高电平 0.3+0.2=0.5（初始参数 0.1/0.7 脉冲，
        # 不可能输出恒 0.5，可区分新旧行为）
        cfg.pulse_duty = 1.0
        cfg.pulse_amplitude = 0.2
        cfg.pulse_base = 0.3
        outs = [c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=(1.0, 1.8),
                         t_s=(30 + i) / 60.0).throttle for i in range(30)]
        assert all(o == pytest.approx(0.5, abs=1e-9) for o in outs), (
            "duty/amplitude/base 热改后应立即生效；旧实现只在 reset 时读取")


class TestRadiusLoopSign:
    """半径环符号（RFC §7.3 机理：频率高→自旋强→半径小）。
    偏内（radius_err>0）应**降频**扩半径——默认 sign=-1 负反馈；
    旧实现偏内增频是正反馈。M2 实证若机理相反，置 +1 翻转。"""

    def _update_at(self, sign, pose):
        cfg = ControllerConfig(beta_target_deg=25.0, circle_center=(1.0, 1.0),
                               circle_radius=0.8, radius_freq_sign=sign)
        c = DriftController(cfg)
        return c, c.update(beta_deg=25.0, yaw_rate_dps=100.0, pose=pose, t_s=0.0)

    def test_inside_car_lowers_freq_by_default(self):
        """车在圆心内侧（dist<R）→ 频率修正为负（降频扩半径）。"""
        c, out = self._update_at(-1.0, pose=(0.9, 1.0))  # dist=0.1 → err=+0.7
        assert out.pulse_freq_adjust_dps_sign == -1
        assert c._pulse.frequency_hz == pytest.approx(4.0 - 2.0 * 0.7)

    def test_outside_car_raises_freq_by_default(self):
        c, out = self._update_at(-1.0, pose=(1.9, 1.0))  # dist=0.9 → err=-0.1
        assert out.pulse_freq_adjust_dps_sign == 1

    def test_sign_flippable_for_m2_tuning(self):
        """机理实证相反时置 +1：偏内增频。"""
        c, out = self._update_at(+1.0, pose=(0.9, 1.0))
        assert out.pulse_freq_adjust_dps_sign == 1
        assert c._pulse.frequency_hz == pytest.approx(4.0 + 2.0 * 0.7)


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
        """β 超目标 → r_des 应比 β 不足时更低（围绕 v/R 前馈基准修正，非单纯变负）。"""
        c = self.make_controller()
        out_low = c.update(beta_deg=10.0, yaw_rate_dps=0.0, pose=(1.0, 1.8), t_s=0.0)
        c2 = self.make_controller()
        out_high = c2.update(beta_deg=40.0, yaw_rate_dps=0.0, pose=(1.0, 1.8), t_s=0.0)
        assert out_high.desired_yaw_rate_dps < out_low.desired_yaw_rate_dps

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
