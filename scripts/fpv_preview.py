#!/usr/bin/env python3
"""FPV 采集预览 + 统计（M1 验收工具）。

用途（docs/arch/fpv-pilot-capture-plan.md §6 M1 验收）：
    稳定 120fps 采集、帧龄 p95 <10ms。画面实时预览 + 覆盖文字统计，
    每秒打印一行 console 统计供验收记录。

必须在有摄像头授权的终端跑（macOS TCC；ZCode 沙箱弹不出授权框）：

    .venv/bin/python scripts/fpv_preview.py
    .venv/bin/python scripts/fpv_preview.py --name "USB3 Video" --fps 120

按键：q / Esc 退出；s 切换统计覆盖文字显示。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from donkeycar.parts.fpv_capture import FpvCaptureCardCamera, FpvCaptureError  # noqa: E402


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = round(q / 100 * (len(sorted_vals) - 1))
    return round(sorted_vals[min(len(sorted_vals) - 1, idx)], 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="USB3 Video", help="设备名子串（默认 USB3 Video）")
    ap.add_argument("--device", default=None, help="显式设备索引/路径（覆盖 --name）")
    ap.add_argument("--backend", default="avfoundation",
                    choices=["avfoundation", "dshow", "v4l2"])
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--fps", type=int, default=120)
    ap.add_argument("--fmt", default="nv12")
    ap.add_argument("--model-w", type=int, default=320)
    ap.add_argument("--model-h", type=int, default=240)
    ap.add_argument("--window-scale", type=float, default=1.0,
                    help="预览窗口缩放（默认 1.0）")
    args = ap.parse_args()

    try:
        cam = FpvCaptureCardCamera(
            device_name=args.name, device=args.device, backend=args.backend,
            width=args.w, height=args.h, fps=args.fps, pixfmt=args.fmt,
            model_w=args.model_w, model_h=args.model_h)
        cam.start()
    except FpvCaptureError as exc:
        print(f"打开设备失败: {exc}", file=sys.stderr)
        return 1

    import cv2
    import numpy as np  # noqa: F401  (cv2 操作隐式用到 shape)

    win = "FPV Capture Preview (q=quit)"
    show_overlay = True
    read_ages = deque(maxlen=360)   # 每次读取时刻的帧龄 ms（读取时刻 - 最新帧到达时刻）
    cached_img = None               # ts 门控转换：槽未更新不重复 reformat
    cached_ts = 0.0
    last_print = time.monotonic()
    print(f"采集中: {args.w}x{args.h}@{args.fps} {args.fmt} | {args.backend} | {args.name}"
          f" | q/Esc 退出", flush=True)

    try:
        while True:
            vf, ts = cam.latest_full_video_frame()
            now = time.monotonic()
            st = cam.stats()
            if vf is not None:
                read_ages.append((now - ts) * 1000.0)  # 取帧等待即帧龄
                if ts != cached_ts:
                    cached_ts = ts
                    cached_img = cv2.cvtColor(
                        vf.reformat(format="rgb24").to_ndarray(), cv2.COLOR_RGB2BGR)
                img = cached_img
                if show_overlay:
                    ages = sorted(read_ages)
                    line1 = (f"capture {st['fps_1s']}fps  "
                             f"arrival p50/p95 {st['arrival_p50_ms']}/{st['arrival_p95_ms']}ms")
                    line2 = (f"age p50/p95 {_pct(ages, 50)}/{_pct(ages, 95)}ms  "
                             f"eagain {st['eagain_retries']}  "
                             f"{'STARVED ' if st['starved'] else ''}{st['status']}")
                    cv2.rectangle(img, (0, 0), (img.shape[1], 56), (0, 0, 0), -1)
                    cv2.putText(img, line1, (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (80, 255, 80), 1, cv2.LINE_AA)
                    cv2.putText(img, line2, (8, 46), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (80, 255, 80), 1, cv2.LINE_AA)
                if args.window_scale != 1.0:
                    img = cv2.resize(img, None, fx=args.window_scale,
                                     fy=args.window_scale)
                cv2.imshow(win, img)
            else:
                placeholder = np.zeros((240, 320, 3), np.uint8)
                cv2.putText(placeholder, "waiting for frames...", (16, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1,
                            cv2.LINE_AA)
                cv2.imshow(win, placeholder)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            if key == ord('s'):
                show_overlay = not show_overlay

            # 每秒 console 统计（验收记录口径）
            if now - last_print >= 1.0:
                ages = sorted(read_ages)
                print(f"  fps={st['fps_1s']}  arrival p50/p95="
                      f"{st['arrival_p50_ms']}/{st['arrival_p95_ms']}ms  "
                      f"read-age p50/p95={_pct(ages, 50)}/{_pct(ages, 95)}ms  "
                      f"frames={st['frames']}  eagain={st['eagain_retries']}  "
                      f"starved={st['starved']}  {st['status']}", flush=True)
                last_print = now
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        cv2.destroyAllWindows()

    print("已停止。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
