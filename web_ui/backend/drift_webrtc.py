# -*- coding: utf-8 -*-
"""WebRTC 预览推流（RFC 演进：60fps 高帧率显示链路）。

aiortc 作 WebRTC 服务端：浏览器发 offer，后端挂一条视频轨道应答。
轨道帧取自引擎的"最新显示帧"（含标签绿框/车头箭头叠加），60fps 节拍
丢旧取新——显示帧率 = 处理帧率，无排队延迟。MJPEG 端点保留为兜底。
"""
import asyncio
import time
from fractions import Fraction
from typing import Callable, Optional, Set

import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame

VIDEO_CLOCK_RATE = 90000
VIDEO_PTIME_60 = 1 / 60  # 60fps 节拍
VIDEO_TIME_BASE = Fraction(1, VIDEO_CLOCK_RATE)


class DisplayFrameTrack(VideoStreamTrack):
    """60fps 视频轨道：每节拍取最新显示帧（丢旧不排队）。"""

    def __init__(self, get_frame: Callable[[], Optional[np.ndarray]]):
        super().__init__()
        self._get_frame = get_frame
        self._black: Optional[np.ndarray] = None  # 缓存静态黑帧，无帧时复用

    async def next_timestamp(self) -> tuple:
        if self.readyState != "live":
            raise MediaStreamError
        if hasattr(self, "_timestamp"):
            self._timestamp += int(VIDEO_PTIME_60 * VIDEO_CLOCK_RATE)
            # 节拍用单调钟：墙钟（NTP 校时/手动改时间）跳变会打乱推流节奏
            wait = self._start + (self._timestamp / VIDEO_CLOCK_RATE) - time.monotonic()
            await asyncio.sleep(max(0.0, wait))
        else:
            self._start = time.monotonic()
            self._timestamp = 0
        return self._timestamp, VIDEO_TIME_BASE

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        frame = self._get_frame()
        if frame is None:
            # 无帧时复用缓存黑帧：每 tick 新分配 2.6MB 会加剧 GC 压力
            if self._black is None:
                self._black = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame = self._black
        h, w = frame.shape[:2]
        if w > 640:
            # 推流编码降半分辨率：运动画面 H.264 软编码 20~35ms 超 60fps
            # 的 16.6ms 预算（实测 api_latency 尖峰），÷4 后 60fps 稳定。
            # 检测仍在全分辨率帧上进行，精度不受影响。
            import cv2
            frame = cv2.resize(frame, (w // 2, h // 2),
                               interpolation=cv2.INTER_AREA)
        vf = VideoFrame.from_ndarray(frame, format="bgr24")
        vf.pts = pts
        vf.time_base = time_base
        return vf


_pcs: Set[RTCPeerConnection] = set()  # 持有活跃连接，防 GC 断流


async def handle_offer(sdp: str, type_: str, get_frame) -> dict:
    """处理浏览器 offer，返回 answer（SDP dict）。"""
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    _pcs.add(pc)

    @pc.on("connectionstatechange")
    def _on_state():
        # disconnected 同样清理：对端断网/页面关闭后连接不会再到 failed
        if pc.connectionState in ("failed", "closed", "disconnected"):
            _pcs.discard(pc)

    pc.addTrack(DisplayFrameTrack(get_frame))
    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=type_))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
    except Exception:
        # 协商失败（如非法 SDP）：必须关闭并移出 _pcs，否则 pc 随
        # 垃圾请求无界泄漏（pc 永不触发 connectionstatechange 清理）
        try:
            await pc.close()
        finally:
            _pcs.discard(pc)
        raise
    return {"sdp": pc.localDescription.sdp, "type": "answer"}


async def close_all() -> None:
    """关闭全部活跃连接（相机停止时调用）。"""
    for pc in list(_pcs):
        try:
            await pc.close()
        except Exception:
            pass
    _pcs.clear()
