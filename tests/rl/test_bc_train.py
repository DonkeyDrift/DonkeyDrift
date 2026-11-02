"""M3 D2:bc_train 灌权正确性与数据管线单测(零 sim;验收重点 = 一致性)。"""

import os
import subprocess
import sys

import numpy as np
import pytest
import torch

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import bc_train  # noqa: E402  (scripts/ 卫生由 bc_train 自身处理)
sys.path.insert(0, _REPO)
from donkeydrifter.rl.bc_data import EpisodeBuffer, write_episode_npz  # noqa: E402


def _fake_tele(i):
    return {"pos": (float(i), 0.5, float(i)), "speed": 2.0, "forward_vel": 1.9,
            "cte": 0.1, "vel": (0.0, 0.0, 2.0), "gyro": (0.0, 0.0, 0.0),
            "accel": (0.0, 0.0, 0.0), "car": (0.0, 0.0, 180.0),
            "active_node": 10 + i, "total_nodes": 250, "frame_id": 100 + i}


@pytest.fixture(scope="module")
def bc_data_dir(tmp_path_factory):
    """合成数据:两局,steer 双侧含 hard 帧,throttle 混合。"""
    d = tmp_path_factory.mktemp("bc_data")
    rng = np.random.default_rng(3)
    for ep in range(2):
        buf = EpisodeBuffer(ep)
        for i in range(120):
            steer = float(np.clip(rng.uniform(-1, 1) if i % 4 else (0.6 if i % 8 else -0.6), -1, 1))
            thr = 0.5 + 0.1 * rng.random()
            buf.add(np.full((120, 160, 3), (i * 7) % 255, np.uint8),
                    rng.uniform(-1, 1, 16).astype(np.float32),
                    (steer, thr, 0.0), _fake_tele(i), 100 + i, 0.05 * i)
        write_episode_npz(str(d), buf)
    return str(d)


def test_split_by_episode_no_leak(bc_data_dir):
    meta = bc_train._metas([bc_data_dir])
    train_mask, val_mask = bc_train.split_by_episode(meta, val_frac=0.5, seed=0)
    eps = meta[:, 0].astype(int)
    assert not (set(eps[train_mask]) & set(eps[val_mask]))  # 整局分层:无局泄漏
    assert train_mask.sum() + val_mask.sum() == len(meta)


def test_state_bc_architecture_matches_sb3():
    """镜像对位:StateBC trunk/head 形状 == SB3 MlpPolicy 实际层。"""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv
    import gymnasium as gym

    class _E(gym.Env):
        metadata = {}
        action_space = gym.spaces.Box(-1, 1, (2,), np.float32)
        observation_space = gym.spaces.Box(-np.inf, np.inf, (16,), np.float32)

        def reset(self, *, seed=None, options=None):
            return np.zeros(16, np.float32), {}

        def step(self, a):
            return np.zeros(16, np.float32), 0.0, False, False, {}

    ppo = PPO("MlpPolicy", DummyVecEnv([_E]), device="cpu", seed=0)
    pi = ppo.policy.mlp_extractor.policy_net
    bc = bc_train.StateBC(obs_dim=16)
    assert pi[0].weight.shape == bc.trunk[0].weight.shape
    assert pi[2].weight.shape == bc.trunk[2].weight.shape
    assert ppo.policy.action_net.weight.shape == bc.head.weight.shape


def test_export_and_predict_consistency_state(bc_data_dir, tmp_path):
    """验收重点:导出 zip 后 PPO.load deterministic 前向 == BC torch 前向(atol 1e-5)。"""
    X, Y, _meta = bc_train.load_arrays([bc_data_dir], "state", filter_brake=True)
    meta = bc_train._metas([bc_data_dir])
    tr, va = bc_train.split_by_episode(meta, 0.1, seed=0)
    model = bc_train.StateBC(obs_dim=16)
    loader = bc_train.build_loader(X[tr], Y[tr], batch=64, hard_oversample=0.3, seed=0)
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    loss_fn = torch.nn.MSELoss()
    for _ in range(2):  # 少量训练使权重非初始
        for xb, yb in loader:
            opt.zero_grad()
            loss_fn(model(xb), yb).backward()
            opt.step()
    zpath = str(tmp_path / "bc_state_export")
    zip_path = bc_train.export_to_sb3_zip(model, "state", 16, zpath)
    assert os.path.exists(zip_path)
    check = bc_train.self_check(model, "state", 16, zip_path, n=256)
    assert check["pass"]


def test_export_and_predict_consistency_pixel(bc_data_dir, tmp_path):
    X, Y, _meta = bc_train.load_arrays([bc_data_dir], "pixel", filter_brake=True)
    meta = bc_train._metas([bc_data_dir])
    tr, _ = bc_train.split_by_episode(meta, 0.1, seed=0)
    model = bc_train.PixelBC()
    with torch.no_grad():
        model(torch.as_tensor(X[:2]))
    loader = bc_train.build_loader(X[tr], Y[tr], batch=16, hard_oversample=0.0, seed=0)
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    loss_fn = torch.nn.MSELoss()
    for _ in range(1):
        for xb, yb in loader:
            opt.zero_grad()
            loss_fn(model(xb), yb).backward()
            opt.step()
    zpath = str(tmp_path / "bc_pixel_export")
    zip_path = bc_train.export_to_sb3_zip(model, "pixel", 3, zpath)
    check = bc_train.self_check(model, "pixel", 3, zip_path, n=32)
    assert check["pass"]


def test_load_arrays_brake_filter(bc_data_dir):
    Xa, Ya, Ma = bc_train.load_arrays([bc_data_dir], "state", filter_brake=False)
    Xb, Yb, Mb = bc_train.load_arrays([bc_data_dir], "state", filter_brake=True)
    assert Xa.shape[0] >= Xb.shape[0]
    assert Ma.shape[0] == Xa.shape[0] and Mb.shape[0] == Xb.shape[0]  # meta 同步过滤
    assert Xa.shape[1] == 16 and Ya.shape[1] == 2
    assert float(np.abs(Ya).max()) <= 1.0 + 1e-6


def test_probe_gate_rejects_flat_steer(tmp_path):
    """探针门:恒直行数据(hard=0)拒训——坏数据不进 A/B。"""
    d = tmp_path / "flat"
    d.mkdir()
    buf = EpisodeBuffer(0)
    for i in range(80):
        buf.add(np.full((120, 160, 3), 60, np.uint8),          # 低纹理:img std 门也挂
                np.zeros(16, np.float32), (0.01, 0.05, 0.0),
                _fake_tele(i), 100 + i, 0.05 * i)
    write_episode_npz(str(d), buf)
    with pytest.raises(SystemExit):
        bc_train.probe_gate([str(d)], force=False)


def test_cli_smoke_end_to_end(bc_data_dir, tmp_path):
    """CLI 端到端(跳探针门的小合成集):出 zip + summary + 一致性 pass。"""
    out_prefix = str(tmp_path / "cli_export")
    r = subprocess.run(
        [sys.executable, os.path.join(_REPO, "scripts", "bc_train.py"),
         "--data", bc_data_dir, "--mode", "state", "--epochs", "2",
         "--out", out_prefix, "--skip-probe", "--no-filter-brake"],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "一致 ✓" in r.stdout
    assert os.path.exists(out_prefix + ".zip")
    summary = __import__("json").load(open(out_prefix + "_summary.json")
                                      if os.path.exists(out_prefix + "_summary.json")
                                      else open(os.path.join(tmp_path, "bc_train_summary.json")))
    assert summary["self_check"]["pass"] is True
