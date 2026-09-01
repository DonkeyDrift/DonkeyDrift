"""simulate_drift_controller 回归测试（M3 验收工具）。

scripts/simulate_drift_controller.py 的 simulate() 是纯函数（玩具运动学
模型闭环 import 生产 drift_controller）。锁定默认配置 10s 仿真 β 收敛到
25°±1° 且 main 退出码 0，防止验收工具被悄悄破坏。
"""

import sys
import unittest
from unittest import mock

# 该脚本 import 时会把 web_ui/backend 插入 sys.path（仓内脚本惯例）
from scripts import simulate_drift_controller as sdc
from drift_controller import ControllerConfig


class SimulateConvergenceTest(unittest.TestCase):

    def test_beta_converges_to_target(self):
        cfg = ControllerConfig()  # 默认 β* = 25°
        rows = sdc.simulate(cfg, duration_s=10.0)
        self.assertTrue(rows)
        tail = rows[int(len(rows) * 0.7):]  # 后 30% 视为稳态
        mean_beta = sum(r[1] for r in tail) / len(tail)
        spread = max(r[1] for r in tail) - min(r[1] for r in tail)
        self.assertAlmostEqual(mean_beta, 25.0, delta=1.0,
                               msg=f"稳态 β 均值 {mean_beta:.2f}° 未收敛到 25°±1°")
        self.assertLess(spread, 6.0, msg=f"稳态 β 极差 {spread:.2f}° 过大")

    def test_main_returns_zero(self):
        with mock.patch.object(sys, "argv", ["simulate_drift_controller.py"]):
            rc = sdc.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
