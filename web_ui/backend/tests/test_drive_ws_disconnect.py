"""
Tests for drive WebSocket robust disconnect handling.

验证客户端在连接建立后、消息接收前断开时，后端不会抛出未捕获的
RuntimeError，而是能正确清理 client_ws 状态。
"""

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

pytestmark = pytest.mark.anyio

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client():
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)
    app = FastAPI()
    app.include_router(drive.router, prefix="/api/drive")
    return TestClient(app), drive


async def test_drive_ws_client_handles_runtime_error_after_disconnect():
    """
    模拟客户端 WebSocket 在 accept 后、receive_text 前断开连接。
    Starlette 内部状态可能变为 DISCONNECTED，receive_text() 抛出 RuntimeError。
    期望 drive_ws 能捕获该异常并正确清理 client_ws。
    """
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)

    mock_ws = AsyncMock(spec=WebSocket)
    # accept 成功
    mock_ws.accept = AsyncMock()
    # 第一次 send_text 成功（初始状态推送）
    mock_ws.send_text = AsyncMock()
    # receive_text 模拟断开后的 RuntimeError
    mock_ws.receive_text = AsyncMock(
        side_effect=RuntimeError('WebSocket is not connected. Need to call "accept" first.')
    )

    # 调用 drive_ws，role=client
    await drive.drive_ws(mock_ws, role="client", client_id="browser-test")

    # 验证 client_ws 被清理
    assert "browser-test" not in drive.drive_state.client_ws


async def test_drive_ws_client_handles_websocket_disconnect():
    """
    模拟客户端正常 WebSocketDisconnect。
    """
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)

    mock_ws = AsyncMock(spec=WebSocket)
    mock_ws.accept = AsyncMock()
    mock_ws.send_text = AsyncMock()
    mock_ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

    await drive.drive_ws(mock_ws, role="client", client_id="browser-test")

    assert "browser-test" not in drive.drive_state.client_ws


def test_drive_ws_client_disconnect_via_testclient():
    """
    通过 TestClient 连接 WebSocket 后立即关闭，验证后端不抛异常。
    """
    client, drive = make_client()

    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-tc") as ws:
        # 连接后立即关闭，模拟页面刷新或网络断开
        pass

    # 后端应已清理该客户端
    assert "browser-tc" not in drive.drive_state.client_ws
