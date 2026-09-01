# -*- coding: utf-8 -*-
"""三路数据同步录制器（RFC 第 6 节）。

以相机帧时戳（笔记本单调钟）为基准，对车端遥测流（rc 60Hz / imu 100Hz，
经 ws 到达）做线性插值对齐，目标误差 <10ms；油门点动特征（频率/占空比/
幅值）在 rc/throttle 序列上滑动窗提取。数据落盘复用 donkeycar tub v2
格式，字段与 RFC 一致——Web UI Tub 管理页直接可见。

不依赖 donkeycar 时（导入失败）抛出明确错误，不降级为私有格式。
"""
import bisect
import threading
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
    """按到达时戳缓存的遥测流，支持任意时刻线性插值（越界钳位到端点）。

    线程安全：push 在 ws 事件循环线程、interpolate 在相机线程执行，
    _t/_fields 两段列表的插入与读取共用一把锁——否则两次 insert 之间
    被插入竞争会撕裂时戳-字段对齐（IndexError/错配）。

    容量：push 后按 retention_s 裁掉早于 newest−30s 的前缀，防无界增长。
    """

    def __init__(self, maxlen: int = 2000, retention_s: float = 30.0):
        # maxlen 仅保留旧签名兼容；长度上限由 retention_s 时间裁剪实现
        self._retention_s = retention_s
        self._t: List[float] = []
        self._fields: List[Dict[str, float]] = []
        self._lock = threading.Lock()

    def push(self, t_s: float, fields: Dict[str, float]) -> None:
        with self._lock:
            # 到达顺序可能偶发乱序（ws 抖动），插值要求时序有序：插入排序
            idx = bisect.bisect_right(self._t, t_s)
            self._t.insert(idx, t_s)
            self._fields.insert(idx, fields)
            # 前缀裁剪：丢弃早于 newest−retention_s 的旧样本
            cutoff = self._t[-1] - self._retention_s
            drop = bisect.bisect_left(self._t, cutoff)
            if drop:
                del self._t[:drop]
                del self._fields[:drop]

    def interpolate(self, t_s: float) -> Dict[str, float]:
        with self._lock:
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
    """油门点动特征提取（RFC 7.3）：施密特触发边沿检测 + 滑动窗统计。

    高电平判定（施密特触发，防单阈值在噪声下抖动出伪边沿、高估频率）：
    throttle > _HIGH_ON 置高、< _HIGH_OFF 置低，迟滞带内保持原状态。
    duty 为时间加权（零阶保持）：Σ 高电平持续时间 / 窗口时长，
    非均匀采样下不失真。
    语义约定：持续高（无边沿）= 无点动 duty=1 freq=0；持续低 = duty=0 freq=0。
    线程安全：push（事件循环线程）与 features（相机线程）共锁。
    """

    _HIGH_ON = 0.35   # 施密特上升阈值（值域 -1..1）
    _HIGH_OFF = 0.25  # 施密特下降阈值（0.25~0.35 迟滞带抗噪声抖动）

    def __init__(self, window_s: float = 1.0):
        self._window_s = window_s
        self._samples: Deque[Tuple[float, float, bool]] = deque()  # (t, throttle, 高电平态)
        self._is_high = False
        self._rising_edges: Deque[float] = deque()
        self._lock = threading.Lock()

    def push(self, t_s: float, throttle: float) -> None:
        with self._lock:
            if throttle > self._HIGH_ON:
                is_high = True
            elif throttle < self._HIGH_OFF:
                is_high = False
            else:
                is_high = self._is_high  # 迟滞带内保持
            self._samples.append((t_s, throttle, is_high))
            if is_high and not self._is_high:
                self._rising_edges.append(t_s)
            self._is_high = is_high
            cutoff = t_s - self._window_s
            while self._samples and self._samples[0][0] < cutoff:
                self._samples.popleft()
            while self._rising_edges and self._rising_edges[0] < cutoff:
                self._rising_edges.popleft()

    def features(self) -> PulseFeatures:
        with self._lock:
            if not self._samples:
                return PulseFeatures(frequency_hz=0.0, duty=0.0, peak_amp=0.0)
            t_start = self._samples[0][0]
            t_end = self._samples[-1][0]
            span = t_end - t_start
            if span <= 0:
                return PulseFeatures(0.0, 0.0, 0.0)
            samples = list(self._samples)
            # 时间加权 duty：零阶保持，段 [t_i, t_{i+1}) 的电平取段首样本
            high_time = 0.0
            for (t0, _, h0), (t1, _, _) in zip(samples, samples[1:]):
                if h0:
                    high_time += t1 - t0
            duty = high_time / span
            # 上升沿计数：不足 2 个边沿时无法构成周期 → 无点动
            n_edges = len(self._rising_edges)
            if n_edges < 2:
                freq = 0.0
            else:
                # 窗内边沿跨越时间即 (n_edges-1) 个周期；同刻双边沿
                # （重复时戳）edge_span=0 无法构成周期，防除零
                edge_span = self._rising_edges[-1] - self._rising_edges[0]
                freq = (n_edges - 1) / edge_span if edge_span > 0 else 0.0
            peak = max((v for _, v, h in samples if h), default=0.0)
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
