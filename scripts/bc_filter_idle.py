#!/usr/bin/env python3
"""M3:BC 采样数据清洗——剔静止帧(网页驾驶采样的已知污染源)。

污染来源(2026-11-02 web1 采样实测):drive 启动后的等待期、圈间停顿都
在录(recorder 无 record 开关门控),原始 19215 帧中 42.5% 为静止帧
(throttle<0.05),其中 14 局几乎纯静止。静止帧教 BC「停车行为」,加剧
sdsandbox 证伪史里的「MSE 多峰平均→油门均值蠕行」——训练前必须剔除。

规则(全部可配):
- 剔除整局:局内静止帧占比 > --idle-ep-frac(默认 0.6);
- 剔除局内帧:throttle < --stand-thr 且 speed < --stand-speed(真站立;
  松油门滑行(speed 高)保留);
- 剔除过滤后 < --min-ep-len 的碎局(默认 50,分层 val 需要有意义的局)。

产物:<out>/bc_%05d.npz(保留原始 ep_id,分层整局口径不变)+ 新
data_card.json(extra 记录过滤规则与前后帧数)。原始目录不动。

用法:
    .venv/bin/python scripts/bc_filter_idle.py --in outputs/bc_data_web1 \
        --out outputs/bc_data_web1_clean
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from donkeydrifter.rl.bc_data import compute_data_card, dump_card, load_dataset  # noqa: E402

# META_COLUMNS 索引(donkeydrifter/rl/bc_data.py):ep_id=0, speed=6, cte=8
_EP, _SPEED = 0, 6


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", required=True, help="原始采样目录")
    ap.add_argument("--out", required=True, help="清洁数据目录(勿与原始同目录)")
    ap.add_argument("--idle-ep-frac", type=float, default=0.6)
    ap.add_argument("--stand-thr", type=float, default=0.05)
    ap.add_argument("--stand-speed", type=float, default=1.0)
    ap.add_argument("--min-ep-len", type=int, default=50)
    args = ap.parse_args()

    src_files = sorted(glob.glob(os.path.join(args.inp, "bc_*.npz")))
    assert src_files, f"无 bc_*.npz: {args.inp}"
    assert os.path.abspath(args.inp) != os.path.abspath(args.out), "out 不得等于 in"
    os.makedirs(args.out, exist_ok=True)

    n_in = n_out = 0
    eps_dropped, eps_kept = [], []
    for f in src_files:
        d = np.load(f)
        steer, thr = d["steer"], d["throttle"]
        meta, speed = d["meta"], d["meta"][:, _SPEED]
        n_in += len(steer)
        ep = int(meta[0, _EP])
        stand = (thr < args.stand_thr) & (speed < args.stand_speed)
        if float(stand.mean()) > args.idle_ep_frac:
            eps_dropped.append((ep, len(steer), float(stand.mean())))
            continue
        keep = ~stand
        if keep.sum() < args.min_ep_len:
            eps_dropped.append((ep, len(steer), "过滤后过短"))
            continue
        eps_kept.append(ep)
        n_out += int(keep.sum())
        np.savez_compressed(
            os.path.join(args.out, f"bc_{ep:05d}.npz"),
            image=d["image"][keep], state=d["state"][keep],
            steer=steer[keep], throttle=thr[keep], brake=d["brake"][keep],
            meta=meta[keep])

    ds = load_dataset(args.out)
    imgs = ds["image"]
    card = compute_data_card(
        steer=ds["steer"], throttle=ds["throttle"], brake=ds["brake"],
        meta=ds["meta"],
        img_std_samples=[float(np.asarray(imgs[::max(len(imgs) // 20, 1)],
                                          np.float32).std())],
        img_std_last_shard=float(np.asarray(imgs[-300:], np.float32).std()),
        extra={"source": "filtered", "filter_from": os.path.abspath(args.inp),
               "filter_rule": (f"idle_ep_frac>{args.idle_ep_frac}; "
                               f"(thr<{args.stand_thr} & speed<{args.stand_speed}) 剔帧; "
                               f"min_ep_len={args.min_ep_len}"),
               "frames_in": n_in, "frames_out": n_out,
               "eps_in": len(src_files), "eps_out": len(eps_kept),
               "eps_dropped": eps_dropped,
               "recorded_at": __import__("time").strftime("%F %T")})
    dump_card(args.out, card)
    print(f"[filter] {n_in} → {n_out} 帧({len(src_files)} → {len(eps_kept)} 局;"
          f"剔局 {len(eps_dropped)} 个)")
    print(f"[filter] 门判定:{card['gates']}")
    print(f"[filter] hard gates 全过:{card['gates_pass_all_hard']} → {args.out}")


if __name__ == "__main__":
    main()
