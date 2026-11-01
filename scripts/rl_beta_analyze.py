#!/usr/bin/env python3
"""D3b:β(滑移角)分布离线分析 + 校准闸门。

输入:rl_teleop_record.py 的产物目录(teleop.npz,可多目录合并)。

方法(双口径互验,X-Z 地面平面口径,标定依据见 donkeydrifter/rl/rewards.py):
  - β_yaw(主口径):heading = wrap(sim 直读 yaw + 180)(度),
    course = atan2(vel_x, vel_z);β = wrap(heading - course)。
  - β_gyro(订单规定方法):heading 由 gyro-z 逐步积分(单段内漂移可接受),
    首个有 yaw 的帧作锚点(校正口径);链与直读的累计偏差单独输出(积分漂移诊断)。
  坐标系假设:Unity 系 y 轴向上,地面平面 X-Z,sim 遥测 vel 为世界系。该假设
  由下方 sanity 闸验证——口径错误时直线段的 β 中位数会显著偏离 0。

sanity 闸(方法可信性,不达标如实报):
  直线匀速段(1s 滑窗:speed∈[1.5,20] 且变异系数<0.25、|gyro_z|中位数<8°/s、
  |cte|中位数<1.0)内 β 中位数应 ≈0,偏差 >5° 判「方法不可信」。
  ⚠ 2026-11-02 实测结论:gyro-z 积分口径在本 sim 上**被闸门否决**——竖直
  角速度轴在 gyro_y(Unity Y-up)且量纲无法用常数标定收敛(×1/×57.3 均
  漂移 40~170°),yaw 直读(+180° 校正)是唯一可信口径,链偏差仅作诊断。

μ=25° 假设裁定:
  n≥200 且 |β| 分布 p50 落在 [20°,30°] → 支持;
  n≥200 且 p50 在带外且 p90>10°(确有漂移样本)→ 推翻(报实测峰位);
  其余 → 数据不足(如实报)。

用法:
    .venv/bin/python scripts/rl_beta_analyze.py outputs/rl_teleop_*/
    .venv/bin/python scripts/rl_beta_analyze.py <dir1> <dir2> --out <json>
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from donkeydrifter.rl.rewards import gyro_step_heading, wrap_deg  # noqa: E402

OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "outputs", "rl_beta_analysis.json")

SPEED_FLOOR = 0.2          # m/s,航向无定义
GATE_SPEED_MIN, GATE_SPEED_MAX = 1.5, 20.0
GATE_SPEED_CV_MAX = 0.25
GATE_GYRO_ABS_MAX = 8.0    # °/s
GATE_CTE_ABS_MAX = 1.0
GATE_MEDIAN_TOL_DEG = 5.0


def load_frames(paths: list) -> dict:
    """合并多个采样目录的 npz 为统一数组(沿帧轴拼接)。"""
    merged: dict[str, list] = {}
    order = ["t", "frame_id", "pos", "speed", "forward_vel", "cte",
             "gyro", "accel", "vel", "rpy", "action"]
    for p in paths:
        npz_path = p if p.endswith(".npz") else os.path.join(p, "teleop.npz")
        data = np.load(npz_path, allow_pickle=False)
        for k in order:
            merged.setdefault(k, []).append(np.asarray(data[k]))
    return {k: np.concatenate(v, axis=0) for k, v in merged.items()}


def compute_betas(d: dict) -> dict:
    """双口径 β(X-Z 地面平面口径,标定见 donkeydrifter/rl/rewards.py)。

    course = atan2(vel_x, vel_z)(零向 +Z);heading = wrap(yaw + 180)
    (sim yaw 直读的 180° 常数偏移,直线段实测标定);gyro 链锚定与积分
    均在校正后口径上进行。
    """
    t, vel, rpy, gyro, speed = d["t"], d["vel"], d["rpy"], d["gyro"], d["speed"]
    n = len(t)
    yaw = rpy[:, 2] if rpy.shape[1] >= 3 else np.full(n, np.nan)

    with np.errstate(invalid="ignore"):
        course = np.degrees(np.arctan2(vel[:, 0], vel[:, 2]))
        moving = speed >= SPEED_FLOOR
        valid_course = moving & ~np.isnan(vel[:, 0]) & ~np.isnan(vel[:, 2])

    heading = wrap_deg(yaw + 180.0)  # 180° 偏移校正;NaN 传播
    beta_yaw = np.full(n, np.nan)
    ok_yaw = valid_course & ~np.isnan(heading)
    beta_yaw[ok_yaw] = wrap_deg((heading - course)[ok_yaw])

    # gyro 积分链:锚定首个有效 yaw(校正口径),随后逐步积分;遇有效 yaw
    # 记录链-直读偏差(积分漂移诊断),链不重锚(保漂移可观测)
    beta_gyro = np.full(n, np.nan)
    chain = np.full(n, np.nan)
    chain_yaw_dev = np.full(n, np.nan)
    h = None
    for i in range(n):
        dt = float(t[i] - t[i - 1]) if i > 0 else 0.0
        if not (0.0 < dt < 0.5):        # 断段(采样间隙)不积分
            if not np.isnan(yaw[i]):
                h = float(wrap_deg(yaw[i] + 180.0))
            chain[i] = h if h is not None else np.nan
            continue
        gz = float(gyro[i, 2]) if not np.isnan(gyro[i, 2]) else 0.0
        if h is None:
            if not np.isnan(yaw[i]):
                h = float(wrap_deg(yaw[i] + 180.0))
        else:
            h = gyro_step_heading(h, gz, dt)
        if h is not None:
            chain[i] = h
            if not np.isnan(yaw[i]):
                chain_yaw_dev[i] = wrap_deg(h - float(wrap_deg(yaw[i] + 180.0)))
    ok = valid_course & ~np.isnan(chain)
    beta_gyro[ok] = wrap_deg((chain - course)[ok])

    return {"beta_yaw": beta_yaw, "beta_gyro": beta_gyro,
            "course_deg": course, "chain_yaw_dev": chain_yaw_dev}


def straight_mask(d: dict, fps: float = 20.0) -> np.ndarray:
    """1s 滑窗直线匀速段标记(逐帧)。"""
    n = len(d["t"])
    w = max(3, int(round(fps)))
    speed, gyro, cte = d["speed"], d["gyro"][:, 2], d["cte"]
    mask = np.zeros(n, dtype=bool)
    for i in range(n):
        lo, hi = max(0, i - w // 2), min(n, i + w // 2 + 1)
        s = speed[lo:hi]
        s = s[~np.isnan(s)]
        if len(s) < w // 2:
            continue
        m = float(np.mean(s))
        if not (GATE_SPEED_MIN <= m <= GATE_SPEED_MAX):
            continue
        if m > 0 and float(np.std(s)) / m > GATE_SPEED_CV_MAX:
            continue
        if abs(float(np.nanmedian(gyro[lo:hi]))) > GATE_GYRO_ABS_MAX:
            continue
        if abs(float(np.nanmedian(cte[lo:hi]))) > GATE_CTE_ABS_MAX:
            continue
        mask[i] = True
    return mask


def dist_stats(beta: np.ndarray) -> dict:
    b = beta[~np.isnan(beta) & (np.abs(beta) <= 90.0)]
    if len(b) == 0:
        return {"n": 0}
    hist, edges = np.histogram(b, bins=36, range=(-90.0, 90.0))
    return {
        "n": int(len(b)),
        "mean": round(float(np.mean(b)), 2),
        "std": round(float(np.std(b)), 2),
        "p10": round(float(np.percentile(b, 10)), 2),
        "p50": round(float(np.percentile(b, 50)), 2),
        "p90": round(float(np.percentile(b, 90)), 2),
        "abs_p50": round(float(np.percentile(np.abs(b), 50)), 2),
        "abs_p90": round(float(np.percentile(np.abs(b), 90)), 2),
        "hist_counts": [int(x) for x in hist],
        "hist_edges": [round(float(x), 1) for x in edges],
    }


def verdict_on_mu25(stats: dict) -> dict:
    """裁定 μ=25° 假设:看 |β| 分布里是否存在「漂移模态」及其峰位。

    只看 p50 会把「无漂移内容的数据」误判成推翻(循线数据 p50≈0 是正常
    的,不代表 μ=25 错)。规则:漂移带(15°~45°,μ±1σ)质量占比 ≥15%
    才认定数据含漂移模态,再比对带内直方图峰位与 μ 的距离。
    """
    n = stats.get("n", 0)
    counts = stats.get("hist_counts")
    edges = stats.get("hist_edges")
    if n < 200 or not counts:
        return {"verdict": "数据不足", "reason": f"有效 β 样本 {n} < 200 或分布退化"}
    centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(len(counts))]
    band = [c for c in centers if 15.0 <= abs(c) <= 45.0]
    band_n = sum(cnt for c, cnt in zip(centers, counts) if 15.0 <= abs(c) <= 45.0)
    drift_mass = band_n / max(n, 1)
    if drift_mass < 0.15:
        return {"verdict": "数据不足",
                "reason": f"漂移带(|β|∈15°~45°)质量占比 {drift_mass:.1%} < 15%,"
                          "数据不含足够漂移模态(循线/慢速数据属正常)",
                "drift_mass_frac": round(drift_mass, 3)}
    band_counts = [(abs(c), cnt) for c, cnt in zip(centers, counts) if 15.0 <= abs(c) <= 45.0]
    peak = max(band_counts, key=lambda x: x[0])[0] if band_counts else None
    if peak is not None and abs(peak - 25.0) <= 5.0:
        return {"verdict": "支持",
                "reason": f"漂移带峰位 ≈{peak:.0f}° 与 μ=25° 距离 ≤5°",
                "drift_mass_frac": round(drift_mass, 3), "peak_deg": round(peak, 1)}
    return {"verdict": "推翻",
            "reason": f"漂移带峰位 ≈{peak:.0f}° 偏离 μ=25°(质量占比 {drift_mass:.1%}),"
                      "实测峰位见直方图",
            "drift_mass_frac": round(drift_mass, 3), "peak_deg": round(peak, 1)}


def analyze(paths: list) -> dict:
    d = load_frames(paths)
    betas = compute_betas(d)
    straight = straight_mask(d)
    res = {"inputs": paths, "frames_total": int(len(d["t"])),
           "frames_moving": int(np.sum(d["speed"] >= SPEED_FLOOR)),
           "frames_straight_window": int(np.sum(straight))}

    # sanity 闸:双口径在直线段的中位数都应 ≈0
    gate = {}
    for key, name in (("beta_yaw", "yaw直读"), ("beta_gyro", "gyro积分")):
        seg = betas[key][straight]
        seg = seg[~np.isnan(seg)]
        med = float(np.median(seg)) if len(seg) else None
        ok = med is not None and abs(med) <= GATE_MEDIAN_TOL_DEG
        gate[name] = {"n_straight": int(len(seg)),
                      "median_deg": None if med is None else round(med, 2),
                      "pass": bool(ok)}
    gate["conclusion"] = (
        "两口径直线段 β 中位数均 ≤5°,航向/航迹坐标系假设成立,方法可信"
        if gate["yaw直读"]["pass"] and gate["gyro积分"]["pass"]
        else "存在口径不可信(见上),β 分布结论按对应口径降级使用")
    res["sanity_gate"] = gate

    res["beta_yaw"] = dist_stats(betas["beta_yaw"])
    res["beta_gyro"] = dist_stats(betas["beta_gyro"])
    dev = betas["chain_yaw_dev"][~np.isnan(betas["chain_yaw_dev"])]
    res["gyro_chain_vs_yaw_drift_deg"] = {
        "n": int(len(dev)),
        "abs_max": round(float(np.max(np.abs(dev))), 2) if len(dev) else None,
        "abs_p95": round(float(np.percentile(np.abs(dev), 95)), 2) if len(dev) else None,
        "note": "gyro 积分链相对 yaw 直读的累计偏差;大值=积分漂移,佐证 yaw 直读为主口径",
    } if len(dev) else {"n": 0}

    primary = res["beta_yaw"] if gate["yaw直读"]["pass"] else res["beta_gyro"]
    res["mu25_assessment"] = verdict_on_mu25(primary)
    res["mu25_note"] = "μ/σ(drift reward 的 25°/10°)为声明式手调超参,本分析为其唯一实证回填来源"
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="teleop 产物目录(含 teleop.npz)或 npz 路径")
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()
    paths = []
    for p in args.paths:
        paths.extend(sorted(glob.glob(p)) or [p])
    res = analyze(paths)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in res.items()
                      if k in ("frames_total", "frames_moving", "frames_straight_window",
                               "sanity_gate", "beta_yaw", "beta_gyro",
                               "gyro_chain_vs_yaw_drift_deg", "mu25_assessment")},
                     ensure_ascii=False, indent=2))
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
