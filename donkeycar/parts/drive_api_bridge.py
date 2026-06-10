#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drive API Bridge - 车端与 Web UI 的 WebSocket 桥接层
"""
import asyncio
import base64
import json
import logging
import os
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
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCIceServer, VideoStreamTrack
    try:
        from aiortc import RTCIceCandidate
    except ImportError:  # aiortc 部分版本不公开该类，回退为原始 dict
        RTCIceCandidate = None
    try:
        from aiortc.sdp import candidate_from_sdp
    except ImportError:
        candidate_from_sdp = None
except Exception:  # pragma: no cover - 运行环境缺少 aiortc 时只影响 WebRTC 媒体轨道
    RTCConfiguration = None
    RTCPeerConnection = None
    RTCSessionDescription = None
    RTCIceServer = None
    RTCIceCandidate = None
    candidate_from_sdp = None
    class VideoStreamTrack:  # type: ignore[no-redef]
        kind = "video"

        def __init__(self):
            pass

logger = logging.getLogger(__name__)


def parse_webrtc_ice_servers(value):
    """解析前后端共用的 ICE servers JSON 配置。"""
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            logger.warning(f"解析 DRIVE_WEBRTC_ICE_SERVERS 失败: {exc}")
            return []
    if not isinstance(value, list):
        logger.warning("DRIVE_WEBRTC_ICE_SERVERS 必须是 JSON 数组")
        return []
    return [item for item in value if isinstance(item, dict)]


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

    def __init__(self, frame_buffer: DriveVideoFrameBuffer, fps: int = 60,
                 clock: Callable[[], float] = time.time):
        super().__init__()
        self.frame_buffer = frame_buffer
        self.fps = fps
        self.clock = clock
        self.last_frame_id = 0
        self.pts = 0
        self.time_base = Fraction(1, fps)
        self.sent_timestamps = deque(maxlen=120)
        self.sent_frames = 0
        self.stale_frames = 0

    async def recv(self):
        if av is None:
            raise RuntimeError("缺少 av 依赖，无法创建 WebRTC 视频帧")

        while True:
            latest = self.frame_buffer.get_latest()
            if latest is not None and latest.frame_id != self.last_frame_id:
                self.last_frame_id = latest.frame_id
                self.pts += 1
                self.sent_frames += 1
                self.sent_timestamps.append(self.clock())
                frame = av.VideoFrame.from_ndarray(latest.frame, format="rgb24")
                frame.pts = self.pts
                frame.time_base = self.time_base
                return frame
            self.stale_frames += 1
            await asyncio.sleep(1.0 / self.fps)

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


class DriveApiBridge:
    """车端 WebSocket 桥接 Part。"""

    def __init__(self, server_url: str = "ws://localhost:8000/api/drive/ws",
                 role: str = "car", reconnect_interval: float = 3.0,
                 auto_start: bool = True, video_transport: str = "webrtc",
                 video_width: int = 320, video_height: int = 240,
                 video_fps: int = 60, webrtc_enabled: bool = True,
                 webrtc_ice_servers=None):
        self.server_url = self._with_role(server_url, role)
        self.http_api_base = self._http_api_base(server_url)
        self.reconnect_interval = reconnect_interval
        self.video_transport = video_transport
        self.video_fps = video_fps
        self.webrtc_enabled = webrtc_enabled
        self.webrtc_ice_servers = parse_webrtc_ice_servers(os.environ.get("DRIVE_WEBRTC_ICE_SERVERS") or webrtc_ice_servers)
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
        self.last_heartbeat = 0.0
        self.last_webrtc_stats = 0.0
        self.active_webrtc_session_id = None
        self.webrtc_peer = None
        self.aiortc_track = None
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
        if msg.get("signal_type") == "ice":
            self._handle_webrtc_ice(msg)

    def _run_async(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        return asyncio.run(coro)

    def _build_webrtc_configuration(self):
        if not self.webrtc_ice_servers or RTCConfiguration is None or RTCIceServer is None:
            return None
        ice_servers = []
        allowed_keys = {"urls", "username", "credential", "credentialType"}
        for server in self.webrtc_ice_servers:
            kwargs = {key: value for key, value in server.items() if key in allowed_keys}
            if "urls" not in kwargs:
                continue
            try:
                ice_servers.append(RTCIceServer(**kwargs))
            except Exception as exc:
                logger.warning(f"忽略无效 WebRTC ICE server 配置: {exc}")
        if not ice_servers:
            return None
        return RTCConfiguration(iceServers=ice_servers)

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

        configuration = self._build_webrtc_configuration()
        peer = RTCPeerConnection(configuration=configuration) if configuration is not None else RTCPeerConnection()
        self.webrtc_peer = peer
        if hasattr(peer, "on"):
            @peer.on("icecandidate")
            def on_icecandidate(candidate):
                self._handle_local_ice_candidate(candidate)
        self.aiortc_track = DriveAiortcVideoTrack(self.frame_buffer, fps=self.video_fps)
        peer.addTrack(self.aiortc_track)
        await peer.setRemoteDescription(RTCSessionDescription(sdp=msg.get("sdp", ""), type="offer"))
        answer = await peer.createAnswer()
        answer_sdp = answer.sdp
        try:
            await asyncio.wait_for(peer.setLocalDescription(answer), timeout=2.0)
            answer_sdp = getattr(peer.localDescription, "sdp", answer.sdp)
        except Exception as exc:
            logger.warning(f"设置 WebRTC local description 失败，回退原始 answer: {exc}")
        self._post_webrtc_answer(msg["session_id"], answer_sdp)

    def _handle_webrtc_ice(self, msg: dict):
        if msg.get("session_id") != self.active_webrtc_session_id or self.webrtc_peer is None:
            return
        candidate = msg.get("candidate")
        if not candidate:
            return
        self._run_async(self.webrtc_peer.addIceCandidate(self._build_remote_ice_candidate(candidate)))

    def _build_remote_ice_candidate(self, candidate: dict):
        if candidate_from_sdp is not None and candidate.get("candidate"):
            parsed = candidate_from_sdp(candidate["candidate"])
            if isinstance(parsed, dict):
                parsed["sdpMid"] = candidate.get("sdpMid")
                parsed["sdpMLineIndex"] = candidate.get("sdpMLineIndex")
            else:
                setattr(parsed, "sdpMid", candidate.get("sdpMid"))
                setattr(parsed, "sdpMLineIndex", candidate.get("sdpMLineIndex"))
            return parsed
        if RTCIceCandidate is not None:
            return RTCIceCandidate(**candidate)
        return candidate

    def _handle_local_ice_candidate(self, candidate):
        if not self.active_webrtc_session_id or candidate is None:
            return
        candidate_text = candidate.to_sdp() if hasattr(candidate, "to_sdp") else getattr(candidate, "candidate", None)
        if not candidate_text:
            return
        self._post_webrtc_ice(self.active_webrtc_session_id, {
            "candidate": candidate_text,
            "sdpMid": getattr(candidate, "sdpMid", None),
            "sdpMLineIndex": getattr(candidate, "sdpMLineIndex", None),
        })

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

    def _send_webrtc_stats(self):
        if not self.active_webrtc_session_id:
            return
        source_stats = self.frame_buffer.stats()
        track = self.aiortc_track or self.webrtc_track
        track_stats = track.stats()
        self._send_json({
            "type": "webrtc_stats",
            "session_id": self.active_webrtc_session_id,
            "source_fps": source_stats.get("source_fps", 0.0),
            "sent_fps": track_stats.get("sent_fps", 0.0),
            "stale_frames": track_stats.get("stale_frames", 0),
            "peer_connection_state": getattr(self.webrtc_peer, "connectionState", None),
            "ice_connection_state": getattr(self.webrtc_peer, "iceConnectionState", None),
            "ice_gathering_state": getattr(self.webrtc_peer, "iceGatheringState", None),
        })

    def _send_heartbeat(self):
        self._send_json({"type": "heartbeat"})

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
            now = time.time()
            if self.connected and now - self.last_heartbeat >= 3.0:
                self.last_heartbeat = now
                self._send_heartbeat()
            if now - self.last_webrtc_stats >= 1.0:
                self.last_webrtc_stats = now
                self._send_webrtc_stats()
            aiortc_sent_frames = getattr(self.aiortc_track, "sent_frames", 0)
            if (RTCPeerConnection is None or av is None or aiortc_sent_frames == 0) and self.connected and now - self.last_frame > 0.05:
                self.last_frame = now
                try:
                    self._send_frame(img_arr, num_records, mode, recording)
                except Exception as e:
                    logger.debug(f"发送降级帧失败: {e}")
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
