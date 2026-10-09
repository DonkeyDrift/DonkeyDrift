# -*- coding: utf-8 -*-
"""帧内时间戳印章（WebRTC 端到端时延闭环测量的测量基准）。

车端默认把每帧的时间戳（模拟器模式=帧到达时刻，实车=入缓冲时刻）烧进像素，
两个消费方据此实测端到端时延：

- scripts/webrtc_loop_probe.py 的 aiortc 接收端：解码印章后与已同步时钟对比；
- 浏览器 Drive 页：canvas 采样呈现帧的印章区域，得「呈现−时间戳」真实 E2E
  （徽标口径）。env DRIVE_WEBRTC_FRAME_STAMP=0 关闭烧入（徽标降级回帧间隔）。

编码为二进制单元条（cell bar）而非文本数字：实心色块对 H.264 有损压缩鲁棒，
解码只需阈值采样，不引入 OCR 依赖。

格式（v1）：
- 2 行 × 28 个 payload cell，每行行首 1 个同步 cell（第 0 行白、第 1 行黑，
  兼作印章存在性与行序校验）；
- cell 6×6px、间距 2px（pitch 8px），整幅印章 232×16px，画在 (4,4) 起，
  外扩 2px 黑色衬底固定对比度；
- payload = 微秒时间戳 >> 4（48bit，64µs 分辨率，MSB 先行、行优先）
  + 8bit 校验和（payload 6 字节逐字节求和取低 8 位）。

解码失败（无印章/校验不过）返回 None：调用方按"该帧不可测"计，不猜值。
"""
from typing import List, Optional

import numpy as np

_CELL = 6
_GAP = 2
_PITCH = _CELL + _GAP  # 8px
_COLS = 28
_ROWS = 2
_X0 = 4
_Y0 = 4
_PAD = 2

STAMP_WIDTH = _X0 + (_COLS + 1) * _PITCH + _PAD          # 242
STAMP_HEIGHT = _Y0 + _ROWS * _PITCH + _PAD               # 26

_BITS = _COLS * _ROWS                                     # 48 时间位 + 8 校验位 = 56
_SYNC_ROW0_ON = True
_SYNC_ROW1_ON = False

_WHITE_MIN = 160   # 同步 cell 判白下限（cell 均值）
_BLACK_MAX = 96    # 同步 cell 判黑上限
_CELL_THRESHOLD = 128


def _payload_bits(micros: int) -> List[int]:
    """微秒时间戳 → 56bit 位序列（48bit 时间 + 8bit 校验和）。"""
    payload = micros >> 4
    data = payload.to_bytes(6, "big")
    value = (payload << 8) | (sum(data) & 0xFF)
    return [(value >> (_BITS - 1 - i)) & 1 for i in range(_BITS)]


def draw_timestamp(frame: np.ndarray, timestamp: float) -> np.ndarray:
    """把捕获时刻烧入帧左上角（原地修改并返回；调用方需传可写副本）。"""
    if frame is None or frame.ndim != 3:
        return frame
    h, w = frame.shape[:2]
    if w < STAMP_WIDTH or h < STAMP_HEIGHT:
        return frame
    micros = int(round(timestamp * 1_000_000))
    bits = _payload_bits(micros)
    # 黑色衬底：固定 cell 对比度，压缩后阈值判定更稳
    frame[_Y0 - _PAD:_Y0 + _ROWS * _PITCH + _PAD,
          _X0 - _PAD:_X0 + (_COLS + 1) * _PITCH + _PAD, :] = 0
    for row in range(_ROWS):
        y = _Y0 + row * _PITCH
        for col in range(_COLS + 1):
            x = _X0 + col * _PITCH
            if col == 0:
                on = _SYNC_ROW0_ON if row == 0 else _SYNC_ROW1_ON
            else:
                on = bool(bits[row * _COLS + col - 1])
            if on:
                frame[y:y + _CELL, x:x + _CELL, :] = 255
    return frame


def read_timestamp(frame: np.ndarray) -> Optional[float]:
    """从帧中解码捕获时刻（秒）。无印章/校验不过 → None。"""
    if frame is None or frame.ndim != 3:
        return None
    h, w = frame.shape[:2]
    if w < _X0 + (_COLS + 1) * _PITCH or h < _Y0 + _ROWS * _PITCH:
        return None
    gray = frame[_Y0:_Y0 + _ROWS * _PITCH,
                 _X0:_X0 + (_COLS + 1) * _PITCH].mean(axis=2)
    value = 0
    for row in range(_ROWS):
        sync = gray[row * _PITCH + 2:row * _PITCH + 2 + _CELL - 4,
                    2:2 + _CELL - 4].mean()
        if row == 0 and sync < _WHITE_MIN:
            return None
        if row == 1 and sync > _BLACK_MAX:
            return None
        for col in range(_COLS):
            x = (col + 1) * _PITCH + 2
            cell = gray[row * _PITCH + 2:row * _PITCH + 2 + _CELL - 4, x:x + _CELL - 4]
            value = (value << 1) | (1 if cell.mean() >= _CELL_THRESHOLD else 0)
    payload = value >> 8
    if sum(payload.to_bytes(6, "big")) & 0xFF != value & 0xFF:
        return None
    return (payload << 4) / 1_000_000.0
