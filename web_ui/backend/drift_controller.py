# -*- coding: utf-8 -*-
"""漂移控制器（RFC 7.2/7.3）：级联 PID + 油门脉冲发生器 + 限幅 + 看门狗。

符号约定（全模块统一，与 state_estimator 一致）：
- 逆时针为正（heading 增、yaw rate 正）；
- β>0 = 车头在航迹左侧（车向右外侧滑）；β 增大需要正的额外横摆，
  故 r_des = k_beta·(β* − β)，β 低于目标 → r_des>0 → steering 正向修正；
- 油门值域 [-1, 1]，下发链路另做 ×100 缩放（不在本模块）。

结构：
- 外环（慢，随帧更新）：β 误差 → 期望横摆率；半径误差 → 脉冲频率修正
- 内环（快，60Hz）：yaw-rate 误差 → 转向（比例 + 积分，带积分限幅）
- 油门脉冲发生器：参数 (freq, duty, amp, base)，相位连续推进
- 保护：输出限幅、转向 delta 限幅（补偿固件无 slew 限幅）、看门狗
"""
import math
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class ControllerConfig:
    beta_target_deg: float = 25.0
    circle_center: Tuple[float, float] = (1.0, 1.0)
    circle_radius: float = 0.8
    nominal_speed_mps: float = 2.0    # 定圆名义车速（前馈计算用）
    # 外环
    k_beta: float = 4.0              # (β*−β)[°] → r_des 修正[°/s]
    max_yaw_rate_dps: float = 300.0
    k_radius_to_freq: float = 2.0    # 半径误差[m] → 频率修正[Hz]（方向由 radius_freq_sign 定）
    radius_freq_sign: float = -1.0   # 半径环符号：-1=按 RFC §7.3 机理负反馈
                                     # （偏内→降频→自旋弱→扩半径）；M2 实证若
                                     # 机理相反，置 +1 翻转
    # 内环
    k_yaw: float = 0.004             # yaw 误差[°/s] → steering
    k_yaw_i: float = 0.002           # 积分消稳态差（初值，明天按实车整定）
    integral_limit: float = 0.6      # 须容纳定圆基准横摆所需的稳态转向量（v/R·r_max⁻¹）
    # 脉冲发生器初值（运行中由外环修正）
    pulse_freq_hz: float = 4.0
    pulse_duty: float = 0.5
    pulse_amplitude: float = 0.6
    pulse_base: float = 0.1
    # 保护
    # 转向摆速限幅 [/s]：每步上限 = rate × dt（节率=相机帧率 20~60fps 可变，
    # 按 tick 固定限幅会让摆速随帧率漂移）。None=沿用旧字段 ×60 兼容映射。
    max_steering_rate_per_s: Optional[float] = None
    # deprecated：每 tick 限幅量纲，仅在未设置 max_steering_rate_per_s 时
    # 按 ×60 映射为摆速（0.05×60=3.0/s，保持 60fps 下行为一致）
    max_steering_delta_per_tick: float = 0.05
    throttle_min: float = -1.0
    throttle_max: float = 1.0

    @property
    def effective_max_steering_rate_per_s(self) -> float:
        """生效的转向摆速上限：新字段优先；未设置时旧字段（deprecated）×60 映射。
        控制律与 /config 展示共用此口径，避免两处各自映射不一致。"""
        if self.max_steering_rate_per_s is not None:
            return self.max_steering_rate_per_s
        return self.max_steering_delta_per_tick * 60.0


@dataclass
class ControlOutput:
    steering: float
    throttle: float
    desired_yaw_rate_dps: float
    pulse_freq_adjust_dps_sign: int   # 半径环频率修正方向（+1/0/−1，供诊断）


class PulseGenerator:
    """油门脉冲发生器：相位连续推进，参数运行时可变（RFC 7.3）。

    高电平段 throttle = base + amplitude，低电平段 throttle = base；
    输出统一钳位 [-1, 1]。改参数只改"每个周期的形状"，相位不清零，
    避免半周期突变。
    """

    def __init__(self, frequency_hz: float, duty: float, amplitude: float, base: float):
        self.frequency_hz = float(frequency_hz)
        self.duty = float(duty)
        self.amplitude = float(amplitude)
        self.base = float(base)
        self._phase = 0.0  # 0..1

    def set_parameters(self, frequency_hz: Optional[float] = None,
                       duty: Optional[float] = None,
                       amplitude: Optional[float] = None,
                       base: Optional[float] = None) -> None:
        if frequency_hz is not None:
            self.frequency_hz = max(0.0, float(frequency_hz))
        if duty is not None:
            self.duty = min(1.0, max(0.0, float(duty)))
        if amplitude is not None:
            self.amplitude = float(amplitude)
        if base is not None:
            self.base = float(base)

    def tick(self, dt: float) -> float:
        if self.frequency_hz <= 0.0:
            u = self.base
        else:
            self._phase = (self._phase + self.frequency_hz * dt) % 1.0
            u = self.base + self.amplitude if self._phase < self.duty else self.base
        return min(1.0, max(-1.0, u))


