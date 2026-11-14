# -*- coding: utf-8 -*-
"""DriveAiortcVideoTrack 的 RTP 时间戳语义回归测试。

pts 必须跟随帧的真实采集时刻（墙钟）推进：WebRTC 的媒体时钟由
pts*time_base 定义，若按「每帧 +1」推进，实际发送速率低于声明 fps 时
（编码波动，实测 48~57fps vs 60fps），接收端看到的媒体时钟会持续慢于
墙钟，长时间运行后接收侧缓冲时序失真。
"""
import asyncio

import numpy as np
import pytest

from donkeycar.parts.drive_api_bridge import (
    DriveAiortcVideoTrack,
    DriveVideoFrameBuffer,
)

pytest.importorskip("av", reason="WebRTC 媒体轨道测试需要 PyAV")


def _push_frame(buf: DriveVideoFrameBuffer, timestamp: float) -> None:
    buf.clock = lambda: timestamp
    buf.update(np.zeros((240, 320, 3), dtype=np.uint8))


def _recv_pts(track: DriveAiortcVideoTrack) -> int:
    return asyncio.run(track.recv()).pts


def test_pts_follows_wall_clock():
    """发送间隔 1s/1.5s 的帧，pts 应分别推进 60/90（60fps 时基下即真实流逝时间）。"""
    buf = DriveVideoFrameBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60)

    _push_frame(buf, 1000.0)
    assert _recv_pts(track) == 0
    _push_frame(buf, 1001.0)
    assert _recv_pts(track) == 60
    _push_frame(buf, 1002.5)
    assert _recv_pts(track) == 150


def test_pts_monotonic_under_wall_clock_backward_jump():
    """墙钟回拨（NTP 校时）时 pts 不回退：退化为每帧 +1 保单调。"""
    buf = DriveVideoFrameBuffer(clock=lambda: 2000.0)
    track = DriveAiortcVideoTrack(buf, fps=60)

    _push_frame(buf, 2000.0)
    first = _recv_pts(track)
    _push_frame(buf, 1999.0)
    second = _recv_pts(track)

    assert second > first


def test_time_base_is_declared_fps():
    """time_base 保持 1/fps：aiortc 编码器据此换算 RTP 时钟（90000Hz）。"""
    buf = DriveVideoFrameBuffer(clock=lambda: 3000.0)
    track = DriveAiortcVideoTrack(buf, fps=30)

    assert float(track.time_base) == pytest.approx(1 / 30)
    _push_frame(buf, 3000.0)
    assert _recv_pts(track) == 0
    _push_frame(buf, 3002.0)
    assert _recv_pts(track) == 60  # 2s × 30fps


class _FakeMono:
    """可控单调钟：测试手动推进，驱动节拍决策无真实等待。"""

    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def test_pacing_repeats_latest_frame_to_hold_cadence():
    """源慢于声明 fps：无新帧期间重复最新帧补满节拍，pts 单调推进。

    重复帧沿用原帧采集时刻（pts 走 +1 兜底），接收端按印章去重后
    时延口径仍是「采集→首现」。"""
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
    assert (second.pts, third.pts) == (1, 2)
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

    确定性复现 pts 竞速：槽位已到、新帧尚未入缓冲——持有分支必须先等住，
    让新帧赢下竞速；否则重复帧占掉 pts 槽，新帧被 +1 顶到下一槽，
    接收端按 pts 调度把新内容晚一个帧周期呈现。"""

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
    """新帧在其 pts 槽竞速窗口内到达：槽位持有让新帧赢，pts 不被顶到下一槽。"""
    mono = _FakeMono()
    buf = _LateArrivalBuffer(clock=lambda: 1000.0)
    track = DriveAiortcVideoTrack(buf, fps=60, pacing_clock=mono)
    tick = lambda k: k / 60 + 0.0005  # noqa: E731 落在槽位刚过，避免浮点边界

    _push_frame(buf, 1000.0)
    mono.t = 0.0
    assert asyncio.run(track.recv()).pts == 0        # 新帧 #1
    mono.t = tick(1)
    assert asyncio.run(track.recv()).pts == 1        # 重复帧
    mono.t = tick(2)
    assert asyncio.run(track.recv()).pts == 2        # 重复帧
    _push_frame(buf, 1000.05)                        # 新帧 #2：50ms 周期（20fps）
    mono.t = tick(3)
    assert asyncio.run(track.recv()).pts == 3        # target=3，未竞速
    mono.t = tick(4)
    assert asyncio.run(track.recv()).pts == 4        # 重复帧
    mono.t = tick(5)
    assert asyncio.run(track.recv()).pts == 5        # 重复帧
    # 新帧 #3 预期落在 50ms 槽：到达晚于槽位 ~0.5ms（竞速窗口内）
    buf.arm_late_arrival(1000.1)
    mono.t = tick(6)
    frame = asyncio.run(track.recv())

    assert frame.pts == 6                            # target=6，未被 +1 顶成 7
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
