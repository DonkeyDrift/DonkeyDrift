"""M3 D0:bc_data 模块与 env.state_vector 单测(零 sim)。"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from donkeydrifter.rl.bc_data import (  # noqa: E402
    GATES, META_COLUMNS, EpisodeBuffer, compute_data_card, load_dataset,
    make_montage, telemetry_to_meta_row, write_episode_npz,
)
from donkeydrifter.rl.env import DonkeyDriftEnv, STATE_OBS_DIM  # noqa: E402


# ---------------------------------------------------------------------------
# EpisodeBuffer / npz 往返
# ---------------------------------------------------------------------------

def _fake_tele(i):
    return {"pos": (1.0 * i, 0.5, 2.0 * i), "speed": 2.0 + 0.01 * i,
            "forward_vel": 1.9, "cte": 0.1 * (i % 3),
            "vel": (0.0, 0.0, 2.0), "gyro": (0.0, 0.0, 3.0),
            "accel": (0.0, 0.0, 0.1), "car": (0.0, 0.0, 180.0),
            "active_node": 10 + i, "total_nodes": 250, "frame_id": 100 + i}


def test_buffer_roundtrip(tmp_path):
    buf = EpisodeBuffer(7)
    for i in range(5):
        buf.add(np.full((120, 160, 3), i, np.uint8),
                np.full(16, i, np.float32), (0.1 * i, 0.5, 0.0),
                _fake_tele(i), 100 + i, 0.05 * i)
    path = write_episode_npz(str(tmp_path), buf)
    assert path.endswith("bc_00007.npz")
    d = np.load(path)
    assert d["image"].shape == (5, 120, 160, 3) and d["image"].dtype == np.uint8
    assert d["state"].shape == (5, 16) and d["state"].dtype == np.float32
    assert d["steer"].shape == (5,) and d["throttle"].shape == (5,) and d["brake"].shape == (5,)
    assert d["meta"].shape == (5, len(META_COLUMNS))
    assert set(d["meta"][:, 0].tolist()) == {7.0}  # meta[:,0]=ep_id 全局唯一
    assert d["meta"][2, list(META_COLUMNS).index("frame_id")] == 102.0
    assert d["meta"][3, list(META_COLUMNS).index("active_node")] == 13.0


def test_empty_buffer_returns_none(tmp_path):
    assert write_episode_npz(str(tmp_path), EpisodeBuffer(0)) is None


def test_bad_image_rejected():
    buf = EpisodeBuffer(1)
    with pytest.raises(ValueError):
        buf.add(np.zeros((5, 5), np.uint8), np.zeros(16, np.float32),
                (0, 0, 0), _fake_tele(0), 1, 0.0)


def test_load_dataset_merges_and_ep_unique(tmp_path):
    for ep in range(3):
        buf = EpisodeBuffer(ep)
        for i in range(4):
            buf.add(np.full((120, 160, 3), ep, np.uint8),
                    np.full(16, ep, np.float32), (0.0, 0.4, 0.0),
                    _fake_tele(i), 100 + i, 0.05 * i)
        write_episode_npz(str(tmp_path), buf)
    ds = load_dataset(str(tmp_path))
    assert ds["image"].shape[0] == 12 and ds["state"].shape == (12, 16)
    eps = set(ds["meta"][:, 0].astype(int).tolist())
    assert eps == {0, 1, 2}  # 跨文件 ep_id 全局唯一(合并后可整局分层)


def test_meta_missing_fields_are_nan():
    row = telemetry_to_meta_row(3, None, 0.1, {"pos": (1, 2, 3)})
    assert row[0] == 3.0
    assert np.isnan(row[list(META_COLUMNS).index("frame_id")])
    assert np.isnan(row[list(META_COLUMNS).index("speed")])


# ---------------------------------------------------------------------------
# data card 门判定
# ---------------------------------------------------------------------------

def _card_inputs(n=3200, hard_frac=0.25, thr_frac=0.5, two_sided=True,
                img_std=30.0):
    rng = np.random.default_rng(0)
    steer = rng.uniform(-1, 1, n)
    n_hard = int(n * hard_frac)
    if two_sided:
        idx = rng.choice(n, n_hard, replace=False)
        steer[idx] = np.where(rng.random(n_hard) > 0.5, 0.6, -0.6)
    else:
        steer[:n_hard] = 0.6  # 单侧
    thr = np.where(rng.random(n) < thr_frac, 0.6, 0.1)
    brake = np.zeros(n)
    meta = np.zeros((n, len(META_COLUMNS)), np.float32)
    meta[:, 0] = rng.integers(0, 8, n)  # 8 局
    return steer, thr, brake, meta, img_std


def test_gates_all_pass_on_good_data():
    steer, thr, brake, meta, _ = _card_inputs()
    card = compute_data_card(steer, thr, brake, meta,
                             img_std_samples=[30.0], img_std_last_shard=30.0)
    g = card["gates"]
    assert g["img_std_gt20"] and g["steer_hard_ge15pct"]
    assert g["thr_gt02_ge30pct"] and g["steer_two_sided"]
    assert g["frames_ge_3000_user_target"]
    assert card["gates_pass_all_hard"]


def test_gates_fail_on_flat_steer():
    steer, thr, brake, meta, _ = _card_inputs()
    steer[:] = 0.02  # 恒直行
    card = compute_data_card(steer, thr, brake, meta,
                             img_std_samples=[30.0], img_std_last_shard=30.0)
    assert not card["gates"]["steer_hard_ge15pct"]
    assert not card["gates"]["steer_two_sided"]
    assert not card["gates_pass_all_hard"]


def test_gates_fail_on_gray_images():
    steer, thr, brake, meta, _ = _card_inputs()
    card = compute_data_card(steer, thr, brake, meta,
                             img_std_samples=[8.0], img_std_last_shard=8.0)
    assert not card["gates"]["img_std_gt20"]  # 盲图/全灰(sdsandbox 同门)


def test_gates_fail_on_low_throttle():
    steer, thr, brake, meta, _ = _card_inputs(thr_frac=0.05)
    card = compute_data_card(steer, thr, brake, meta,
                             img_std_samples=[30.0], img_std_last_shard=30.0)
    assert not card["gates"]["thr_gt02_ge30pct"]


def test_card_keys_aligned_with_sdsandbox():
    steer, thr, brake, meta, _ = _card_inputs()
    card = compute_data_card(steer, thr, brake, meta,
                             img_std_samples=[30.0], img_std_last_shard=30.0)
    for k in ("pairs_total", "episodes", "steer_mean", "steer_std", "steer_p05",
              "steer_p95", "steer_hard_frac", "thr_mean", "thr_std",
              "thr_gt02_frac", "img_std_last_shard", "throttle_hist_10"):
        assert k in card, k


def test_montage(tmp_path):
    imgs = np.random.default_rng(1).integers(0, 255, (20, 120, 160, 3), dtype=np.uint8)
    path = make_montage(imgs, str(tmp_path / "montage.jpg"))
    assert os.path.exists(path) and os.path.getsize(path) > 0


# ---------------------------------------------------------------------------
# env.state_vector 与训练 state obs 同口径
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self, info):
        self.active_node = info.get("active_node")
        self.total_nodes = info.get("total_nodes")
        self.is_game_over = lambda: False
        self.calc_reward = lambda done: 0.0


class _FakeViewer:
    def __init__(self, info):
        self.handler = _FakeHandler(info)


def test_state_vector_matches_training_obs(monkeypatch):
    """数据集口径 = 策略观测口径:同一函数逐位一致(M3 D0 硬要求)。"""
    env = DonkeyDriftEnv(sim_path="remote")
    info = {"pos": (1.0, 0.5, 2.0), "speed": 3.0, "forward_vel": 2.5, "cte": -0.4,
            "vel": (0.1, 0.0, 3.0), "gyro": (0.0, 0.0, -5.0),
            "accel": (0.0, 0.2, 0.0), "active_node": 42, "total_nodes": 250}
    monkeypatch.setattr(env, "_sim_viewer", lambda: _FakeViewer(info))
    env._cam.info = info
    a = env.state_vector(prev_action=(0.3, 0.7))
    # 训练口径:pixel 关闭 → state 模式的 _build_obs 用内部 _prev_action
    env._prev_action = (0.3, 0.7)
    b, defects = env._build_obs()
    assert not defects
    assert a.shape == (STATE_OBS_DIM,) == b.shape
    assert np.array_equal(a, b)  # 逐位一致
    # pixel 模式 env 也可取 state_vector(采样器用法)
    env.obs_mode = "pixel"
    c = env.state_vector(prev_action=(0.3, 0.7))
    assert np.array_equal(c, b)


def test_state_vector_prev_action_explicit(monkeypatch):
    env = DonkeyDriftEnv(sim_path="remote")
    info = {"pos": (0.0, 0.0, 0.0), "speed": 1.0, "cte": 0.0,
            "vel": (0.0, 0.0, 1.0), "gyro": (0.0, 0.0, 0.0), "accel": (0.0, 0.0, 0.0),
            "active_node": 0, "total_nodes": 250}
    monkeypatch.setattr(env, "_sim_viewer", lambda: _FakeViewer(info))
    env._cam.info = info
    v = env.state_vector(prev_action=(-0.5, 0.8))
    assert v[14] == pytest.approx(-0.5)   # prev steer 不缩放
    assert v[15] == pytest.approx(0.8)    # prev throttle 不缩放
    assert v[0] == pytest.approx(0.0)     # cte=0 → 0
