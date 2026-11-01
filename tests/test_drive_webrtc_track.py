# -*- coding: utf-8 -*-
"""DriveAiortcVideoTrack 的 RTP 时间戳语义回归测试。

pts*time_base 使用 90kHz 时钟：真实新帧保留采集间隔，
重复帧跟随单调钟，单调保护不增加一整帧。
"""
import asyncio

import numpy as np
import pytest

from donkeycar.parts.drive_api_bridge import (
    DriveAiortcVideoTrack,
    DriveVideoFrameBuffer,
    DriveVideoFrame,
)

pytest.importorskip("av", reason="WebRTC 媒体轨道测试需要 PyAV")


def _push_frame(buf: DriveVideoFrameBuffer, timestamp: float) -> None:
    buf.clock = lambda: timestamp
    buf.update(np.zeros((240, 320, 3), dtype=np.uint8))


def _recv_pts(track: DriveAiortcVideoTrack) -> int:
    return asyncio.run(track.recv()).pts


def test_pts_follows_wall_clock():
    """RTP ticks follow elapsed seconds, independently of declared FPS."""
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60)

    _push_frame(buf, 1000.0)
    assert _recv_pts(track) == 0
    _push_frame(buf, 1001.0)
    assert _recv_pts(track) == 90000
    _push_frame(buf, 1002.5)
    assert _recv_pts(track) == 225000


def test_pts_monotonic_under_wall_clock_backward_jump():
    """墙钟回拨时仅增加一个 RTP tick，保持严格单调。"""
    buf = DriveVideoFrameBuffer(clock=lambda: 2000.0)
    track = DriveAiortcVideoTrack(buf, fps=60)

    _push_frame(buf, 2000.0)
    first = _recv_pts(track)
    _push_frame(buf, 1999.0)
    second = _recv_pts(track)

    assert second == first + 1


@pytest.mark.parametrize("fps", [30, 60])
def test_time_base_is_rtp_clock(fps):
    """The media time base is always 90 kHz."""
    buf = DriveVideoFrameBuffer(clock=lambda: 3000.0)
    track = DriveAiortcVideoTrack(buf, fps=fps)

    assert float(track.time_base) == pytest.approx(1 / 90000)
    _push_frame(buf, 3000.0)
    assert _recv_pts(track) == 0
    _push_frame(buf, 3002.0)
    assert _recv_pts(track) == 180000


class _FakeMono:
    """可控单调钟：测试手动推进，驱动节拍决策无真实等待。"""

    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def test_pacing_repeats_latest_frame_to_hold_cadence():
    """源慢于声明 fps：无新帧期间重复最新帧补满节拍，pts 单调推进。

    重复帧印章沿用采集时刻，媒体 PTS 随单调钟推进。"""
    mono = _FakeMono()
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)

    _push_frame(buf, 1000.0)
    first = asyncio.run(track.recv())          # 真实新帧：立即出帧
    mono.t = 1 / 60
    second = asyncio.run(track.recv())         # 无新帧：节拍槽补重复帧
    mono.t = 2 / 60
    third = asyncio.run(track.recv())

    assert first.pts == 0
    assert (second.pts, third.pts) == (1500, 3000)
    assert track.repeat_frames == 2
    assert track.stats()["sent_frames"] == 3


def test_pacing_never_emits_faster_than_declared_fps():
    """新帧出帧后未到下一个节拍槽：补帧必须等待，不允许同槽连发。"""
    mono = _FakeMono()
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)

    _push_frame(buf, 1000.0)
    mono.t = 0.02
    asyncio.run(track.recv())                  # 新帧立即出帧
    mono.t = 0.0201                            # 同一节拍槽内再次取帧
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(asyncio.wait_for(track.recv(), timeout=0.05))
    assert track.repeat_frames == 0


def test_pacing_slot_after_late_fresh_still_emits():
    """新帧晚于自己的节拍槽到达（源节拍过冲）：两连发后下个槽不得跳过。

    旧逻辑两连发后扣欠预算、下槽跳过补偿 → 呈现侧 33ms 空洞（帧间隔
    p95 超标）；小额欠账出帧把空洞填平，间隔序列回到 60Hz 均匀。"""
    mono = _FakeMono()
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)

    _push_frame(buf, 1000.0)
    mono.t = 0.0
    asyncio.run(track.recv())                  # 新帧立即出帧
    for slot in (1, 2, 3):
        mono.t = slot / 60
        asyncio.run(track.recv())              # 槽 1..3 补重复帧（第 3 槽抢在新帧前）
    _push_frame(buf, 1000.05)                  # 源 20fps：新帧晚 3ms 到
    mono.t = 3 / 60 + 0.003
    asyncio.run(track.recv())                  # 与第 3 槽构成两连发
    mono.t = 4 / 60 + 0.003                    # 下个槽带小额欠账仍须出帧
    asyncio.run(track.recv())

    assert track.repeat_frames == 4
    assert track.stats()["sent_frames"] == 6


