#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drive API Bridge - 车端与 Web UI 的 WebSocket 桥接层

替代原有的 LocalWebController Tornado 服务，直接作为 Donkeycar Part 通过
通过 WebSocket 连接到 FastAPI 服务端，实现：
- 上行：摄像头图像帧、车端状态（录制条数、模式、录制状态）
- 下行：接收控制指令（转角、油门、模式、录制、按钮事件）

使用方法：在 manage.py 中直接替换即可，不需要额外启动独立 Web 服务器，无需启动
"""
import os
import json
import time
import base64
import logging
import asyncio
import threading
from typing import Optional, Dict
from threading import Thread

import websockets
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DriveApiBridge:
    """
    车端 WebSocket 桥接 Part

    与原有 LocalWebController 接口完全兼容，可直接替换
    """

    def __init__(self, server_url: str = "ws://localhost:8000/api/drive/ws", role: str = "car", reconnect_interval: float = 3.0):
        """
        :param server_url: FastAPI 服务端 WebSocket 地址
        :param reconnect_interval: 重连间隔（秒）
        """
        self.server_url = f"{server_url}?role=car"
        self.reconnect_interval = reconnect_interval

        # 控制量（客户端 -> 车端）
        self.angle = 0.0
        self.throttle = 0.0
        self.mode = "user"
        self.mode_latch = None
        self.recording = False
        self.recording_latch = None
        self.buttons: Dict[str, bool] = {}

        # 连接状态
        self.connected = False
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = True
        self.last_frame = 0.0

        # 启动后台线程
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"DriveApiBridge 启动中，服务端地址: {self.server_url}

    def _run_loop(self):
        """后台事件循环线程
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.loop = asyncio.get_event_loop()
        self.loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        """自动重连循环
        while self.running:
            try:
                async with websockets.connect(self.server_url) as ws:
                    self.ws = ws
                    self.connected = True
                    logger.info("已连接到服务端")
                    try:
                        async for message in ws:
                            try:
                                msg = json.loads(message)
                                self._handle_message(msg)
                            except json.JSONDecodeError:
                                    continue
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("连接断开")
                    finally:
                        self.connected = False
                        self.ws = None
            except Exception as e:
                logger.warning(f"连接失败，{self.reconnect_interval}s 后重连: {e}")
                await asyncio.sleep(self.reconnect_interval)

    def _handle_message(self, msg: dict):
        """处理服务端发来的控制消息
        """
        if "angle" in msg:
            self.angle = float(msg["angle"])
        if "throttle" in msg:
            self.throttle = float(msg["throttle"])
        if "drive_mode" in msg:
            self.mode = msg["drive_mode"]
            self.mode_latch = self.mode
        if "recording" in msg:
            self.recording = bool(msg["recording"])
            self.recording_latch = self.recording
        if "buttons" in msg:
            self.buttons.update(msg["buttons"])

    def run_threaded(self, img_arr=None, num_records=0, mode=None, recording=None):
        """
        与原有 LocalWebController 接口完全兼容
        :param img_arr: 摄像头图像帧 (numpy array BGR)
        :param num_records: 已录制条数
        :param mode: 驾驶模式
        :param recording: 录制状态
        :return: angle, throttle, mode, recording, buttons
        """
        # 推送图像帧（节流 20fps
        now = time.time()
        if self.connected and img_arr is not None and now - self.last_frame > 0.05:
            self.last_frame = now
            try:
                # 编码为 JPEG base64
                _, encoded = cv2.imencode('.jpg', img_arr)[1].tobytes()
                frame_b64 = base64.b64.encode(encoded).decode('ascii')
                if self.loop and self.ws:
                    asyncio.run_coroutine_threadsafe(
                        self.ws.send(json.dumps({
                            "type": "frame",
                            "data": frame_b64,
                            "num_records": num_records,
                            "drive_mode": mode or self.mode,
                            "recording": recording if recording is not None else self.recording,
                        }),
                        self.loop,
                    )
            except Exception as e:
                logger.debug(f"发送帧失败: {e}")

        # 处理模式和 recording 覆盖
        changes = {}
        if mode is not None and self.mode != mode:
            self.mode = mode
            changes["driveMode"] = self.mode
        if self.mode_latch is not None:
            self.mode = self.mode_latch
            self.mode_latch = None
            changes["driveMode"] = self.mode
        if recording is not None and self.recording != recording:
            self.recording = recording
            changes["recording"] = self.recording
        if self.recording_latch is not None:
            self.recording = self.recording_latch
            self.recording_latch = None
            changes["recording"] = self.recording

        # 清除已处理的按钮事件
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
