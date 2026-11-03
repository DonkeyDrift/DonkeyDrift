#!/usr/bin/env python3
"""M3:held-out 评测执行器(prereg 唯一口径;D3 A/B 与 D4 定标共用)。

加载 SB3 zip → 独立 sim 实例 × N 局(held-out 课程种子)→ 分解 reward 口径
逐局指标 → json。评测对两臂盲执行:同一脚本、同一实例池、同一种子序列。

口径(prereg 锁定):
- sync 0.05 × state obs(16 维)× DecomposedRewardWrapper(Phase A cfg,与
  训练 reward 同一配置——ep_rew = 分解 total 累计,非 sim raw);
- held-out spawn 种子基数默认 50000+(训练用 1000+ 系,不重叠);
- 长局 max 2000 步;指标:ep_rew / 出界率(truncated 占比)/ ep_len /
  progress 分量累计 / cte 分布摘要;
- 关闭顺序与 sim 清单走 M2 纪律(子进程精确 pid,零 pkill)。

用法:
    .venv/bin/python scripts/rl_eval.py --model outputs/rl_runs/rl_m2_smoke/snap_100000/model \
        --tag m2snap100 --episodes 12 --spawn-seed-base 50000 --port 9301
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim  # noqa: E402
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402
from donkeydrifter.rl.curriculum import CurriculumConfig, SpawnCurriculum  # noqa: E402
from donkeydrifter.rl.rewards import DecomposedRewardWrapper, RewardConfig  # noqa: E402

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def evaluate(model_path: str, sim_app: str, port: int, episodes: int,
             spawn_seed_base: int, max_steps: int, time_step: float,
             cte_limit: float, label: str, anchor_path=None) -> dict:
    from stable_baselines3 import PPO

    anchor_cfg = None
    if anchor_path:
        with open(anchor_path, encoding="utf-8") as f:
            doc = json.load(f)
        anchor_cfg = {"mode": "line", "offsets": doc["offsets"],
                      "cte_unit_gain": doc["cte_unit_gain"]}
    model = PPO.load(model_path, device="cpu")
    proc = launch_sim(sim_app, port=port, headless=True,
                      log_path=os.path.join(REPO_ROOT, "outputs",
                                            f"sim_eval_{label}_{port}.log"))
    env = DonkeyDriftEnv(sim_port=port, sim_path="remote", obs_mode="state",
                         img_enc="none", sync_mode=True, sync_time_step=time_step,
                         cte_limit=cte_limit, max_episode_steps=max_steps,
                         spawn_curriculum=SpawnCurriculum(CurriculumConfig(
                             seed=spawn_seed_base)), cte_anchor=anchor_cfg,
                         connect_timeout_s=90.0, name=f"eval-{label}")
    episodes_out = []
    try:
        wrapped = DecomposedRewardWrapper(env, cfg=RewardConfig(w_done=1.0))
        for ep in range(episodes):
            obs, info = wrapped.reset()
            done = False
            total = 0.0
            steps = 0
            comp_sum = {"cte": 0.0, "progress": 0.0, "drift": 0.0,
                        "overspeed": 0.0, "done": 0.0}
            ctes = []
            end_reason = "max_steps"
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, r, term, trunc, sinfo = wrapped.step(action)
                total += r
                steps += 1
                ctes.append(float(sinfo.get("cte") or 0.0))
                comps = sinfo.get("reward_components") or {}
                for k in comp_sum:
                    comp_sum[k] += comps.get(k, 0.0)
                if term:
                    end_reason = "terminated"
                    break
                if trunc:
                    end_reason = sinfo.get("rl/trunc_reason", "truncated")
                    break
            episodes_out.append({
                "ep": ep, "ep_rew": round(total, 3), "ep_len": steps,
                "end_reason": end_reason,
                "mean_abs_cte": round(float(np.mean(np.abs(ctes))), 3) if ctes else None,
                "max_abs_cte": round(float(np.max(np.abs(ctes))), 3) if ctes else None,
                "components": {k: round(v, 3) for k, v in comp_sum.items()},
            })
    finally:
        env.close()
        stop_sim(proc=proc)

    rews = [e["ep_rew"] for e in episodes_out]
    off = sum(1 for e in episodes_out if e["end_reason"].startswith("cte_limit"))
    summary = {
        "episodes": episodes,
        "mean_ep_rew": round(statistics.mean(rews), 3) if rews else None,
        "std_ep_rew": round(statistics.pstdev(rews), 3) if len(rews) > 1 else 0.0,
        "offtrack_rate": round(off / episodes, 3) if episodes else None,
        "terminated_rate": round(sum(1 for e in episodes_out
                                     if e["end_reason"] == "terminated") / episodes, 3)
        if episodes else None,
        "mean_ep_len": round(statistics.mean(e["ep_len"] for e in episodes_out), 1)
        if episodes else None,
        "mean_abs_cte_all": round(float(np.mean([e["mean_abs_cte"] for e in episodes_out
                                                 if e["mean_abs_cte"] is not None])), 3)
        if episodes else None,
    }
    return {"label": label, "model": os.path.abspath(model_path),
            "anchor": {"mode": "line" if anchor_cfg else "center",
                       "source": anchor_path,
                       "cte_unit_gain": (anchor_cfg or {}).get("cte_unit_gain"),
                       "cte_limit": cte_limit},
            "port": port, "episodes_detail": episodes_out, "summary": summary}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="SB3 zip 路径")
    ap.add_argument("--tag", required=True, help="输出文件名标识")
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--port", type=int, default=9301)
    ap.add_argument("--episodes", type=int, default=12, help="总局数(prereg ≥10)")
    ap.add_argument("--spawn-seed-base", type=int, default=50000,
                    help="held-out 课程种子基数(训练用 1000+ 系,不重叠)")
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--time-step", type=float, default=0.05)
    ap.add_argument("--cte-limit", type=float, default=2.0)
    ap.add_argument("--cte-anchor", default=None,
                    help="M4:行车线锚 json;缺省=center。口径红线:必须与被评模型的训练 anchor 一致")
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "outputs", "rl_eval"))
    args = ap.parse_args()

    t0 = time.time()
    result = evaluate(args.model, args.sim_app, args.port, args.episodes,
                      args.spawn_seed_base, args.max_steps, args.time_step,
                      args.cte_limit, args.tag, anchor_path=args.cte_anchor)
    result["meta"] = {"anchor_cli": args.cte_anchor or "center(未显式指定)",
                      "sim_app": resolve_sim_exe(args.sim_app),
                      "spawn_seed_base": args.spawn_seed_base,
                      "max_steps": args.max_steps, "time_step": args.time_step,
                      "cte_limit": args.cte_limit,
                      "wall_s": round(time.time() - t0, 1),
                      "finished_at": time.strftime("%F %T")}
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"eval_{args.tag}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