class Watchdog:
    """丢帧/断线看门狗：超时未 feed 即过期（触发 Park + MODE 0 的判定由编排层执行）。"""

    def __init__(self, timeout_s: float = 0.2):
        self.timeout_s = timeout_s
        self._last_feed: Optional[float] = None

    def feed(self, t_s: float) -> None:
        self._last_feed = t_s

    def expired(self, now: float) -> bool:
        if self._last_feed is None:
            return True
        return (now - self._last_feed) > self.timeout_s


class DriftController:
    def __init__(self, config: ControllerConfig):
        self.cfg = config
        self._pulse = PulseGenerator(config.pulse_freq_hz, config.pulse_duty,
                                     config.pulse_amplitude, config.pulse_base)
        self._yaw_integral = 0.0
        self._last_steering = 0.0
        self._last_t: Optional[float] = None
        self._watchdog = Watchdog(timeout_s=0.2)

    @property
    def watchdog(self) -> Watchdog:
        return self._watchdog

    def reset(self) -> None:
        self._yaw_integral = 0.0
        self._last_steering = 0.0
        self._last_t = None
        self._pulse = PulseGenerator(self.cfg.pulse_freq_hz, self.cfg.pulse_duty,
                                     self.cfg.pulse_amplitude, self.cfg.pulse_base)

    def update(self, beta_deg: float, yaw_rate_dps: float,
               pose: Tuple[float, float], t_s: float) -> ControlOutput:
        # NaN/inf 防线：非有限输入直接抛错，由编排层捕获走看门狗路径；
        # 控制器绝不消化 NaN（比较语义下限幅/积分会被钉死在边界）
        if not (math.isfinite(beta_deg) and math.isfinite(yaw_rate_dps)
                and math.isfinite(t_s)
                and math.isfinite(pose[0]) and math.isfinite(pose[1])):
            raise ValueError(
                f"控制器输入含 NaN/inf：beta_deg={beta_deg!r} "
                f"yaw_rate_dps={yaw_rate_dps!r} pose={pose!r} t_s={t_s!r}")
        self._watchdog.feed(t_s)
        dt = 0.0
        if self._last_t is not None:
            dt = max(t_s - self._last_t, 0.0)
        self._last_t = t_s

        # ── 外环：前馈（定圆所需基准横摆 = v/R）+ β 误差修正 ──
        # 稳态漂移时总横摆必须等于航迹角速度 v/R（非零），修正量围绕该基准。
        feedforward_dps = (self.cfg.nominal_speed_mps / self.cfg.circle_radius
                           * 180.0 / math.pi)
        beta_err = self.cfg.beta_target_deg - beta_deg
        r_des = feedforward_dps + self.cfg.k_beta * beta_err
        r_des = max(-self.cfg.max_yaw_rate_dps, min(self.cfg.max_yaw_rate_dps, r_des))

        # ── 外环：半径误差 → 脉冲频率修正。RFC §7.3 机理：频率高→自旋强→
        #    半径小；故负反馈为 偏内→降频→扩半径（radius_freq_sign=-1）。
        #    M2 实证若机理相反，把 radius_freq_sign 置 +1 整体翻转。──
        dx = pose[0] - self.cfg.circle_center[0]
        dy = pose[1] - self.cfg.circle_center[1]
        dist = math.hypot(dx, dy)
        radius_err = self.cfg.circle_radius - dist  # >0=车偏内（需扩半径）
        freq_adjust = (self.cfg.radius_freq_sign
                       * self.cfg.k_radius_to_freq * radius_err)
        if freq_adjust > 1e-9:
            freq_sign = 1
        elif freq_adjust < -1e-9:
            freq_sign = -1
        else:
            freq_sign = 0
        new_freq = min(12.0, max(0.0, self.cfg.pulse_freq_hz + freq_adjust))
        # 四参数每拍全量下发：Web 面板热改 duty/amplitude/base 当拍生效
        # （PulseGenerator 相位连续，改参数无半周期毛刺）
        self._pulse.set_parameters(frequency_hz=new_freq,
                                   duty=self.cfg.pulse_duty,
                                   amplitude=self.cfg.pulse_amplitude,
                                   base=self.cfg.pulse_base)

        # ── 内环：yaw-rate 误差 → 转向（P + 抗饱和 I）──
        yaw_err = r_des - yaw_rate_dps
        self._yaw_integral = max(-self.cfg.integral_limit,
                                 min(self.cfg.integral_limit,
                                     self._yaw_integral + self.cfg.k_yaw_i * yaw_err * dt))
        steering_raw = self.cfg.k_yaw * yaw_err + self._yaw_integral
        steering = min(1.0, max(-1.0, steering_raw))

        # delta 限幅 dt 化（补偿固件无 slew 限幅）：摆速上限 × 本拍 dt。
        # 首帧 dt=0 沿用 1/60 名义步长：从 0 起步同样限幅。
        rate = self.cfg.effective_max_steering_rate_per_s
        max_step = rate * (dt if dt > 0 else 1.0 / 60.0)
        steering = min(self._last_steering + max_step,
                       max(self._last_steering - max_step, steering))
        self._last_steering = steering

        # ── 油门：脉冲发生器 ──
        throttle = self._pulse.tick(dt if dt > 0 else 1.0 / 60.0)
        throttle = min(self.cfg.throttle_max, max(self.cfg.throttle_min, throttle))

        return ControlOutput(steering=steering, throttle=throttle,
                             desired_yaw_rate_dps=r_des,
                             pulse_freq_adjust_dps_sign=freq_sign)
