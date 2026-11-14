# -*- coding: utf-8 -*-
"""帧内时间戳印章编解码测试（WebRTC e2e 时延探针的测量基准）。"""
import time

import numpy as np

from donkeycar.parts.video_timestamp import (
    STAMP_HEIGHT,
    STAMP_WIDTH,
    draw_timestamp,
    read_timestamp,
)


def test_roundtrip_preserves_timestamp():
    ts = time.time()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    draw_timestamp(frame, ts)
    decoded = read_timestamp(frame)

    assert decoded is not None
    assert abs(decoded - ts) * 1e6 < 64  # 编码分辨率 64µs


def test_survives_quantization_noise():
    """量化噪声（模拟 H.264 压缩）下仍可解码。"""
    ts = time.time()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    draw_timestamp(frame, ts)

    noisy = frame.astype(np.int16) + np.random.randint(-12, 13, frame.shape, dtype=np.int16)
    decoded = read_timestamp(np.clip(noisy, 0, 255).astype(np.uint8))

    assert decoded is not None
    assert abs(decoded - ts) * 1e6 < 128


def test_plain_black_frame_decodes_to_none():
    assert read_timestamp(np.zeros((240, 320, 3), dtype=np.uint8)) is None


def test_checksum_rejects_corrupted_stamp():
    ts = time.time()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    draw_timestamp(frame, ts)
    # 整格取反第 0 行第 5 个 payload cell（x: 4+5*8 .. +6）：必改一个比特
    cell = frame[4:10, 4 + 5 * 8:4 + 5 * 8 + 6]
    cell[:, :] = 0 if cell.mean() > 128 else 255

    assert read_timestamp(frame) is None


def test_small_frame_skips_drawing():
    ts = time.time()
    small = np.zeros((120, 160, 3), dtype=np.uint8)

    assert draw_timestamp(small, ts) is small
    assert read_timestamp(small) is None


def test_stamp_fits_in_driving_resolution():
    assert 320 >= STAMP_WIDTH
    assert 240 >= STAMP_HEIGHT


def test_grayscale_frame_returns_none():
    assert read_timestamp(np.zeros((240, 320), dtype=np.uint8)) is None
