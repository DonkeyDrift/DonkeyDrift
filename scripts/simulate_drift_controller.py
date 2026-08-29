# -*- coding: utf-8 -*-
"""漂移控制器离线闭环仿真（M3 验收）。

用玩具运动学模型（非车辆动力学，验证对象是控制器接线/方向/限幅/收敛）：
    r   ← r + (k_r·steering·r_max − r)·dt/T_r      横摆一阶滞后
    ψ̇   = v / R_ref                                  航迹角速度（恒速定圆）
    β   ← β + (r − ψ̇)·dt
    轨迹积分 course → (x, y) 供半径环反馈

用法：
    python scripts/simulate_drift_controller.py [--beta-target 25] [--csv out.csv]
判定：|β − β*| 稳态误差 < 3° 且无发散 → 仿真通过。
"""
import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_ui" / "backend"))

from drift_controller import ControllerConfig, DriftController

RAD2DEG = 180.0 / math.pi
DEG2RAD = math.pi / 180.0


def simulate(cfg: ControllerConfig, duration_s: float = 10.0, dt: float = 1.0 / 60.0):
    # 玩具模型参数
    v = 2.0                 # 车速 m/s
    r_max = 300.0           # 最大横摆 °/s
    k_r = 1.0               # 转向→横摆增益（满舵即刻期望 r_max）
    T_r = 0.15              # 横摆响应时间常数 s

    ctrl = DriftController(cfg)
    beta = 5.0              # 初值：起漂后不久的小侧滑
    yaw_rate = 0.0
    course = 0.0            # 航迹角（rad）
    x, y = cfg.circle_center[0] + cfg.circle_radius, cfg.circle_center[1]
    psi_dot_deg = v / cfg.circle_radius * RAD2DEG  # 定圆航迹角速度

    rows = []
    n = int(duration_s / dt)
    for i in range(n):
        t = i * dt
        out = ctrl.update(beta_deg=beta, yaw_rate_dps=yaw_rate, pose=(x, y), t_s=t)
        # 玩具动力学推进
        yaw_rate += (k_r * out.steering * r_max - yaw_rate) * dt / T_r
        beta += (yaw_rate - psi_dot_deg) * dt
        course += psi_dot_deg * dt * DEG2RAD
        x += v * math.cos(course) * dt
        y += v * math.sin(course) * dt
        rows.append((t, beta, yaw_rate, out.steering, out.throttle))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="漂移控制器离线仿真（M3）")
    parser.add_argument("--beta-target", type=float, default=25.0)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--csv", default=None, help="可选：输出 β/控制曲线 CSV")
    args = parser.parse_args()

    cfg = ControllerConfig(beta_target_deg=args.beta_target)
    rows = simulate(cfg, duration_s=args.duration)

    tail = rows[int(len(rows) * 0.7):]  # 后 30% 视为稳态
    mean_beta = sum(r[1] for r in tail) / len(tail)
    spread = max(r[1] for r in tail) - min(r[1] for r in tail)
    ok = abs(mean_beta - args.beta_target) < 3.0 and spread < 6.0

    print(f"β* = {args.beta_target:.1f}°，稳态均值 β = {mean_beta:.2f}°，"
          f"稳态极差 {spread:.2f}°")
    print("✅ 仿真通过：β 收敛并保持" if ok else
          "❌ 仿真未通过：检查控制器方向/增益/限幅配置")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t_s", "beta_deg", "yaw_rate_dps", "steering", "throttle"])
            writer.writerows(rows)
        print(f"曲线已写入 {args.csv}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
