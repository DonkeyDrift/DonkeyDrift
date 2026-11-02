"""M3 D0:BC 数据集格式、data card、蒙太奇(纯函数,零 sim,D0 采样与 D2 训练共用)。

格式(对齐 sdsandbox src/bc_collect.py / bc_train.py 口径,并扩展 state 列):
    bc_%05d.npz{
        image:    [N,120,160,3] uint8   (NN 输入帧,HWC;训练侧 /255 → CHW)
        state:    [N,16]        float32 (env.state_vector() 原样,训练 state obs 同函数)
        steer:    [N]           float32 ∈[-1,1]
        throttle: [N]           float32 ∈[-1,1]
        brake:    [N]           float32 ∈[0,1]  (人驾手刹;BC 训练默认过滤 brake>0 帧)
        meta:     [N,K]         float32 列见 META_COLUMNS;meta[:,0]=ep_id 目录内全局唯一
    }
配对口径 = **观测→动作**(obs_k 配人对 obs_k 的反应 a_k),与 M1 teleop.npz 的
「动作→结果」口径不同;meta 的 frame_id 使两种都可重建。

data card 键名对齐 sdsandbox(pairs_total/episodes/steer_*/steer_hard_frac/thr_*/
thr_gt02_frac/img_std_last_shard/throttle_hist_10)+ 门判定(gates)。门口径:
img std>20、|steer|>0.3 占比≥15%、throttle>0.2 占比≥30%(relax 口径)、steer 双侧。
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

__all__ = [
    "META_COLUMNS", "HARD_STEER", "GATES",
    "EpisodeBuffer", "write_episode_npz", "load_dataset",
    "compute_data_card", "make_montage",
]

# meta 列定义(float32;索引稳定,追加只能加在末尾)
META_COLUMNS: List[str] = [
    "ep_id", "frame_id", "t",
    "pos_x", "pos_y", "pos_z", "speed", "forward_vel", "cte",
    "vel_x", "vel_y", "vel_z", "gyro_x", "gyro_y", "gyro_z",
    "accel_x", "accel_y", "accel_z", "roll", "pitch", "yaw",
    "active_node", "total_nodes",
]
HARD_STEER = 0.3  # 纠偏帧阈值(sdsandbox bc_train.py:141/172 同值)

# 门口径(sdsandbox bc_collect.py:190-213 同值;thr 门 relax 到 0.30)
GATES: Dict[str, float] = {
    "img_std_min": 20.0,
    "steer_hard_frac_min": 0.15,
    "thr_gt02_frac_min": 0.30,
    "steer_two_sided_abs": 0.10,   # p05 < -0.10 且 p95 > +0.10
    "frames_min_user": 3000,       # 用户采样目标(只报不拦)
}


def _f(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x


def telemetry_to_meta_row(ep_id: int, frame_id: Any, t: float, tele: Dict[str, Any]) -> np.ndarray:
    """遥测 dict → meta 行(列序 META_COLUMNS;缺失字段 NaN)。"""
    pos = tele.get("pos") or (None, None, None)
    vel = tele.get("vel") or (None, None, None)
    gyro = tele.get("gyro") or (None, None, None)
    acc = tele.get("accel") or (None, None, None)
    rpy = tele.get("car") or (None, None, None)
    row = [
        float(ep_id), _f(frame_id), float(t),
        _f(pos[0]), _f(pos[1]), _f(pos[2]),
        _f(tele.get("speed")), _f(tele.get("forward_vel")), _f(tele.get("cte")),
        _f(vel[0]), _f(vel[1]), _f(vel[2]),
        _f(gyro[0]), _f(gyro[1]), _f(gyro[2]),
        _f(acc[0]), _f(acc[1]), _f(acc[2]),
        _f(rpy[0]), _f(rpy[1]), _f(rpy[2]),
        _f(tele.get("active_node")), _f(tele.get("total_nodes")),
    ]
    return np.asarray(row, dtype=np.float32)


class EpisodeBuffer:
    """一局的帧缓冲;flush 时写 bc_%05d.npz。"""

    def __init__(self, ep_id: int):
        self.ep_id = int(ep_id)
        self.images: List[np.ndarray] = []
        self.states: List[np.ndarray] = []
        self.actions: List[Sequence[float]] = []
        self.meta: List[np.ndarray] = []

    def __len__(self) -> int:
        return len(self.images)

    def add(self, image: np.ndarray, state: np.ndarray, action: Sequence[float],
            tele: Dict[str, Any], frame_id: Any, t: float) -> None:
        img = np.asarray(image, dtype=np.uint8)
        if img.ndim != 3 or img.shape[2] != 3:
            raise ValueError(f"image 须为 HxWx3 uint8,得到 {img.shape}")
        st = np.asarray(state, dtype=np.float32)
        if st.ndim != 1:
            raise ValueError(f"state 须为一维向量,得到 {st.shape}")
        self.images.append(img)
        self.states.append(st)
        self.actions.append((float(action[0]), float(action[1]),
                             float(action[2]) if len(action) > 2 else 0.0))
        self.meta.append(telemetry_to_meta_row(self.ep_id, frame_id, t, tele))


def write_episode_npz(out_dir: str, buf: EpisodeBuffer) -> Optional[str]:
    """写一局;空局返回 None。文件号 = ep_id(目录内唯一)。"""
    if len(buf) == 0:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"bc_{buf.ep_id:05d}.npz")
    acts = np.asarray(buf.actions, dtype=np.float32)
    np.savez_compressed(
        path,
        image=np.stack(buf.images), state=np.stack(buf.states),
        steer=acts[:, 0], throttle=acts[:, 1], brake=acts[:, 2],
        meta=np.stack(buf.meta))
    return path


def load_dataset(dir_or_files, require_state: bool = True) -> Dict[str, np.ndarray]:
    """合并目录(或文件列表)内全部 bc_*.npz;ep_id 已是目录内唯一,原样保留。"""
    if isinstance(dir_or_files, str):
        files = sorted(glob.glob(os.path.join(dir_or_files, "bc_*.npz")))
    else:
        files = sorted(dir_or_files)
    if not files:
        raise FileNotFoundError(f"无 bc_*.npz:{dir_or_files}")
    keys = ["image", "steer", "throttle", "brake", "meta"] + (["state"] if require_state else [])
    acc: Dict[str, list] = {k: [] for k in keys}
    for f in files:
        d = np.load(f)
        for k in keys:
            if k not in d:
                raise KeyError(f"{f} 缺键 {k}")
            acc[k].append(d[k])
    out = {k: np.concatenate(v, axis=0) for k, v in acc.items()}
    out["files"] = np.asarray(files)
    return out


def compute_data_card(steer: np.ndarray, throttle: np.ndarray, brake: np.ndarray,
                      meta: np.ndarray, img_std_samples: Sequence[float],
                      img_std_last_shard: float, fps_measured: Optional[float] = None,
                      dropped_frames: int = 0, disconnects: int = 0,
                      spawn_points: Optional[list] = None,
                      extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """data card + 门判定(键名对齐 sdsandbox;gates 子字典逐项 bool)。"""
    st = np.asarray(steer, dtype=float)
    th = np.asarray(throttle, dtype=float)
    br = np.asarray(brake, dtype=float)
    ep_ids = np.asarray(meta[:, 0], dtype=int) if len(meta) else np.zeros(0, int)
    uniq, counts = np.unique(ep_ids, return_counts=True)
    n = int(len(st))
    steer_hard = float(np.mean(np.abs(st) > HARD_STEER)) if n else 0.0
    thr_ok = float(np.mean(th > 0.2)) if n else 0.0
    p05 = float(np.percentile(st, 5)) if n else 0.0
    p95 = float(np.percentile(st, 95)) if n else 0.0
    hist, _ = np.histogram(np.clip(th, 0, 1), bins=10, range=(0, 1))
    img_std_global = float(np.mean(img_std_samples)) if len(img_std_samples) else float("nan")
    card: Dict[str, Any] = {
        "pairs_total": n,
        "episodes": int(len(uniq)),
        "episode_lengths": {int(e): int(c) for e, c in zip(uniq, counts)},
        "steer_mean": float(st.mean()) if n else 0.0,
        "steer_std": float(st.std()) if n else 0.0,
        "steer_p05": p05, "steer_p95": p95,
        "steer_hard_frac": steer_hard,
        "thr_mean": float(th.mean()) if n else 0.0,
        "thr_std": float(th.std()) if n else 0.0,
        "thr_gt02_frac": thr_ok,
        "throttle_hist_10": [int(x) for x in hist],
        "brake_frac": float(np.mean(br > 0.0)) if n else 0.0,
        "img_std_last_shard": float(img_std_last_shard),
        "img_std_global_mean": img_std_global,
        "fps_measured": fps_measured,
        "dropped_frames": int(dropped_frames),
        "disconnects": int(disconnects),
        "spawn_points": spawn_points or [],
        "pairing": "obs_k -> a_k(观测→动作)",
    }
    if extra:
        card.update(extra)
    gates = {
        "img_std_gt20": bool(float(img_std_last_shard) > GATES["img_std_min"]),
        "steer_hard_ge15pct": bool(steer_hard >= GATES["steer_hard_frac_min"]),
        "thr_gt02_ge30pct": bool(thr_ok >= GATES["thr_gt02_frac_min"]),
        "steer_two_sided": bool(p05 < -GATES["steer_two_sided_abs"]
                                and p95 > GATES["steer_two_sided_abs"]),
        "frames_ge_3000_user_target": bool(n >= GATES["frames_min_user"]),
    }
    hard_gates = ["img_std_gt20", "steer_hard_ge15pct", "thr_gt02_ge30pct", "steer_two_sided"]
    card["gates"] = gates
    card["gates_pass_all_hard"] = all(gates[g] for g in hard_gates)
    card["gate_thresholds"] = dict(GATES)
    return card


def make_montage(images: np.ndarray, path: str, grid: int = 4) -> str:
    """均匀抽 grid² 帧拼 grid×grid jpg(人工复核采样质量用)。"""
    from PIL import Image

    n = len(images)
    k = grid * grid
    if n == 0:
        raise ValueError("无图像")
    pick = np.linspace(0, n - 1, k).astype(int)
    tiles = [np.asarray(images[i], dtype=np.uint8) for i in pick]
    rows = [np.concatenate(tiles[r * grid:(r + 1) * grid], axis=1) for r in range(grid)]
    mosaic = np.concatenate(rows, axis=0)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(mosaic).save(path, quality=85)
    return path


def dump_card(out_dir: str, card: Dict[str, Any]) -> str:
    path = os.path.join(out_dir, "data_card.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    return path
