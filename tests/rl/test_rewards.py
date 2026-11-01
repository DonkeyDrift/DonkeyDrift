"""D2 分解式 reward 单测:纯函数、零 sim 依赖,pytest 直接绿。

覆盖订单要求的断言面:
- 每项符号与量级
- cte deadband 边界
- 速度门下 progress=0
- 超速惩罚单调性
- NaN/缺失字段防御
- 双重计罚不出现(配置校验 + 序列断言)
"""

import math

import numpy as np
import pytest

from donkeydrifter.rl.rewards import (
    RewardConfig,
    compute_beta_deg,
    gyro_step_heading,
    reward,
    wrap_deg,
)


def _info(**kw):
    base = {
        "pos": (0.0, 0.0, 0.0),
        "speed": 3.0,
        "cte": 0.0,
        "gyro": (0.0, 0.0, 0.0),
        "accel": (0.0, 0.0, 0.0),
        "vel": (3.0, 0.0, 0.0),
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# cte 项:符号、量级、deadband 边界
# ---------------------------------------------------------------------------

def test_cte_inside_deadband_no_penalty():
    total, comps = reward(None, _info(cte=0.3), cfg=RewardConfig())
    assert comps["cte"] == 0.0


def test_cte_deadband_boundary_exact():
    # |cte| = deadband → over=0 → 不罚(边界归入不罚侧)
    _, c0 = reward(None, _info(cte=0.5), cfg=RewardConfig())
    _, c1 = reward(None, _info(cte=-0.5), cfg=RewardConfig())
    assert c0["cte"] == 0.0 and c1["cte"] == 0.0
    # 刚出界一点 → 小二次罚
    _, c2 = reward(None, _info(cte=0.6), cfg=RewardConfig())
    assert c2["cte"] < 0.0
    assert abs(c2["cte"]) < 0.05  # 量级:0.5*1*(0.1²)=0.005,远小于 0.05


def test_cte_penalty_sign_and_huber_magnitude():
    cfg = RewardConfig()
    _, c = reward(None, _info(cte=1.0), cfg=cfg)
    # over=0.5=delta → huber=0.5*0.25=0.125
    assert c["cte"] == pytest.approx(-0.125)
    # 线性段:|cte|=2.0 → over=1.5 → huber=0.5*(1.5-0.25)=0.625
    _, c2 = reward(None, _info(cte=2.0), cfg=cfg)
    assert c2["cte"] == pytest.approx(-0.625)
    assert c2["cte"] < c["cte"]  # 越远越罚(单调)


# ---------------------------------------------------------------------------
# progress 项:速度门、node/位移两法、符号
# ---------------------------------------------------------------------------

def test_progress_zero_below_speed_floor():
    prev = _info(active_node=10.0, total_nodes=100.0)
    cur = _info(speed=0.2, active_node=11.0, total_nodes=100.0)  # speed < 0.3
    _, c = reward(prev, cur, cfg=RewardConfig())
    assert c["progress"] == 0.0
    assert c["progress_method"] == "none"


def test_progress_node_method_forward_and_backward():
    cfg = RewardConfig()
    prev = _info(active_node=10.0, total_nodes=100.0)
    fwd = _info(active_node=11.0, total_nodes=100.0)
    _, c = reward(prev, fwd, cfg=cfg)
    assert c["progress"] == pytest.approx(1.0)  # +1 节点
    bwd = _info(active_node=9.0, total_nodes=100.0)
    _, c = reward(prev, bwd, cfg=cfg)
    assert c["progress"] == pytest.approx(-1.0)  # 倒车负进度


def test_progress_node_wraparound():
    prev = _info(active_node=99.0, total_nodes=100.0)
    cur = _info(active_node=1.0, total_nodes=100.0)
    _, c = reward(prev, cur, cfg=RewardConfig())
    assert c["progress"] == pytest.approx(2.0)  # 99→0→1 环绕 = +2


def test_progress_no_active_node_falls_back_to_displacement():
    prev = _info(pos=(0.0, 0.0, 0.0))
    cur = _info(pos=(1.0, 0.0, 0.0), vel=(3.0, 0.0, 0.0))
    _, c = reward(prev, cur, cfg=RewardConfig())
    assert c["progress_method"] == "displacement"
    assert c["progress"] == pytest.approx(1.0)  # 纯 x 向前进 1m
    # 侧移不产生前向投影
    cur_side = _info(pos=(0.0, 1.0, 0.0), vel=(3.0, 0.0, 0.0))
    _, c2 = reward(prev, cur_side, cfg=RewardConfig())
    assert c2["progress"] == pytest.approx(0.0, abs=1e-9)


def test_progress_requires_prev_info():
    _, c = reward(None, _info(active_node=5.0, total_nodes=100.0), cfg=RewardConfig())
    assert c["progress"] == 0.0


# ---------------------------------------------------------------------------
# drift 项:形状、速度门、β 缺失防御
# ---------------------------------------------------------------------------

def test_drift_peak_at_mu_and_gaussian_shape():
    cfg = RewardConfig(w_drift=1.0)
    at_mu = _info(speed=6.0, beta_deg=25.0)
    _, c = reward(None, at_mu, cfg=cfg)
    assert c["drift"] == pytest.approx(1.0, abs=1e-9)  # 峰值=权重(×speed_norm=1)
    off = _info(speed=6.0, beta_deg=25.0 + 2 * cfg.drift_sigma_deg)
    _, c2 = reward(None, off, cfg=cfg)
    assert 0.0 < c2["drift"] < 0.15  # 2σ 处 exp(-2)≈0.135,量级 sanity


def test_drift_gated_by_speed_floor():
    cfg = RewardConfig(w_drift=1.0)
    slow = _info(speed=1.0, beta_deg=25.0)  # speed < 2.0 floor
    _, c = reward(None, slow, cfg=cfg)
    assert c["drift"] == 0.0  # 原地/低速打转不刷漂移分


def test_drift_missing_beta_is_zero_and_defected():
    cfg = RewardConfig(w_drift=1.0)
    _, c = reward(None, _info(speed=6.0), cfg=cfg)
    assert c["drift"] == 0.0
    assert "beta_deg" in c["defects"]


def test_drift_off_by_default():
    _, c = reward(None, _info(speed=6.0, beta_deg=25.0), cfg=RewardConfig())
    assert c["drift"] == 0.0


# ---------------------------------------------------------------------------
# 超速惩罚:单调性
# ---------------------------------------------------------------------------

def test_overspeed_monotonic_beyond_cap_and_zero_below():
    cfg = RewardConfig(w_overspeed=1.0, speed_max_mps=8.0)
    _, c7 = reward(None, _info(speed=7.0), cfg=cfg)
    assert c7["overspeed"] == 0.0
    r8 = reward(None, _info(speed=8.0), cfg=cfg)[1]["overspeed"]
    r9 = reward(None, _info(speed=9.0), cfg=cfg)[1]["overspeed"]
    r10 = reward(None, _info(speed=10.0), cfg=cfg)[1]["overspeed"]
    assert r8 == 0.0
    assert r9 == pytest.approx(-1.0) and r10 == pytest.approx(-2.0)
    assert r10 < r9 < r8


# ---------------------------------------------------------------------------
# 存活/步惩罚 vs timeout:配置互斥 + 序列不双重计罚
# ---------------------------------------------------------------------------

def test_step_and_timeout_mutually_exclusive_by_config():
    with pytest.raises(ValueError):
        RewardConfig(w_step=0.01, w_timeout=5.0)


def test_timeout_fires_once_on_terminal_frame_only():
    cfg = RewardConfig(w_timeout=5.0)
    prev = _info()
    mid = _info(truncated=False)
    _, c_mid = reward(prev, mid, cfg=cfg)
    assert c_mid["timeout"] == 0.0
    final = _info(truncated=True)
    _, c_final = reward(prev, final, cfg=cfg)
    assert c_final["timeout"] == pytest.approx(-5.0)
    # 序列断言:整条轨迹里 timeout 只在标 truncated 的帧出现一次
    seq = [mid, mid, final]
    fired = [reward(prev if i == 0 else seq[i - 1], f, cfg=cfg)[1]["timeout"] for i, f in enumerate(seq)]
    assert fired == [0.0, 0.0, -5.0]
    assert sum(1 for x in fired if x != 0.0) == 1


def test_step_penalty_applies_every_step_but_not_terminal_style():
    cfg = RewardConfig(w_step=0.01)
    _, c = reward(None, _info(), cfg=cfg)
    assert c["step"] == pytest.approx(-0.01)
    assert c["timeout"] == 0.0  # w_step 路径不存在 timeout 罚


# ---------------------------------------------------------------------------
# NaN/缺失字段防御
# ---------------------------------------------------------------------------

def test_nan_fields_defected_not_propagated():
    cfg = RewardConfig()
    bad = _info(cte=float("nan"), speed=float("nan"))
    total, comps = reward(None, bad, cfg=cfg)
    assert math.isfinite(total)
    assert "cte" in comps["defects"] and "speed" in comps["defects"]
    assert comps["cte"] == 0.0 and comps["overspeed"] == 0.0


def test_none_fields_defected():
    info = {"cte": None, "speed": None, "pos": None, "vel": None}
    total, comps = reward(None, info, cfg=RewardConfig())
    assert math.isfinite(total)
    assert set(["cte", "speed"]) <= set(comps["defects"])


def test_total_is_sum_of_components():
    cfg = RewardConfig(w_cte=1.0, w_overspeed=0.5)
    total, comps = reward(None, _info(cte=1.0, speed=9.0), cfg=cfg)
    manual = comps["cte"] + comps["progress"] + comps["drift"] + comps["overspeed"] + comps["step"] + comps["timeout"] + comps["done"]
    assert total == pytest.approx(manual)
    assert total < 0  # 本例只有罚项


# ---------------------------------------------------------------------------
# β 计算
# ---------------------------------------------------------------------------

def test_wrap_deg():
    assert wrap_deg(0) == 0.0
    assert wrap_deg(190) == pytest.approx(-170.0)
    assert wrap_deg(-190) == pytest.approx(170.0)
    assert wrap_deg(360) == pytest.approx(0.0)


def test_beta_yaw_method():
    # 车头朝北(yaw=90),速度向东 → β = 90-0 = +90(纯侧滑)
    info = _info(speed=3.0, vel=(3.0, 0.0, 0.0), car=(0.0, 0.0, 90.0))
    beta = compute_beta_deg(None, info, method="yaw")
    assert beta == pytest.approx(90.0)
    # 同向 → 0
    info2 = _info(speed=3.0, vel=(0.0, 3.0, 0.0), car=(0.0, 0.0, 90.0))
    assert compute_beta_deg(None, info2, method="yaw") == pytest.approx(0.0)


def test_beta_gyro_chain():
    # 积分链:heading 90°,gyro_z=+10°/s,dt=0.05 → heading 90.5;速度向东
    prev = {"rl/heading_deg": 90.0}
    cur = _info(speed=3.0, vel=(3.0, 0.0, 0.0), gyro=(0.0, 0.0, 10.0), dt_s=0.05)
    beta = compute_beta_deg(prev, cur, method="gyro")
    assert beta == pytest.approx(wrap_deg(90.5 - 0.0))


def test_beta_undefined_at_rest():
    info = _info(speed=0.0, vel=(0.0, 0.0, 0.0), car=(0.0, 0.0, 90.0))
    assert compute_beta_deg(None, info, method="auto") is None


def test_gyro_step_heading_wraps():
    assert gyro_step_heading(179.0, 10.0, 0.2) == pytest.approx(wrap_deg(181.0))


# ---------------------------------------------------------------------------
# numpy 数组 action 记账
# ---------------------------------------------------------------------------

def test_action_recorded():
    _, comps = reward(None, _info(), action=np.array([0.3, 0.7]), cfg=RewardConfig())
    assert comps["action"] == pytest.approx([0.3, 0.7])
