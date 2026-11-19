#!/usr/bin/env python3
"""FPV 训练数据录制器（M3 数据面：docs/arch/fpv-pilot-capture-plan.md §4）。

单时钟免对齐：FPV 帧（本机采集卡）+ 人工打杆/遥测（WheelLink WS 回显）在**同进程
同一时钟**落 donkey tub——规避双机时间戳对齐问题。tub schema 兼容 train.py：

    cam/image_array  720p 全帧（image_array，tub 自动存 jpg）
    user/angle       = 回显 Steer（人工打杆实际值，RcRecordMerge 同语义）
    user/throttle    = 带符号油门：Throttle - Brake；GearR 按下整体取反；GearN 按下不录
                       （§2.2 定案：D 正/刹车负/R 取反/N 不录）
    user/mode        = human / ai_shadow / ai（回显 mode）
    tele/speed|vbat|pitch|roll|yaw|lq = 遥测（缺测=NaN 原样入库）

用法（有摄像头授权的终端；WS 通到 Windows WheelLink 9870）：
    .venv/bin/python scripts/fpv_record.py --ws-host 192.168.x.x
    # Enter=开始/暂停录制，q+Enter=退出（也可 --record 直接开录）
    # --shadow 同时把 AI cmd 经 WS 送出（ai_shadow 首航采集用，另见 fpv_fake_inference.py）
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field

_REPO_ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from donkeycar.parts.fpv_capture import FpvCaptureCardCamera  # noqa: E402
from donkeycar.parts.tub_v2 import TubWriter  # noqa: E402

INPUTS = [
    "cam/image_array", "user/angle", "user/throttle", "user/mode",
    "tele/speed", "tele/vbat", "tele/pitch", "tele/roll", "tele/yaw", "tele/lq",
]
TYPES = [
    "image_array", "float", "float", "str",
    "float", "float", "float", "float", "float", "float",
]


@dataclass
class EchoState:
    """WS 回显快照（接收线程写、录制线程读）。ready=至少一条 input 回显到达。"""

    lock: threading.Lock = field(default_factory=threading.Lock)
    ready: bool = False
    steer: float = 0.0
    throttle: float = 0.0
    brake: float = 0.0
    mode: str = "human"
    gear_r: bool = False
    gear_n: bool = False
    # 遥测（缺测 NaN）
    speed: float = float("nan")
    vbat: float = float("nan")
    pitch: float = float("nan")
    roll: float = float("nan")
    yaw: float = float("nan")
    lq: float = float("nan")

    def snapshot(self):
        with self.lock:
            return (self.ready, self.steer, self.throttle, self.brake, self.mode,
                    self.gear_r, self.gear_n,
                    self.speed, self.vbat, self.pitch, self.roll, self.yaw, self.lq)


def ws_receive_loop(uri: str, state: EchoState, stop: threading.Event) -> None:
    """WS 回显接收线程（websockets 同步客户端）；断线指数退避重连。"""
    from websockets.sync.client import connect

    backoff = 1.0
    while not stop.is_set():
        try:
            with connect(uri, open_timeout=5) as ws:
                print(f"[ws] 已连接 {uri}", flush=True)
                backoff = 1.0
                for message in ws:
                    if stop.is_set():
                        return
                    try:
                        msg = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    kind = msg.get("t")
                    with state.lock:
                        if kind == "input":
                            axes = msg.get("axes", {})
                            buttons = msg.get("buttons", {})
                            state.ready = True
                            state.steer = float(axes.get("Steer", 0.0) or 0.0)
                            state.throttle = float(axes.get("Throttle", 0.0) or 0.0)
                            state.brake = float(axes.get("Brake", 0.0) or 0.0)
                            state.mode = str(msg.get("mode", "human"))
                            state.gear_r = bool(buttons.get("GearR", False))
                            state.gear_n = bool(buttons.get("GearN", False))
                        elif kind == "mode":
                            state.mode = str(msg.get("mode", state.mode))
                        elif kind == "tele":
                            state.speed = _num(msg.get("speedKmh"))
                            state.vbat = _num(msg.get("vbat"))
                            state.pitch = _num(msg.get("pitch"))
                            state.roll = _num(msg.get("roll"))
                            state.yaw = _num(msg.get("yaw"))
                            state.lq = _num(msg.get("lq"))
        except Exception as exc:  # 连接断开/异常：退避重连
            print(f"[ws] 连接断开（{exc}），{backoff:.0f}s 后重连", flush=True)
            if stop.wait(backoff):
                return
            backoff = min(backoff * 2, 15.0)


def _num(value, default=float("nan")) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ws-host", default="127.0.0.1", help="WheelLink 所在机 IP")
    ap.add_argument("--ws-port", type=int, default=9870)
    ap.add_argument("--out", default=None, help="tub 目录（默认 tubs/tub_<时间戳>）")
    ap.add_argument("--fps", type=float, default=30.0, help="录制频率（默认 30Hz）")
    ap.add_argument("--record", action="store_true", help="启动即录（跳过 Enter 开关）")
    ap.add_argument("--name", default="USB3 Video", help="采集卡设备名")
    ap.add_argument("--backend", default="avfoundation",
                    choices=["avfoundation", "dshow", "v4l2"])
    ap.add_argument("--device", default=None, help="显式设备索引（覆盖 --name）")
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--cap-fps", type=int, default=120, help="采集协商帧率")
    args = ap.parse_args()

    import os
    out = args.out or os.path.join(_REPO_ROOT, "tubs",
                                   time.strftime("tub_%y-%m-%d_%H-%M-%S"))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    cam = FpvCaptureCardCamera(
        device_name=args.name, device=args.device, backend=args.backend,
        width=args.w, height=args.h, fps=args.cap_fps)
    cam.start()

    state = EchoState()
    stop = threading.Event()
    ws_uri = f"ws://{args.ws_host}:{args.ws_port}/ai"
    ws_thread = threading.Thread(
        target=ws_receive_loop, args=(ws_uri, state, stop), daemon=True)
    ws_thread.start()

    writer = TubWriter(out, inputs=INPUTS, types=TYPES, async_write=True)
    recording = args.record
    period = 1.0 / args.fps
    records = skipped_n = skipped_noecho = 0
    print(f"[rec] tub={out} | 录制={'开' if recording else '关'} | "
          f"{args.fps}Hz | Enter 开关录制 / q+Enter 退出", flush=True)

    def stdin_loop():
        nonlocal recording
        for line in sys.stdin:
            if line.strip().lower() == "q":
                stop.set()
                return
            recording = not recording
            print(f"[rec] 录制={'开' if recording else '关'}", flush=True)

    threading.Thread(target=stdin_loop, daemon=True).start()

    next_t = time.monotonic()
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now < next_t:
                time.sleep(min(next_t - now, 0.02))
                continue
            next_t += period

            frame, _ = cam.latest_full_frame()
            if frame is None:
                continue
            ready, steer, throttle, brake, mode, gear_r, gear_n, speed, vbat, pitch, roll, yaw, lq = state.snapshot()
            if not recording:
                continue
            if not ready:
                skipped_noecho += 1
                continue
            if gear_n:  # §2.2：N 挡不录
                skipped_n += 1
                continue

            # §2.2 油门标签语义：D 正 / 刹车负 / R 取反
            label_throttle = throttle - brake
            if gear_r:
                label_throttle = -label_throttle

            writer.run(frame, steer, label_throttle, mode,
                       speed, vbat, pitch, roll, yaw, lq)
            records += 1
            if records % 100 == 0:
                print(f"[rec] {records} 条（N 挡跳过 {skipped_n}，无回显跳过 {skipped_noecho}）",
                      flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        writer.close()
        cam.stop()
        print(f"[rec] 完成：{records} 条 → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
