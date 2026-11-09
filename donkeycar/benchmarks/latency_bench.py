#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""车端推理与自动驾驶主循环时延基准。

两个子命令（可直接跑，也被 donkeycar/tests/test_latency_bench.py 复用）：

  infer   单次模型推理时延：走真实 pilot.run 路径（含图像归一化），
          报告 mean/p50/p90/p95/p99/max 与当量 fps。
  loop    完整自动驾驶主循环时延：Vehicle + PilotHolder + 相机 Part +
          执行器 Part，报告实际达成频率（Hz）与各 Part 在主循环内的耗时。

用法示例：
  # 单车模型单次推理（模型类型按扩展名自动推导）
  python -m donkeycar.benchmarks.latency_bench infer \
      --model ~/projects/mycar/models/deployed.tflite

  # 扫描目录下所有模型逐个测推理
  python -m donkeycar.benchmarks.latency_bench infer \
      --scan ~/projects/mycar/models

  # 完整自动驾驶主循环：目标 60Hz，跑 1200 次迭代
  python -m donkeycar.benchmarks.latency_bench loop \
      --model ~/projects/mycar/models/deployed.tflite --rate 60 --iterations 1200

说明：
  * `loop` 用 MockCamera 提供固定帧、用占位执行器接收输出，因此测的是
    「取帧 → PilotHolder（缩放+归一化+推理）→ 下发」这一条主循环路径；
    不包含 WebRTC 视频编码、录制写盘等生产环境里的额外并发 Part。
  * 结果受机器后台负载影响，建议在接近真实行驶的负载下测量。
"""
from __future__ import annotations

import argparse
import glob
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# 扩展名 → 模型类型，与 templates/complete.py 的推导保持一致
_MODEL_TYPE_BY_EXT: Sequence[Tuple[str, str]] = (
    (".tflite", "tflite_linear"),
    (".trt", "tensorrt_linear"),
    (".aidem", "aidlite_linear"),
    (".ckpt", "torch_linear"),
    (".h5", "linear"),
    (".savedmodel", "linear"),
    (".json", "linear"),
)


def model_type_for_path(path: str) -> Optional[str]:
    """按扩展名推导模型类型，无法识别时返回 None。"""
    lower = path.lower()
    for ext, mtype in _MODEL_TYPE_BY_EXT:
        if lower.endswith(ext):
            return mtype
    return None


def make_cfg(width: int = 320, height: int = 240, depth: int = 3,
             model_type: str = "linear"):
    """构造一个最小 Config，字段取值与车端一致。"""
    from donkeycar.config import Config
    cfg = Config()
    cfg.IMAGE_W = width
    cfg.IMAGE_H = height
    cfg.IMAGE_DEPTH = depth
    cfg.DEFAULT_MODEL_TYPE = model_type
    return cfg


def percentile_stats(times_ms: Sequence[float]) -> Dict[str, float]:
    """把一组耗时（ms）汇总为均值/分位/极值与当量 fps。"""
    arr = np.asarray(times_ms, dtype=float)
    if arr.size == 0:
        raise ValueError("times_ms 为空，无法统计")
    return {
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
        "fps": float(1000.0 / arr.mean()),
        "n": int(arr.size),
    }


def load_frame(path: Optional[str], width: int, height: int) -> Optional[np.ndarray]:
    """读取一张真实图片并缩放到 (width, height)，RGB uint8；失败返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    import cv2
    img = cv2.imread(path)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(cv2.resize(img, (width, height)))


