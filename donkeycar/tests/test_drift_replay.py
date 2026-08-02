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


def test_missing_clip_file_degrades_instead_of_raising(tmp_path, clock):
    """clip 文件不存在时不抛异常，降级为未加载（输出 0,0）。

    回归测试：数据目录被清空后 manage.py drive 不应在启动时崩溃。
    """
    missing = str(tmp_path / "no_such_clip.json")
    part = DriftReplayPart(clip_path=missing)
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
    part.run()  # t=0，确立 _start_mono
    # 推进到末尾（400ms）
    clock.advance(0.4)
    a_end, _ = part.run()  # 末帧 angle=0.0
    # 再推进，超过 clip 末尾但仍在 transition 期内，应仍输出末帧
    clock.advance(0.1)
    a_restart, _ = part.run()
    # 500ms 在第二轮开始前的 transition 期内，末帧 angle=0.0
    assert a_restart == pytest.approx(0.0)


def test_infinite_loop_never_stops(clip_file, clock):
    """loop<=0 时无限循环，不会回到 (0,0)。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0, loop=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()  # t=0，确立 _start_mono
    # 推进到单次末尾（400ms）
    clock.advance(0.4)
    a_end, _ = part.run()  # 末帧 angle=0.0
    assert a_end == pytest.approx(0.0)
    # 再推进，超过 clip 末尾但仍在 transition 期内，输出末帧
    clock.advance(0.1)
    a_restart, _ = part.run()
    assert a_restart == pytest.approx(0.0)  # transition 期内仍为 0.0
    # 推进到 transition 结束并触发循环重置
    clock.advance(0.25)
    a_reset, _ = part.run()  # 重置瞬间 elapsed=0，输出首帧 angle=0.0
    assert a_reset == pytest.approx(0.0)
    # 再推进到第二轮第 2 帧（100ms 处）
    clock.advance(0.1)
    a_second, _ = part.run()
    assert a_second == pytest.approx(0.5)


def test_speed_scales_timeline(clip_file, clock):
    """speed=2.0 时间轴压缩一半：0.05s 应取到第 2 帧。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0, speed=2.0,
                           max_delta_steering=1.0, max_delta_throttle=1.0)
    part.run()  # 第 1 帧
    clock.advance(0.05)  # 50ms -> 原本 100ms 的位置（speed=2）
    a, t = part.run()
    assert a == pytest.approx(0.5)  # 第 2 帧


def test_interpolation_between_samples(clip_file, clock):
    """默认启用线性插值：两帧中间应取中间值。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0,
                           interpolate=True)
    part.run()  # t=0, angle=0.0
    clock.advance(0.05)  # 50ms，在第 1 帧（0ms）与第 2 帧（100ms）正中间
    a, t = part.run()
    assert a == pytest.approx(0.25)  # (0.0 + 0.5) / 2
    assert t == pytest.approx(0.25)


def test_interpolation_can_be_disabled(clip_file, clock):
    """interpolate=False 时回到零阶保持（取不超前的最后一帧）。"""
    part = DriftReplayPart(clip_path=clip_file, warmup_frames=0,
                           max_delta_steering=1.0, max_delta_throttle=1.0,
                           interpolate=False)
    part.run()  # t=0
    clock.advance(0.05)  # 50ms，零阶保持仍应输出第 1 帧
    a, t = part.run()
    assert a == pytest.approx(0.0)
    assert t == pytest.approx(0.0)


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
