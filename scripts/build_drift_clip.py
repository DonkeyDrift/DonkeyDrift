#!/usr/bin/env python3
"""MUS4 漂移操作回放 clip 构建工具。

从 Donkeycar Tub v2 录制数据中抽取人工驾驶的转向/油门时间序列，
支持选段、拼接、归一化与调速率，输出标准 replay clip JSON，
供 DriftReplayPart 按时戳回放。

Usage:
    build_drift_clip.py [--speed=<f>] [--scale-throttle=<f>] [--scale-angle=<f>]
                        [--clip-throttle=<f>] [--clip-angle=<f>]
                        [--transition-ms=<n>] [--out=<path>]
                        <tub>...
    build_drift_clip.py (-h | --help)

Options:
    -h --help                  显示帮助
    --speed=<f>                回放速率倍率 [default: 1.0]
    --scale-throttle=<f>       油门缩放系数 [default: 1.0]
    --scale-angle=<f>          转向缩放系数 [default: 1.0]
    --clip-throttle=<f>        油门限幅上限（-1~1 域）[default: 0.6]
    --clip-angle=<f>           转向限幅上限（-1~1 域）[default: 1.0]
    --transition-ms=<n>        段间静置帧时长 ms [default: 300]
    --out=<path>               输出 clip 路径，默认车目录 data/clips/

输出 JSON schema：mus4.drift_replay_clip.v1，含 samples（t_rel/angle/throttle）
与 meta（来源、速率、段数、缩放参数）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from docopt import docopt

from donkeycar.parts.tub_v2 import Tub


# 标准 clip schema 标识，DriftReplayPart 据此校验
CLIP_SCHEMA = "mus4.drift_replay_clip.v1"


def load_tub_records(tub_path: str | Path) -> list[dict]:
    """从 Tub v2 读取录制记录，抽取控制字段。

    :param tub_path: tub 目录路径
    :return: dict 列表，每条含 angle/throttle/mode/t_ms/index。
             angle/throttle 为 -1~1 浮点（donkeycar 约定），
             t_ms 为录制时戳毫秒，index 为 tub 内序号。
             自动跳过已软删除的记录（ManifestIterator 行为）。
    """
    tub = Tub(str(tub_path), read_only=True)
    records: list[dict] = []
    for raw in tub:
        records.append({
            "angle": float(raw.get("user/angle", 0.0)),
            "throttle": float(raw.get("user/throttle", 0.0)),
            "mode": raw.get("user/mode", "user"),
            "t_ms": int(raw.get("_timestamp_ms", 0)),
            "index": int(raw.get("_index", 0)),
        })
    tub.close()
    return records


def build_segment(
    records: Sequence[dict],
    start_index: int | None = None,
    end_index: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[dict]:
    """按 _index 区间或时戳区间裁剪。

    index 与 ms 区间均为闭区间 [start, end]。同时指定时按交集。
    """
    result = []
    for r in records:
        if start_index is not None and r["index"] < start_index:
            continue
        if end_index is not None and r["index"] > end_index:
            continue
        if start_ms is not None and r["t_ms"] < start_ms:
            continue
        if end_ms is not None and r["t_ms"] > end_ms:
            continue
        result.append(dict(r))
    return result


def concat_segments(segments: Sequence[Sequence[dict]], transition_ms: int = 300) -> list[dict]:
    """多段拼接，段间插入静置帧（angle=0, throttle=0）。

    静置帧持续 transition_ms：其 t_ms = 前段末尾 + transition_ms（表示静置
    结束时刻）；后段整体平移使首帧 = 静置帧 t_ms + transition_ms，保留原始
    帧间间隔。这样时戳严格递增：前段末尾 < 静置帧 < 后段首帧。
    单段不插入静置帧。
    """
    if len(segments) <= 1:
        return [dict(r) for r in (segments[0] if segments else [])]

    merged: list[dict] = []
    # 第一段：保留原始 t_ms
    first = [r for r in segments[0] if r]
    for r in first:
        merged.append(dict(r))
    cursor_ms = merged[-1]["t_ms"] if merged else 0

    for seg in segments[1:]:
        seg = [r for r in seg if r]
        if not seg:
            continue
        # 静置帧：t_ms = 前段末尾 + transition_ms（静置结束时刻）
        cursor_ms += transition_ms
        merged.append({
            "index": -1,
            "t_ms": cursor_ms,
            "angle": 0.0,
            "throttle": 0.0,
            "mode": "local",
        })
        # 后段从静置帧之后再过 transition_ms 开始，保留原始帧间间隔
        cursor_ms += transition_ms
        seg_start = seg[0]["t_ms"]
        for r in seg:
            new_r = dict(r)
            new_r["t_ms"] = cursor_ms + (r["t_ms"] - seg_start)
            merged.append(new_r)
        cursor_ms = merged[-1]["t_ms"]
    return merged


def apply_scale(
    records: Sequence[dict],
    throttle_scale: float = 1.0,
    angle_scale: float = 1.0,
    throttle_clip: float = 0.6,
    angle_clip: float = 1.0,
) -> list[dict]:
    """对所有记录的 throttle/angle 缩放并限幅（-1~1 域）。

    不区分 mode：回放的是人工录制段（mode='user'），缩放限幅应统一生效。
    """
    result = []
    for r in records:
        new_r = dict(r)
        thr = max(-throttle_clip, min(throttle_clip, r["throttle"] * throttle_scale))
        ang = max(-angle_clip, min(angle_clip, r["angle"] * angle_scale))
        new_r["throttle"] = thr
        new_r["angle"] = ang
        result.append(new_r)
    return result


def resample_timeline(records: Sequence[dict], speed: float = 1.0) -> list[dict]:
    """按速率重采样时间轴，生成相对时戳 t_rel（ms）。

    speed>1 加速（时间压缩），speed<1 减速（时间拉伸）。
    t_rel 首帧为 0，其余为相对首帧的时戳差 / speed。
    """
    if not records:
        return []
    base = records[0]["t_ms"]
    result = []
    for r in records:
        new_r = dict(r)
        new_r["t_rel"] = (r["t_ms"] - base) / speed if speed > 0 else 0.0
        result.append(new_r)
    return result


def build_clip(records: Sequence[dict], source: str = "", speed: float = 1.0) -> dict:
    """组装标准 clip JSON（schema mus4.drift_replay_clip.v1）。

    :param records: 记录。若已过 resample 含 t_rel 则直接用；
                    否则从 t_ms 派生（首帧为 0，其余相对首帧）。
    :return: clip dict，含 schema/samples/meta。
    """
    samples = []
    base_t = records[0]["t_ms"] if records else 0
    for r in records:
        if "t_rel" in r:
            t_rel = r["t_rel"]
        else:
            t_rel = r.get("t_ms", 0.0) - base_t
        samples.append({
            "t_rel": t_rel,
            "angle": r.get("angle", 0.0),
            "throttle": r.get("throttle", 0.0),
        })
    return {
        "schema": CLIP_SCHEMA,
        "samples": samples,
        "meta": {
            "source": source,
            "speed": speed,
            "sample_count": len(samples),
        },
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = docopt(__doc__, argv=list(argv) if argv is not None else None)
    tub_paths = args["<tub>"]
    speed = float(args["--speed"])
    scale_thr = float(args["--scale-throttle"])
    scale_ang = float(args["--scale-angle"])
    clip_thr = float(args["--clip-throttle"])
    clip_ang = float(args["--clip-angle"])
    transition_ms = int(args["--transition-ms"])
    out_path = args["--out"]

    if speed <= 0:
        print(f"错误：--speed 必须 > 0（当前 {speed}），否则时间轴无意义", flush=True)
        return 1

    # 每个 tub 的用户段作为独立段传入 concat_segments：逐段平移时戳并在
    # 段间插静置帧，保证跨 tub 合并（第二个 tub 时戳可能早于第一个）后
    # 时戳仍严格递增——回放端 DriftReplayPart 假设 t_rel 单调
    segments: list[list[dict]] = []
    sources = []
    for tp in tub_paths:
        recs = load_tub_records(tp)
        # 仅取人工驾驶录制段（donkeycar user/mode='user'），过滤 AI 接管段
        # （local/local_angle）。漂移回放复现的是人工操作。
        seg = [r for r in recs if r["mode"] == "user"]
        if seg:
            segments.append(seg)
            sources.append(Path(tp).name)
    if not segments:
        print("未找到人工驾驶录制段（mode='user'）", flush=True)
        return 1

    merged = concat_segments(segments, transition_ms=transition_ms)
    scaled = apply_scale(merged, throttle_scale=scale_thr, angle_scale=scale_ang,
                          throttle_clip=clip_thr, angle_clip=clip_ang)
    resampled = resample_timeline(scaled, speed=speed)
    clip = build_clip(resampled, source="+".join(sources), speed=speed)

    if not out_path:
        out_path = str(Path("data/clips") / (sources[0] + "_clip.json") if sources else "drift_clip.json")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clip, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"clip 已写入: {out}（{len(clip['samples'])} 帧）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