def bench_inference(model_path: str, model_type: Optional[str] = None,
                    cfg=None, image: Optional[np.ndarray] = None,
                    iterations: int = 200, warmup: int = 10) -> Dict:
    """测量单次模型推理时延（真实 pilot.run 路径，含归一化）。

    返回 dict 含 model/type/load_ms/input_shape 及 mean/p50/p90/p95/p99/max/fps。
    """
    from donkeycar import utils as dk

    if cfg is None:
        cfg = make_cfg()
    if model_type is None:
        model_type = model_type_for_path(model_path) or cfg.DEFAULT_MODEL_TYPE

    t0 = time.perf_counter()
    pilot = dk.get_model_by_type(model_type, cfg)
    pilot.load(model_path)
    load_ms = (time.perf_counter() - t0) * 1000.0

    try:
        shape = tuple(int(x) for x in pilot.get_input_shape("img_in")[-3:])
    except Exception:
        shape = (cfg.IMAGE_H, cfg.IMAGE_W, cfg.IMAGE_DEPTH)

    img = image
    if img is None or tuple(img.shape) != shape:
        img = (np.random.rand(*shape) * 255).astype(np.uint8)

    for _ in range(max(0, warmup)):
        pilot.run(img)
    times: List[float] = []
    for _ in range(iterations):
        t = time.perf_counter()
        pilot.run(img)
        times.append((time.perf_counter() - t) * 1000.0)

    try:
        pilot.shutdown()
    except Exception:
        pass

    res = {
        "model": os.path.basename(model_path),
        "path": model_path,
        "type": model_type,
        "load_ms": load_ms,
        "input_shape": shape,
    }
    res.update(percentile_stats(times))
    return res


class _DummyActuator:
    """占位执行器：仅接收 pilot 输出，不写任何硬件。"""

    def run(self, angle, throttle):
        return None


def bench_drive_loop(model_path: str, model_type: Optional[str] = None,
                     cfg=None, frame: Optional[np.ndarray] = None,
                     rate_hz: int = 60, iterations: int = 1200) -> Dict:
    """测量完整自动驾驶主循环时延（Vehicle + PilotHolder + 相机 + 执行器）。

    返回 dict 含 achieved_hz/period_ms/count/total_s/load_ms 及 parts（各 Part 统计）。
    """
    from donkeycar.vehicle import Vehicle
    from donkeycar.parts.pilot_holder import PilotHolder
    from donkeycar.parts.camera import MockCamera

    if cfg is None:
        cfg = make_cfg()
    if model_type is None:
        model_type = model_type_for_path(model_path) or cfg.DEFAULT_MODEL_TYPE
    if frame is None:
        frame = (np.random.rand(cfg.IMAGE_H, cfg.IMAGE_W, cfg.IMAGE_DEPTH)
                 * 255).astype(np.uint8)

    t0 = time.perf_counter()
    holder = PilotHolder(cfg)
    holder.load(model_path, model_type)
    load_ms = (time.perf_counter() - t0) * 1000.0

    v = Vehicle()
    v.add(MockCamera(image=frame), outputs=["cam/image_array"], threaded=True)
    v.add(holder, inputs=["cam/image_array"],
          outputs=["pilot/angle", "pilot/throttle"])
    v.add(_DummyActuator(), inputs=["pilot/angle", "pilot/throttle"], outputs=[])

    count, total = v.start(rate_hz=rate_hz, max_loop_count=iterations, verbose=False)

    parts: Dict[str, Dict[str, float]] = {}
    for part, rec in v.profiler.records.items():
        arr = rec["times"][1:-1]  # 丢弃首尾，去掉启动/收尾异常值
        if not arr:
            continue
        parts[type(part).__name__] = percentile_stats([t * 1000.0 for t in arr])

    return {
        "model": os.path.basename(model_path),
        "type": model_type,
        "load_ms": load_ms,
        "rate_hz_target": rate_hz,
        "iterations": iterations,
        "count": count,
        "total_s": total,
        "achieved_hz": (count / total) if total > 0 else 0.0,
        "period_ms": (1000.0 * total / count) if count else 0.0,
        "parts": parts,
    }


def format_inference(res: Dict) -> str:
    return (
        f"{res['model']:28s} type={res['type']:15s} in={res['input_shape']}  "
        f"load={res['load_ms']:.0f}ms\n"
        f"{'':28s} mean {res['mean']:7.2f}  p50 {res['p50']:7.2f}  "
        f"p90 {res['p90']:7.2f}  p95 {res['p95']:7.2f}  p99 {res['p99']:7.2f}  "
        f"max {res['max']:8.2f} ms  ({res['fps']:6.1f} fps, n={res['n']})"
    )


