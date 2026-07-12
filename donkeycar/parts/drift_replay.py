"""MUS4 漂移操作回放 Part。

DriftReplayPart 是一个"假 Pilot"：实现与 KerasPilot 同构的 Part 接口
（输出 pilot/angle、pilot/throttle，-1~1，run_condition='run_pilot'），
用"录制数据按 t_rel 时戳重放"替代"模型推理"。

链路：DriftReplayPart -> pilot/* -> DriveMode -> steering/throttle
      -> ArdPWMSteering/Throttle -> 串口下发 -> ESP32。

安全机制（Part 内部，-1~1 域）：
- 限幅：max_throttle/max_steering
- delta 限幅：max_delta_throttle/max_delta_steering（固件无 slew rate）
- 首尾包络：开头发 warmup_frames 帧 (0,0)；结尾发 (0,0) 收尾
- 失效安全：park 信号注入或 shutdown 时输出 (0,0)
- 循环：loop 次数到末尾后重置
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# 标准 clip schema，与 scripts/build_drift_clip.py 保持一致
CLIP_SCHEMA = "mus4.drift_replay_clip.v1"


class DriftReplayPart:
    """漂移回放 Part，按录制时戳输出 (angle, throttle)。

    :param clip_path: replay clip JSON 路径，None 表示未加载（输出 0,0）
    :param speed: 回放速率倍率（>1 加速）
    :param loop: 循环次数（1=单次，>1 循环）
    :param max_throttle: 油门上限（0~1）
    :param max_steering: 转向上限（0~1）
    :param max_delta_throttle: 油门单帧最大变化
    :param max_delta_steering: 转向单帧最大变化
    :param warmup_frames: 首部 (0,0) 预热帧数
    :param transition_ms: 循环重置时的静置时长 ms
    """

    def __init__(
        self,
        clip_path: str | Path | None = None,
        speed: float = 1.0,
        loop: int = 1,
        max_throttle: float = 0.6,
        max_steering: float = 1.0,
        max_delta_throttle: float = 0.2,
        max_delta_steering: float = 0.3,
        warmup_frames: int = 10,
        transition_ms: int = 300,
    ):
        self.speed = speed
        self.loop = max(1, int(loop))
        self.max_throttle = max_throttle
        self.max_steering = max_steering
        self.max_delta_throttle = max_delta_throttle
        self.max_delta_steering = max_delta_steering
        self.warmup_frames = warmup_frames
        self.transition_ms = transition_ms

        self._samples: list[dict] = []
        self._clip_duration_ms = 0.0
        if clip_path is not None:
            self._load_clip(clip_path)

        # 运行时状态
        self._loaded = len(self._samples) > 0
        self._start_mono: float | None = None
        self._warmup_remaining = warmup_frames
        self._loop_count = 0
        self._last_angle = 0.0
        self._last_throttle = 0.0
        self._parked = False
        self._shutdown = False

    def _load_clip(self, clip_path: str | Path) -> None:
        data = json.loads(Path(clip_path).read_text(encoding="utf-8"))
        if data.get("schema") != CLIP_SCHEMA:
            raise ValueError(f"clip schema 不匹配：期望 {CLIP_SCHEMA}，实际 {data.get('schema')!r}")
        self._samples = list(data.get("samples", []))
        if self._samples:
            self._clip_duration_ms = float(self._samples[-1].get("t_rel", 0.0))

    def _elapsed_ms(self) -> float:
        """从回放起始到当前的真实时间（ms），按 speed 缩放。"""
        if self._start_mono is None:
            return 0.0
        return (time.monotonic() - self._start_mono) * 1000.0 * self.speed

    def _sample_at(self, t_rel_ms: float) -> dict | None:
        """线性查找当前时戳对应的样本（取不超前的最后一帧）。"""
        if not self._samples:
            return None
        chosen = self._samples[0]
        for s in self._samples:
            if float(s.get("t_rel", 0.0)) <= t_rel_ms:
                chosen = s
            else:
                break
        return chosen

    def _clamp(self, value: float, limit: float) -> float:
        return max(-limit, min(limit, float(value)))

    def _limit_delta(self, value: float, previous: float, max_delta: float) -> float:
        if max_delta <= 0:
            return value
        return max(previous - max_delta, min(previous + max_delta, value))

    def run(self, park: bool = False) -> tuple[float, float]:
        """Vehicle 主循环调用，输出 (angle, throttle)。

        :param park: 外部注入的 park 信号（True 时输出 0,0 并停发）
        """
        if self._shutdown or not self._loaded:
            return 0.0, 0.0

        if park:
            self._parked = True
            self._last_angle = 0.0
            self._last_throttle = 0.0
            return 0.0, 0.0

        # 首部预热帧
        if self._warmup_remaining > 0:
            self._warmup_remaining -= 1
            self._last_angle = 0.0
            self._last_throttle = 0.0
            if self._start_mono is None:
                self._start_mono = time.monotonic()
            return 0.0, 0.0

        if self._start_mono is None:
            self._start_mono = time.monotonic()

        elapsed = self._elapsed_ms()
        total_duration = self._clip_duration_ms + (self.transition_ms if self.loop > 1 else 0)

        # 循环结束判定
        if self.loop > 1 and self._loop_count + 1 < self.loop and elapsed > total_duration:
            self._loop_count += 1
            self._start_mono = time.monotonic()
            elapsed = 0.0

        # 超过总回放时长（含所有循环），输出末帧后归零
        if elapsed > self._clip_duration_ms and self._loop_count + 1 >= self.loop:
            self._last_angle = 0.0
            self._last_throttle = 0.0
            return 0.0, 0.0

        sample = self._sample_at(elapsed)
        if sample is None:
            return self._last_angle, self._last_throttle

        angle = self._clamp(sample.get("angle", 0.0), self.max_steering)
        throttle = self._clamp(sample.get("throttle", 0.0), self.max_throttle)

        # delta 限幅（固件无 slew rate，这是上位机必须承担的安全责任）
        angle = self._limit_delta(angle, self._last_angle, self.max_delta_steering)
        throttle = self._limit_delta(throttle, self._last_throttle, self.max_delta_throttle)

        self._last_angle = angle
        self._last_throttle = throttle
        return angle, throttle

    def shutdown(self) -> None:
        """停止回放，后续输出 (0,0)。"""
        self._shutdown = True
        self._last_angle = 0.0
        self._last_throttle = 0.0
