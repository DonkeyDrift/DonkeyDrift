#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drive API Bridge - 车端与 Web UI 的 WebSocket 桥接层
"""
import asyncio
import base64
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from threading import Thread
from typing import Callable, Dict, Optional
from fractions import Fraction
from urllib.parse import urlsplit, urlunsplit

import requests

try:
    import cv2
except Exception:  # pragma: no cover - 运行环境缺少 OpenCV 时只影响图像上传
    cv2 = None

try:
    import websockets
except Exception:  # pragma: no cover - 运行环境缺少 websockets 时由连接线程记录错误
    websockets = None

try:
    import av
except Exception:  # pragma: no cover - 运行环境缺少 av 时只影响 WebRTC 媒体轨道
    av = None

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
except Exception:  # pragma: no cover - 运行环境缺少 aiortc 时只影响 WebRTC 媒体轨道
    RTCPeerConnection = None
    RTCSessionDescription = None
    class VideoStreamTrack:  # type: ignore[no-redef]
        kind = "video"

        def __init__(self):
            pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DriveVideoFrame:
    frame_id: int
    frame: object
    timestamp: float


class DriveVideoFrameBuffer:
    """只保留最新图像帧的低延迟缓冲。"""

    def __init__(self, width: int = 320, height: int = 240,
                 clock: Callable[[], float] = time.time, history_size: int = 120):
        self.width = width
        self.height = height
        self.clock = clock
        self.frame_id = 0
        self.latest: Optional[DriveVideoFrame] = None
        self.timestamps = deque(maxlen=history_size)

    def update(self, img_arr):
        if img_arr is None:
            return None

        frame = self._resize(img_arr)
        timestamp = self.clock()
        self.frame_id += 1
        self.timestamps.append(timestamp)
        self.latest = DriveVideoFrame(frame_id=self.frame_id, frame=frame, timestamp=timestamp)
        return self.latest

    def _resize(self, img_arr):
        shape = getattr(img_arr, "shape", None)
        if shape is None or len(shape) < 2:
            return img_arr
        if shape[0] == self.height and shape[1] == self.width:
            return img_arr
        if cv2 is None:
            return img_arr
        return cv2.resize(img_arr, (self.width, self.height))

    def get_latest(self):
        return self.latest

    def stats(self):
        if len(self.timestamps) < 2:
            source_fps = 0.0
        else:
            elapsed = self.timestamps[-1] - self.timestamps[0]
            source_fps = 0.0 if elapsed <= 0 else (len(self.timestamps) - 1) / elapsed
        return {"source_fps": source_fps, "frame_id": self.frame_id}


class DriveWebRtcVideoTrack:
    """从最新帧缓冲输出真实新帧的 WebRTC 视频轨道。"""

    def __init__(self, frame_buffer: DriveVideoFrameBuffer, fps: int = 60,
                 clock: Callable[[], float] = time.time):
        self.frame_buffer = frame_buffer
        self.fps = fps
        self.clock = clock
        self.last_frame_id = 0
        self.sent_timestamps = deque(maxlen=120)
        self.sent_frames = 0
        self.stale_frames = 0
        self.stopped = False

    async def recv(self):
        if self.stopped:
            return None
        latest = self.frame_buffer.get_latest()
        if latest is None or latest.frame_id == self.last_frame_id:
            self.stale_frames += 1
            await asyncio.sleep(0)
            return None

        self.last_frame_id = latest.frame_id
        self.sent_frames += 1
        self.sent_timestamps.append(self.clock())
        return latest

    def stop(self):
        self.stopped = True

    def stats(self):
        if len(self.sent_timestamps) < 2:
            sent_fps = 0.0
        else:
            elapsed = self.sent_timestamps[-1] - self.sent_timestamps[0]
            sent_fps = 0.0 if elapsed <= 0 else (len(self.sent_timestamps) - 1) / elapsed
        return {
            "sent_fps": sent_fps,
            "sent_frames": self.sent_frames,
            "stale_frames": self.stale_frames,
        }


class DriveAiortcVideoTrack(VideoStreamTrack):
    """aiortc 使用的视频轨道，输出最新真实帧。"""

    def __init__(self, frame_buffer: DriveVideoFrameBuffer, fps: int = 60):
        super().__init__()
        self.frame_buffer = frame_buffer
        self.fps = fps
        self.last_frame_id = 0
        self.pts = 0
        self.time_base = Fraction(1, fps)

    async def recv(self):
        if av is None:
            raise RuntimeError("缺少 av 依赖，无法创建 WebRTC 视频帧")

        while True:
            latest = self.frame_buffer.get_latest()
            if latest is not None and latest.frame_id != self.last_frame_id:
                self.last_frame_id = latest.frame_id
                self.pts += 1
                frame = av.VideoFrame.from_ndarray(latest.frame, format="rgb24")
                frame.pts = self.pts
                frame.time_base = self.time_base
                return frame
            await asyncio.sleep(1.0 / self.fps)


class DriveApiBridge:
    """车端 WebSocket 桥接 Part。"""

    def __init__(self, server_url: str = "ws://localhost:8000/api/drive/ws",
                 role: str = "car", reconnect_interval: float = 3.0,
                 auto_start: bool = True, video_transport: str = "webrtc",
                 video_width: int = 320, video_height: int = 240,
                 video_fps: int = 60, webrtc_enabled: bool = True):
        self.server_url = self._with_role(server_url, role)
        self.http_api_base = self._http_api_base(server_url)
        self.reconnect_interval = reconnect_interval
        self.video_transport = video_transport
        self.video_fps = video_fps
        self.webrtc_enabled = webrtc_enabled
        self.frame_buffer = DriveVideoFrameBuffer(width=video_width, height=video_height)

        self.angle = 0.0
        self.throttle = 0.0
        self.mode = "user"
        self.mode_latch = None
        self.recording = False
        self.recording_latch = None
        self.buttons: Dict[str, bool] = {}

        self.connected = False
        self.ws = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False
        self.last_frame = 0.0
        self.thread = None
        self.active_webrtc_session_id = None
        self.webrtc_peer = None
        self.webrtc_track = DriveWebRtcVideoTrack(self.frame_buffer, fps=video_fps)

        if auto_start:
            self.start()

    @staticmethod
    def _with_role(server_url: str, role: str) -> str:
        separator = "&" if "?" in server_url else "?"
        return f"{server_url}{separator}role={role}"

    @staticmethod
    def _http_api_base(server_url: str) -> str:
        parsed = urlsplit(server_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        path = parsed.path
        if path.endswith("/ws"):
            path = path[:-3]
        return urlunsplit((scheme, parsed.netloc, path.rstrip("/"), "", ""))

    def start(self):
        self.running = True
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"DriveApiBridge 启动中，服务端地址: {self.server_url}")

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        if websockets is None:
            logger.error("缺少 websockets 依赖，无法连接 Web Console Drive")
            return

        while self.running:
            try:
                async with websockets.connect(self.server_url) as ws:
                    self.ws = ws
                    self.connected = True
                    logger.info("已连接到 Web Console Drive 服务端")
                    try:
                        async for message in ws:
                            try:
                                self._handle_message(json.loads(message))
                            except json.JSONDecodeError:
                                continue
                    finally:
                        self.connected = False
                        self.ws = None
            except Exception as e:
                logger.warning(f"连接失败，{self.reconnect_interval}s 后重连: {e}")
                await asyncio.sleep(self.reconnect_interval)

    def _handle_message(self, msg: dict):
        """处理服务端发来的控制消息。"""
        if msg.get("type") == "webrtc_signal":
            self._handle_webrtc_signal(msg)
            return
        if "angle" in msg:
            self.angle = float(msg["angle"])
        if "throttle" in msg:
            self.throttle = float(msg["throttle"])
        if "drive_mode" in msg:
            self.mode_latch = msg["drive_mode"]
        if "recording" in msg:
            self.recording_latch = bool(msg["recording"])
        if "buttons" in msg:
            self.buttons.update(msg["buttons"])

    def _send_json(self, payload: dict):
        if not self.loop or not self.ws:
            return
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(payload)), self.loop)

    def _handle_webrtc_signal(self, msg: dict):
        """处理 WebRTC 信令。"""
        if msg.get("signal_type") == "offer" and msg.get("session_id"):
            self.active_webrtc_session_id = msg["session_id"]
            self._run_async(self._accept_webrtc_offer(msg))

    def _run_async(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        return asyncio.run(coro)

    async def _accept_webrtc_offer(self, msg: dict):
        if RTCPeerConnection is None or RTCSessionDescription is None:
            logger.warning("缺少 aiortc 依赖，无法建立 WebRTC PeerConnection")
            return

        if self.webrtc_peer is not None:
            close = getattr(self.webrtc_peer, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

        peer = RTCPeerConnection()
        self.webrtc_peer = peer
        peer.addTrack(DriveAiortcVideoTrack(self.frame_buffer, fps=self.video_fps))
        await peer.setRemoteDescription(RTCSessionDescription(sdp=msg.get("sdp", ""), type="offer"))
        answer = await peer.createAnswer()
        await peer.setLocalDescription(answer)
        self._post_webrtc_answer(msg["session_id"], peer.localDescription.sdp)

    def _post_json(self, path: str, payload: dict):
        url = f"{self.http_api_base}{path}"
        response = requests.post(url, json=payload, timeout=3)
        response.raise_for_status()
        return response

    def _post_webrtc_answer(self, session_id: str, sdp: str):
        self._post_json("/webrtc/answer", {
            "session_id": session_id,
            "sdp": sdp,
            "type": "answer",
        })

    def _post_webrtc_ice(self, session_id: str, candidate: dict):
        self._post_json("/webrtc/ice", {
            "session_id": session_id,
            "source": "car",
            "candidate": candidate,
        })

    def _send_frame(self, img_arr, num_records=0, mode=None, recording=None):
        if cv2 is None:
            return
        frame = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            return
        frame_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        self._send_json({
            "type": "frame",
            "data": frame_b64,
            "num_records": num_records,
            "drive_mode": mode or self.mode,
            "recording": recording if recording is not None else self.recording,
        })

    def update(self):
        return None

    def run_threaded(self, img_arr=None, num_records=0, mode=None, recording=None):
        if img_arr is not None and self.video_transport == "webrtc":
            self.frame_buffer.update(img_arr)
        else:
            now = time.time()
            if self.connected and img_arr is not None and now - self.last_frame > 0.05:
                self.last_frame = now
                try:
                    self._send_frame(img_arr, num_records, mode, recording)
                except Exception as e:
                    logger.debug(f"发送帧失败: {e}")

        if mode is not None:
            self.mode = mode
        if self.mode_latch is not None:
            self.mode = self.mode_latch
            self.mode_latch = None

        if recording is not None:
            self.recording = recording
        if self.recording_latch is not None:
            self.recording = self.recording_latch
            self.recording_latch = None

        buttons = self.buttons
        self.buttons = {}
        return self.angle, self.throttle, self.mode, self.recording, buttons

    def run(self, img_arr=None, num_records=0, mode=None, recording=None):
        return self.run_threaded(img_arr, num_records, mode, recording)

    def shutdown(self):
        self.running = False
        self.webrtc_track.stop()
        if self.loop and self.ws:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
            except Exception:
                pass
        logger.info("DriveApiBridge 已停止")
