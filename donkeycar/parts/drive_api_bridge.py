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
from threading import Thread
from typing import Dict, Optional

try:
    import cv2
except Exception:  # pragma: no cover - 运行环境缺少 OpenCV 时只影响图像上传
    cv2 = None

try:
    import websockets
except Exception:  # pragma: no cover - 运行环境缺少 websockets 时由连接线程记录错误
    websockets = None

logger = logging.getLogger(__name__)


class DriveApiBridge:
    """车端 WebSocket 桥接 Part。"""

    def __init__(self, server_url: str = "ws://localhost:8000/api/drive/ws",
                 role: str = "car", reconnect_interval: float = 3.0,
                 auto_start: bool = True):
        self.server_url = self._with_role(server_url, role)
        self.reconnect_interval = reconnect_interval

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

        if auto_start:
            self.start()

    @staticmethod
    def _with_role(server_url: str, role: str) -> str:
        separator = "&" if "?" in server_url else "?"
        return f"{server_url}{separator}role={role}"

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

    def _send_frame(self, img_arr, num_records=0, mode=None, recording=None):
        if cv2 is None:
            return
        ok, encoded = cv2.imencode(".jpg", img_arr)
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
        if self.loop and self.ws:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
            except Exception:
                pass
        logger.info("DriveApiBridge 已停止")
