# -*- coding: utf-8 -*-
"""三路数据同步录制器（RFC 第 6 节）。

以相机帧时戳（笔记本单调钟）为基准，对车端遥测流（rc 60Hz / imu 100Hz，
经 ws 到达）做线性插值对齐，目标误差 <10ms；油门点动特征（频率/占空比/
幅值）在 rc/throttle 序列上滑动窗提取。数据落盘复用 donkeycar tub v2
格式，字段与 RFC 一致——Web UI Tub 管理页直接可见。

不依赖 donkeycar 时（导入失败）抛出明确错误，不降级为私有格式。
"""
import bisect
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

TUB_INPUTS = [
    "overhead/image_array", "pose/x", "pose/y", "pose/heading_deg",
    "state/beta", "state/yaw_rate",
    "state/throttle_pulse_freq", "state/throttle_duty", "state/throttle_pulse_amp",
    "rc/steering", "rc/throttle", "imu/gyr_z",
]

TUB_TYPES = ["image_array"] + ["float"] * (len(TUB_INPUTS) - 1)


class TelemetryBuffer:
    """按到达时戳缓存的遥测流，支持任意时刻线性插值（越界钳位到端点）。"""

    def __init__(self, maxlen: int = 2000):
        self._t: List[float] = []
        self._fields: List[Dict[str, float]] = []
        self._window: Deque[Tuple[float, Dict[str, float]]] = deque(maxlen=maxlen)

    def push(self, t_s: float, fields: Dict[str, float]) -> None:
        # 到达顺序可能偶发乱序（ws 抖动），插值要求时序有序：插入排序
        idx = bisect.bisect_right(self._t, t_s)
        self._t.insert(idx, t_s)
        self._fields.insert(idx, fields)

    def interpolate(self, t_s: float) -> Dict[str, float]:
        if not self._t:
            return {}
        if t_s <= self._t[0]:
            return dict(self._fields[0])
        if t_s >= self._t[-1]:
            return dict(self._fields[-1])
        idx = bisect.bisect_left(self._t, t_s)
        t0, t1 = self._t[idx - 1], self._t[idx]
        f0, f1 = self._fields[idx - 1], self._fields[idx]
        span = t1 - t0
        ratio = (t_s - t0) / span if span > 0 else 0.0
        out: Dict[str, float] = {}
        for key in set(f0) | set(f1):
            v0, v1 = f0.get(key), f1.get(key)
            if v0 is None:
                out[key] = v1
            elif v1 is None:
                out[key] = v0
            else:
                out[key] = v0 + (v1 - v0) * ratio
        return out


@dataclass
class PulseFeatures:
    frequency_hz: float
    duty: float
    peak_amp: float


class ThrottlePulseAnalyzer:
    """油门点动特征提取（RFC 7.3）：阈值化边沿检测 + 滑动窗统计。

    高电平判定：throttle > high_threshold（默认 0.3，值域 -1..1）。
    语义约定：持续高（无边沿）= 无点动 duty=1 freq=0；持续低 = duty=0 freq=0。
    """

    def __init__(self, window_s: float = 1.0, high_threshold: float = 0.3):
        self._window_s = window_s
        self._high_threshold = high_threshold
        self._samples: Deque[Tuple[float, float]] = deque()  # (t, throttle)
        self._was_high = False
        self._rising_edges: Deque[float] = deque()

    def push(self, t_s: float, throttle: float) -> None:
        self._samples.append((t_s, throttle))
        is_high = throttle > self._high_threshold
        if is_high and not self._was_high:
            self._rising_edges.append(t_s)
        self._was_high = is_high
        cutoff = t_s - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        while self._rising_edges and self._rising_edges[0] < cutoff:
            self._rising_edges.popleft()

    def features(self) -> PulseFeatures:
        if not self._samples:
            return PulseFeatures(frequency_hz=0.0, duty=0.0, peak_amp=0.0)
        t_start = self._samples[0][0]
        t_end = self._samples[-1][0]
        span = t_end - t_start
        if span <= 0:
            return PulseFeatures(0.0, 0.0, 0.0)
        highs = [v for _, v in self._samples if v > self._high_threshold]
        duty = len(highs) / len(self._samples)
        # 上升沿计数：不足 2 个边沿时无法构成周期 → 无点动
        n_edges = len(self._rising_edges)
        if n_edges < 2:
            freq = 0.0
        else:
            # 窗内边沿跨越时间即 (n_edges-1) 个周期
            freq = (n_edges - 1) / (self._rising_edges[-1] - self._rising_edges[0])
        peak = max(highs) if highs else 0.0
        return PulseFeatures(frequency_hz=float(freq), duty=float(duty),
                             peak_amp=float(peak))


class SyncRecorder:
    """相机帧 + 遥测插值 + 点动特征 → tub v2。"""

    def __init__(self, path: str, tub_inputs=None):
        try:
            from donkeycar.parts.tub_v2 import Tub
        except ImportError as exc:
            raise RuntimeError(
                "录制需要 donkeycar 包（笔记本端应安装 donkeydrifter）") from exc
        inputs = tub_inputs or TUB_INPUTS
        types = ["image_array"] + ["float"] * (len(inputs) - 1)
        self._tub = Tub(base_path=path, inputs=inputs, types=types)
        self._telemetry = TelemetryBuffer()
        self._pulse = ThrottlePulseAnalyzer()
        self.frames_written = 0

    def on_telemetry(self, t_s: float, fields: Dict[str, float]) -> None:
        self._telemetry.push(t_s, fields)
        if "rc/throttle" in fields:
            self._pulse.push(t_s, fields["rc/throttle"])

    def on_camera_frame(self, t_s: float, image: np.ndarray,
                        pose: Dict[str, float], beta_deg: float,
                        yaw_rate_dps: float) -> None:
        tel = self._telemetry.interpolate(t_s)
        if not tel:
            return  # 遥测未到，不写残缺记录
        feats = self._pulse.features()
        record = {
            "overhead/image_array": image,
            "pose/x": float(pose["x"]),
            "pose/y": float(pose["y"]),
            "pose/heading_deg": float(pose["heading_deg"]),
            "state/beta": float(beta_deg),
            "state/yaw_rate": float(yaw_rate_dps),
            "state/throttle_pulse_freq": feats.frequency_hz,
            "state/throttle_duty": feats.duty,
            "state/throttle_pulse_amp": feats.peak_amp,
            "rc/steering": float(tel.get("rc/steering", 0.0)),
            "rc/throttle": float(tel.get("rc/throttle", 0.0)),
            "imu/gyr_z": float(tel.get("imu/gyr_z", 0.0)),
        }
        self._tub.write_record(record)
        self.frames_written += 1

    def close(self) -> None:
        try:
            self._tub.close()
        except AttributeError:
            pass  # donkeycar Tub 无显式 close（v2 实现为惰性句柄）
