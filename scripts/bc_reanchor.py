#!/usr/bin/env python3
"""M4 D1.5:BC 数据重锚变换(bc_data_web1_clean → bc_data_web2_anchor)。

只动 cte 口径:image/action/其余 state 分量原样;变换:
    state[:,0](cte 分量,缩放 /2)← (cte_raw/gain − offset[node]) / 2
    meta[:,8](cte 列)           ← cte_raw/gain − offset[node](米制锚定值)
其中 cte_raw 反解自 state[:,0]×2(M3 采样时 state 分量 = cte_sim/2),
node 由 pos 对中心线最近搜索(时序连续窗,局边界全搜)。

规则与前后分布写入新目录 data_card.json(原始目录不动)。
"""

from __future__ import annotations

import argparse
import glob
import json
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
    driveline_gate, load_driveline, nearest_node_seq, reanchor_cte,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COL_CTE = 8
STATE_CTE_SCALE = 2.0  # env state obs 的 cte 分量缩放(_STATE_SCALES["cte"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default="outputs/bc_data_web1_clean")
    ap.add_argument("--out", default="outputs/bc_data_web2_anchor")
    ap.add_argument("--driveline", default="docs/arch/rl-m4-driveline.json")
    ap.add_argument("--centerline", default="docs/arch/rl-m4-centerline.json")
    args = ap.parse_args()

    offsets = load_driveline(args.driveline)
    cl = np.asarray(json.load(open(args.centerline))["positions"], dtype=float)
    gain = float(json.load(open(args.driveline))["cte_unit_gain"])

    ds = load_dataset(args.src)
    meta_all, state_all = ds["meta"], ds["state"]
    nodes = nearest_node_seq(meta_all[:, 3:6], cl, window=32, ep_ids=meta_all[:, 0])
    cte_raw = state_all[:, 0] * STATE_CTE_SCALE      # 反解 sim 原始 cte
    cte_new = reanchor_cte(cte_raw / gain, nodes, offsets)  # 米制锚定

    os.makedirs(args.out, exist_ok=True)
    n_files = 0
    for f in sorted(glob.glob(os.path.join(args.src, "bc_*.npz"))):
        d = dict(np.load(f))
        lo, hi = int(d["meta"][0, 0]), None  # ep_id 连续段定位(meta 已按局连续)
        ep = int(d["meta"][0, 0])
        sel = np.where(meta_all[:, 0].astype(int) == ep)[0]
        if len(sel) != len(d["meta"]):  # 同 ep_id 分片不存在(逐局文件),直接按序
            sel = np.arange(0, 0)
        st = d["state"].copy()
        mt = d["meta"].copy()
        if len(sel) == len(st):
            st[:, 0] = cte_new[sel] / STATE_CTE_SCALE
            mt[:, COL_CTE] = cte_new[sel]
        else:
            # 兜底:按全局序同位替换(逐局文件与全局拼接一一对应的前缀段)
            start = int(np.where(meta_all[:, 0].astype(int) == ep)[0][0])
            st[:, 0] = cte_new[start:start + len(st)] / STATE_CTE_SCALE
            mt[:, COL_CTE] = cte_new[start:start + len(st)]
        np.savez_compressed(os.path.join(args.out, os.path.basename(f)),
                            **{**d, "state": st, "meta": mt})
        n_files += 1

    # 新口径 data card(含换算规则与前后分布)
    card = {
        "pairs_total": int(len(cte_new)),
        "episodes": int(len(set(meta_all[:, 0].astype(int).tolist()))),
        "transform": {"rule": "cte_m = cte_sim/gain − offset[node];state[:,0]=cte_m/2",
                      "cte_unit_gain": gain, "driveline": args.driveline,
                      "node_mapping": "nearest centerline node, window ±32, ep-reset"},
        "cte_before_m": {"over2_frac": float((np.abs(cte_raw / gain) > 2).mean()),
                         "mean_abs": float(np.abs(cte_raw / gain).mean())},
        "cte_after_m": {"over2_frac": float((np.abs(cte_new) > 2).mean()),
                        "mean_abs": float(np.abs(cte_new).mean())},
        "gate": driveline_gate(cte_new),
        "steer_hard_frac": float((np.abs(ds["steer"]) > 0.3).mean()),
        "img_std_last": float(ds["image"][-300:].astype(float).std()),
        "recorded_at": __import__("time").strftime("%F %T"),
    }
    with open(os.path.join(args.out, "data_card.json"), "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: card[k] for k in
                      ("pairs_total", "episodes", "cte_before_m", "cte_after_m", "gate")},
                     ensure_ascii=False, indent=1))
    print(f"{n_files} 局 → {args.out}")


if __name__ == "__main__":
    main()
