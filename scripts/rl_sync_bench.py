#!/usr/bin/env python3
"""D2(M2):sync 吞吐实测表 + 确定性验证。

矩阵:
  - 吞吐:单 env × {sync 0.05, sync 0.02} × state(必测);
          sync 0.05 × pixel(参考,少步数+超时守卫——sdsandbox 有 GPU 回读挂起
          前科,本路径是 gym JPEG 链路,仍按守卫跑);
          异步 state(参照基线);2 env × 0.05 × state(双端口双 sim,单进程
          轮转 + 可选 --multi 双进程;**不用 SB3**;死锁/异常如实报不解)。
  - 确定性:同 seed + 同动作序列,两次完整 rollout(同实例两次 reset;
          另跑一次「重拉 sim 后」的 rollout 作跨实例参考),逐帧比对
          pos/cte/speed/yaw,报 max delta。

产物:outputs/rl_sync_bench.json。纪律:sim 只按自家子进程 pid 停,零 pkill。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _sim_proc import launch_sim, stop_sim  # noqa: E402

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"


def _save(path: str, result: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def _sim_cpu(pid: int) -> float:
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "%cpu="],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return float(out) if out else float("nan")
    except (subprocess.SubprocessError, ValueError):
        return float("nan")


def _actions(n: int) -> np.ndarray:
    """确定性动作序列:温和正弦转向 + 定油门(0.5)。"""
    t = np.arange(n) * 0.05
    return np.stack([0.4 * np.sin(2 * np.pi * t / 6.0), np.full(n, 0.5)], axis=1)


def _run_env(port: int, n_steps: int, sync_mode=True, sync_time_step=0.05,
             obs_mode="state", sim_app=DEFAULT_SIM_APP, log_name="bench") -> dict:
    proc = launch_sim(sim_app, port=port, headless=True,
                      log_path=os.path.join(REPO_ROOT, "outputs", f"{log_name}.log"))
    env = DonkeyDriftEnv(sim_port=port, sim_path="remote", obs_mode=obs_mode,
                         img_enc="none" if obs_mode == "state" else None,
                         sync_mode=sync_mode, sync_time_step=sync_time_step,
                         connect_timeout_s=90.0, frame_wait_timeout_s=2.0,
                         name=f"bench-{port}")
    try:
        env.reset(options={"spawn": True}, seed=99)
        acts = _actions(n_steps)
        durs, stale = [], 0
        cpu_samples = []
        last_cpu_t = 0.0
        t0 = time.perf_counter()
        for i in range(n_steps):
            t1 = time.perf_counter()
            _, _, _, _, info = env.step(acts[i])
            durs.append(time.perf_counter() - t1)
            if info.get("rl/stale"):
                stale += 1
            now = time.perf_counter()
            if now - last_cpu_t > 2.0 and proc is not None:
                cpu_samples.append(_sim_cpu(proc.pid))
                last_cpu_t = now
        elapsed = time.perf_counter() - t0
        return {
            "config": {"port": port, "mode": "sync" if sync_mode else "async",
                       "sync_time_step": sync_time_step, "obs": obs_mode},
            "n_steps": n_steps,
            "steps_per_s": round(n_steps / elapsed, 2),
            "step_ms_p50": round(statistics.median(durs) * 1000, 2),
            "step_ms_p95": round(sorted(durs)[int(0.95 * len(durs)) - 1] * 1000, 2),
            "stale": stale,
            "sim_cpu_pct_samples": [round(x, 1) for x in cpu_samples],
        }
    finally:
        env.close()
        stop_sim(proc=proc)


def bench_throughput(args) -> list:
    results = []
    for label, kw, n in [
        ("sync_0.05_state", dict(sync_mode=True, sync_time_step=0.05), args.steps),
        ("sync_0.02_state", dict(sync_mode=True, sync_time_step=0.02), args.steps),
        ("async_state_ref", dict(sync_mode=False), args.steps),
    ]:
        print(f"[bench] {label} ×{n} ...")
        r = _run_env(9091, n, log_name=f"sim_bench_{label}", **kw)
        r["label"] = label
        results.append(r)
        print(f"[bench]   {r['steps_per_s']} 步/s (p50 {r['step_ms_p50']}ms)")
    if args.with_pixel:
        print("[bench] sync_0.05_pixel(参考,守卫 200 步)...")
        try:
            r = _run_env(9091, 200, sync_mode=True, sync_time_step=0.05,
                         obs_mode="pixel", log_name="sim_bench_pixel")
            r["label"] = "sync_0.05_pixel"
            if r["steps_per_s"] < 2.0:
                r["note"] = "吞吐 <2 步/s,疑似渲染链路挂起(守卫阈值),结论如实记录"
            results.append(r)
            print(f"[bench]   {r['steps_per_s']} 步/s")
        except Exception as e:
            results.append({"label": "sync_0.05_pixel", "error": f"{type(e).__name__}: {e}",
                            "note": "像素吞吐探针异常,如实记录"})
    return results


def bench_two_env(args) -> dict:
    """2 env × 0.05 × state:双端口双 sim。单进程轮转(+可选双进程)。"""
    out = {"mode": "single_process_interleaved"}
    procs = []
    envs = []
    try:
        for port in (9091, 9094):  # sim 实例占 port/port+1,双实例须隔 ≥2(实测教训)
            procs.append(launch_sim(DEFAULT_SIM_APP, port=port, headless=True,
                                    log_path=os.path.join(REPO_ROOT, "outputs",
                                                          f"sim_bench_2env_{port}.log")))
            envs.append(DonkeyDriftEnv(sim_port=port, sim_path="remote",
                                       obs_mode="state", img_enc="none",
                                       sync_mode=True, sync_time_step=0.05,
                                       connect_timeout_s=90.0, name=f"bench2-{port}"))
        acts = _actions(args.steps // 2)
        durs = []
        t0 = time.perf_counter()
        done_flags = [False, False]
        i = 0
        while not all(done_flags) and i < args.steps:
            for k, env in enumerate(envs):
                if i >= len(acts):
                    done_flags[k] = True
                    continue
                t1 = time.perf_counter()
                env.step(acts[i])
                durs.append(time.perf_counter() - t1)
            i += 1
        elapsed = time.perf_counter() - t0
        total = sum(len(acts) for _ in envs)
        out.update({
            "total_steps": total, "wall_elapsed_s": round(elapsed, 2),
            "combined_steps_per_s": round(total / elapsed, 2),
            "per_step_ms_p50": round(statistics.median(durs) * 1000, 2),
            "sim_cpu_pct": [round(_sim_cpu(p.pid), 1) for p in procs],
            "note": "单进程轮转受 GIL 约束;combined ≈ 单 env 吞吐即 GIL 顶死,"
                    "M3 多开须进程隔离(--multi 变体给参照)",
        })
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["note"] = out.get("note", "") + "(异常如实报,不解决,留给 M3 决策)"
    finally:
        for env in envs:
            try:
                env.close()
            except Exception:
                pass
        for p in procs:
            stop_sim(proc=p)
    return out


def _mp_worker(port: int, n: int, q) -> None:
    # 注意:sim 实例监听 port 与 port+1(lsof LISTEN 实测),多实例端口须隔 ≥2
    """模块级(可 pickle):子进程独占 env+sim 跑吞吐。"""
    try:
        q.put(_run_env(port, n, log_name=f"sim_bench_mp_{port}"))
    except Exception as e:
        q.put({"port": port, "error": f"{type(e).__name__}: {e}"})


def bench_two_env_multiproc(args) -> dict:
    """双进程隔离变体:每进程独占 env+sim,聚合吞吐(GIL 顶死时的对照)。"""
    import multiprocessing as mp

    q = mp.Queue()
    n_each = args.steps // 2
    ps = [mp.Process(target=_mp_worker, args=(port, n_each, q)) for port in (9091, 9094)]
    t0 = time.perf_counter()
    for p in ps:
        p.start()
    results = [q.get(timeout=600) for _ in ps]
    elapsed = time.perf_counter() - t0
    for p in ps:
        p.join(timeout=30)
    oks = [r for r in results if "steps_per_s" in r]
    return {"mode": "two_process_isolated", "wall_elapsed_s": round(elapsed, 2),
            "combined_steps_per_s": round(sum(r["steps_per_s"] for r in oks), 2),
            "per_env": results,
            "note": "双进程各自启停 sim,墙钟含两次 sim 启动(~20s),"
                    "combined 为保守下界"}


def bench_determinism(args) -> dict:
    """同 seed + 同动作序列,两次 rollout 逐帧比对。"""
    n = args.det_steps
    acts = _actions(n)

    def rollout(env):
        obs, info = env.reset(options={"spawn": True}, seed=42)
        frames = [{"pos": tuple(info["pos"]), "cte": info["cte"],
                   "speed": info["speed"], "yaw": info["car"][2]}]
        for i in range(n):
            _, _, _, _, sinfo = env.step(acts[i])
            frames.append({"pos": tuple(sinfo["pos"]), "cte": sinfo["cte"],
                           "speed": sinfo["speed"], "yaw": sinfo["car"][2]})
        return frames

    def compare(fa, fb):
        deltas = {"pos": [], "cte": [], "speed": [], "yaw": []}
        for a, b in zip(fa, fb):
            deltas["pos"].append(max(abs(a["pos"][k] - b["pos"][k]) for k in range(3)))
            deltas["cte"].append(abs(a["cte"] - b["cte"]))
            deltas["speed"].append(abs(a["speed"] - b["speed"]))
            dy = abs((a["yaw"] - b["yaw"] + 180) % 360 - 180)
            deltas["yaw"].append(dy)
        return {k: {"max": float(np.max(v)), "mean": float(np.mean(v))}
                for k, v in deltas.items()}

    proc = launch_sim(DEFAULT_SIM_APP, port=9091, headless=True,
                      log_path=os.path.join(REPO_ROOT, "outputs", "sim_bench_det.log"))
    env = DonkeyDriftEnv(sim_port=9091, sim_path="remote", obs_mode="state",
                         img_enc="none", sync_mode=True, sync_time_step=0.05,
                         connect_timeout_s=90.0, name="bench-det")
    out = {}
    try:
        fa = rollout(env)
        fb = rollout(env)
        out["same_instance"] = compare(fa, fb)
        out["same_instance"]["note"] = "同 sim 实例两次 reset(seed=42)+ 同动作序列"
    finally:
        env.close()
        stop_sim(proc=proc)
    # 跨实例参考:重拉 sim 后第三次 rollout
    proc = launch_sim(DEFAULT_SIM_APP, port=9091, headless=True,
                      log_path=os.path.join(REPO_ROOT, "outputs", "sim_bench_det2.log"))
    env = DonkeyDriftEnv(sim_port=9091, sim_path="remote", obs_mode="state",
                         img_enc="none", sync_mode=True, sync_time_step=0.05,
                         connect_timeout_s=90.0, name="bench-det2")
    try:
        fc = rollout(env)
        out["fresh_instance"] = compare(fa, fc)
        out["fresh_instance"]["note"] = "重拉 sim 实例后同 seed 同序列(跨实例参考)"
    finally:
        env.close()
        stop_sim(proc=proc)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--steps", type=int, default=1000, help="每配置吞吐步数")
    ap.add_argument("--det-steps", type=int, default=400, help="确定性 rollout 步数")
    ap.add_argument("--with-pixel", action="store_true", help="加像素吞吐参考(守卫)")
    ap.add_argument("--with-multi", action="store_true", help="加 2env 探针")
    ap.add_argument("--multi-proc", action="store_true", help="2env 用双进程隔离变体")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "outputs", "rl_sync_bench.json"))
    args = ap.parse_args()

    result = {"meta": {"sim_app": DEFAULT_SIM_APP,
                       "started": time.strftime("%F %T"),
                       "sb3": None, "torch": None}}
    try:
        import stable_baselines3 as sb3
        import torch
        result["meta"]["sb3"] = sb3.__version__
        result["meta"]["torch"] = torch.__version__
    except ImportError:
        pass

    result["throughput"] = bench_throughput(args)
    _save(args.out, result)  # 分段写盘:单项失败不丢已有结果
    if args.with_multi:
        try:
            result["two_env_single_proc"] = bench_two_env(args)
        except Exception as e:
            result["two_env_single_proc"] = {"error": f"{type(e).__name__}: {e}"}
        _save(args.out, result)
        if args.multi_proc:
            try:
                result["two_env_two_proc"] = bench_two_env_multiproc(args)
            except Exception as e:
                result["two_env_two_proc"] = {"error": f"{type(e).__name__}: {e}"}
            _save(args.out, result)
    print("[bench] 确定性验证 ...")
    result["determinism"] = bench_determinism(args)

    _save(args.out, result)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["determinism"], ensure_ascii=False, indent=2))
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
