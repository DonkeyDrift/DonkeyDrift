#!/usr/bin/env python3
"""M2 D3:训练产物离线判读(components.jsonl → ep_rew/ep_len 曲线 + 分量行为)。

用法:
    .venv/bin/python scripts/rl_train_analyze.py outputs/rl_runs/rl_m2_smoke

输出 run_dir/train_analysis.json:
  - episodes:每局 ep_rew/ep_len/终止原因
  - windows:按 10 局滑窗的 ep_rew/ep_len 均值序列(曲线数据)
  - components:各分量在全程/前 20%/后 20% 的均值与符号占比
  - progress_method 占比;raw_reward 与分解 reward 的相关性(对账)
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np


def load(run_dir: str) -> list:
    rows = []
    with open(os.path.join(run_dir, "components.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def analyze(run_dir: str) -> dict:
    rows = load(run_dir)
    n = len(rows)
    comps = ["cte", "progress", "drift", "overspeed", "step", "timeout", "done"]

    # 分局
    episodes = []
    for r in rows:
        if r.get("terminated") or r.get("truncated"):
            episodes.append({"ep_rew": r["ep_rew"], "ep_len": r["ep_steps"],
                             "end": "terminated" if r.get("terminated") else "truncated"})
    ep_rew = np.array([e["ep_rew"] for e in episodes], dtype=float)
    ep_len = np.array([e["ep_len"] for e in episodes], dtype=float)

    def win(a, w=10):
        if len(a) < w:
            return [round(float(np.mean(a)), 3)] if len(a) else []
        return [round(float(np.mean(a[i:i + w])), 3) for i in range(0, len(a) - w + 1, w)]

    def seg_stats(key, lo, hi):
        vals = np.array([r.get(key, 0.0) for r in rows[lo:hi]], dtype=float)
        if len(vals) == 0:
            return {}
        return {"mean": round(float(vals.mean()), 5),
                "pos_frac": round(float((vals > 0).mean()), 3),
                "neg_frac": round(float((vals < 0).mean()), 3),
                "zero_frac": round(float((vals == 0).mean()), 3)}

    k = max(1, n // 5)
    components = {}
    for c in comps:
        components[c] = {"all": seg_stats(c, 0, n),
                         "first20pct": seg_stats(c, 0, k),
                         "last20pct": seg_stats(c, n - k, n)}

    methods = {}
    for r in rows:
        m = r.get("progress_method", "none")
        methods[m] = methods.get(m, 0) + 1

    raw = np.array([r.get("raw_reward", 0.0) for r in rows], dtype=float)
    dec = np.array([r.get("reward", 0.0) for r in rows], dtype=float)
    corr = float(np.corrcoef(raw, dec)[0, 1]) if n > 2 and raw.std() > 0 and dec.std() > 0 else None

    ends = {}
    for e in episodes:
        ends[e["end"]] = ends.get(e["end"], 0) + 1

    out = {
        "run_dir": run_dir, "steps_logged": n, "episodes": len(episodes),
        "episode_end_reasons": ends,
        "ep_rew": {"mean": round(float(ep_rew.mean()), 3) if len(ep_rew) else None,
                   "first10_mean": round(float(ep_rew[:10].mean()), 3) if len(ep_rew) >= 10 else None,
                   "last10_mean": round(float(ep_rew[-10:].mean()), 3) if len(ep_rew) >= 10 else None,
                   "max": round(float(ep_rew.max()), 3) if len(ep_rew) else None,
                   "window10": win(ep_rew)},
        "ep_len": {"mean": round(float(ep_len.mean()), 1) if len(ep_len) else None,
                   "first10_mean": round(float(ep_len[:10].mean()), 1) if len(ep_len) >= 10 else None,
                   "last10_mean": round(float(ep_len[-10:].mean()), 1) if len(ep_len) >= 10 else None,
                   "max": int(ep_len.max()) if len(ep_len) else None,
                   "window10": win(ep_len)},
        "components": components,
        "progress_method_counts": methods,
        "raw_vs_decomposed_reward_corr": None if corr is None else round(corr, 3),
    }
    with open(os.path.join(run_dir, "train_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def main():
    run_dir = sys.argv[1]
    out = analyze(run_dir)
    print(json.dumps({k: v for k, v in out.items() if k != "components"},
                     ensure_ascii=False, indent=2))
    print("components (all / first20% / last20%):")
    for c, d in out["components"].items():
        print(f"  {c:10s} all={d['all'].get('mean')} first={d['first20pct'].get('mean')} "
              f"last={d['last20pct'].get('mean')}  pos/neg/zero(all)="
              f"{d['all'].get('pos_frac')}/{d['all'].get('neg_frac')}/{d['all'].get('zero_frac')}")


if __name__ == "__main__":
    main()
