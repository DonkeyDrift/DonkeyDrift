#!/usr/bin/env python3
"""M0:FPV 采集卡探测——格式矩阵 / 真实帧率 / 帧龄分布 / 抓帧。

目的(方案 docs/arch/fpv-pilot-capture-plan.md §6 M0):
    1) 确认 UVC 采集卡("USB3 Video")可协商档位,优先找原生 1280x720@120(图传内容原生档);
    2) 每档实测到达帧率与帧间隔分布(p50/p95),判定 PASS(实测≥请求×0.9 且帧数≥10);
    3) frame 子命令抓一帧存 PNG,供对毫秒计时器拍照法测"相机→PC"段延迟。

产出:
    docs/arch/fpv-card-probe.json   (matrix 模式;含推荐档位 recommendation)
    stdout 人读摘要

看门狗设计(本机实测教训):macOS TCC 未授权时 AVFoundation 打开会**阻塞在 C 层**,
实测 SIGALRM 软超时打不断、Ctrl-C 也可能迟钝——唯一可靠看门狗是子进程 + timeout 硬杀
(matrix 模式即此);single 模式供授权终端直跑,开卡前打印提示,>10s 无响应人工中断。

用法:
    .venv/bin/python scripts/fpv_card_probe.py list
    # 推荐按名字解析(实测 macOS 枚举索引不稳定,两轮 0/1 互换):
    .venv/bin/python scripts/fpv_card_probe.py --name "USB3 Video" matrix
    .venv/bin/python scripts/fpv_card_probe.py single --w 1280 --h 720 --fps 120 --fmt nv12 [--dur 4]
    .venv/bin/python scripts/fpv_card_probe.py frame [--out /tmp/fpv_frame.png]
    # Windows 迁移后:--backend dshow --device "video=USB3 Video"

校验:matrix 全档 FAIL 且出现 hang/no_frames → 优先怀疑 TCC 授权(指引见 TCC_HINT),
    授权后在带权限的终端重跑;退出码 1。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPORT_PATH = os.path.join(_REPO_ROOT, "docs", "arch", "fpv-card-probe.json")

TCC_HINT = (
    "疑似 macOS 摄像头权限(TCC)拦截:系统设置→隐私与安全性→摄像头→"
    "勾选运行本脚本的终端 App,首次运行会弹窗;授权后重跑"
)

# avfoundation/dshow 私有选项同名:framerate / video_size / pixel_format
# 候选优先级 = 列表顺序(原生 720p120 优先,内容原生档最省带宽;1080p120 备选)
CANDIDATES = [
    (1280, 720, 120, "nv12"),
    (1280, 720, 120, "mjpeg"),
    (1920, 1080, 120, "nv12"),
    (1920, 1080, 120, "mjpeg"),
    (1280, 720, 60, "nv12"),
    (1920, 1080, 60, "nv12"),
    (640, 480, 120, "nv12"),
]


def _pct(sorted_vals: list[float], p: float) -> float:
    """nearest-rank 百分位;空表返回 0.0。"""
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _interval_stats(arrivals_s: list[float]) -> dict:
    gaps = [b - a for a, b in zip(arrivals_s, arrivals_s[1:]) if b > a]
    gaps.sort()
    return {
        "p50_ms": round(_pct(gaps, 50) * 1000, 2),
        "p95_ms": round(_pct(gaps, 95) * 1000, 2),
        "max_ms": round(gaps[-1] * 1000, 2) if gaps else 0.0,
    }


def _enumerate_avfoundation() -> list[tuple[str, str]]:
    """枚举视频设备 → [(index, name)];失败抛 RuntimeError。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg(brew install ffmpeg)")
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True, timeout=15,
    )
    devices: list[tuple[str, str]] = []
    section = None
    pat = re.compile(r"\[(\d+)\] (.+)$")
    for line in (proc.stderr or "").splitlines():
        if "video devices" in line:
            section = "video"
        elif "audio devices" in line:
            section = "audio"
        elif section == "video":
            m = pat.search(line)
            if m:
                devices.append((m.group(1), m.group(2).strip()))
    return devices


def cmd_list(args: argparse.Namespace) -> int:
    try:
        devices = _enumerate_avfoundation()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for idx, name in devices:
        print(f"[video] [{idx}] {name}")
    return 0


def _resolve_device_by_name(substr: str) -> str:
    """按名字子串解析设备索引;找不到/多义时退出报错(索引不稳定,名字才是稳定键)。"""
    devices = _enumerate_avfoundation()
    hits = [(i, n) for i, n in devices if substr.lower() in n.lower()]
    if len(hits) != 1:
        print(f"--name '{substr}' 匹配 {len(hits)} 个设备(需要唯一): {hits or devices}",
              file=sys.stderr)
        sys.exit(1)
    return hits[0][0]


