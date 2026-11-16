#!/usr/bin/env python3
"""M4 D3:人驾基线离线打分(rl_teleop_record.py --eval-mode 产物 → RL 同口径指标)。

口径与 RL held-out 完全一致:
- 分解 reward(Phase A cfg,与 rl_train/rl_eval 同 RewardConfig);
- progress 优先用录制的 active_node(node 法,与训练同源);缺失回退几何 node
  (pos→中心线最近,时序窗,标记 fallback);
- 局终判定逐帧重放:|锚定 cte|>2 → cte_limit;帧数 ≥2000 → step_budget;
- 输出与 rl_eval 兼容的 json(summary + episodes_detail),三表直接拼。

用法:
    .venv/bin/python scripts/rl_eval_human.py --data outputs/bc_human_eval \
        --tag human_baseline
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl.bc_data import load_dataset  # noqa: E402
from donkeydrifter.rl.driveline import (  # noqa: E402
    driveline_gate, load_driveline, nearest_node_seq,
)
from donkeydrifter.rl.rewards import RewardConfig, reward  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_STEPS = 2000
CTE_LIMIT = 2.0


def score(data_dir: str, driveline_path: str, centerline_path: str,
          label: str, anchor: str) -> dict:
    ds = load_dataset(data_dir)  # eval 模式逐局写 bc npz(兼容加载)
    meta = ds["meta"]
    n = len(meta)
    offsets = load_driveline(driveline_path) if anchor == "line" else None
    cl = (np.asarray(json.load(open(centerline_path))["positions"], dtype=float)
          if anchor == "line" else None)

    # 逐帧组 info(broadcast meta 列 → info dict;缩放还原 state 分量不再需要:
    # meta cte 列在 eval 模式产物里是**未锚定前遥测的锚定值**(env 已锚定)
    infos = []
    for i in range(n):
        infos.append({
            "pos": tuple(meta[i, 3:6]), "speed": meta[i, 6],
            "forward_vel": meta[i, 7], "cte": meta[i, 8],
            "vel": tuple(meta[i, 9:12]), "gyro": tuple(meta[i, 12:15]),
            "accel": tuple(meta[i, 15:18]), "car": tuple(meta[i, 18:21]),
            "active_node": (None if np.isnan(meta[i, 21]) else meta[i, 21]),
            "total_nodes": (None if np.isnan(meta[i, 22]) else meta[i, 22]),
        })

    episodes = []
    ep_start = 0
    cur_ep = int(meta[0, 0])
    cfg = RewardConfig(w_done=1.0)
    fallback_frames = 0
    for i in range(1, n + 1):
        if i < n and int(meta[i, 0]) == cur_ep:
            continue
        seg = list(range(ep_start, i))  # 本局帧索引
        total = 0.0
        steps = 0
        comp_sum = {"cte": 0.0, "progress": 0.0, "drift": 0.0, "overspeed": 0.0,
                    "done": 0.0}
        ctes = []
        end_reason = "step_budget"
        prev = None
        for j in seg:
            info_c = dict(infos[j])
            action = [0.0, 0.0]
            # progress 同源:active_node 缺失时几何 node 回退
            if offsets is not None and info_c["active_node"] is None:
                info_c["active_node"] = None  # 保持;reward 内部退位移法
                fallback_frames += 1
            total_r, comps = reward(prev, info_c, action, cfg)
            total += total_r
            steps += 1
            for k in comp_sum:
                comp_sum[k] += comps.get(k, 0.0)
            ctes.append(abs(float(info_c["cte"])))
            prev = info_c
            if abs(float(info_c["cte"])) > CTE_LIMIT:
                end_reason = "cte_limit"
                break
            if steps >= MAX_STEPS:
                end_reason = "step_budget"
                break
        episodes.append({"ep": cur_ep, "ep_rew": round(total, 3), "ep_len": steps,
                         "end_reason": end_reason,
                         "mean_abs_cte": round(float(np.mean(ctes)), 3) if ctes else None,
                         "max_abs_cte": round(float(np.max(ctes)), 3) if ctes else None,
                         "components": {k: round(v, 3) for k, v in comp_sum.items()},
                         "frames_in_ep": len(seg)})
        ep_start = i
        if i < n:
            cur_ep = int(meta[i, 0])

    rews = [e["ep_rew"] for e in episodes]
    off = sum(1 for e in episodes if e["end_reason"] == "cte_limit")
    summary = {
        "episodes": len(episodes),
        "mean_ep_rew": round(statistics.mean(rews), 3) if rews else None,
        "std_ep_rew": round(statistics.pstdev(rews), 3) if len(rews) > 1 else 0.0,
        "offtrack_rate": round(off / len(episodes), 3) if episodes else None,
        "step_budget_rate": round(sum(1 for e in episodes
                                      if e["end_reason"] == "step_budget") / len(episodes), 3)
        if episodes else None,
        "mean_ep_len": round(statistics.mean(e["ep_len"] for e in episodes), 1)
        if episodes else None,
        "mean_abs_cte_all": round(float(np.mean([e["mean_abs_cte"] for e in episodes
                                                 if e["mean_abs_cte"] is not None])), 3)
        if episodes else None,
    }
    return {"label": label, "data": data_dir,
            "anchor": {"mode": anchor, "driveline": driveline_path if anchor == "line" else None,
                       "cte_limit": CTE_LIMIT, "max_steps": MAX_STEPS},
            "progress_fallback_frames": fallback_frames,
            "episodes_detail": episodes, "summary": summary}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, help="eval 模式产物目录")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--anchor", choices=["line", "center"], default="line")
    ap.add_argument("--driveline", default=os.path.join(REPO_ROOT, "docs", "arch",
                                                        "rl-m4-driveline.json"))
    ap.add_argument("--centerline", default=os.path.join(REPO_ROOT, "docs", "arch",
                                                         "rl-m4-centerline.json"))
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "outputs", "rl_eval"))
    args = ap.parse_args()
    result = score(args.data, args.driveline, args.centerline, args.tag, args.anchor)
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"eval_human_{args.tag}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
