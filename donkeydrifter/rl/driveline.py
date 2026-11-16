"""M4 D1:行车线提取与重锚定数学(纯函数,零 sim;D1.2 提取与 D1.5 BC 变换共用)。

口径纪律(订单):一切量用 **sim 自报 cte**(带符号,与 reward 同源),
node 映射只提供索引——不引入外部坐标假设。

关键约定:
- 中心折线 = rl_centerline_probe.py 逐 node 精确 spawn 的 pos 序列(闭合环);
- 帧 → node:最近中心线点,**时序连续性约束**(窗 ±window 围绕上一帧结果,
  防"自近邻赛道段串位"——环形赛道上对侧段距离可能更近);**局边界(ep 切换)
  全搜重置**;
- node → offset:该 node 上人驾帧的 sim cte 环形中位数 → 循环平滑(忽略 NaN)
  → 缺 node 环形线性插值;
- 重锚:cte' = cte − offset[node]。
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "nearest_node_seq", "circular_smooth", "interpolate_missing",
    "reanchor_cte", "load_driveline", "driveline_gate",
]


def nearest_node_seq(pos: Sequence[Sequence[float]], centerline: Sequence[Sequence[float]],
                     window: int = 32, ep_ids: Optional[Sequence] = None) -> np.ndarray:
    """每帧 pos → 最近中心线 node 索引(时序连续窗;局边界全搜重置)。"""
    cl = np.asarray(centerline, dtype=float)
    n = len(cl)
    P = np.asarray(pos, dtype=float)[:, :3]
    out = np.zeros(len(P), dtype=int)
    prev: Optional[int] = None
    prev_ep = None
    for i in range(len(P)):
        ep = None if ep_ids is None else ep_ids[i]
        if prev is None or (ep_ids is not None and ep != prev_ep):
            cand = range(n)                       # 首帧/新局:全搜
        else:
            cand = ((prev + k) % n for k in range(-window, window + 1))
        best, best_d = None, None
        for j in cand:
            d = float(np.sum((cl[j] - P[i]) ** 2))
            if best_d is None or d < best_d:
                best, best_d = j, d
        out[i] = int(best)
        prev = int(best)
        prev_ep = ep
    return out


def circular_smooth(values: Sequence[float], window: int = 5) -> np.ndarray:
    """环形滑动均值(忽略 NaN;窗口半宽 = window//2;NaN 位置保持 NaN 供插值)。"""
    v = np.asarray(values, dtype=float)
    n = len(v)
    half = max(1, window // 2)
    out = np.full(n, np.nan)
    for i in range(n):
        acc = []
        for k in range(-half, half + 1):
            x = v[(i + k) % n]
            if not math.isnan(x):
                acc.append(x)
        if acc:
            out[i] = float(np.mean(acc))
    return out


def interpolate_missing(values: Sequence[float]) -> np.ndarray:
    """环形线性插值 NaN(全 NaN 则原样返回)。"""
    v = np.asarray(values, dtype=float).copy()
    n = len(v)
    known = np.where(~np.isnan(v))[0]
    if len(known) == 0 or len(known) == n:
        return v
    for i in range(n):
        if not math.isnan(v[i]):
            continue
        # 环形向前/后找最近已知
        d_fwd = next((k for k in range(1, n + 1) if not math.isnan(v[(i + k) % n])), None)
        d_bwd = next((k for k in range(1, n + 1) if not math.isnan(v[(i - k) % n])), None)
        lo = v[(i - d_bwd) % n]   # type: ignore[index]
        hi = v[(i + d_fwd) % n]   # type: ignore[index]
        # 环形线性权重:按到两侧已知点的距离插值;环形跨度上 wrap 一次取直
        span = d_fwd + d_bwd
        w = d_bwd / span
        v[i] = lo + (hi - lo) * w
    return v


def reanchor_cte(cte: Sequence[float], nodes: Sequence[int],
                 offsets: Sequence[float]) -> np.ndarray:
    """cte' = cte − offset[node]。"""
    off = np.asarray(offsets, dtype=float)
    nd = np.asarray(nodes, dtype=int)
    return np.asarray(cte, dtype=float) - off[nd % len(off)]


def load_driveline(path: str) -> np.ndarray:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return np.asarray(d["offsets"], dtype=float)


def driveline_gate(cte_reanchored: Sequence[float]) -> Dict[str, object]:
    """D1.3 硬门:|cte'|>2 占比 <10% 且 mean|cte'|<1.0。"""
    c = np.abs(np.asarray(cte_reanchored, dtype=float))
    over2 = float((c > 2.0).mean()) if len(c) else 1.0
    mean_abs = float(c.mean()) if len(c) else float("inf")
    return {"over2_frac": round(over2, 4), "over2_lt_010": bool(over2 < 0.10),
            "mean_abs_cte": round(mean_abs, 4), "mean_lt_10": bool(mean_abs < 1.0),
            "pass": bool(over2 < 0.10 and mean_abs < 1.0), "n": int(len(c))}
