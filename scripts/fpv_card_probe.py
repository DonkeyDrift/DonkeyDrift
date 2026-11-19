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
    # matrix 默认按名解析采集卡(实测 macOS 枚举索引不稳定,曾打到内置摄像头):
    .venv/bin/python scripts/fpv_card_probe.py matrix
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

# 默认按名解析的采集卡名(索引不稳定;不指定时会打到内置摄像头——2026-11-20 实测踩坑)
DEFAULT_AVFOUNDATION_NAME = "USB3 Video"

# EAGAIN 对症提示(Errno 35:授权未决/被拒,或设备被独占)
EAGAIN_HINT = (
    "EAGAIN:① 终端未获摄像头授权(系统设置→隐私与安全性→摄像头,勾选后重跑);"
    "② 设备被其他 App 占用(关掉 OBS/采卡软件再试)"
)

# 读帧期 EAGAIN 判死提示(仅在连续 1.5s 无任何帧投递后触发)。
# 2026-11-20 实测定案:avfoundation 读帧间隙的 EAGAIN 是常态(需重试,循环内已处理);
# 真正持续无帧才是授权/占用/无信号问题。本卡无 HDMI 信号时 OBS 仍见待机画面
# (卡自产待机帧),"无信号不吐帧"基本排除。
EAGAIN_READ_HINT = (
    "持续 EAGAIN(>1.5s 无帧):① 终端摄像头授权(系统设置→隐私与安全性→摄像头,"
    "确认敲命令的终端 App 在列表且已打开);② 设备被其他 App 占用;③ HDMI 无信号。"
    "判定捷径:照片 Booth 打开该相机看有无画面——有画面=卡正常,聚焦查①"
)


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


def _open_container(args: argparse.Namespace,
                    w: int | None, h: int | None, fps: int | None, fmt: str | None):
    import av  # 延迟导入:仅 single/frame 需要,坏环境时 list 仍可用

    options = None
    if w:  # w=None 表示"不指定格式"探测(验证授权/设备,或让驱动挑默认档)
        options = {
            "framerate": str(fps),
            "video_size": f"{w}x{h}",
            "pixel_format": fmt,
        }
    return av.open(args.device, format=args.backend, options=options)


