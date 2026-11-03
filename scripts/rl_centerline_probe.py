#!/usr/bin/env python3
"""M4 D1.1:中心线探针——RL env(sync)逐 node 精确 spawn 读 pos → 中心折线。

spawn_cfg = {node_index: i, lateral_offset: 0, heading_noise: 0}(M1 smoke #7
实证 node_index 精确出生);固定 seed 保证可复现。产出:
    docs/arch/rl-m4-centerline.json
    {total_nodes, positions: [[x,y,z]×N], closed: bool, spacing: {mean/max/min},
     probe_seed, recorded_at}
校验:点数 = totalNodes;闭合(首尾相邻距 ≤ 3×平均相邻距)——不满足 = 探针
有错,如实报并退出码 1。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim  # noqa: E402
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DEFAULT = os.path.join(REPO_ROOT, "docs", "arch", "rl-m4-centerline.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--port", type=int, default=9401)
    ap.add_argument("--probe-seed", type=int, default=777)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--limit", type=int, default=0, help="只探前 N 个 node(0=全部;自测用)")
    args = ap.parse_args()

    proc = launch_sim(args.sim_app, port=args.port, headless=True,
                      log_path=os.path.join(REPO_ROOT, "outputs",
                                            f"sim_centerline_{args.port}.log"))
    positions = []
    total_nodes = None
    env = DonkeyDriftEnv(sim_port=args.port, sim_path="remote", obs_mode="state",
                         img_enc="none", sync_mode=True, sync_time_step=0.05,
                         connect_timeout_s=90.0, name="centerline-probe")
    try:
        # 先任意复位一次拿 total_nodes
        _, info = env.reset()
        total_nodes = int(info.get("total_nodes") or 0)
        if total_nodes < 2:
            raise SystemExit(f"total_nodes 异常: {total_nodes}(探针无法继续)")
        n = args.limit or total_nodes
        print(f"[probe] total_nodes={total_nodes},探 {n} 个(node 0..{n-1})")
        for i in range(n):
            cfg = {"node_index": i, "lateral_offset": 0.0, "heading_noise": 0.0}
            _, rinfo = env.reset(options={"spawn_cfg": cfg}, seed=args.probe_seed)
            pos = [round(float(x), 4) for x in rinfo["pos"][:3]]
            positions.append(pos)
            if (i + 1) % 50 == 0:
                print(f"[probe] {i+1}/{n}")
    finally:
        env.close()
        stop_sim(proc=proc)

    # 校验
    if len(positions) >= 2:
        adj = [math.dist(positions[i], positions[(i + 1) % len(positions)])
               for i in range(len(positions))]
        mean_adj = statistics.mean(adj)
        closed = adj[-1] <= max(3.0 * mean_adj, 2.0)
    else:
        mean_adj, closed = float("nan"), False
    full = len(positions) == total_nodes
    ok = full and closed
    out = {
        "total_nodes": total_nodes, "probed": len(positions),
        "positions": positions,
        "closed": bool(closed), "full_coverage": bool(full),
        "spacing": {"mean": round(mean_adj, 4),
                    "max": round(max(adj), 4) if adj else None,
                    "min": round(min(adj), 4) if adj else None},
        "probe_seed": args.probe_seed, "sim_app": resolve_sim_exe(args.sim_app),
        "recorded_at": time.strftime("%F %T"),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[probe] 点数 {len(positions)}/{total_nodes} | 闭合 {closed} | "
          f"间距 mean={out['spacing']['mean']} max={out['spacing']['max']}")
    print(f"→ {args.out}")
    if not ok:
        print("[probe] 校验未过(点数不全或未闭合)——探针有错,禁止进入 D1.2",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
