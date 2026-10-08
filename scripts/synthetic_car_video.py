#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合成车端视频源：以精确节拍生成运动画面，喂给 DriveApiBridge 真实链路。

用途：无需真实相机/实车即可闭环验证 WebRTC 视频链路的帧率与时延。
生成的画面为滚动条纹 + 逐帧变化内容（逼编码器持续出帧，不会跳帧）。
配合 scripts/webrtc_loop_probe.py 构成完整闭环测试。

用法：
  python scripts/synthetic_car_video.py --server ws://127.0.0.1:8123/api/drive/ws \
      --fps 60 --probe
"""
import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from donkeycar.parts.drive_api_bridge import DriveApiBridge  # noqa: E402


def generate_frame(counter: int, width: int, height: int) -> np.ndarray:
    """滚动对角条纹：每帧内容唯一且持续运动。"""
    yy, xx = np.mgrid[0:height, 0:width]
    phase = counter * 3
    r = ((xx + yy + phase) * 5) & 0xFF
    g = ((xx - yy + phase * 2) * 7) & 0xFF
    b = ((xx // 2 + phase) * 11) & 0xFF
    return np.stack([r, g, b], axis=2).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="合成车端 60fps 视频源")
    parser.add_argument("--server", default="ws://127.0.0.1:8000/api/drive/ws")
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--probe", action="store_true", help="开启时延印章")
    args = parser.parse_args()

    bridge = DriveApiBridge(
        server_url=args.server,
        role="car",
        video_transport="webrtc",
        video_width=args.width,
        video_height=args.height,
        video_fps=int(args.fps),
        auto_start=True,
        latency_probe=args.probe,
    )

    running = True

    def _stop(_sig, _frm):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print(f"合成源启动：{args.fps:.1f}fps {args.width}x{args.height} → {args.server}"
          f"{'（探针印章开）' if args.probe else ''}", flush=True)
    counter = 0
    interval = 1.0 / args.fps
    next_tick = time.monotonic()
    dropped_ticks = 0
    while running:
        next_tick += interval
        sleep = next_tick - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
        else:
            # 节拍落后（GC/调度抖动）：跳过补偿，避免突发补帧
            dropped_ticks += 1
            next_tick = time.monotonic()
        bridge.run_threaded(img_arr=generate_frame(counter, args.width, args.height),
                            num_records=0)
        counter += 1

    bridge.shutdown()
    print(f"合成源退出：共 {counter} 帧，掉拍 {dropped_ticks}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