def _run_single(args: argparse.Namespace,
                w: int | None, h: int | None, fps: int | None, fmt: str | None,
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
    label = f"{w}x{h}@{fps} {fmt}" if w else "default(无格式约束)"
    # 开卡前提示:无权限环境实测会阻塞在 AVFoundation C 层,SIGALRM 打不断,
    # 手跑时超过 ~10s 无响应就 Ctrl-C,先按 TCC_HINT 授权再跑(推荐直接用 matrix)
    print(f"[{label}] 打开设备中(>10s 无响应≈TCC 挂起,Ctrl-C 中断)…",
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
        msg = str(exc)
        if "Errno 35" in msg or "temporarily unavailable" in msg:
            # EAGAIN 实测两因:终端摄像头授权未决/被拒;设备被其他 App 独占(OBS 等)
            result.update(status="eagain", error=EAGAIN_HINT + f" | 原始错误:{msg[:120]}")
        else:
            result.update(status="open_error", error=msg[:300])
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)
        return result

    arrivals: list[float] = []
    eagain_retries = 0
    last_progress = t_open0
    loop_start = None
    cap = (fps or 600) * dur_s * 2  # fps=None(default 档)时按 600fps 上限截断
    deadline = time.monotonic() + dur_s
    decoder = container.decode(video=0)
    loop_end = deadline
    # 2026-11-20 实测定案:ffmpeg avfoundation 读帧间隙常返 EAGAIN,CLI ffmpeg 内部
    # 重试而 PyAV 直接抛——必须睡 5ms 重试;连续 1.5s 无任何帧投递才判真死
    # (内置相机实测:首帧 1145ms 后突发 4 帧,旧逻辑首帧前 EAGAIN 即误判)。
    # 同日续证:NV12 各档突发 2-4 帧后 demuxer 返回 EOF(StopIteration)提前退出
    # ——PyAV 非阻塞与 avfoundation 兼容性问题,用 fftest 子命令的 CLI/OpenCV
    # 双参照判别(第三方参照分支原则)。
    try:
        while time.monotonic() < deadline:
            if loop_start is None:
                loop_start = time.monotonic()
            try:
                frame = next(decoder)
            except StopIteration:
                loop_end = time.monotonic()
                result.update(
                    status="eof",
                    error=f"demuxer EOF:仅 {len(arrivals)} 帧后流结束(PyAV 非阻塞"
                          f"与 avfoundation 兼容性问题疑似;跑 fftest 用 CLI ffmpeg/"
                          f"OpenCV 双参照判别)")
                break
            except OSError as exc:
                msg = str(exc)
                if "Errno 35" in msg or "temporarily unavailable" in msg:
                    eagain_retries += 1
                    if time.monotonic() - last_progress > 1.5:
                        loop_end = time.monotonic()
                        result.update(status="eagain_read", error=EAGAIN_READ_HINT)
                        break
                    time.sleep(0.005)
                    continue
                loop_end = time.monotonic()
                result.update(status="decode_error", error=msg[:300])
                break
            now = time.monotonic()
            last_progress = now
            if result["first_frame_ms"] is None:
                result["first_frame_ms"] = round((now - t_open0) * 1000, 1)
            arrivals.append(now)
            if len(arrivals) >= cap:
                loop_end = now
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
    result["eagain_retries"] = eagain_retries
    if len(arrivals) >= 2:
        # 吞吐口径:帧数/实际采集循环时长(从首帧到循环结束)——突发到达时
        # 帧间隔口径会虚高;EOF 早退时该值会如实走低
        span = max(loop_end - arrivals[0], 1e-3)
        result["measured_fps"] = round(len(arrivals) / span, 1)
        result["intervals"] = _interval_stats(arrivals)
    if len(arrivals) == 0 and result["status"] == "ok":
        result.update(status="no_frames", error=TCC_HINT)
    return result


def cmd_single(args: argparse.Namespace) -> int:
    try:
        w, h, fps, fmt = (None, None, None, None) if getattr(args, "any", False) \
            else (args.w, args.h, args.fps, args.fmt)
        result = _run_single(args, w, h, fps, fmt, args.dur)
    except BaseException as exc:  # 子进程也要把崩溃回报给 matrix(2026-11-20 实测教训)
        import traceback
        result = {"w": getattr(args, "w", None), "h": getattr(args, "h", None),
                  "fps_req": getattr(args, "fps", None), "fmt": getattr(args, "fmt", None),
                  "status": "child_crash",
                  "error": "".join(traceback.format_exception(exc))[-400:]}
    # 父进程(matrix)靠这行聚合;stdout 前缀保证可 grep
    print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    keys = ("w", "h", "fps_req", "fmt", "frames", "measured_fps",
            "first_frame_ms", "status")
    print(f"  { {k: result.get(k) for k in keys} }")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    print(f"目标设备: [{args.device}] (backend={args.backend}, "
          f"name={args.name!r})——索引不对请先跑 list 核对", flush=True)
    rows: list[dict] = []
    # 末尾追加"不指定格式"档:它能出帧=授权/设备 OK,失败是格式协商问题;
    # 它也失败=授权/占用问题(EAGAIN 提示会给出对症指引)
    for w, h, fps, fmt in CANDIDATES + [(None, None, None, None)]:
        label = f"{w}x{h}@{fps} {fmt}" if w else "default(无格式约束)"
        print(f"== 探测 {label} ...", flush=True)
        # 注意:--backend/--device 是主解析器参数,必须放在子命令之前
        cmd = [sys.executable, os.path.abspath(__file__),
               "--backend", args.backend, "--device", args.device,
               "single", "--dur", str(args.dur)]
        if w:
            cmd += ["--w", str(w), "--h", str(h), "--fps", str(fps), "--fmt", fmt]
        else:
            cmd += ["--any"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=args.dur + 25)
            line = next((l for l in proc.stdout.splitlines()
                         if l.startswith("RESULT_JSON:")), None)
            row = json.loads(line[len("RESULT_JSON:"):]) if line else {
                "w": w, "h": h, "fps_req": fps, "fmt": fmt,
                "status": "child_exit",
                "error": f"rc={proc.returncode} {(proc.stderr or '')[-400:]}",
            }
        except subprocess.TimeoutExpired:
            row = {"w": w, "h": h, "fps_req": fps, "fmt": fmt,
                   "status": "hang_killed", "error": TCC_HINT}
        passed = (row.get("status") == "ok"
                  and row.get("frames", 0) >= 10
                  and row.get("wall_s", 0) >= args.dur * 0.8  # EOF 早退不放行
                  and (row.get("fps_req") is None
                       or row.get("measured_fps", 0) >= row["fps_req"] * 0.9))
        row["pass"] = passed
        rows.append(row)
        print(f"   -> {row['status']}  frames={row.get('frames', 0)} "
              f"measured={row.get('measured_fps', 0)}fps "
              f"wall={row.get('wall_s', '-')}s first={row.get('first_frame_ms', '-')}ms "
              f"retry={row.get('eagain_retries', '-')} "
              f"p95={row.get('intervals', {}).get('p95_ms', '-')}ms "
              f"{'PASS' if passed else ''}", flush=True)

    # 推荐只从"显式格式"档里选(default 档只作授权/占用判据)
    recommendation = next((r for r in rows if r["pass"] and r.get("fps_req")), None)
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

    print(f"\n推荐档位: {rec_str or '无(全档失败)'}")
    default_row = next((r for r in rows if r.get("fps_req") is None), None)
    if default_row and default_row.get("status") == "ok":
        print(f"default 档出帧 {default_row.get('measured_fps')}fps → 授权/设备正常,"
              f"失败档是格式协商问题(对照 OBS 属性面板'输入格式'下拉核对)")
    print(f"报告: {_REPORT_PATH}")
    if recommendation is None:
        hints = {r.get("status") for r in rows}
        if hints & {"eagain_read"}:
            print(EAGAIN_READ_HINT)
        elif hints & {"eagain"}:
            print(EAGAIN_HINT)
        elif hints & {"hang_killed", "hang_timeout", "no_frames"}:
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


def cmd_fftest(args: argparse.Namespace) -> int:
    """第三方参照判别:PyAV 疑似 EOF 早退时,用 CLI ffmpeg(内部重试)与
    OpenCV(AVFoundation 原生)双参照测持续出帧——谁持续谁就是 M1 的采集层。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("未找到 ffmpeg", file=sys.stderr)
        return 1
    modes = [(1920, 1080, 120), (1280, 720, 120)]
    verdicts = []
    for w, h, fps in modes:
        print(f"== fftest {w}x{h}@{fps} nv12 ==", flush=True)
        # --- 参照 1: CLI ffmpeg(同 libavfoundation,但阻塞+内部重试) ---
        cli_fps = None
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-f", "avfoundation",
                 "-framerate", str(fps), "-pixel_format", "nv12",
                 "-video_size", f"{w}x{h}", "-i", args.device,
                 "-t", "10", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30)
            chunks = (proc.stderr or "").replace("\r", "\n").splitlines()
            # 协商出的流参数行:tbr = 设备实际提供的帧率档(判虚标的决定性证据)
            stream_line = next((l for l in chunks if "Stream #0:0" in l), None)
            if stream_line:
                print(f"  [CLI ffmpeg]  协商流: {stream_line.strip()[:110]}")
            stat = next((l for l in reversed(chunks) if "frame=" in l), "")
            import re as _re
            m = _re.search(r"frame=\s*(\d+).*?fps=\s*([\d.]+)", stat)
            if m:
                cli_fps = float(m.group(2))
                print(f"  [CLI ffmpeg]  frames={m.group(1)} fps={cli_fps} "
                      f"{'OK' if cli_fps >= fps * 0.8 else '低'}")
            else:
                print(f"  [CLI ffmpeg]  无统计行 rc={proc.returncode} "
                      f"tail={ (proc.stderr or '')[-120:]!r}")
        except subprocess.TimeoutExpired:
            print("  [CLI ffmpeg]  超时(30s)")
        # --- 参照 2: OpenCV CAP_AVFoundation(原生 API,不经 ffmpeg) ---
        cv_fps = None
        try:
            import cv2
            import threading
            holder = {}

            def _cv_worker():
                t0 = time.monotonic()
                cap = cv2.VideoCapture(int(args.device), cv2.CAP_AVFOUNDATION)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, fps)
                fps_readback = cap.get(cv2.CAP_PROP_FPS)
                n, first_ms, deadline = 0, None, time.monotonic() + 4
                while time.monotonic() < deadline:
                    ok, frame = cap.read()
                    if ok:
                        n += 1
                        if first_ms is None:
                            first_ms = round((time.monotonic() - t0) * 1000, 1)
                    elif n == 0:
                        time.sleep(0.005)
                cap.release()
                holder["r"] = (n, first_ms, frame.shape if n else None, fps_readback)

            th = threading.Thread(target=_cv_worker, daemon=True)
            th.start()
            th.join(15)
            if "r" not in holder:
                print("  [OpenCV]      打开/读帧挂起(>15s,授权或占用)")
            else:
                n, first_ms, shape, fps_rb = holder["r"]
                cv_fps = round(n / 4, 1)
                print(f"  [OpenCV]      frames={n} fps={cv_fps} first={first_ms}ms "
                      f"shape={shape} FPS回读={fps_rb:.0f} "
                      f"{'OK' if cv_fps and cv_fps >= fps * 0.8 else '低'}")
        except ImportError:
            print("  [OpenCV]      cv2 不可用")
        verdicts.append((w, h, fps, cli_fps, cv_fps))

    print("\n== 判读 ==")
    all_vals = [v for _, _, _, c, o in verdicts for v in (c, o) if v is not None]
    if any(v >= 50 for v in all_vals):
        best = max(all_vals)
        note = ""
        if best < 108:
            note = ("(低于请求的 120)→ 源端帧率问题:HDMI 源(VRX)输出档或待机画面帧率,"
                    "非采集层;接好图传、VRX 输出设为 720p120 后重跑复核")
        print(f"采集链路可用:双参照持续出帧,当前实际帧率≈{best:.0f}fps {note}")
        return 0
    print("两参照均不能持续出帧 → 卡/驱动/占用层问题:"
          "重插 USB 换口(零成本先做)→ 换线/HDMI 源 → 系统报告查 USB 设备")
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
    p_single.add_argument("--any", action="store_true",
                          help="不指定格式(默认档)——验证授权/设备是否可用")

    p_frame = sub.add_parser("frame", help="抓一帧存 PNG")
    p_frame.add_argument("--index", default=None, help="显式设备索引(覆盖 --name)")
    p_frame.add_argument("--out", default="/tmp/fpv_frame.png")

    sub.add_parser("fftest", help="CLI ffmpeg + OpenCV 双参照持续出帧判别"
                    "(PyAV EOF 早退时定位采集层选型)")

    args = parser.parse_args()
    # avfoundation 默认按名解析采集卡(索引不稳定;2026-11-20 实测裸跑打到内置摄像头)
    if (args.backend == "avfoundation" and not args.name
            and getattr(args, "index", None) is None):
        args.name = DEFAULT_AVFOUNDATION_NAME
    # 解析优先级:子命令 --index > --name(按名解析,索引不稳定) > --device 默认
    if args.backend == "avfoundation":
        idx = getattr(args, "index", None)
        if idx is not None:
            args.device = str(idx)
        elif args.name:
            args.device = _resolve_device_by_name(args.name)

    return {"list": cmd_list, "matrix": cmd_matrix,
            "single": cmd_single, "frame": cmd_frame,
            "fftest": cmd_fftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
