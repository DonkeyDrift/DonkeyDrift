#!/usr/bin/env python3
"""D3a:sim 遥控驾驶遥测采样(β 校准闸门的真数据源)。

两种驱动方式:
  --script demo|straight|circle|slalom   脚本化控制序列(管线验证/无人工时用)
  (默认)                                 终端键控 teleop:采样时由使用者驾驶漂移
    w/s 油门增减  a/d 转向  space 刹车  x 归零  q 退出(终端 raw 模式,松键保持)

录制内容(每帧新遥测):t/frame_id/pos/speed/forward_vel/cte/gyro/accel/vel/
roll-pitch-yaw/action → <out>/teleop.npz + teleop.jsonl + meta.json
产物目录默认 outputs/(已 gitignore,不进 git)。

用法:
    .venv/bin/python scripts/rl_teleop_record.py --script demo
    .venv/bin/python scripts/rl_teleop_record.py                 # 人工漂移采样
    .venv/bin/python scripts/rl_teleop_record.py --sim-app <p>   # 指定 sim
"""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import sys
import termios
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim  # noqa: E402

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 键控 teleop(终端 raw 模式)
# ---------------------------------------------------------------------------

class KeyTeleop:
    """终端 raw 模式读键,保持式(按住渐变、松开保持当前值)。"""

    def __init__(self, steer_rate=1.2, throttle_rate=0.6):
        self.steer = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.quit = False
        self._steer_rate = steer_rate
        self._thr_rate = throttle_rate
        self._old_attr = None

    def __enter__(self):
        self._old_attr = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *exc):
        if self._old_attr is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_attr)

    def poll(self, dt: float) -> None:
        keys = ""
        while select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch:
                keys += ch
        if "q" in keys or "\x03" in keys:  # q / Ctrl-C
            self.quit = True
        if "x" in keys:
            self.steer = self.throttle = self.brake = 0.0
        if "a" in keys:
            self.steer = max(-1.0, self.steer - self._steer_rate * dt)
        if "d" in keys:
            self.steer = min(1.0, self.steer + self._steer_rate * dt)
        if "w" in keys:
            self.brake = 0.0
            self.throttle = min(1.0, self.throttle + self._thr_rate * dt)
        if "s" in keys:
            self.throttle = max(-1.0, self.throttle - self._thr_rate * dt)
        if " " in keys:
            self.brake = 1.0
            self.throttle = 0.0

    def action(self):
        return (self.steer, self.throttle, self.brake)


# ---------------------------------------------------------------------------
# 脚本化控制序列
# ---------------------------------------------------------------------------

def scripted_action(pattern: str, t: float) -> tuple:
    """按模式名返回 (steer, throttle, brake)。demo 覆盖直行/定圆/回正/蛇行。"""
    if pattern == "straight":
        return (0.0, 0.5, 0.0)
    if pattern == "circle":
        return (0.55, 0.6, 0.0)
    if pattern == "slalom":
        return (0.7 * math.sin(2 * math.pi * t / 3.0), 0.55, 0.0)
    if pattern == "demo":
        # 0-3s 直行加速 → 3-8s 定圆 → 8-9s 回直 → 9-16s 蛇行 → 16-18s 直行 → 停
        if t < 3.0:
            return (0.0, min(0.6, 0.2 * t), 0.0)
        if t < 8.0:
            return (0.55, 0.6, 0.0)
        if t < 9.0:
            return (0.0, 0.4, 0.0)
        if t < 16.0:
            return (0.7 * math.sin(2 * math.pi * (t - 9.0) / 3.0), 0.55, 0.0)
        if t < 18.0:
            return (0.0, 0.4, 0.0)
        return (0.0, 0.0, 1.0)
    raise ValueError(f"未知脚本模式 {pattern!r}")


# ---------------------------------------------------------------------------
# 录制主循环
# ---------------------------------------------------------------------------

