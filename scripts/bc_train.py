#!/usr/bin/env python3
"""M3 D2:BC 训练管线(移植 sdsandbox src/bc_train.py 配方,纯 torch 零 Lightning)。

- state-BC(主线):镜像 SB3 MlpPolicy——pi trunk Linear(·→64)Tanh→Linear(64→64)Tanh
  + action_net Linear(64→2)(SB3 2.9.2 实测默认 net_arch=[64,64]);
- pixel-BC(导出 sanity 用):NatureCNN 镜像(SB3 CnnPolicy features 512 口径);
- 消费 bc_data.py 的 bc_%05d.npz(观测→动作配对);整局 90/10 分层 val;
  |steer|>0.3 纠偏帧过采样 ≥30%(WeightedRandomSampler,--hard-oversample);
  探针门(img std>20 / hard≥15% / thr>0.2≥30% / steer 双侧)不达标拒训(--force 覆盖);
  brake>0 帧默认过滤(--no-filter-brake 关)——SB3 动作空间无 brake 维;
- 导出 SB3 zip:构造 PPO → 灌 features_extractor/mlp_extractor/action_net →
  num_timesteps=0 → save;热启动 = `scripts/rl_train.py --resume <zip>`;
- 明确不做(sdsandbox 证伪史):分类头、λ 损失级正则。

一致性自检(--self-check,默认开):导出后 PPO.load(zip) deterministic 前向 vs
BC torch 前向同输入 atol 1e-5——灌权正确性的机器证明,亦是交付验收对象。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler  # noqa: E402

sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl.bc_data import (  # noqa: E402  (仓库包,scripts 已移除)
    GATES, load_dataset, compute_data_card, dump_card,
)

# ---------------------------------------------------------------------------
# 模型(镜像 SB3;层顺序/激活与 SB3 2.9.2 逐层对位,灌权依赖此结构)
# ---------------------------------------------------------------------------


class StateBC(nn.Module):
    """state(16) → [steer, throttle];镜像 SB3 MlpPolicy pi trunk + action_net。"""

    def __init__(self, obs_dim: int = 16, act_dim: int = 2, hidden: int = 64):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
        )
        self.head = nn.Linear(hidden, act_dim)   # ↔ SB3 action_net

    def forward(self, x):
        return self.head(self.trunk(x))


class NatureCNN(nn.Module):
    """SB3 CnnPolicy features_extractor(NatureCNN, features_dim=512)逐层镜像。"""

    def __init__(self, in_ch: int = 3, features_dim: int = 512):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(in_ch, 32, 8, 4), nn.ReLU(),
            nn.Conv2d(32, 64, 4, 2), nn.ReLU(),
            nn.Conv2d(64, 64, 3, 1), nn.ReLU(),
        )
        self.linear = None  # flatten → 512,首次 forward 物化(sdsandbox bc_train.py:26 同法)
        self.features_dim = features_dim

    def forward(self, x):
        h = self.cnn(x)
        if self.linear is None:
            # 扁平尺寸必须取 flatten 后的 shape[1](=C×H×W);取 shape[1] 会拿到
            # 通道数 64 → linear(64→512),flatten(11264) 进不去(实测踩坑)
            n_flat = int(torch.flatten(h, 1).shape[1])
            self.linear = nn.Linear(n_flat, self.features_dim).to(x.device)
        return self.linear(torch.flatten(h, 1))


class PixelBC(nn.Module):
    """image(CHW /255)→ [steer, throttle];cnn+linear+relu ↔ features_extractor。

    ⚠ SB3 2.9 NatureCNN.linear 是 Sequential(Linear, ReLU)——**features 尾部
    有 ReLU**(sdsandbox bc_train.py:6 的镜像注释同口径);漏掉会静默产生
    一致性失败(2026-11-02 实测踩坑)。
    """

    def __init__(self, in_ch: int = 3, act_dim: int = 2):
        super().__init__()
        self.backbone = NatureCNN(in_ch)
        self.out_relu = nn.ReLU()                 # ↔ SB3 linear Sequential 尾部 ReLU
        self.head = nn.Linear(512, act_dim)       # ↔ SB3 action_net

    def forward(self, x):
        f = self.backbone(x)
        return self.head(self.out_relu(f))


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------

def load_arrays(data_dirs: list, mode: str, filter_brake: bool):
    """合并多目录;返回 X(state 或 /255-CHW image)、Y([steer,throttle])、
    meta(**与 keep 掩码同步过滤**——分层 val 的局索引必须对齐同一批样本)。"""
    Xs, Ys, Ms = [], [], []
    for d in data_dirs:
        ds = load_dataset(d)
        brake = ds["brake"]
        keep = (brake <= 0.0) if filter_brake else np.ones(len(brake), bool)
        y = np.stack([ds["steer"], ds["throttle"]], axis=1)[keep].astype(np.float32)
        if mode == "state":
            Xs.append(ds["state"][keep].astype(np.float32))
        else:
            # /255 → CHW(SB3 normalize_images=True 同口径,一次性转省显存)
            img = ds["image"][keep].astype(np.float32) / 255.0
            Xs.append(np.transpose(img, (0, 3, 1, 2)))
        Ys.append(y)
        Ms.append(ds["meta"][keep])
    return np.concatenate(Xs), np.concatenate(Ys), np.concatenate(Ms)


def split_by_episode(meta: np.ndarray, val_frac: float = 0.1, seed: int = 0):
    """整局分层(sdsandbox bc_train.py:123-124 同法):val 抽整局,防相邻帧泄漏。"""
    eps = np.asarray(meta[:, 0], dtype=int)
    uniq = np.unique(eps)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(uniq))
    n_val = max(1, int(round(len(uniq) * val_frac)))
    val_set = set(uniq[perm[:n_val]].tolist())
    val_mask = np.array([e in val_set for e in eps])
    return ~val_mask, val_mask


def build_loader(X, Y, batch: int, hard_oversample: float, seed: int,
                 shuffle: bool = True):
    ds = TensorDataset(torch.as_tensor(X), torch.as_tensor(Y))
    if hard_oversample > 0:
        hard = np.abs(Y[:, 0]) > 0.3   # sdsandbox 同阈值
        cur = float(hard.mean()) if len(hard) else 0.0
        weights = np.ones(len(hard), dtype=np.float64)
        if hard.sum() > 0 and cur < hard_oversample:
            weights[hard] = hard_oversample / max(cur, 1e-6)
        gen = torch.Generator().manual_seed(seed)
        sampler = WeightedRandomSampler(torch.as_tensor(weights), len(weights),
                                        replacement=True, generator=gen)
        return DataLoader(ds, batch_size=batch, sampler=sampler, generator=gen)
    gen = torch.Generator().manual_seed(seed)
    return DataLoader(ds, batch_size=batch, shuffle=shuffle, generator=gen)


# ---------------------------------------------------------------------------
# 探针门(用 data card 门拒绝坏数据)
# ---------------------------------------------------------------------------

def probe_gate(data_dirs: list, force: bool) -> dict:
    steer_all, thr_all, brake_all, meta_all = [], [], [], []
    img_std_samples: list = []
    last_std = float("nan")
    for d in data_dirs:
        ds = load_dataset(d)
        steer_all.append(ds["steer"])
        thr_all.append(ds["throttle"])
        brake_all.append(ds["brake"])
        meta_all.append(ds["meta"])
        imgs = ds["image"]
        last_std = float(imgs[-300:].astype(float).std())
        img_std_samples.append(last_std)
    card = compute_data_card(
        steer=np.concatenate(steer_all), throttle=np.concatenate(thr_all),
        brake=np.concatenate(brake_all), meta=np.concatenate(meta_all),
        img_std_samples=img_std_samples, img_std_last_shard=last_std)
    print("[probe] gates:", json.dumps(card["gates"], ensure_ascii=False),
          "| hard_pass:", card["gates_pass_all_hard"])
    if not card["gates_pass_all_hard"] and not force:
        raise SystemExit("[probe] data card 门未过——拒绝训练(可用 --force 覆盖,须在报告说明)")
    return card


# ---------------------------------------------------------------------------
# 训练与导出
# ---------------------------------------------------------------------------

def train_bc(args) -> dict:
    torch.manual_seed(args.seed)
    X, Y, meta = load_arrays(args.data, args.mode, filter_brake=not args.no_filter_brake)
    print(f"[bc] 样本 {len(X)}(mode={args.mode}, filter_brake={not args.no_filter_brake})")
    card = probe_gate(args.data, args.force) if not args.skip_probe else {}

    train_mask, val_mask = split_by_episode(meta, val_frac=args.val_frac, seed=args.seed)
    Xtr, Ytr = X[train_mask], Y[train_mask]
    Xva, Yva = X[val_mask], Y[val_mask]
    print(f"[bc] 整局分层:train {len(Xtr)} / val {len(Xva)}")

    if args.mode == "state":
        model: nn.Module = StateBC(obs_dim=X.shape[1])
    else:
        model = PixelBC()
        with torch.no_grad():  # 物化 lazy linear
            model(torch.as_tensor(Xtr[:2]))

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss()
    train_loader = build_loader(Xtr, Ytr, args.batch, args.hard_oversample,
                                args.seed, shuffle=True)

    def val_metrics():
        model.eval()
        with torch.no_grad():
            xv, yv = torch.as_tensor(Xva), torch.as_tensor(Yva)
            pred = model(xv)
            mse = loss_fn(pred, yv).item()
            return {"val_mse": round(mse, 6),
                    "val_mse_steer": round(float(((pred[:, 0] - yv[:, 0]) ** 2).mean()), 6),
                    "val_mse_throttle": round(float(((pred[:, 1] - yv[:, 1]) ** 2).mean()), 6)}

    history = []
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        tot, nb = 0.0, 0
        for xb, yb in train_loader:
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            tot += loss.item()
            nb += 1
        vm = val_metrics()
        history.append({"epoch": epoch, "train_mse": round(tot / max(nb, 1), 6), **vm})
        print(f"[bc] epoch {epoch}: train_mse={history[-1]['train_mse']} val_mse={vm['val_mse']}")
    wall = time.time() - t0
    final = val_metrics()
    print(f"[bc] 训练完成 {wall:.0f}s;final {final}")
    return {"model": model, "history": history, "final_val": final,
            "wall_s": round(wall, 1), "card": card}


def _metas(dirs: list) -> np.ndarray:
    return np.concatenate([load_dataset(d)["meta"] for d in dirs])


def export_to_sb3_zip(bc_model: nn.Module, mode: str, obs_dim: int, path: str) -> str:
    """灌权 → SB3 zip(num_timesteps=0;sdsandbox bc_train.py:235-253 同法)。"""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv
    import gymnasium as gym

    class _DummyEnv(gym.Env):
        metadata = {}
        action_space = gym.spaces.Box(-1.0, 1.0, (2,), np.float32)
        observation_space = (gym.spaces.Box(-np.inf, np.inf, (obs_dim,), np.float32)
                             if mode == "state"
                             else gym.spaces.Box(0, 255, (120, 160, 3), np.uint8))

        def reset(self, *, seed=None, options=None):
            return np.zeros(self.observation_space.shape, np.float32), {}

        def step(self, a):
            return np.zeros(self.observation_space.shape, np.float32), 0.0, False, False, {}

    policy_cls = "MlpPolicy" if mode == "state" else "CnnPolicy"
    ppo = PPO(policy_cls, DummyVecEnv([_DummyEnv]), device="cpu", seed=0)
    with torch.no_grad():  # 叶子参数要求 grad,原地 copy_ 须在 no_grad 下
        if mode == "state":
            # mlp_extractor.policy_net: [Linear(in→64), Tanh, Linear(64→64), Tanh]
            pi = ppo.policy.mlp_extractor.policy_net
            pi[0].weight.copy_(bc_model.trunk[0].weight)
            pi[0].bias.copy_(bc_model.trunk[0].bias)
            pi[2].weight.copy_(bc_model.trunk[2].weight)
            pi[2].bias.copy_(bc_model.trunk[2].bias)
        else:
            fe = ppo.policy.features_extractor
            fe.cnn.load_state_dict(bc_model.backbone.cnn.state_dict())
            # SB3 2.9 NatureCNN.linear 是 Sequential(Linear, ReLU)(flatten 在
            # forward 内做;120×160 → 11264 → 512)。Linear 位置不硬编码索引,
            # 按类型探测(Sequential 布局随 SB3 版本变化,实测踩过 [1] 的坑)
            linear_layer = next(m for m in fe.linear if isinstance(m, nn.Linear))
            linear_layer.weight.copy_(bc_model.backbone.linear.weight)
            linear_layer.bias.copy_(bc_model.backbone.linear.bias)
        ppo.policy.action_net.weight.copy_(bc_model.head.weight)
        ppo.policy.action_net.bias.copy_(bc_model.head.bias)
    ppo.num_timesteps = 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    ppo.save(path)
    return path + ".zip" if not path.endswith(".zip") else path


def self_check(bc_model: nn.Module, mode: str, obs_dim: int, zip_path: str,
               n: int = 256, atol: float = 1e-5) -> dict:
    """灌权机器证明:PPO.load(zip) deterministic 前向 == BC torch 前向(atol 1e-5)。"""
    from stable_baselines3 import PPO

    model = PPO.load(zip_path, device="cpu")
    rng = np.random.default_rng(0)
    with torch.inference_mode():
        if mode == "state":
            obs = rng.uniform(-2, 2, (n, obs_dim)).astype(np.float32)
            obs_t = torch.as_tensor(obs)
            bc_out = bc_model(obs_t).numpy()
        else:
            imgs = rng.integers(0, 255, (n, 120, 160, 3), dtype=np.uint8)
            obs = imgs
            x = torch.as_tensor(imgs.astype(np.float32) / 255.0).permute(0, 3, 1, 2)
            bc_out = bc_model(x).numpy()
        # 用 policy._predict(分布 mode,**不经 action-space clip**)而非 predict:
        # predict 会 clip 到 [-1,1],大权重自检输入下会产生假不一致(实测踩坑)。
        # 这正是热启动后 PPO 的确定性动作取值路径,口径等价。
        obs_tensor, _ = model.policy.obs_to_tensor(np.asarray(obs))
        sb_out = model.policy._predict(obs_tensor, deterministic=True).numpy()
    max_delta = float(np.max(np.abs(sb_out - bc_out)))
    ok = max_delta <= atol
    print(f"[self-check] max|SB3−BC| = {max_delta:.2e}(atol {atol}) → "
          + ("一致 ✓" if ok else "不一致 ✗"))
    return {"max_abs_delta": max_delta, "atol": atol, "pass": bool(ok), "n": n}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", nargs="+", required=True, help="bc_data 目录(可多个)")
    ap.add_argument("--mode", choices=["state", "pixel"], default="state")
    ap.add_argument("--out", default="outputs/bc_export", help="导出目录(zip 前缀)")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-4, help="BC 自身训练 lr(与 PPO 无关)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--hard-oversample", type=float, default=0.3,
                    help="|steer|>0.3 过采样目标占比(sdsandbox 同值;0=关)")
    ap.add_argument("--no-filter-brake", action="store_true", help="保留 brake>0 帧")
    ap.add_argument("--force", action="store_true", help="探针门未过仍训练(须报告说明)")
    ap.add_argument("--skip-probe", action="store_true", help="跳过探针门(自测管线用)")
    ap.add_argument("--no-self-check", action="store_true")
    args = ap.parse_args()

    result = train_bc(args)
    model = result["model"]
    obs_dim = 16
    if args.mode == "pixel":
        obs_dim = 3
    zip_path = export_to_sb3_zip(model, args.mode, obs_dim, args.out)
    print(f"[bc] 导出 → {zip_path}")
    check = None
    if not args.no_self_check:
        check = self_check(model, args.mode, 16 if args.mode == "state" else 3, zip_path)
        if not check["pass"]:
            print("[bc] 灌权一致性未过——禁止用于热启动", file=sys.stderr)
            sys.exit(2)
    out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
    with open(os.path.join(out_dir, "bc_train_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": args.mode, "data": args.data, "epochs": args.epochs,
                   "batch": args.batch, "lr": args.lr, "seed": args.seed,
                   "hard_oversample": args.hard_oversample,
                   "filter_brake": not args.no_filter_brake,
                   "final_val": result["final_val"], "history_tail": result["history"][-5:],
                   "wall_s": result["wall_s"], "export": zip_path,
                   "self_check": check,
                   "card_gates": (result["card"] or {}).get("gates"),
                   "torch": torch.__version__,
                   "finished_at": time.strftime("%F %T")},
                  f, ensure_ascii=False, indent=2)
    print(f"[bc] summary → {os.path.join(out_dir, 'bc_train_summary.json')}")


if __name__ == "__main__":
    main()
