"""DriftReplayPart 单元测试。

覆盖 donkeycar/parts/drift_replay.py：DriftReplayPart 作为"假 Pilot"，
按 replay clip 的 t_rel 时戳调度，输出 (angle, throttle) ∈ [-1,1]，
写入 pilot/angle、pilot/throttle。

AAA 模式；时间用 monkeypatch 注入可控时钟，避免依赖真实时间。
"""

import json
import tempfile
from pathlib import Path

import pytest

from donkeycar.parts.drift_replay import DriftReplayPart, CLIP_SCHEMA


def _write_clip(path, samples, source="test", speed=1.0):
    """写一个最小 replay clip JSON。"""
    clip = {
        "schema": CLIP_SCHEMA,
        "samples": samples,
        "meta": {"source": source, "speed": speed, "sample_count": len(samples)},
    }
    Path(path).write_text(json.dumps(clip), encoding="utf-8")


@pytest.fixture
def clip_file(tmp_path):
    path = tmp_path / "clip.json"
    samples = [
        {"t_rel": 0.0, "angle": 0.0, "throttle": 0.0},
        {"t_rel": 100.0, "angle": 0.5, "throttle": 0.5},
        {"t_rel": 200.0, "angle": 1.0, "throttle": 0.8},
        {"t_rel": 300.0, "angle": 0.5, "throttle": 0.3},
        {"t_rel": 400.0, "angle": 0.0, "throttle": 0.0},
    ]
    _write_clip(path, samples)
    return str(path)


class FakeClock:
    """可控单调时钟，替代 time.monotonic。"""

    def __init__(self, start=0.0):
        self.now = start

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clk = FakeClock()
    import donkeycar.parts.drift_replay as mod
    monkeypatch.setattr(mod.time, "monotonic", clk.monotonic)
    return clk


def test_run_returns_zero_before_clip_loaded(clock):
    """未加载 clip 时返回 (0,0)。"""
    part = DriftReplayPart(clip_path=None)
    angle, throttle = part.run()
    assert angle == 0.0
    assert throttle == 0.0


def test_first_frames_after_load_are_warmup_zero(clip_file, clock):
    """加载后首部预热帧为 (0,0)。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=3)
    for _ in range(3):
        a, t = part.run()
        assert a == 0.0
        assert t == 0.0


def test_frame_scheduled_by_timestamp(clip_file, clock):
    """按 t_rel 调度：t=0.1s 应取第 2 帧（angle=0.5）。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()  # t=0, 第 1 帧
    clock.advance(0.1)  # 100ms -> 第 2 帧
    a, t = part.run()
    assert a == pytest.approx(0.5)
    assert t == pytest.approx(0.5)


def test_throttle_clamped_to_max(clip_file, clock, tmp_path):
    """油门超限被钳到 max_throttle。第 3 帧 throttle=0.8 超 0.6 上限。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_throttle=0.6,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()  # t=0 起始帧，确立 _start_mono
    clock.advance(0.2)  # 200ms -> 第 3 帧 throttle=0.8
    a, t = part.run()
    assert t == pytest.approx(0.6)  # 钳到 0.6


def test_steering_delta_limited(clip_file, clock):
    """转向瞬变被 delta 限制。

    第 1 帧 angle=0.0，第 2 帧 angle=0.5，delta=0.5。
    设 max_delta_steering=0.2，则第 2 帧只能到 0.2。
    """
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=0.2)
    part.run()  # angle=0.0
    clock.advance(0.1)  # 第 2 帧
    a, _ = part.run()
    assert a == pytest.approx(0.2)  # 被限制在 +0.2


def test_loop_restarts_clip(clip_file, clock):
    """循环：到末尾后重置继续。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0, loop=2,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    # 推进到末尾（400ms）
    clock.advance(0.4)
    a_end, _ = part.run()  # 末帧 angle=0.0
    # 再推进，应回到开头
    clock.advance(0.1)
    a_restart, _ = part.run()
    # 500ms 在第二轮的第 1 帧（t_rel=0.0）附近
    assert a_restart == pytest.approx(0.0)


def test_speed_scales_timeline(clip_file, clock):
    """speed=2.0 时间轴压缩一半：0.05s 应取到第 2 帧。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0, speed=2.0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()  # 第 1 帧
    clock.advance(0.05)  # 50ms -> 原本 100ms 的位置（speed=2）
    a, t = part.run()
    assert a == pytest.approx(0.5)  # 第 2 帧


def test_shutdown_emits_zero(clip_file, clock):
    """shutdown 后输出 (0,0)。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()
    clock.advance(0.1)
    part.run()  # 已在驱动中
    part.shutdown()
    a, t = part.run()
    assert a == 0.0
    assert t == 0.0


def test_park_signal_stops_output(clip_file, clock):
    """检测 park 时输出 (0,0)，对应固件 ControlMixer.cpp:77 约束。

    park 信号通过外部注入（模拟 RC Park 锁定）。
    """
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()
    clock.advance(0.2)
    # 正常应输出第 3 帧
    a_normal, _ = part.run()
    assert a_normal == pytest.approx(1.0)

    # 模拟 park 锁定
    part.run(park=True)
    clock.advance(0.05)
    a_park, t_park = part.run(park=True)
    assert a_park == 0.0
    assert t_park == 0.0


def test_load_invalid_schema_raises(tmp_path):
    """schema 不匹配时拒绝加载。"""
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema": "wrong", "samples": []}))
    with pytest.raises(ValueError):
        DriftReplayPart(clip_path=str(path))
