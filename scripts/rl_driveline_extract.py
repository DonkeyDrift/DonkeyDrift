#!/usr/bin/env python3
"""M4 D1.2:人驾行车线提取(bc_data_web1_clean → node→offset 表)+ D1.3 硬门。

流程:每帧 pos → 最近 node(时序连续窗 ±32,局边界全搜;见
donkeydrifter/rl/driveline.py)→ 每 node 收集该帧 sim cte 的中位数 →
循环平滑(窗 5,忽略缺失)→ 缺 node 环形线性插值 → offsets 表。

硬门(D1.3,不过不许进 D2):人驾数据重锚后 |cte'|>2 占比 <10% 且
mean|cte'|<1.0(米制)。不达标退出码 1。

**单位真相(2026-11-03 实测,推翻订单事实 4 的隐含假设,已按纪律上报)**:
sim 自报 cte **不是米**——对账拟合 `cte_sim = gain × signed_d(米)`,
gain = **−8.119**(R²=0.993,残差 p50 0.05m;决定性实验:spawn lateral=0 时
sim cte≈0 → 锚同源,纯单位增益)。因此本脚本:①拟合 gain 并落档;
②**offsets 表与重锚后 cte' 全部以米为单位**;③M4 env 全链(reward/截断/obs)
统一 cte_m = cte_sim / gain,cte_limit 参数自此为米。

产出:docs/arch/rl-m4-driveline.json
    {total_nodes, cte_unit_gain, offsets(米): [...], coverage, gate(米制), ...}
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl.bc_data import load_dataset  # noqa: E402
from donkeydrifter.rl.driveline import (  # noqa: E402
    circular_smooth, driveline_gate, interpolate_missing, nearest_node_seq,
    reanchor_cte,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTERLINE_DEFAULT = os.path.join(REPO_ROOT, "docs", "arch", "rl-m4-centerline.json")
OUT_DEFAULT = os.path.join(REPO_ROOT, "docs", "arch", "rl-m4-driveline.json")
COL_CTE = META_CTE = 8  # META_COLUMNS.index("cte")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="outputs/bc_data_web1_clean")
    ap.add_argument("--centerline", default=CENTERLINE_DEFAULT)
    ap.add_argument("--window", type=int, default=32)
    ap.add_argument("--smooth-window", type=int, default=5)
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()

    with open(args.centerline, encoding="utf-8") as f:
        cl_doc = json.load(f)
    centerline = cl_doc["positions"]
    n_nodes = len(centerline)

    ds = load_dataset(args.data)
    meta = ds["meta"]
    pos = meta[:, 3:6]          # META_COLUMNS: pos_x/y/z
    cte = meta[:, COL_CTE]
    ep_ids = meta[:, 0]
    valid = ~np.isnan(cte) & ~np.isnan(pos[:, 0])
    pos, cte, ep_ids = pos[valid], cte[valid], ep_ids[valid]
    print(f"[driveline] 帧 {len(pos)}(有效 cte/pos),中心线 {n_nodes} node")

    nodes = nearest_node_seq(pos, centerline, window=args.window, ep_ids=ep_ids)

    # 单位对账:cte_sim = gain × signed_d(米),过原点最小二乘(见模块 docstring)
    tang = np.zeros_like(np.asarray(centerline, dtype=float))
    cl = np.asarray(centerline, dtype=float)
    for i in range(n_nodes):
        t = cl[(i + 1) % n_nodes] - cl[(i - 1) % n_nodes]
        tang[i] = t / (np.linalg.norm(t) + 1e-9)
    nd_here = nodes
    d_vec = pos - cl[nd_here]
    signed = d_vec[:, 0] * (-tang[nd_here][:, 2]) + d_vec[:, 2] * tang[nd_here][:, 0]
    gain = float(np.sum(cte * signed) / max(np.sum(signed * signed), 1e-9))
    # 拟合质量(R²)与增益合理性门(量级应 ~-8;偏离 = 数据/几何异常)
    pred = gain * signed
    r2 = 1 - ((cte - pred) ** 2).sum() / ((cte - cte.mean()) ** 2).sum()
    print(f"[driveline] 单位对账: cte_sim = {gain:.3f} × signed_d(m), R²={r2:.4f}")
    if not (0.3 < abs(gain) < 30 and r2 > 0.95):
        raise SystemExit(f"[driveline] 增益/拟合异常(gain={gain:.3f}, R²={r2:.4f})——"
                         "几何或数据有问题,禁止继续")
    cte_m = cte / gain  # 米制(sim 原始 → 米)

    # 每 node 收集 **米制** cte → 中位数
    per_node: dict[int, list] = {}
    for nd, c in zip(nodes.tolist(), cte_m.tolist()):
        per_node.setdefault(nd, []).append(c)
    raw = np.full(n_nodes, np.nan)
    for nd, vals in per_node.items():
        raw[nd] = float(np.median(vals))
    covered = len(per_node)
    smoothed = circular_smooth(raw, window=args.smooth_window)
    offsets = interpolate_missing(smoothed)

    # 硬门(米制):重锚后人驾 cte' 分布
    cte_r = reanchor_cte(cte_m, nodes, offsets)
    gate = driveline_gate(cte_r)

    print(f"[driveline] 覆盖 node {covered}/{n_nodes}(缺失 {n_nodes - covered} 已插值)")
    print(f"[driveline] offset: median|o|={np.median(np.abs(offsets)):.3f} "
          f"max|o|={np.max(np.abs(offsets)):.3f}")
    before = {"over2_frac": float((np.abs(cte_m) > 2).mean()),
              "mean_abs_cte": float(np.abs(cte_m).mean())}
    print(f"[driveline] 锚定前 |cte|>2={before['over2_frac']:.1%} "
          f"mean|cte|={before['mean_abs_cte']:.3f}")
    print(f"[driveline] 锚定后 |cte'|>2={gate['over2_frac']:.1%} "
          f"mean|cte'|={gate['mean_abs_cte']:.3f} → 门 {'PASS' if gate['pass'] else 'FAIL'}")

    out = {
        "total_nodes": n_nodes,
        "cte_unit_gain": round(gain, 4),
        "cte_units": "sim 原始 cte 为增益单位;本文件 offsets 与重锚 cte' 均为米;"
                     "env 侧统一 cte_m = cte_sim / gain",
        "fit_r2": round(r2, 4),
        "offsets": [round(float(x), 4) for x in offsets],
        "coverage": {"nodes_covered": covered,
                     "frames": int(len(pos)),
                     "per_node_counts_p50": float(np.median([len(v) for v in per_node.values()]))
                     if per_node else 0,
                     "missing_nodes_interpolated": int(n_nodes - covered)},
        "smoothing": {"window": args.smooth_window, "median_then_smooth": True},
        "search_window": args.window,
        "before_anchor": {"over2_frac": round(before["over2_frac"], 4),
                          "mean_abs_cte": round(before["mean_abs_cte"], 4)},
        "gate": gate,
        "source_data": args.data,
        "centerline_source": args.centerline,
        "recorded_at": __import__("time").strftime("%F %T"),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"→ {args.out}")
    if not gate["pass"]:
        print("[driveline] 硬门未过——提取/映射有错,禁止进入 D2(订单纪律)",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