class _LateArrivalBuffer(DriveVideoFrameBuffer):
    """首次 wait_for_new_frame 被调用时模拟「新帧恰在持有窗口内到达」。

    确定性复现补帧竞速：持有分支让临近的新帧优先于重复帧出帧。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._late_timestamp = None

    def arm_late_arrival(self, timestamp: float) -> None:
        self._late_timestamp = timestamp

    async def wait_for_new_frame(self, last_frame_id: int, timeout: float):
        if self._late_timestamp is not None:
            ts = self._late_timestamp
            self._late_timestamp = None
            _push_frame(self, ts)
        return await super().wait_for_new_frame(last_frame_id, timeout)


def test_pacing_holds_expected_slot_so_fresh_wins_pts_race():
    """新帧在持有窗口内到达，保留采集 PTS 且不额外发送重复帧。"""
    mono = _FakeMono()
    buf = _LateArrivalBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)
    tick = lambda k: k / 60 + 0.0005  # noqa: E731 落在槽位刚过，避免浮点边界

    _push_frame(buf, 1000.0)
    mono.t = 0.0
    assert asyncio.run(track.recv()).pts == 0        # 新帧 #1
    mono.t = tick(1)
    assert asyncio.run(track.recv()).pts == 1545    # 16.7ms + 0.5ms
    mono.t = tick(2)
    assert asyncio.run(track.recv()).pts == 3045
    _push_frame(buf, 1000.05)                        # 新帧 #2：50ms 周期（20fps）
    mono.t = tick(3)
    assert asyncio.run(track.recv()).pts == 4500
    mono.t = tick(4)
    assert asyncio.run(track.recv()).pts == 6000
    mono.t = tick(5)
    assert asyncio.run(track.recv()).pts == 7500
    # 新帧 #3 预期落在 50ms 槽：到达晚于槽位 ~0.5ms（竞速窗口内）
    buf.arm_late_arrival(1000.1)
    mono.t = tick(6)
    frame = asyncio.run(track.recv())

    assert frame.pts == 9000
    assert track.repeat_frames == 4                  # 槽 1/2/4/5 补重复帧


def test_pacing_stops_repeating_when_source_stalls():
    """源静默超过 REPEAT_MAX_AGE_S：不再补重复帧，冻结画面显式停摆。"""
    mono = _FakeMono()
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)

    _push_frame(buf, 1000.0)
    mono.t = 0.0
    asyncio.run(track.recv())
    mono.t = 2.0                                # 源已静默 2s（>1s 门限）
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(asyncio.wait_for(track.recv(), timeout=0.05))
    assert track.repeat_frames == 0


def test_pacing_env_can_disable(monkeypatch):
    """DRIVE_WEBRTC_FRAME_PACING=0 关闭节拍补帧（退回只发真实新帧）。"""
    monkeypatch.setenv("DRIVE_WEBRTC_FRAME_PACING", "0")
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60)
    assert track.pacing is False


def test_jittered_slightly_fast_source_has_no_accumulated_drift():
    track = DriveAiortcVideoTrack(DriveVideoFrameBuffer(), fps=60, pacing=False)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    previous = -1
    for i in range(6000):
        elapsed = i / 60.1 + (0.004 if i % 2 else 0.0)
        frame = track._emit(
            DriveVideoFrame(i + 1, image, 1000.0 + elapsed), fresh=True)
        assert frame.pts > previous
        assert abs(float(frame.pts * frame.time_base) - elapsed) <= 1 / 90000
        previous = frame.pts
    assert track.pts_bumps == 0


def test_short_frame_intervals_are_not_rounded_to_frame_slots():
    track = DriveAiortcVideoTrack(DriveVideoFrameBuffer(), pacing=False)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    times = [0.0, 0.022, 0.034, 0.054, 0.067]
    for i, elapsed in enumerate(times):
        frame = track._emit(
            DriveVideoFrame(i + 1, image, 1000.0 + elapsed), fresh=True)
        assert float(frame.pts * frame.time_base) == pytest.approx(
            elapsed, abs=1 / 90000)


def test_equal_timestamps_only_add_one_rtp_tick():
    track = DriveAiortcVideoTrack(DriveVideoFrameBuffer(), pacing=False)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    pts = [
        track._emit(DriveVideoFrame(i + 1, image, 1000.0), fresh=True).pts
        for i in range(3)
    ]
    assert pts == [0, 1, 2]
    assert track.pts_bumps == 2


def test_repeat_then_fresh_preserves_stamp_and_only_adds_one_tick(monkeypatch):
    import donkeycar.parts.drive_api_bridge as module

    stamps = []
    monkeypatch.setattr(module, "draw_timestamp", lambda image, ts: stamps.append(ts))
    mono = _FakeMono()
    track = DriveAiortcVideoTrack(
        DriveVideoFrameBuffer(), pacing_clock=mono, latency_probe=True)
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    first = DriveVideoFrame(1, image, 1000.0)
    track._emit(first, fresh=True)
    mono.t = 0.02
    repeat = track._emit(first)
    mono.t = 0.0201
    fresh = track._emit(DriveVideoFrame(2, image, 1000.019), fresh=True)
    assert repeat.pts == 1800
    assert fresh.pts == repeat.pts + 1
    assert stamps == [1000.0, 1000.0, 1000.019]
    assert track.pts_bumps == 1


def test_vp8_encoder_accepts_high_precision_track_timestamps():
    from donkeycar.parts.webrtc_encoder import TunedVp8Encoder

    track = DriveAiortcVideoTrack(DriveVideoFrameBuffer(), pacing=False)
    encoder = TunedVp8Encoder()
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    timestamps = []
    for i, elapsed in enumerate([0.0, 0.022, 0.034, 0.054]):
        frame = track._emit(
            DriveVideoFrame(i + 1, image, 1000.0 + elapsed), fresh=True)
        payloads, timestamp = encoder.encode(frame)
        assert payloads
        assert timestamp == frame.pts
        timestamps.append(timestamp)
    assert all(b > a for a, b in zip(timestamps, timestamps[1:]))
