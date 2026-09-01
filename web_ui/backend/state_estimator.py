# -*- coding: utf-8 -*-
"""β（侧滑角）估计器（RFC 第 5 节）。

输入：俯拍位姿序列（标签帧，低频噪声但绝对值准）+ 陀螺仪横摆角速度
（高频可靠，用于标签帧间与丢帧间隙）。

结构（互补滤波建在 heading 域，避免与 β 视觉值重复计数陀螺贡献）：
- heading_est ← heading_est + r·dt（陀螺预测，每步）
- heading_est ← heading_est + α·(标签 heading − heading_est)（视觉校正）
- course = 位姿割线（0.2s 基线摊薄位姿噪声——逐帧差分在低速段帧位移
  贴近 2cm 阈值、被噪声主导方向随机，见交接文档 §4.4/§6；陀螺横摆率
  半程外推消割线滞后，假设 β̇≈0，β 瞬变期误差有界；无低通——低通对
  匀速旋转航迹有稳态滞后）
- β = wrap(heading_est − course)

锚定：直行/静止段调用 anchor() 清空状态重新锁定，抑制累积漂移。
对外角度单位为度，范围 (-180, 180]。
"""
import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


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
                 beta_decay_s: float = 0.3, course_baseline_s: float = 0.2,
                 pose_window_s: float = 0.5):
        self._alpha = visual_weight
        self._min_step_m = min_step_m
        self._beta_decay_s = beta_decay_s
        self._course_baseline_s = course_baseline_s
        self._pose_window_s = pose_window_s  # 须 > course_baseline_s，位姿滑窗
        self._poses: Deque[PoseSample] = deque()
        self._course_deg: Optional[float] = None
        self._heading_deg: Optional[float] = None
        self._beta_deg: float = 0.0
        self._last_t: Optional[float] = None
        # 非有限输入丢弃计数（NaN/inf 防线，诊断用）
        self.nan_dropped: int = 0

    # 测试注入口：直接设定内部状态，验证滤波层本身
    def _set_internal(self, heading_deg: float, course_deg: float) -> None:
        self._heading_deg = heading_deg
        self._course_deg = course_deg

    def anchor(self) -> None:
        """锚定：已知 β≈0（直行/静止）时清空状态重新锁定，抑制累积漂移。"""
        self._heading_deg = None
        self._course_deg = None
        self._poses.clear()
        self._beta_deg = 0.0
        self._last_t = None  # 时间状态一并重置：锚定后首帧 dt 重新起步

    def update(self, pose: Optional[PoseSample], yaw_rate_dps: float,
               t_s: Optional[float] = None) -> BetaEstimate:
        """推进一个时步。pose=None 表示本时步无标签帧（丢帧间隙），
        仅陀螺预测 heading；此时必须显式给 t_s 供积分。"""
        # NaN/inf 防线：非有限位姿按丢帧处理、非有限横摆率按 0 处理。
        # Python 比较语义下 NaN 会钉死 min/max 限幅并永久污染 heading，
        # 一个坏帧即可让控制链路满舵，必须在入口拦截。
        if pose is not None and not (
                math.isfinite(pose.x) and math.isfinite(pose.y)
                and math.isfinite(pose.heading_deg) and math.isfinite(pose.t_s)):
            self.nan_dropped += 1
            pose = None
        if not math.isfinite(yaw_rate_dps):
            self.nan_dropped += 1
            yaw_rate_dps = 0.0
        if t_s is not None and not math.isfinite(t_s):
            self.nan_dropped += 1
            t_s = None
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

        # 2) 航迹角割线：以 ≥course_baseline_s 前的点为基线——取**最新**满足
        #    跨度的前序点（与 drift_vision._baseline_index 语义一致；从最旧端
        #    取会把跨度钉死在 pose_window_s，baseline 参数失效）。无满基线点
        #    时回退最早点、跨度 <0.05s 不算，防除零噪声；基线位移不足
        #    min_step_m 视为静止（冻结 β 走衰减）。割线方向代表基线中点
        #    时刻，用陀螺横摆率外推 span/2 消滞后（β̇≈0 假设）。
        stationary = False
        if pose is not None:
            self._poses.append(pose)
            while self._poses and pose.t_s - self._poses[0].t_s > self._pose_window_s:
                self._poses.popleft()
            base: Optional[PoseSample] = None
            for p in reversed(self._poses):
                if pose.t_s - p.t_s >= self._course_baseline_s:
                    base = p
                    break
            if base is None and len(self._poses) >= 2:
                first = self._poses[0]
                if pose.t_s - first.t_s >= 0.05:
                    base = first
            if base is not None:
                dx, dy = pose.x - base.x, pose.y - base.y
                if math.hypot(dx, dy) >= self._min_step_m:
                    secant = math.degrees(math.atan2(dy, dx))
                    span = pose.t_s - base.t_s
                    self._course_deg = wrap_deg(secant + yaw_rate_dps * span / 2.0)
                else:
                    stationary = True

        # 3) β = 融合 heading − 航迹角；静止时速度≈0 无侧滑可言，
        #    冻结的旧 β 按时间常数衰减到 0（防误读与 AUTO 误触发接管）
        if stationary and self._course_deg is not None:
            # dt=0（同时戳重帧）表示时间没走：衰减因子应为 1（冻结），
            # 而非 0（清零）——否则重帧会瞬间抹掉 β
            decay = math.exp(-dt / self._beta_decay_s) if dt > 0 else 1.0
            self._beta_deg = self._beta_deg * decay
        elif self._heading_deg is not None and self._course_deg is not None:
            self._beta_deg = wrap_deg(self._heading_deg - self._course_deg)

        return BetaEstimate(beta_deg=self._beta_deg,
                            course_deg=self._course_deg,
                            heading_deg=self._heading_deg)
