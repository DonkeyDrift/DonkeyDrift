#!/usr/bin/env python3
"""台架假推理客户端（M2 验收：docs/plan/ai-bench-runbook.md 场景 1~5 通用）。

向 WheelLink WS 桥（ws://host:9870/ai）按固定频率发假 cmd，模拟推理端：
    {"t":"cmd","steer":..., "throttle":..., "seq":..., "ts":...}

同时接收并打印下行（input 回显 / tele 遥测 / mode 通知），供台架观察三态轮换、
软夺权与 failsafe。throttle 带符号：正=油门、负=刹车（WheelLink 侧拆 Throttle/Brake）。

用法（Mac/任意有 websockets 的机器，局域网可达 Windows 后端）：
    # 场景 1：空转注入（恒 0 转向 + 0.2 油门）
    .venv/bin/python scripts/fpv_fake_inference.py --host 192.168.x.x --throttle 0.2

    # 场景 3：摆动（打方向盘看软夺权）
    .venv/bin/python scripts/fpv_fake_inference.py --pattern wiggle

    # 场景 4：断流 failsafe（跑 5 秒即退）
    .venv/bin/python scripts/fpv_fake_inference.py --throttle 0.2 --duration 5

    # 场景 5：只发流不给油（观察 ARM 后零油门）
    .venv/bin/python scripts/fpv_fake_inference.py --pattern stop

Ctrl-C 干净退出（断开后 WheelLink 侧 100ms 腐化 → 看门狗 failsafe，预期行为）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time

import websockets


def build_cmd(pattern: str, t: float, seq: int, steer: float, throttle: float):
    if pattern == "wiggle":
        s = math.sin(2 * math.pi * 0.5 * t) * max(steer, 0.3)
        th = max(throttle, 0.1)
    elif pattern == "stop":
        s, th = 0.0, 0.0
    else:  # straight
        s, th = steer, throttle
    return {"t": "cmd", "steer": round(s, 4), "throttle": round(th, 4),
            "seq": seq, "ts": int(time.time() * 1000)}


async def run(args: argparse.Namespace) -> None:
    uri = f"ws://{args.host}:{args.port}/ai"
    period = 1.0 / args.rate
    seq = 0
    t0 = time.monotonic()
    last_print = t0
    recv_counts = {"input": 0, "tele": 0, "mode": 0, "other": 0}

    async with websockets.connect(uri, open_timeout=5) as ws:
        print(f"已连接 {uri} | pattern={args.pattern} steer={args.steer} "
              f"throttle={args.throttle} rate={args.rate}Hz（Ctrl-C 退出）", flush=True)

        async def receiver():
            async for message in ws:
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    recv_counts["other"] += 1
                    continue
                kind = msg.get("t", "?")
                recv_counts[kind if kind in recv_counts else "other"] += 1
                if kind == "mode":
                    print(f"  ← mode = {msg.get('mode')}", flush=True)

        recv_task = asyncio.create_task(receiver())

        try:
            while True:
                now = time.monotonic()
                if args.duration > 0 and now - t0 >= args.duration:
                    break
                seq += 1
                await ws.send(json.dumps(
                    build_cmd(args.pattern, now - t0, seq, args.steer, args.throttle)))
                if now - last_print >= 2.0:
                    print(f"  已发 {seq} cmd | 收 input×{recv_counts['input']} "
                          f"tele×{recv_counts['tele']} mode×{recv_counts['mode']}", flush=True)
                    last_print = now
                await asyncio.sleep(period)
        finally:
            recv_task.cancel()

    print(f"已退出（共发 {seq} cmd）——WheelLink 侧将腐化→failsafe，预期行为。", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1", help="WheelLink 所在机 IP（默认回环）")
    ap.add_argument("--port", type=int, default=9870)
    ap.add_argument("--rate", type=int, default=30, help="cmd 频率 Hz（协议 ≥10）")
    ap.add_argument("--steer", type=float, default=0.0, help="straight/wiggle 的基础转向 [-1,1]")
    ap.add_argument("--throttle", type=float, default=0.2,
                    help="带符号油门：正=油门 负=刹车（首跑建议 ≤0.25）")
    ap.add_argument("--pattern", choices=["straight", "wiggle", "stop"], default="straight")
    ap.add_argument("--duration", type=float, default=0.0, help="秒；0=一直跑")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n中断退出。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