def _open_container(args: argparse.Namespace, w: int, h: int, fps: int, fmt: str):
    import av  # 延迟导入:仅 single/frame 需要,坏环境时 list 仍可用

    options = {
        "framerate": str(fps),
        "video_size": f"{w}x{h}",
        "pixel_format": fmt,
    }
    return av.open(args.device, format=args.backend, options=options)


def _run_single(args: argparse.Namespace, w: int, h: int, fps: int, fmt: str,
                dur_s: float) -> dict:
    """单档探测(可能在本进程或子进程):decode 循环记到达时刻。"""
    result = {
        "backend": args.backend, "device": args.device,
        "w": w, "h": h, "fps_req": fps, "fmt": fmt,
        "frames": 0, "wall_s": 0.0, "measured_fps": 0.0,
        "first_frame_ms": None, "intervals": {},
        "status": "ok", "error": None,
    }
    t_open0 = time.monotonic()
    # 开卡前提示:无权限环境实测会阻塞在 AVFoundation C 层,SIGALRM 打不断,
    # 手跑时超过 ~10s 无响应就 Ctrl-C,先按 TCC_HINT 授权再跑(推荐直接用 matrix)
    print(f"[{w}x{h}@{fps} {fmt}] 打开设备中(>10s 无响应≈TCC 挂起,Ctrl-C 中断)…",
          file=sys.stderr, flush=True)
    # 软看门狗:matrix 父进程另有 timeout 硬杀,这里兜底直接手跑的场景
    def _alarm(signum, frame):
        raise TimeoutError("decode 超时(可能 TCC 挂起)")
    prev_handler = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(dur_s) + 10)
    try:
        container = _open_container(args, w, h, fps, fmt)
    except TimeoutError:
        result.update(status="hang_timeout", error=TCC_HINT)
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)
        return result
    except Exception as exc:  # av.AVError 等
        result.update(status="open_error", error=str(exc)[:300])
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)
        return result

    arrivals: list[float] = []
    try:
        deadline = time.monotonic() + dur_s
        for frame in container.decode(video=0):
            now = time.monotonic()
            if result["first_frame_ms"] is None:
                result["first_frame_ms"] = round((now - t_open0) * 1000, 1)
            arrivals.append(now)
            if now >= deadline or len(arrivals) >= fps * dur_s * 2:
                break
    except TimeoutError:
        result.update(status="hang_timeout", error=TCC_HINT)
    except KeyboardInterrupt:
        pass
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)
        container.close()

    wall = time.monotonic() - t_open0
    result["wall_s"] = round(wall, 2)
    result["frames"] = len(arrivals)
    if len(arrivals) >= 2 and wall > 0:
        result["measured_fps"] = round((len(arrivals) - 1) / (arrivals[-1] - arrivals[0]), 1)
        result["intervals"] = _interval_stats(arrivals)
    if len(arrivals) == 0 and result["status"] == "ok":
        result.update(status="no_frames", error=TCC_HINT)
    return result