def record(args) -> str:
    proc = None
    if not args.remote:
        proc = launch_sim(args.sim_app, port=args.port,
                          log_path=os.path.join(REPO_ROOT, "outputs",
                                                f"sim_teleop_{int(time.time())}.log"))
    env = DonkeyDriftEnv(sim_host=args.host, sim_port=args.port, sim_path="remote",
                         obs_mode="state", img_enc="none",
                         connect_timeout_s=90.0, frame_wait_timeout_s=2.0,
                         name=args.car_name)
    out_dir = os.path.join(REPO_ROOT, "outputs",
                           f"rl_teleop_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    print(f"[teleop] 输出目录:{out_dir}")
    try:
        obs, info = env.reset()
        print(f"[teleop] 已连接并复位(mode={info.get('rl/reset_mode')});"
              + ("脚本模式:" + args.script if args.script else
                 "键控:w/s 油门 a/d 转向 space 刹车 x 归零 q 退出"))
        t0 = time.perf_counter()
        last_t = t0
        teleop = KeyTeleop() if not args.script else None
        with (teleop if teleop else _NullCtx()) as kt:
            while True:
                now = time.perf_counter()
                dt = now - last_t
                last_t = now
                elapsed = now - t0
                if args.script:
                    if elapsed > args.duration:
                        break
                    steer, throttle, brake = scripted_action(args.script, elapsed)
                else:
                    kt.poll(dt)
                    if kt.quit:
                        break
                    steer, throttle, brake = kt.action()
                tok = env._frame_token()
                env._cam.run_threaded(steer, throttle, brake)
                if not env._wait_new_frame(tok, 2.0):
                    print("[teleop][警告] 2s 无新遥测(连接异常?)")
                    continue
                cam_info = dict(getattr(env._cam, "info", {}) or {})
                row = {
                    "t": round(time.perf_counter() - t0, 4),
                    "frame_id": cam_info.get("frame_id"),
                    "pos": list(cam_info.get("pos", (None, None, None))),
                    "speed": cam_info.get("speed"),
                    "forward_vel": cam_info.get("forward_vel"),
                    "cte": cam_info.get("cte"),
                    "gyro": list(cam_info.get("gyro", (None, None, None))),
                    "accel": list(cam_info.get("accel", (None, None, None))),
                    "vel": list(cam_info.get("vel", (None, None, None))),
                    "rpy": list(cam_info.get("car", (None, None, None))),
                    "action": [round(steer, 3), round(throttle, 3), round(brake, 3)],
                }
                rows.append(row)
                if args.script and int(elapsed * 2) != int((elapsed - dt) * 2):
                    print(f"[teleop] {elapsed:5.1f}s / {args.duration}s  "
                          f"speed={row['speed']:.2f} cte={row['cte']:.2f} "
                          f"帧数={len(rows)}")
    finally:
        env.close()
        if proc is not None:
            stop_sim(proc=proc)

    if not rows:
        print("[teleop] 无数据,不落盘")
        return ""
    # npz(定长数组)+ jsonl(逐行原始)+ meta
    import numpy as np

    def col(key, idx=None):
        out = []
        for r in rows:
            v = r[key]
            if idx is not None:
                v = v[idx] if v is not None and len(v) > idx else None
            out.append(float(v) if v is not None else float("nan"))
        return np.array(out)

    arrays = {
        "t": col("t"), "frame_id": col("frame_id"),
        "pos": np.stack([col("pos", i) for i in range(3)], axis=1),
        "speed": col("speed"), "forward_vel": col("forward_vel"), "cte": col("cte"),
        "gyro": np.stack([col("gyro", i) for i in range(3)], axis=1),
        "accel": np.stack([col("accel", i) for i in range(3)], axis=1),
        "vel": np.stack([col("vel", i) for i in range(3)], axis=1),
        "rpy": np.stack([col("rpy", i) for i in range(3)], axis=1),
        "action": np.stack([col("action", i) for i in range(3)], axis=1),
    }
    npz_path = os.path.join(out_dir, "teleop.npz")
    np.savez_compressed(npz_path, **arrays)
    jsonl_path = os.path.join(out_dir, "teleop.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {
        "script": args.script, "duration_s": args.duration, "rows": len(rows),
        "sim_app": args.sim_app, "port": args.port,
        "recorded_at": time.strftime("%F %T"),
        "note": "键控采样=使用者驾驶;npz 列含 NaN 表示该帧字段缺失",
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[teleop] 落盘 {len(rows)} 帧 → {npz_path}")
    return out_dir


class _NullCtx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9091)
    ap.add_argument("--remote", action="store_true", help="不拉 sim,连已运行的")
    ap.add_argument("--script", choices=["demo", "straight", "circle", "slalom"],
                    help="脚本化控制(无人工)")
    ap.add_argument("--duration", type=float, default=20.0, help="脚本模式时长(秒)")
    ap.add_argument("--car-name", default="rl-teleop")
    args = ap.parse_args()
    record(args)


if __name__ == "__main__":
    main()
