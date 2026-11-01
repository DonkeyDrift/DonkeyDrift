#!/usr/bin/env python3
"""D5:双 sim 实例统计对拍脚手架(可选项,时间盒交付)。

口径声明(订单原文):**统计分布对比,不是逐位对拍**——两个 sim 实例的
确定性互不成立(PhysX 多线程非确定,见 sdsandbox AGENTS.md)。

流程:同一脚本化控制序列(直行加速→定圆)分别打两个 sim 实例
(默认同二进制、不同端口),落两侧遥测,输出 speed/|cte|/航向变化率/
位移效率 的分布对比摘要。当前使用者侧只有一份 sdsim 构建,本脚手架实测
的是**实例间方差**(M3 多开训练的前置事实);若未来拿到不同 sim 二进制,
--sim-app-a/--sim-app-b 传不同路径即变成真双 sim 对拍。

用法:
    .venv/bin/python scripts/rl_dualsim_probe.py
    .venv/bin/python scripts/rl_dualsim_probe.py --port-a 9091 --port-b 9092
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim  # noqa: E402

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"


def run_sequence(port: int, sim_app: str, seq, log_name: str) -> dict:
    """在一个 sim 实例上跑脚本序列,返回逐帧遥测摘要数组。"""
    proc = launch_sim(sim_app, port=port,
                      log_path=os.path.join(REPO_ROOT, "outputs", log_name))
    env = DonkeyDriftEnv(sim_port=port, sim_path="remote", obs_mode="state",
                         img_enc="none", connect_timeout_s=90.0,
                         frame_wait_timeout_s=2.0, name=f"dualsim-{port}")
    rows = []
    try:
        env.reset()
        t0 = time.perf_counter()
        last_t = t0
        while True:
            now = time.perf_counter()
            dt, last_t = now - last_t, now
            elapsed = now - t0
            if elapsed > seq["total_s"]:
                break
            steer, throttle = seq["control"](elapsed)
            tok = env._frame_token()
            env._cam.run_threaded(steer, throttle, 0.0)
            if not env._wait_new_frame(tok, 2.0):
                continue
            info = dict(getattr(env._cam, "info", {}) or {})
            rows.append({
                "t": round(elapsed, 3),
                "pos": list(info.get("pos", (np.nan,) * 3)),
                "speed": info.get("speed", np.nan),
                "cte": info.get("cte", np.nan),
                "yaw": (info.get("car") or (np.nan,) * 3)[2],
            })
    finally:
        env.close()
        stop_sim(proc=proc)
    return {"port": port, "rows": rows}


def summarize(run: dict) -> dict:
    rows = run["rows"]
    if len(rows) < 50:
        return {"port": run["port"], "n": len(rows), "error": "样本不足"}
    speed = np.array([r["speed"] for r in rows], dtype=float)
    cte = np.array([abs(r["cte"]) for r in rows], dtype=float)
    yaw = np.unwrap(np.deg2rad([r["yaw"] for r in rows]))
    yaw_rate = np.abs(np.rad2deg(np.diff(yaw)) / np.diff([r["t"] for r in rows]))
    pos = np.array([[r["pos"][0], r["pos"][2]] for r in rows], dtype=float)
    step_len = np.linalg.norm(np.diff(pos, axis=0), axis=1)
    path_len = float(np.nansum(step_len))
    net = float(np.linalg.norm(pos[-1] - pos[0]))

    def stats(a):
        a = a[~np.isnan(a)]
        if len(a) == 0:
            return {}
        return {"n": int(len(a)), "mean": round(float(np.mean(a)), 3),
                "p50": round(float(np.percentile(a, 50)), 3),
                "p90": round(float(np.percentile(a, 90)), 3),
                "max": round(float(np.max(a)), 3)}

    return {"port": run["port"], "n_frames": len(rows),
            "speed": stats(speed), "abs_cte": stats(cte),
            "abs_yaw_rate_deg_s": stats(yaw_rate),
            "path_len_m": round(path_len, 2), "net_displacement_m": round(net, 2),
            "displacement_efficiency": round(net / path_len, 3) if path_len > 0 else None}


def compare(sum_a: dict, sum_b: dict) -> dict:
    out = {}
    for key in ("speed", "abs_cte", "abs_yaw_rate_deg_s"):
        sa, sb = sum_a.get(key) or {}, sum_b.get(key) or {}
        if sa.get("p50") is not None and sb.get("p50") is not None:
            p50a, p50b = sa["p50"], sb["p50"]
            rel = abs(p50a - p50b) / max(abs(p50b), 1e-6)
            out[key] = {"p50_a": p50a, "p50_b": p50b,
                        "rel_diff_p50": round(rel, 3),
                        "within_10pct": bool(rel <= 0.10)}
    eff_a = sum_a.get("displacement_efficiency")
    eff_b = sum_b.get("displacement_efficiency")
    if eff_a is not None and eff_b is not None:
        out["displacement_efficiency"] = {"a": eff_a, "b": eff_b,
                                          "abs_diff": round(abs(eff_a - eff_b), 3)}
    agree = all(v.get("within_10pct") for v in out.values()
                if isinstance(v, dict) and "within_10pct" in v)
    out["verdict"] = (
        "两实例同序列分布一致(p50 相对差 ≤10%)——M3 多开实例间方差可接受"
        if agree else
        "存在 >10% 的 p50 相对差——M3 多开需按实例分布归一/课程再评估(见逐项)")
    return out


def circle_seq():
    """直行加速 6s → 定圆 12s(总 18s)。"""
    total_s = 18.0

    def control(t):
        if t < 6.0:
            return (0.0, min(0.6, 0.2 * t))
        return (0.5, 0.55)
    return {"total_s": total_s, "control": control}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app-a", default=DEFAULT_SIM_APP)
    ap.add_argument("--sim-app-b", default=DEFAULT_SIM_APP)
    ap.add_argument("--port-a", type=int, default=9091)
    ap.add_argument("--port-b", type=int, default=9092)
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "outputs",
                                                  "rl_dualsim_probe.json"))
    args = ap.parse_args()
    seq = circle_seq()
    print(f"[dualsim] 实例A {args.sim_app_a}:{args.port_a}")
    run_a = run_sequence(args.port_a, args.sim_app_a, seq, f"dualsim_a_{args.port_a}.log")
    print(f"[dualsim]   {len(run_a['rows'])} 帧")
    print(f"[dualsim] 实例B {args.sim_app_b}:{args.port_b}")
    run_b = run_sequence(args.port_b, args.sim_app_b, seq, f"dualsim_b_{args.port_b}.log")
    print(f"[dualsim]   {len(run_b['rows'])} 帧")

    sum_a, sum_b = summarize(run_a), summarize(run_b)
    result = {"meta": {"sim_app_a": resolve_sim_exe(args.sim_app_a),
                       "sim_app_b": resolve_sim_exe(args.sim_app_b),
                       "ports": [args.port_a, args.port_b],
                       "sequence": "straight 6s -> circle(steer 0.5) 12s",
                       "note": "统计分布对比口径,非逐位对拍;同二进制时度量实例间方差",
                       "recorded_at": time.strftime("%F %T")},
              "instance_a": sum_a, "instance_b": sum_b,
              "comparison": compare(sum_a, sum_b)}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
