# -*- coding: utf-8 -*-
"""β 估计器单元测试（RFC 第 5 节）：航迹差分、互补滤波、wrap、锚定。

合成场景：圆周运动下生成位姿序列（可叠加恒定 heading 偏置模拟漂移侧滑角），
以及带噪视觉 β + 干净陀螺的融合场景。纯计算，无 I/O。
"""
import math
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from state_estimator import BetaEstimator, PoseSample


def circle_pose(t_s, radius=0.8, omega=2.0, beta_deg=0.0, center=(1.0, 1.0)):
    """生成沿逆时针圆周运动的位姿；heading 相对切线额外偏置 beta_deg（漂移）。"""
    cx, cy = center
    ang = omega * t_s
    x = cx + radius * math.cos(ang)
    y = cy + radius * math.sin(ang)
    tangent_deg = math.degrees(ang) + 90.0  # 逆时针切线方向
    return PoseSample(x=x, y=y, heading_deg=tangent_deg + beta_deg, t_s=t_s)


class TestBetaEstimation:
    def test_pure_circle_gives_zero_beta(self):
        """无偏置圆周（普通行驶）→ β 应收敛到 0 附近。"""
        est = BetaEstimator()
        out = None
        for i in range(1, 121):
            out = est.update(circle_pose(i * 0.05), yaw_rate_dps=360 / (2 * math.pi) * 2.0)
        assert abs(out.beta_deg) < 2.0

    def test_constant_drift_angle_is_recovered(self):
        """heading 恒偏置 25°（漂移）→ β 应收敛到 25° 附近（容差 2°）。"""
        est = BetaEstimator()
        out = None
        for i in range(1, 121):
            out = est.update(circle_pose(i * 0.05, beta_deg=25.0),
                             yaw_rate_dps=360 / (2 * math.pi) * 2.0)
        assert out.beta_deg == pytest.approx(25.0, abs=2.0)

    def test_negative_drift_angle(self):
        est = BetaEstimator()
        out = None
        for i in range(1, 121):
            out = est.update(circle_pose(i * 0.05, beta_deg=-30.0),
                             yaw_rate_dps=360 / (2 * math.pi) * 2.0)
        assert out.beta_deg == pytest.approx(-30.0, abs=2.0)

    def test_stationary_pose_does_not_diverge(self):
        """静止（位距不足）不更新航迹角，β 保持上一估计，无 NaN/爆炸。"""
        est = BetaEstimator()
        out = est.update(PoseSample(x=1.0, y=1.0, heading_deg=10.0, t_s=0.0), yaw_rate_dps=0.0)
        for i in range(1, 20):
            out = est.update(PoseSample(x=1.0, y=1.0, heading_deg=10.0, t_s=0.05 * i),
                             yaw_rate_dps=0.0)
        assert math.isfinite(out.beta_deg)
        assert abs(out.beta_deg) < 1.0

    def test_stationary_decays_frozen_beta(self):
        """斜推后停住：冻结的旧 β（非零侧滑残影）应随静止时间衰减到 0，
        否则 AUTO 观察态会被冻结 β 误触发接管。"""
        est = BetaEstimator()
        # 沿 +x 直推但车头偏 -30°（β=-30° 的侧滑姿态），随后原地停住
        est.update(PoseSample(x=1.0, y=1.0, heading_deg=-30.0, t_s=0.0), yaw_rate_dps=0.0)
        for i in range(1, 16):
            est.update(PoseSample(x=1.0 + 0.03 * i, y=1.0, heading_deg=-30.0,
                                  t_s=0.05 * i), yaw_rate_dps=0.0)
        assert abs(est.update(PoseSample(x=1.45, y=1.0, heading_deg=-30.0, t_s=0.8),
                              yaw_rate_dps=0.0).beta_deg) > 15.0  # 运动中 β 确实非零
        t = 0.85
        for _ in range(40):  # 静止 2 秒（位距不足，course 冻结）
            out = est.update(PoseSample(x=1.45, y=1.0, heading_deg=-30.0, t_s=t),
                             yaw_rate_dps=0.0)
            t += 0.05
        assert abs(out.beta_deg) < 1.0, "静止 2s 后 β 应衰减到 0 附近"

    def test_moving_after_stationarity_recovers_beta(self):
        """静止衰减后恢复运动：β 立即回到新的 heading−course 差分，无残留。"""
        est = BetaEstimator()
        est.update(PoseSample(x=1.0, y=1.0, heading_deg=-30.0, t_s=0.0), yaw_rate_dps=0.0)
        for i in range(1, 11):  # 建立 β=-30
            est.update(PoseSample(x=1.0 + 0.03 * i, y=1.0, heading_deg=-30.0,
                                  t_s=0.05 * i), yaw_rate_dps=0.0)
        t = 0.55
        for _ in range(20):  # 静止衰减
            est.update(PoseSample(x=1.3, y=1.0, heading_deg=-30.0, t_s=t), yaw_rate_dps=0.0)
            t += 0.05
        # 恢复直行（heading=0 且沿 +x 移动 → β≈0）
        for i in range(1, 11):
            out = est.update(PoseSample(x=1.3 + 0.03 * i, y=1.0, heading_deg=0.0, t_s=t),
                             yaw_rate_dps=0.0)
            t += 0.05
        assert abs(out.beta_deg) < 2.0, "恢复运动后 β 应反映新姿态，而非残留"

    def test_beta_wraps_across_180(self):
        """β 接近 ±180 边界时按最短角差处理，不出现 359° 之类的伪值。"""
        est = BetaEstimator()
        # heading=175°，航迹角=-175° → 真实 β=350°→wrap 为 -10°
        est._set_internal(heading_deg=175.0, course_deg=-175.0)
        out = est.update(PoseSample(x=1.5, y=1.0, heading_deg=175.0, t_s=1.0),
                         yaw_rate_dps=0.0)
        assert out.beta_deg == pytest.approx(-10.0, abs=1.0)
        assert -180.0 <= out.beta_deg <= 180.0