def cmd_single(args: argparse.Namespace) -> int:
    result = _run_single(args, args.w, args.h, args.fps, args.fmt, args.dur)
    # 父进程(matrix)靠这行聚合;stdout 前缀保证可 grep
    print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    readable = {k: result[k] for k in ("w", "h", "fps_req", "fmt", "frames",
                                       "measured_fps", "first_frame_ms", "status")}
    print(f"  {readable}")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    rows: list[dict] = []
    for w, h, fps, fmt in CANDIDATES:
        label = f"{w}x{h}@{fps} {fmt}"
        print(f"== 探测 {label} ...", flush=True)
        # 注意:--backend/--device 是主解析器参数,必须放在子命令之前
        cmd = [sys.executable, os.path.abspath(__file__),
               "--backend", args.backend, "--device", args.device,
               "single",
               "--w", str(w), "--h", str(h), "--fps", str(fps),
               "--fmt", fmt, "--dur", str(args.dur)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=args.dur + 25)
            line = next((l for l in proc.stdout.splitlines()
                         if l.startswith("RESULT_JSON:")), None)
            row = json.loads(line[len("RESULT_JSON:"):]) if line else {
                "w": w, "h": h, "fps_req": fps, "fmt": fmt,
                "status": "no_result", "error": (proc.stderr or "")[-200:],
            }
        except subprocess.TimeoutExpired:
            row = {"w": w, "h": h, "fps_req": fps, "fmt": fmt,
                   "status": "hang_killed", "error": TCC_HINT}
        passed = (row.get("status") == "ok"
                  and row.get("frames", 0) >= 10
                  and row.get("measured_fps", 0) >= row["fps_req"] * 0.9)
        row["pass"] = passed
        rows.append(row)
        print(f"   -> {row['status']}  frames={row.get('frames', 0)} "
              f"measured={row.get('measured_fps', 0)}fps "
              f"p95={row.get('intervals', {}).get('p95_ms', '-')}ms "
              f"{'PASS' if passed else ''}", flush=True)

    recommendation = next((r for r in rows if r["pass"]), None)
    rec_str = (f"{recommendation['w']}x{recommendation['h']}@"
               f"{recommendation['fps_req']} {recommendation['fmt']}") if recommendation else None
    report = {
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backend": args.backend, "device": args.device,
        "candidates": rows,
        "recommendation": rec_str,
    }
    os.makedirs(os.path.dirname(_REPORT_PATH), exist_ok=True)
    with open(_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n推荐档位: {report['recommendation'] or '无(全档失败)'}")
    print(f"报告: {_REPORT_PATH}")
    if recommendation is None:
        hints = {r.get("status") for r in rows}
        if hints & {"hang_killed", "hang_timeout", "no_frames"}:
            print(TCC_HINT)
        return 1
    return 0


def cmd_frame(args: argparse.Namespace) -> int:
    """抓一帧存 PNG(供内容确认/毫秒计时器拍照法);顺带 30 帧间隔统计。"""
    last_err = None
    for w, h, fps, fmt in CANDIDATES:
        try:
            container = _open_container(args, w, h, fps, fmt)
        except Exception as exc:
            last_err = str(exc)
            continue
        arrivals, img = [], None
        deadline = time.monotonic() + 3
        try:
            for frame in container.decode(video=0):
                arrivals.append(time.monotonic())
                img = frame  # 只留最新
                if len(arrivals) >= 30 or time.monotonic() >= deadline:
                    break
        finally:
            container.close()
        if img is None:
            print(f"{w}x{h}@{fps} {fmt}: 打开成功但无帧。{TCC_HINT}", file=sys.stderr)
            return 1
        rgb = img.to_ndarray()  # avfoundation nv12 解码后帧;如需强制:img.reformat(format="rgb24")
        try:
            from PIL import Image
            Image.fromarray(rgb).save(args.out)
            print(f"已存 {args.out}  shape={rgb.shape}  "
                  f"intervals={_interval_stats(arrivals)}")
            return 0
        except ImportError:
            print(f"PIL 不可用;帧 shape={rgb.shape},首帧已解 "
                  f"intervals={_interval_stats(arrivals)}")
            return 0
    print(f"所有候选档打开失败(最后错误:{last_err})", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default="avfoundation",
                        choices=["avfoundation", "dshow", "v4l2"],
                        help="采集后端(默认 avfoundation;Windows 迁移后 dshow)")
    parser.add_argument("--device", default="0",
                        help="avfoundation 索引 / dshow 'video=USB3 Video' / v4l2 /dev/video0")
    parser.add_argument("--name", default=None,
                        help="按设备名子串解析索引(avfoundation;优先于 --device,子命令 --index 最高)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="枚举视频设备")

    p_matrix = sub.add_parser("matrix", help="候选档位矩阵探测(子进程隔离)")
    p_matrix.add_argument("--index", default=None, help="显式设备索引(覆盖 --name)")
    p_matrix.add_argument("--dur", type=float, default=4.0, help="每档采集秒数")

    p_single = sub.add_parser("single", help="单档探测(直跑,需已授权)")
    p_single.add_argument("--w", type=int, default=1280)
    p_single.add_argument("--h", type=int, default=720)
    p_single.add_argument("--fps", type=int, default=120)
    p_single.add_argument("--fmt", default="nv12")
    p_single.add_argument("--dur", type=float, default=4.0)

    p_frame = sub.add_parser("frame", help="抓一帧存 PNG")
    p_frame.add_argument("--index", default=None, help="显式设备索引(覆盖 --name)")
    p_frame.add_argument("--out", default="/tmp/fpv_frame.png")

    args = parser.parse_args()
    # 解析优先级:子命令 --index > --name(按名解析,索引不稳定) > --device 默认
    if args.backend == "avfoundation":
        idx = getattr(args, "index", None)
        if idx is not None:
            args.device = str(idx)
        elif args.name:
            args.device = _resolve_device_by_name(args.name)

    return {"list": cmd_list, "matrix": cmd_matrix,
            "single": cmd_single, "frame": cmd_frame}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
