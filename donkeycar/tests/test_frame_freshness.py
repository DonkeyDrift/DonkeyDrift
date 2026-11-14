# -*- coding: utf-8 -*-
"""frame_freshness 侧信道 + 模拟器帧到达时间戳/去重语义。"""
import numpy as np
import pytest

from donkeycar.parts import frame_freshness
from donkeycar.parts.drive_api_bridge import DriveVideoFrameBuffer


def test_set_get_roundtrip_and_reset():
    assert frame_freshness.get_source_arrival() is None
    ts = frame_freshness.set_source_arrival(1234.5)
    assert ts == 1234.5
    assert frame_freshness.get_source_arrival() == 1234.5
    frame_freshness.reset_source_arrival()
    assert frame_freshness.get_source_arrival() is None


def test_set_source_arrival_monotonic_on_clock_rollback():
    frame_freshness.set_source_arrival(2000.0)
    # 时钟回拨：保留较大值，保证去重比较与 pts 单调
    assert frame_freshness.set_source_arrival(1999.0) == 2000.0
    assert frame_freshness.get_source_arrival() == 2000.0


def test_buffer_dedups_same_arrival_and_uses_arrival_timestamp():
    # 模拟器模式：侧信道有值
    frame_freshness.set_source_arrival(1000.5)
    buf = DriveVideoFrameBuffer(width=320, height=240)
    img = np.zeros((240, 320, 3), dtype=np.uint8)

    first = buf.update(img)
    assert first.frame_id == 1
    assert first.timestamp == 1000.5  # 帧时间戳 = 到达时刻（轮询等待计入时延口径）

    # 车辆循环再次轮询同帧（同到达时刻）：不刷新 frame_id、不换时间戳
    again = buf.update(img)
    assert again is first
    assert buf.frame_id == 1
    assert buf.get_latest() is first

    # 新一帧到达：正常推进
    frame_freshness.set_source_arrival(1000.6)
    second = buf.update(img)
    assert second.frame_id == 2
    assert second.timestamp == 1000.6
    assert buf.stats()["frame_id"] == 2


def test_buffer_legacy_without_side_channel_uses_clock():
    # 实车路径：侧信道为空 → 原行为（update 时钟 + 不去重）
    buf = DriveVideoFrameBuffer(width=320, height=240, clock=lambda: 555.0)
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    first = buf.update(img)
    second = buf.update(img)
    assert first.frame_id == 1
    assert second.frame_id == 2
    assert first.timestamp == 555.0
    assert second.timestamp == 555.0


def test_dgym_set_frame_publishes_arrival_to_side_channel():
    pytest.importorskip("gym_donkeycar")
    from donkeycar.parts.dgym import DonkeyGymEnv

    env = DonkeyGymEnv.__new__(DonkeyGymEnv)  # 跳过 __init__（不连模拟器）
    env._img_h, env._img_w = 120, 160
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    env._set_frame(frame)
    assert frame_freshness.get_source_arrival() is not None
    # preview 保留原分辨率、cam 帧按 img_w×img_h 下采样
    assert env.preview_frame.shape == (240, 320, 3)
    assert env.frame.shape == (120, 160, 3)

    # raw_frame=None 不更新侧信道
    before = frame_freshness.get_source_arrival()
    env._set_frame(None)
    assert frame_freshness.get_source_arrival() == before