class TestComplementaryFilter:
    def test_fusion_reduces_noise(self):
        """带噪视觉 β（σ=3°）+ 干净陀螺 → 融合输出噪声明显小于输入噪声。

        场景：静止车（位姿不动，course 固定），视觉 heading 每帧带高斯噪声，
        β_visual 即带噪观测；α=0.2 的一阶融合等效低通，输出 std 应显著小于 3°。
        """
        import random
        random.seed(42)
        est = BetaEstimator(visual_weight=0.2)
        est._set_internal(heading_deg=25.0, course_deg=0.0)
        noisy_inputs = []
        outputs = []
        for i in range(1, 301):
            noisy = 25.0 + random.gauss(0.0, 3.0)
            noisy_inputs.append(noisy)
            pose = PoseSample(x=1.0, y=1.0, heading_deg=noisy, t_s=0.05 * i)
            outputs.append(est.update(pose, yaw_rate_dps=0.0).beta_deg)
        import statistics
        tail_in = statistics.pstdev(noisy_inputs[100:])
        tail_out = statistics.pstdev(outputs[100:])
        assert tail_in == pytest.approx(3.0, abs=0.5)
        assert tail_out < tail_in * 0.5, (
            f"融合后 std {tail_out:.2f}° 应显著小于输入 {tail_in:.2f}°")

    def test_gyro_carries_fast_changes(self):
        """视觉丢帧（pose=None）时，陀螺积分维持 heading/β 的快速变化分量。"""
        est = BetaEstimator(visual_weight=0.1)
        est._set_internal(heading_deg=20.0, course_deg=0.0)
        for i in range(1, 11):
            out = est.update(None, yaw_rate_dps=60.0, t_s=0.05 * i)
        assert out.beta_deg > 25.0, "陀螺正横摆应推动 β 增大"


class TestAnchoring:
    def test_anchor_resets_to_zero(self):
        est = BetaEstimator()
        est._set_internal(heading_deg=40.0, course_deg=0.0)
        out = est.update(PoseSample(x=1.0, y=1.0, heading_deg=40.0, t_s=0.0),
                         yaw_rate_dps=0.0)
        assert abs(out.beta_deg - 40.0) < 5.0
        est.anchor()
        out = est.update(PoseSample(x=1.0, y=1.0, heading_deg=0.0, t_s=0.05),
                         yaw_rate_dps=0.0)
        assert abs(out.beta_deg) < 5.0
