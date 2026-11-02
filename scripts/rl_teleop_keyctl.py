"""M3 D0:teleop 键控与脚本序列(从 M1 rl_teleop_record.py 抽出,零 sim 依赖)。

D0 增量:KeyTeleop 记录 last_keys(采样主循环读 `r` 键开新局)。
"""

from __future__ import annotations

import math
import select
import sys
import termios
import tty


class KeyTeleop:
    """终端 raw 模式读键,保持式(按住渐变、松开保持当前值)。"""

    def __init__(self, steer_rate=1.2, throttle_rate=0.6):
        self.steer = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.quit = False
        self.last_keys = ""          # 最近一次 poll 收到的键(D0:r 键新局检测)
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
        self.last_keys = keys
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


def scripted_action(pattern: str, t: float):
    """按模式名返回 (steer, throttle, brake)。demo 覆盖直行/定圆/回正/蛇行。"""
    if pattern == "straight":
        return (0.0, 0.5, 0.0)
    if pattern == "circle":
        return (0.55, 0.6, 0.0)
    if pattern == "slalom":
        return (0.7 * math.sin(2 * math.pi * t / 3.0), 0.55, 0.0)
    if pattern == "demo":
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


class _NullCtx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