def format_loop(res: Dict) -> str:
    lines = [
        f"模型 {res['model']}（{res['type']}）加载 {res['load_ms']:.0f} ms",
        f"主循环：{res['count']} 次迭代 / {res['total_s']:.3f} s = "
        f"实测 {res['achieved_hz']:.2f} Hz"
        f"（目标 {res['rate_hz_target']}Hz，周期 {res['period_ms']:.2f} ms）",
        "各 Part 主循环内耗时（ms）：",
    ]
    for name, s in res["parts"].items():
        lines.append(
            f"  {name:24s} mean {s['mean']:7.2f}  p50 {s['p50']:7.2f}  "
            f"p95 {s['p95']:7.2f}  p99 {s['p99']:7.2f}  max {s['max']:8.2f}"
        )
    return "\n".join(lines)


def _iter_models(args) -> List[str]:
    models: List[str] = list(args.model or [])
    if args.scan:
        for ext in ("*.tflite", "*.h5", "*.trt", "*.aidem", "*.ckpt", "*.savedmodel"):
            models += sorted(glob.glob(os.path.join(args.scan, "**", ext),
                                       recursive=True))
    return models


def cmd_infer(args) -> int:
    models = _iter_models(args)
    if not models:
        print("未指定模型：请用 --model <path>（可重复）或 --scan <dir>")
        return 2
    cfg = make_cfg(args.width, args.height, args.depth)
    for path in models:
        try:
            res = bench_inference(path, model_type=args.type, cfg=cfg,
                                  iterations=args.iterations, warmup=args.warmup)
        except Exception as e:  # noqa: BLE001 - 单个模型失败不影响其余
            msg = f"{type(e).__name__}: {e}".replace("\n", " ")
            if len(msg) > 160:
                msg = msg[:157] + "..."
            print(f"{os.path.basename(path):28s} [失败: {msg}]")
            continue
        print(format_inference(res))
    return 0


def cmd_loop(args) -> int:
    cfg = make_cfg(args.width, args.height, args.depth)
    frame = load_frame(args.image, args.width, args.height) if args.image else None
    res = bench_drive_loop(args.model, model_type=args.type, cfg=cfg, frame=frame,
                           rate_hz=args.rate, iterations=args.iterations)
    print(format_loop(res))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="latency_bench",
        description="车端推理与自动驾驶主循环时延基准",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("infer", help="单次模型推理时延")
    pi.add_argument("--model", action="append",
                    help="模型文件路径，可重复指定")
    pi.add_argument("--scan", help="扫描该目录（递归）下所有模型文件")
    pi.add_argument("--type", help="模型类型，缺省按扩展名推导")
    pi.add_argument("--iterations", type=int, default=200, help="测量迭代数（默认 200）")
    pi.add_argument("--warmup", type=int, default=10, help="预热迭代数（默认 10）")
    pi.add_argument("--width", type=int, default=320, help="配置图像宽（默认 320）")
    pi.add_argument("--height", type=int, default=240, help="配置图像高（默认 240）")
    pi.add_argument("--depth", type=int, default=3, help="配置图像通道（默认 3）")
    pi.set_defaults(func=cmd_infer)

    pl = sub.add_parser("loop", help="完整自动驾驶主循环时延")
    pl.add_argument("--model", required=True, help="模型文件路径")
    pl.add_argument("--type", help="模型类型，缺省按扩展名推导")
    pl.add_argument("--rate", type=int, default=60, help="主循环目标频率 Hz（默认 60）")
    pl.add_argument("--iterations", type=int, default=1200,
                    help="主循环迭代数（默认 1200）")
    pl.add_argument("--image", help="用作相机帧的图片（缺省用随机帧）")
    pl.add_argument("--width", type=int, default=320, help="配置图像宽（默认 320）")
    pl.add_argument("--height", type=int, default=240, help="配置图像高（默认 240）")
    pl.add_argument("--depth", type=int, default=3, help="配置图像通道（默认 3）")
    pl.set_defaults(func=cmd_loop)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
