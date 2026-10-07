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
