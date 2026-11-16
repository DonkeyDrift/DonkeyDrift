"""M4 D1:行车线提取/重锚定数学 + env cte_anchor 三处统一单测(零 sim)。"""

import os
import sys

import numpy as np
import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO)
from donkeydrifter.rl.driveline import (  # noqa: E402
    circular_smooth, driveline_gate, interpolate_missing, nearest_node_seq,
    reanchor_cte,
)
from donkeydrifter.rl.env import DonkeyDriftEnv  # noqa: E402


# ---------------------------------------------------------------------------
# driveline 纯函数
# ---------------------------------------------------------------------------

def _circle_line(n=250, r=10.0):
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([r * np.cos(ang), np.zeros(n), r * np.sin(ang)], axis=1)


def test_nearest_node_wraps_around_zero():
    cl = _circle_line()
    # 角度接近 2π(即 node 249/0 边界)的点
    p = cl[249] + [0.0, 0.0, 0.01]
    q = cl[0] + [0.0, 0.0, -0.01]
    seq = nearest_node_seq([p, q], cl, window=32)
    assert seq[0] == 249 and seq[1] == 0  # 跨 0 回绕


def test_nearest_node_window_blocks_far_segment():
    """对侧中心线点(距离 0,全搜必选)在窗约束下不许跳(时序连续性语义):
    窗硬选窗内最近 node——哪怕它几何上远(跨圈/瞬移保护,代价是错 node)。"""
    cl = _circle_line()
    seq = nearest_node_seq([cl[0], cl[125]], cl, window=32)
    assert seq[1] != 125
    assert seq[1] in [(0 + k) % 250 for k in range(-32, 33)]


def test_nearest_node_resets_full_search_on_episode_change():
    cl = _circle_line()
    seq = nearest_node_seq([cl[0], cl[125]], cl, window=4, ep_ids=[0, 1])
    assert seq[1] == 125  # 新局全搜:窗再小也允许跳


def test_circular_smooth_wraps_and_ignores_nan():
    # wrap:头部窗口吃到尾部值(环形语义;250-node 实环下只影响端点 ±2)
    v = [0.0] * 9 + [10.0]
    s = circular_smooth(v, window=3)
    assert s[0] == pytest.approx((0.0 + 10.0 + 0.0) / 3)
    # NaN 忽略:已知值均值不被 NaN 拉偏
    v2 = [2.0, np.nan, 4.0, np.nan, 6.0]
    s2 = circular_smooth(v2, window=3)
    assert s2[0] == pytest.approx(4.0)          # 环形邻居 v4=6, v1=NaN(NaN 忽略)
    assert s2[2] == pytest.approx(4.0)          # 两侧邻居均 NaN → 仅自身
    # 环形窗口无已知 → NaN(留给插值);有已知(哪怕环绕)→ 环形均值
    v3 = [np.nan, np.nan, 4.0]
    s3 = circular_smooth(v3, window=3)
    assert s3[0] == pytest.approx(4.0)   # 环形邻居 v2=4(窗口内)
    v4 = [np.nan, np.nan, np.nan]
    s4 = circular_smooth(v4, window=3)
    assert np.isnan(s4[0]) and np.isnan(s4[1])


def test_interpolate_missing_wraps():
    v = [1.0, np.nan, np.nan, np.nan, 3.0] + [9.0] * 5
    out = interpolate_missing(v)
    assert out[1] == pytest.approx(1.5) and out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(2.5)
    # 环形距离加权:位置 6 到 v4=3.0(后向 2 步)与 v0=1.0(环绕前向 2 步)→ 中点
    v2 = [1.0] + [np.nan] * 3 + [3.0] + [np.nan] * 3
    out2 = interpolate_missing(v2)
    assert out2[5] == pytest.approx(2.5)   # v4=3 后 1 步 / v0=1 前 4 步
    assert out2[6] == pytest.approx(2.0)   # 两侧各 2 步 → 中点


def test_reanchor_and_gate():
    offsets = np.full(10, 0.5)
    cte = np.array([0.5, 0.6, 0.4, 3.0])
    nodes = np.array([0, 1, 2, 3])
    r = reanchor_cte(cte, nodes, offsets)
    assert r[:3] == pytest.approx([0.0, 0.1, -0.1])
    g = driveline_gate(r)
    assert g["over2_frac"] == pytest.approx(0.25) and not g["pass"]


