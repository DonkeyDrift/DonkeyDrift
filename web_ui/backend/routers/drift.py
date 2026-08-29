# -*- coding: utf-8 -*-
"""第三视角漂移 API（RFC 第 4/8 节）。

- GET  /state              状态快照（会话、β、事件、配置）
- POST /session/start      {mode: calibrate|record|auto [, tub_path]}
- POST /session/stop       结束当前模式（AUTO 停止时下发 MODE 0 + 零油门）
- POST /config             更新控制器参数（白名单数值项）
- GET  /frame.jpg          俯拍快照（无相机时 503）

与 drive 通路的衔接（进程内，不新开链路）：
- 遥测：drive_state.telemetry_hooks → drift_engine.ingest_telemetry_msg
- 控制：drift_engine.send_sink → drive_state.send_to_car（与浏览器客户端同构）
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from drift_engine import drift_engine

router = APIRouter()


class SessionStartRequest(BaseModel):
    mode: str = Field(..., description="calibrate | record | auto")
    tub_path: Optional[str] = None


@router.get("/state")
async def drift_state():
    return drift_engine.snapshot()


@router.post("/session/start")
async def session_start(request: SessionStartRequest):
    try:
        drift_engine.start(request.mode, tub_path=request.tub_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "state": drift_engine.session.state.value}


@router.post("/session/stop")
async def session_stop():
    try:
        drift_engine.stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "state": drift_engine.session.state.value}


@router.post("/config")
async def update_config(request: dict):
    try:
        drift_engine.update_config(request)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "config": drift_engine.snapshot()["config"]}


@router.get("/frame.jpg")
async def overhead_frame():
    frame = drift_engine.last_preview_jpeg
    if frame is None:
        raise HTTPException(status_code=503, detail="俯拍相机未就绪")
    return Response(content=frame, media_type="image/jpeg")


def install_drive_hooks() -> None:
    """进程内接线：把引擎挂到 drive 通路上（main.py 启动时调用一次）。"""
    import routers.drive as drive_mod

    loop = asyncio.get_event_loop()

    def _send_sink(msg: dict) -> None:
        asyncio.run_coroutine_threadsafe(drive_mod.drive_state.send_to_car(msg), loop)

    drift_engine.send_sink = _send_sink

    def _telemetry_hook(msg: dict) -> None:
        drift_engine.ingest_telemetry_msg(msg)

    drive_mod.drive_state.telemetry_hooks.append(_telemetry_hook)
