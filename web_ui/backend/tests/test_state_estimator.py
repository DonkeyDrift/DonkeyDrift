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


class TestNanGuards:
    """NaN/inf 防线：非有限输入不得污染 heading/course 状态。

    实测确认 Python 比较语义下 min(0.6, nan)=0.6（积分钉满幅）、
    min(1.0, max(-1.0, nan))=-1.0（转向满舵），一个 NaN 位姿即可永久
    污染估计器。非有限位姿按丢帧处理、非有限横摆率按 0 处理并计数。
    """

    def _warm_up(self, est):
        """建立正常状态：沿 +x 移动、heading=10°，11 帧。"""
        for i in range(1, 11):
            est.update(PoseSample(x=1.0 + 0.03 * i, y=1.0, heading_deg=10.0,
                                  t_s=0.05 * i), yaw_rate_dps=5.0)

    def test_nan_pose_dropped_like_frame_loss(self):
        est = BetaEstimator()
        self._warm_up(est)
        poses_before = len(est._poses)
        out = est.update(PoseSample(x=float("nan"), y=1.0, heading_deg=10.0,
                                    t_s=0.55), yaw_rate_dps=5.0)
        assert math.isfinite(out.beta_deg)
        assert out.heading_deg is not None and math.isfinite(out.heading_deg)
        assert len(est._poses) == poses_before, "NaN 位姿不得进入位姿窗"
        assert est.nan_dropped >= 1
        # 后续正常帧无缝恢复：heading 未被 NaN 污染
        out = est.update(PoseSample(x=1.36, y=1.0, heading_deg=10.0, t_s=0.6),
                         yaw_rate_dps=5.0)
        assert math.isfinite(out.beta_deg)
        assert abs(out.beta_deg) < 30.0

    @pytest.mark.parametrize("field", ["x", "y", "heading_deg", "t_s"])
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_nonfinite_pose_fields_dropped(self, field, bad):
        est = BetaEstimator()
        self._warm_up(est)
        kwargs = dict(x=1.35, y=1.0, heading_deg=10.0, t_s=0.55)
        kwargs[field] = bad
        dropped_before = est.nan_dropped
        out = est.update(PoseSample(**kwargs), yaw_rate_dps=5.0)
        assert math.isfinite(out.beta_deg)
        assert est.nan_dropped == dropped_before + 1
        # _last_t 不得被非有限时戳污染
        assert est._last_t is not None and math.isfinite(est._last_t)

    def test_nan_yaw_rate_treated_as_zero(self):
        """非有限横摆率按 0 处理：heading 不得被 NaN 积分污染。"""
        est = BetaEstimator()
        est._set_internal(heading_deg=20.0, course_deg=0.0)
        est.update(None, yaw_rate_dps=0.0, t_s=0.0)
        out = est.update(None, yaw_rate_dps=float("nan"), t_s=0.05)
        assert est.nan_dropped == 1
        assert out.heading_deg == pytest.approx(20.0, abs=1e-9)
        assert out.beta_deg == pytest.approx(20.0, abs=1e-9)
        # 之后陀螺积分恢复正常
        out = est.update(None, yaw_rate_dps=60.0, t_s=0.10)
        assert out.heading_deg == pytest.approx(23.0, abs=1e-9)


class TestSecantBaselineSelection:
    """割线基线取点语义：应取"最新的满足跨度 ≥baseline 的前序点"
    （与 drift_vision._baseline_index 一致），稳态实际跨度 ≈course_baseline_s。

    旧实现从 deque 最旧端迭代取到窗内最旧点，稳态跨度=pose_window_s(0.5s)，
    course_baseline_s=0.2 成死参数。行为级验证：割线角度噪声 σ_ang ∝ 1/跨度，
    0.2s 基线的 β 抖动应约为 0.5s 基线的 2.5 倍（噪声摊薄减少换响应速度，
    这是 0.2s 基线的设计取舍，不是回归）。
    """

    def _beta_std(self, baseline_s, window_s, xs, ys):
        est = BetaEstimator(course_baseline_s=baseline_s, pose_window_s=window_s)
        dt = 1.0 / 60.0
        betas = []
        for i in range(1, 181):  # 3s @60Hz，0.5 m/s 向 +x，heading 恒 25°
            out = est.update(PoseSample(x=xs[i], y=ys[i], heading_deg=25.0,
                                        t_s=i * dt), yaw_rate_dps=0.0)
            betas.append(out.beta_deg)
        import statistics
        return statistics.pstdev(betas[-60:])

    def test_actual_span_follows_baseline_param(self):
        """同一噪声序列下，0.2s 基线的 β 抖动应显著大于 0.5s 基线
        （比值≈跨度反比 2.5）；旧实现两种基线都落在窗内最旧点 → 比值≈1。"""
        import random
        random.seed(7)
        dt = 1.0 / 60.0
        n = 181
        xs = [0.0] + [0.5 * i * dt + random.gauss(0.0, 0.008) for i in range(1, n)]
        ys = [1.0] + [1.0 + random.gauss(0.0, 0.008) for i in range(1, n)]
        std_02 = self._beta_std(0.2, 0.5, xs, ys)
        std_05 = self._beta_std(0.5, 0.6, xs, ys)
        ratio = std_02 / std_05
        assert ratio > 1.8, (
            f"0.2s/0.5s 基线抖动比 {ratio:.2f} 应≈2.5；≈1 说明基线参数没生效")
        assert std_02 > 4.0, (
            f"0.2s 基线抖动 {std_02:.1f}° 应≈6.5°（σ8mm/0.1m 位移）；"
            f"明显更小说明实际跨度远大于 0.2s")