# ---------------------------------------------------------------------------
# env 三处统一(reward cte 项 / cte_limit 截断 / state obs cte 分量)
# ---------------------------------------------------------------------------

GAIN = -8.114
OFFSETS = np.zeros(250)
OFFSETS[5] = -0.4   # node5 行车线在 sim-cte 正方向 0.4×|gain| 米处(锚定后为正偏)


class _FakeHandler:
    def __init__(self, info):
        self.active_node = info.get("active_node")
        self.total_nodes = info.get("total_nodes")
        self.is_game_over = lambda: False
        self.calc_reward = lambda done: 0.0


class _FakeViewer:
    def __init__(self, info):
        self.handler = _FakeViewer_holder(info)


def _FakeViewer_holder(info):
    h = _FakeHandler(info)
    return h


def _anchor_env(monkeypatch, cte_raw, active_node=5):
    env = DonkeyDriftEnv(sim_path="remote",
                         cte_anchor={"mode": "line", "offsets": OFFSETS.tolist(),
                                     "cte_unit_gain": GAIN})
    info = {"pos": (0.0, 0.0, 0.0), "speed": 3.0, "forward_vel": 2.5,
            "cte": cte_raw, "vel": (0.0, 0.0, 3.0), "gyro": (0.0, 0.0, 0.0),
            "accel": (0.0, 0.0, 0.0), "active_node": active_node,
            "total_nodes": 250}
    monkeypatch.setattr(env, "_sim_viewer", lambda: _FakeViewer(info))
    env._cam.info = dict(info)
    return env


def test_anchor_single_point_info(monkeypatch):
    """info["cte"] 被替换为米制锚定值;raw 保留。"""
    env = _anchor_env(monkeypatch, cte_raw=-3.2, active_node=5)
    env._apply_cte_anchor(env._cam.info)
    # cte_m = -3.2 / -8.114 = +0.3944;anchored = 0.3944 - (-0.4) = 0.7944
    assert env._cam.info["cte"] == pytest.approx(0.3944 + 0.4, abs=1e-3)
    assert env._cam.info["cte_raw"] == pytest.approx(-3.2)
    assert env._cam.info["cte_anchor_node"] == 5


def test_anchor_center_mode_is_noop(monkeypatch):
    env = DonkeyDriftEnv(sim_path="remote")  # center
    info = {"cte": -3.2, "active_node": 5}
    env._apply_cte_anchor(info)
    assert info["cte"] == -3.2 and "cte_raw" not in info


def test_anchor_truncation_uses_anchored(monkeypatch):
    """cte_limit 判定吃锚定值:raw 超 sim 界但锚定后 |cte'|≤2 → 不截断。"""
    env = _anchor_env(monkeypatch, cte_raw=-3.2, active_node=5)  # anchored≈0.794
    env._apply_cte_anchor(env._cam.info)
    env._step_count = 1
    obs, defects = env._build_obs()
    assert not defects
    anchored = float(env._cam.info["cte"])
    assert abs(anchored) <= env.cte_limit  # 米制 0.79 ≤ 2.0


def test_anchor_state_obs_component(monkeypatch):
    """state obs 的 cte 分量 = 锚定米制值 / 2.0(缩放表)。"""
    env = _anchor_env(monkeypatch, cte_raw=-3.2, active_node=5)
    env._apply_cte_anchor(env._cam.info)
    env._prev_action = (0.0, 0.0)
    vec, defects = env._build_state_vec(env._prev_action)
    assert not any(d == "idx0" for d in defects)
    assert vec[0] == pytest.approx(env._cam.info["cte"] / 2.0)


def test_anchor_missing_active_node_counts_defect(monkeypatch):
    env = _anchor_env(monkeypatch, cte_raw=-3.2, active_node=None)
    before = env._anchor_defects
    env._apply_cte_anchor(env._cam.info)
    assert env._anchor_defects == before + 1
    assert env._cam.info["cte"] == -3.2  # 保持原值(不伪造)
