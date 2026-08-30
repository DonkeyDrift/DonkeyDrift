# -*- coding: utf-8 -*-
"""β（侧滑角）估计器（RFC 第 5 节）。

输入：俯拍位姿序列（标签帧，低频噪声但绝对值准）+ 陀螺仪横摆角速度
（高频可靠，用于标签帧间与丢帧间隙）。

结构（互补滤波建在 heading 域，避免与 β 视觉值重复计数陀螺贡献）：
- heading_est ← heading_est + r·dt（陀螺预测，每步）
- heading_est ← heading_est + α·(标签 heading − heading_est)（视觉校正）
- course = 位姿差分（割线角 + 半步外推，无低通——低通对匀速旋转
  航迹有稳态滞后；位置噪声由 heading 互补滤波吸收）
- β = wrap(heading_est − course)

锚定：直行/静止段调用 anchor() 清空状态重新锁定，抑制累积漂移。
对外角度单位为度，范围 (-180, 180]。
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class PoseSample:
    x: float
    y: float
    heading_deg: float
    t_s: float


@dataclass
class BetaEstimate:
    beta_deg: float
    course_deg: Optional[float]   # 航迹角（度，None=尚无足够位移）
    heading_deg: Optional[float]  # 融合后的车头朝向


def wrap_deg(angle: float) -> float:
    """归一化到 (-180, 180]。"""
    a = (angle + 180.0) % 360.0 - 180.0
    return a if a != -180.0 else 180.0


class BetaEstimator:
    def __init__(self, visual_weight: float = 0.3, min_step_m: float = 0.02,
                 beta_decay_s: float = 0.3):
        self._alpha = visual_weight
        self._min_step_m = min_step_m
        self._beta_decay_s = beta_decay_s
        self._prev: Optional[PoseSample] = None
        self._course_deg: Optional[float] = None
        self._last_raw_course: Optional[float] = None
        self._heading_deg: Optional[float] = None
        self._beta_deg: float = 0.0
        self._last_t: Optional[float] = None

    # 测试注入口：直接设定内部状态，验证滤波层本身
    def _set_internal(self, heading_deg: float, course_deg: float) -> None:
        self._heading_deg = heading_deg
        self._course_deg = course_deg

    def anchor(self) -> None:
        """锚定：已知 β≈0（直行/静止）时清空状态重新锁定，抑制累积漂移。"""
        self._heading_deg = None
        self._course_deg = None
        self._last_raw_course = None
        self._prev = None
        self._beta_deg = 0.0

    def update(self, pose: Optional[PoseSample], yaw_rate_dps: float,
               t_s: Optional[float] = None) -> BetaEstimate:
        """推进一个时步。pose=None 表示本时步无标签帧（丢帧间隙），
        仅陀螺预测 heading；此时必须显式给 t_s 供积分。"""
        now = t_s if t_s is not None else (pose.t_s if pose is not None else self._last_t)
        dt = 0.0
        if self._last_t is not None and now is not None:
            dt = max(now - self._last_t, 0.0)
        if now is not None:
            self._last_t = now

        # 1) heading 互补滤波：陀螺预测 →（有标签时）视觉校正
        if self._heading_deg is not None and dt > 0:
            self._heading_deg = wrap_deg(self._heading_deg + yaw_rate_dps * dt)
        if pose is not None:
            if self._heading_deg is None:
                self._heading_deg = pose.heading_deg
            else:
                innovation = wrap_deg(pose.heading_deg - self._heading_deg)
                self._heading_deg = wrap_deg(self._heading_deg + self._alpha * innovation)

        # 2) 航迹角差分（静止保护：位距不足不更新；半步外推消割线滞后）
        stationary = False
        if pose is not None and self._prev is not None:
            dx, dy = pose.x - self._prev.x, pose.y - self._prev.y
            if math.hypot(dx, dy) >= self._min_step_m:
                raw_course = math.degrees(math.atan2(dy, dx))
                if self._last_raw_course is not None and dt > 0:
                    rate = wrap_deg(raw_course - self._last_raw_course) / dt
                    raw_course = wrap_deg(raw_course + rate * dt / 2.0)
                self._last_raw_course = raw_course
                self._course_deg = raw_course
            else:
                stationary = True

        # 3) β = 融合 heading − 航迹角；静止时速度≈0 无侧滑可言，
        #    冻结的旧 β 按时间常数衰减到 0（防误读与 AUTO 误触发接管）
        if pose is not None:
            self._prev = pose
        if stationary and self._course_deg is not None:
            decay = math.exp(-dt / self._beta_decay_s) if dt > 0 else 0.0
            self._beta_deg = self._beta_deg * decay
        elif self._heading_deg is not None and self._course_deg is not None:
            self._beta_deg = wrap_deg(self._heading_deg - self._course_deg)

        return BetaEstimate(beta_deg=self._beta_deg,
                            course_deg=self._course_deg,
                            heading_deg=self._heading_deg)
