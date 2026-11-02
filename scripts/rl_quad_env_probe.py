#!/usr/bin/env python3
"""M3 D5(可选):4-env 双进程扩展探针。

端口 9101/9104/9107/9110(隔 3:sim 实例占 port 与 port+1,M2 已核)。
每进程独占 env+sim(进程隔离,M2 实测 SB3 VecEnv 死锁的规避形态),
报聚合吞吐/CPU/稳定性;SB3 SubprocVecEnv 对照列为可选子项(--sb3-vec,
撞 sdsandbox 死锁坑的风险如实报,不解决)。

用法:
    .venv/bin/python scripts/rl_quad_env_probe.py --steps 500
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import numpy as np
import subprocess
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
PORTS = [9101, 9104, 9107, 9110]


def _mp_worker(port: int, n: int, q) -> None:
    """单进程:独占 env+sim 跑 n 步吞吐(sync 0.05 × state × none)。"""
    try:
        _sd = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _sd)  # 子进程继承主进程清理后的 path,自行补
        from _sim_proc import launch_sim, stop_sim
        sys.path[:] = [p for p in sys.path
                       if os.path.abspath(p or os.getcwd()) != _sd]
        from donkeydrifter.rl import DonkeyDriftEnv
        proc = launch_sim(DEFAULT_SIM_APP, port=port, headless=True,
                          log_path=os.path.join(REPO_ROOT, "outputs",
                                                f"sim_quad_{port}.log"))
        env = DonkeyDriftEnv(sim_port=port, sim_path="remote", obs_mode="state",
                             img_enc="none", sync_mode=True, sync_time_step=0.05,
                             connect_timeout_s=120.0, name=f"quad-{port}")
        import statistics
        try:
            env.reset(options={"spawn": True}, seed=port)
            durs, stale = [], 0
            t0 = time.perf_counter()
            for _ in range(n):
                t1 = time.perf_counter()
                _, _, _, _, info = env.step((0.0, 0.5))
                durs.append(time.perf_counter() - t1)
                if info.get("rl/stale"):
                    stale += 1
            elapsed = time.perf_counter() - t0
            q.put({"port": port, "steps_per_s": round(n / elapsed, 2),
                   "step_ms_p50": round(statistics.median(durs) * 1000, 2),
                   "stale": stale})
        finally:
            env.close()
            stop_sim(proc=proc)
    except Exception as e:
        q.put({"port": port, "error": f"{type(e).__name__}: {e}"})


def _sim_cpu_pct() -> list:
    out = subprocess.run(["ps", "ax", "-o", "pid,%cpu,comm"],
                         capture_output=True, text=True).stdout
    rows = [l.split() for l in out.splitlines() if "donkey_sim" in l and "grep" not in l]
    return sorted(round(float(r[1]), 1) for r in rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=500, help="每进程步数")
    ap.add_argument("--sb3-vec", action="store_true",
                    help="附加 SB3 SubprocVecEnv 对照(死锁风险如实报)")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "outputs",
                                                  "rl_quad_env_probe.json"))
    args = ap.parse_args()

    result: dict = {"ports": PORTS, "steps_each": args.steps,
                    "started": time.strftime("%F %T")}
    q = mp.Queue()
    ps = [mp.Process(target=_mp_worker, args=(p, args.steps, q)) for p in PORTS]
    t0 = time.perf_counter()
    for p in ps:
        p.start()
    got = [q.get(timeout=600) for _ in ps]
    wall = time.perf_counter() - t0
    for p in ps:
        p.join(timeout=60)
    oks = [r for r in got if "steps_per_s" in r]
    result["four_env_two_phase"] = {
        "per_env": got,
        "combined_steps_per_s": round(sum(r["steps_per_s"] for r in oks), 2) if oks else None,
        "wall_elapsed_s": round(wall, 1),
        "sim_cpu_pct_during": _sim_cpu_pct(),
        "note": "墙钟含 4×sim 启动(~40s);吞吐为各进程独立测量之和(保守下界)",
    }
    print(json.dumps(result["four_env_two_phase"], ensure_ascii=False, indent=2))

    if args.sb3_vec:
        # 可选对照:SB3 SubprocVecEnv 4 env(sdsandbox 死锁坑;如实报,不解决)
        sub = {"status": None}
        try:
            from _sim_proc import launch_sim, stop_sim
            from stable_baselines3.common.vec_env import SubprocVecEnv
            procs = [launch_sim(DEFAULT_SIM_APP, port=p, headless=True,
                                log_path=os.path.join(REPO_ROOT, "outputs",
                                                      f"sim_quadsb3_{p}.log"))
                     for p in (9131, 9134, 9137, 9140)]

            def _mk(port):
                def _f():
                    return DonkeyDriftEnv(sim_port=port, sim_path="remote",
                                          obs_mode="state", img_enc="none",
                                          sync_mode=True, sync_time_step=0.05,
                                          connect_timeout_s=120.0,
                                          name=f"quadvl-{port}")
                return _f
            t0 = time.perf_counter()
            vec = SubprocVecEnv([_mk(p) for p in (9131, 9134, 9137, 9140)])
            vec.reset()
            n = args.steps // 2
            for _ in range(n):
                vec.step([np.zeros(2, np.float32)] * 4)
            dt = time.perf_counter() - t0
            sub = {"status": "completed", "combined_steps_per_s": round(n * 4 / dt, 2)}
            vec.close()
        except Exception as e:
            sub = {"status": f"failed/hang-caught: {type(e).__name__}: {e}",
                   "note": "sdsandbox 死锁口径复现与否的记录,不解决"}
        finally:
            for p in (9131, 9134, 9137, 9140):
                from _sim_proc import stop_sim
                stop_sim(port=p)
        result["sb3_subprocvecenv_control"] = sub
        print(json.dumps(sub, ensure_ascii=False))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
