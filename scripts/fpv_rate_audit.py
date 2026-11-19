#!/usr/bin/env python3
"""fps 归因审计:~85fps 是设备硬件上限,还是读取端的 EAGAIN 重试节拍?

背景(fpv_card_probe.py 的实测链):CLI ffmpeg 720p@120 稳态 ~84-86fps,被定案为
"卡硬件上限";但所有测出 85 的读取器共用同一条 av_read_frame+EAGAIN 重试路径,
且 30fps 内置相机也出现"突发 4 帧后 EAGAIN"——EAGAIN 是 avfoundation 读路径的
常态返回(avf_read_frame 不阻塞等帧),重试节拍本身会封顶交付速率。
本脚本用同一 PyAV 栈、两种重试节拍各开一段会话,直接分离两个假说:

  phase A(busy)  : 每次读取新建 decode generator,EAGAIN 立即重试(零睡眠)
  phase B(sleep) : 同上但睡 5ms 重试(= fpv_card_probe 行为,已知稳态 ~85)

判读:
  A >= 110fps            → 85=读取节拍,卡可 120,「虚标/硬件上限」结论翻案
  A ~= 85 且唯一帧 ~= A   → 硬件上限坐实(设备就给这么多)
  A ~= 85 且唯一帧 ~= 60  → 设备在复制 60fps 输入(输出时钟 ~85),源帧率另查 VRX
  唯一帧 ~= 60(输入 120)  → 源只给 60fps(HDMI 输出档问题,查 VRX 菜单)

唯一帧 = 帧内容哈希(blake2b/8B)去重——相邻重复帧即复制帧(60→120 协商档下
每帧应出现两次)。

用法(必须在有摄像头授权的终端跑):
  .venv/bin/python scripts/fpv_rate_audit.py                  # 默认 720p@120,5s/段
  .venv/bin/python scripts/fpv_rate_audit.py --fps 240        # 换协商档
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

import av


def _resolve_device(name_substr: str) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg(brew install ffmpeg)")
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True, timeout=15)
    devices = []
    section = None
    for line in (proc.stderr or "").splitlines():
        if "video devices" in line:
            section = "video"
        elif "audio devices" in line:
            section = "audio"
        elif section == "video":
            m = re.search(r"\[(\d+)\] (.+)$", line)
            if m:
                devices.append((m.group(1), m.group(2).strip()))
    hits = [(i, n) for i, n in devices if name_substr.lower() in n.lower()]
    if len(hits) != 1:
        raise RuntimeError(f"--name {name_substr!r} 匹配 {len(hits)} 个设备: {hits or devices}")
    return hits[0][0]


def _read_once(container) -> tuple[object, str | None]:
    """一次读取尝试:每次新建 generator(avf EAGAIN 会杀死 generator,
    复用死 generator 只会拿到 StopIteration——这正是 fpv_card_probe
    'eof' 误诊的机制)。返回 (frame, 错误标签)。"""
    gen = container.decode(video=0)
    try:
        return next(gen), None
    except StopIteration:
        return None, "eof"
    except OSError as exc:
        msg = str(exc)
        if "Errno 35" in msg or "temporarily unavailable" in msg:
            return None, "eagain"
        return None, f"error:{msg[:80]}"


def _run_phase(label: str, args: argparse.Namespace, sleep_s: float) -> dict:
    print(f"== {label} (EAGAIN 重试睡眠={sleep_s * 1000:.0f}ms) ==", flush=True)
    options = {"framerate": str(args.fps), "video_size": f"{args.w}x{args.h}",
               "pixel_format": args.fmt}
    container = av.open(args.device, format=args.backend, options=options)
    arrivals: list[float] = []
    hash_list: list[str] = []
    eagain = eof = errors = 0
    t0 = time.monotonic()
    deadline = t0 + args.dur
    try:
        while time.monotonic() < deadline:
            frame, err = _read_once(container)
            if err == "eagain":
                eagain += 1
                if sleep_s:
                    time.sleep(sleep_s)
                continue
            if err == "eof":
                eof += 1
                break
            if err:
                errors += 1
                if errors > 20:
                    break
                continue
            now = time.monotonic()
            arrivals.append(now)
            # 唯一帧:降采样 luma 哈希(NV12 plane0 含行距填充,但填充恒定,足够判重)
            try:
                h = hashlib.blake2b(bytes(frame.planes[0])[::64], digest_size=8)
                hash_list.append(h.hexdigest())
            except Exception:
                hash_list.append("")
    finally:
        container.close()

    wall = time.monotonic() - t0
    n = len(arrivals)
    hashes = set(hash_list)
    stats = {"label": label, "frames": n, "wall_s": round(wall, 2),
             "fps": round(n / wall, 1) if wall > 0 else 0,
             "unique": len(hashes), "eagain": eagain, "eof": eof, "errors": errors}
    # 重复帧位置分析(内容帧率判据):内容 N fps 装进 120Hz 交付容器 → 每 ceil(120/N)
    # 帧复制 1 帧、位置差恒定(如 100fps→每 6 帧);120fps 内容+静止跳帧 → 成串分布
    dup_pos = [i for i in range(1, len(hash_list)) if hash_list[i] == hash_list[i - 1]]
    if dup_pos:
        deltas = [b - a for a, b in zip(dup_pos, dup_pos[1:])]
        runs, run = [], 1
        for a, b in zip(dup_pos, dup_pos[1:]):
            if b == a + 1:
                run += 1
            else:
                runs.append(run)
                run = 1
        runs.append(run)
        stats["dup"] = {
            "count": len(dup_pos),
            "delta_min": min(deltas) if deltas else None,
            "delta_med": sorted(deltas)[len(deltas) // 2] if deltas else None,
            "delta_max": max(deltas) if deltas else None,
            "eq567": sum(1 for d in deltas if 5 <= d <= 7),
            "runs_max": max(runs),
        }
    if n >= 2:
        gaps = sorted(b - a for a, b in zip(arrivals, arrivals[1:]) if b > a)
        p = lambda q: gaps[min(len(gaps) - 1, round(q / 100 * (len(gaps) - 1)))]
        stats["p50_ms"] = round(p(50) * 1000, 2)
        stats["p95_ms"] = round(p(95) * 1000, 2)
        # 逐秒帧数/逐秒唯一帧(内容帧率主判据:稳定 N<120 = N fps 内容装 120Hz 容器)
        per_sec, uniq_sec = [], []
        for i in range(int(wall) + 1):
            lo = arrivals[0] + i
            idxs = [j for j, t in enumerate(arrivals) if lo <= t < lo + 1]
            if idxs:
                per_sec.append(len(idxs))
                uniq_sec.append(len({hash_list[j] for j in idxs}))
        stats["per_sec"] = per_sec
        stats["uniq_sec"] = uniq_sec
    print(f"  frames={n} fps={stats['fps']} unique={len(hashes)} "
          f"p50={stats.get('p50_ms', '-')}ms p95={stats.get('p95_ms', '-')}ms "
          f"eagain={eagain} eof={eof}", flush=True)
    if "dup" in stats:
        d = stats["dup"]
        print(f"  重复帧={d['count']}/{n} 位置差 min/med/max="
              f"{d['delta_min']}/{d['delta_med']}/{d['delta_max']} "
              f"(5~7 占比 {d['eq567']}/{max(1, d['count'] - 1)}) 连串最长={d['runs_max']}",
              flush=True)
    if "per_sec" in stats:
        print(f"  逐秒帧数={stats['per_sec']}", flush=True)
        print(f"  逐秒唯一帧={stats['uniq_sec']}", flush=True)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="USB3 Video", help="设备名子串(默认 USB3 Video)")
    ap.add_argument("--device", default=None, help="显式设备索引(覆盖 --name)")
    ap.add_argument("--backend", default="avfoundation")
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--fps", type=int, default=120, help="协商帧率(默认 120)")
    ap.add_argument("--fmt", default="nv12")
    ap.add_argument("--dur", type=float, default=5.0, help="每段秒数")
    args = ap.parse_args()
    if args.device is None:
        args.device = _resolve_device(args.name)
    print(f"目标: [{args.device}] {args.w}x{args.h}@{args.fps} {args.fmt}", flush=True)

    try:
        a = _run_phase("phase A busy", args, sleep_s=0.0)
        b = _run_phase("phase B sleep5ms", args, sleep_s=0.005)
    except Exception as exc:  # av.AVError 不全继承 OSError
        msg = str(exc)
        hint = ("疑似 TCC 摄像头授权(系统设置→隐私与安全性→摄像头,授权后重跑)"
                if "Errno 35" in msg else "")
        print(f"打开/采集失败: {msg} {hint}", file=sys.stderr)
        return 1

    print("\n== 判读 ==")
    fa, fb = a["fps"], b["fps"]
    ua = a["unique"]
    if fa >= 110:
        print(f"✅ A={fa}fps ≫ B={fb}fps → **85 是读取端重试节拍,卡可跑 ~120**;"
              f"「硬件上限/虚标」结论翻案,M1 可拿满帧率")
    elif fa >= 75:
        if ua < a["frames"] * 0.8:
            print(f"⚠ A={fa}fps 且 unique={ua}/{a['frames']} → 设备输出含复制帧"
                  f"(源帧率低于协商档,设备复制到协商帧率);实际内容帧率≈{ua / a['wall_s']:.0f}fps")
        else:
            print(f"❌ A≈B≈{fa}fps 且 unique={ua}≈frames → **硬件上限坐实**,"
                  f"设备就给这么多,换卡才有 120")
    else:
        print(f"⚠ A={fa}fps 偏低,unique={ua}/{a['frames']}——"
              f"先查源(VRX HDMI 输出帧率)与设备占用,再看逐秒形态")
    # 内容帧率判据(主=逐秒唯一帧稳定性,辅=重复帧位置差)。
    # 2026-11-20 实测教训:100fps 内容装 120Hz 容器时位置差因双时钟域漂移散布 1~11
    # (仅 77% 落 5~7),而逐秒唯一帧稳定钉在 100——稳定性才是内容帧率的可靠指纹;
    # "120fps 内容+静止跳帧"的唯一帧数应随场景动静波动,不会每秒恰 100。
    for st in (a, b):
        d = st.get("dup")
        uq_all = st.get("uniq_sec") or []
        uq = uq_all[1:] if len(uq_all) >= 4 else uq_all  # 裁首秒(预热追赶帧)
        if not d:
            print(f"  [{st['label']}] 无重复帧 → 内容帧率=交付帧率(全唯一)")
            continue
        denom = max(1, d["count"] - 1)
        if len(uq) >= 3 and (max(uq) - min(uq)) <= 4:
            mean_u = sum(uq) / len(uq)
            if mean_u < 112:
                print(f"  [{st['label']}] 逐秒唯一帧稳定 {uq} → "
                      f"**内容 ≈{mean_u:.0f}fps 装进 120Hz 容器**"
                      f"(每秒 ~{120 - mean_u:.0f} 帧重复;位置差散布=双时钟域漂移)")
                continue
            print(f"  [{st['label']}] 逐秒唯一帧稳定 {uq}≈交付 → 内容≈120fps(偶发静止跳帧)")
            continue
        if d["eq567"] >= denom * 0.9 and d["runs_max"] <= 2:
            est = 120 * (1 - 1 / max(1, d["delta_med"])) if d["delta_med"] else 0
            print(f"  [{st['label']}] 重复帧位置差稳定 5~7(中位 {d['delta_med']}) → "
                  f"**内容 ≈{est:.0f}fps 装进 120Hz 容器**(每 {d['delta_med']} 帧复制 1)")
        else:
            print(f"  [{st['label']}] 逐秒唯一帧波动 {uq} + 连串最长 {d['runs_max']} → "
                  f"以静止跳帧为主(编码器 skip),内容帧率≈交付")
    return 0


if __name__ == "__main__":
    sys.exit(main())