class TestBoundaryConditions:
    """边界修复：dt=0 的静止衰减不得清零 β；anchor() 完备清理时间状态。"""

    def test_stationary_decay_frozen_at_dt_zero(self):
        """同时戳连续两帧（dt=0）：β 应保持不变——dt=0 表示时间没走，
        衰减因子应为 1（冻结），而非 0（清零）。"""
        est = BetaEstimator()
        # 沿 +x 直推、车头偏 -30°，建立非零 β
        est.update(PoseSample(x=1.0, y=1.0, heading_deg=-30.0, t_s=0.0),
                   yaw_rate_dps=0.0)
        for i in range(1, 16):
            est.update(PoseSample(x=1.0 + 0.03 * i, y=1.0, heading_deg=-30.0,
                                  t_s=0.05 * i), yaw_rate_dps=0.0)
        # 停住：持续静止 >0.2s，让割线基线也落在静止段内（否则基线仍指向
        # 运动段、位移超阈，走的是 course 重算分支而非衰减分支）
        t = 0.80
        for _ in range(7):  # 0.80..1.10，0.05s 步长
            est.update(PoseSample(x=1.45, y=1.0, heading_deg=-30.0, t_s=t),
                       yaw_rate_dps=0.0)
            t += 0.05
        out1 = est.update(PoseSample(x=1.45, y=1.0, heading_deg=-30.0, t_s=t),
                          yaw_rate_dps=0.0)
        out2 = est.update(PoseSample(x=1.45, y=1.0, heading_deg=-30.0, t_s=t),
                          yaw_rate_dps=0.0)
        assert out1.beta_deg != 0.0, "前提：静止早期 β 尚未衰减到 0"
        assert out2.beta_deg == pytest.approx(out1.beta_deg, abs=1e-12), (
            "dt=0 时 β 不应变化（衰减冻结），更不得直接清零")

    def test_anchor_clears_last_t(self):
        """anchor() 应清空 _last_t：锚定后首帧 dt 必须重新起步，
        不得携带锚定前的时间差。"""
        est = BetaEstimator()
        est.update(PoseSample(x=1.0, y=1.0, heading_deg=10.0, t_s=5.0),
                   yaw_rate_dps=0.0)
        est.anchor()
        assert est._last_t is None
        # 锚定后大时间跳变不产生 dt 冲击（陀螺积分从 None heading 重新锁定）
        out = est.update(PoseSample(x=1.0, y=1.0, heading_deg=10.0, t_s=100.0),
                         yaw_rate_dps=300.0)
        assert math.isfinite(out.beta_deg)
        assert abs(out.beta_deg) < 1.0, "锚定后静止同向，β 应≈0 而非被陀螺冲击"


class TestSecantBaselineCourse:
    """割线基线航迹角（交接文档 §6 遗留项）：控制链路 course_deg 从逐帧差分
    换 0.2s 割线基线，解决低速段帧位移贴近 2cm 阈值时被位姿噪声主导的问题。"""

    def test_low_speed_noisy_straight_line_recovers_beta(self):
        """低速（0.5m/s，60fps → 帧位移 0.83cm < 2cm 阈值）直行+位姿噪声：
        β 均值应收敛到真实侧滑角 25°，且抖动受限（割线基线摊薄噪声）。

        逐帧差分下超阈帧方向随机、其余帧按静止衰减，β 均值无法收敛。
        """
        import random
        import statistics
        random.seed(42)
        est = BetaEstimator()
        dt = 1.0 / 60.0
        betas = []
        for i in range(1, 181):  # 3s @60Hz，0.5 m/s 向 +x，heading 恒 25°（β=25）
            x = 0.5 * i * dt + random.gauss(0.0, 0.008)
            y = 1.0 + random.gauss(0.0, 0.008)
            out = est.update(PoseSample(x=x, y=y, heading_deg=25.0, t_s=i * dt),
                             yaw_rate_dps=0.0)
            betas.append(out.beta_deg)
        tail = betas[-60:]
        mean = statistics.mean(tail)
        std = statistics.pstdev(tail)
        assert mean == pytest.approx(25.0, abs=4.0), (
            f"低速段 β 均值 {mean:.1f}° 应收敛到 25°")
        # 0.2s 真实跨度的噪声下限：√2·σ_pos/(v·S)=√2·8mm/0.1m≈6.5°
        # （取点修正前 bug 跨度=0.5s 窗，该阈值 8° 是按错误跨度校准的）
        assert std < 10.0, f"低速段 β 抖动 std {std:.1f}° 应 < 10°"

    def test_slow_crawl_tracks_course(self):
        """爬行（0.15m/s，60fps → 帧位移 2.5mm 远低于 2cm 阈值）：
        割线基线 0.2s 累计 3cm 位移应正常解算航迹角；逐帧差分永不更新
        （course 保持 None、β 卡 0）。"""
        est = BetaEstimator()
        dt = 1.0 / 60.0
        out = None
        for i in range(1, 121):  # 2s 爬行向 +x，heading 恒 20°（β=20）
            out = est.update(PoseSample(x=0.15 * i * dt, y=1.0, heading_deg=20.0,
                                        t_s=i * dt), yaw_rate_dps=0.0)
        assert out.course_deg is not None, "爬行段应有航迹角输出"
        assert out.course_deg == pytest.approx(0.0, abs=5.0)
        assert out.beta_deg == pytest.approx(20.0, abs=5.0)
