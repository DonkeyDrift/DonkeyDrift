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


class CameraStartRequest(BaseModel):
    camera_index: int = 0
    tag_id: int = 0
    calibration_file: str = Field(..., description="单应性标定文件（.npz）路径")
    width: int = 1280
    height: int = 720
    fps: int = 60
    heading_offset_deg: float = Field(
        0.0, description="贴标旋转补偿（°）：标签贴反 180° 填 180，转 90° 填 ±90")
    exposure: Optional[float] = Field(
        None, description="手动曝光（DirectShow log2 秒：-6=1/64s、-7=1/128s、"
        "-8=1/256s）；留空自动。快推丢检测（运动模糊）时压短曝光")


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


# MJPEG 预览流帧率上限（与引擎预览编码节流一致，防空转）
_MJPEG_PUSH_HZ = 15.0


@router.get("/frame.mjpg")
async def overhead_frame_mjpg():
    """俯拍预览 MJPEG 流：浏览器 <img> 直连，取代轮询换图。"""
    import asyncio

    async def _stream():
        boundary = b"--frame\r\n"
        interval = 1.0 / _MJPEG_PUSH_HZ
        while True:
            jpeg = drift_engine.last_preview_jpeg
            if jpeg is not None:
                yield (boundary
                       + b"Content-Type: image/jpeg\r\n"
                       + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                       + jpeg + b"\r\n")
            await asyncio.sleep(interval)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(_stream(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@router.post("/camera/start")
async def camera_start(request: CameraStartRequest):
    from drift_vision import AprilTagDetector, FieldHomography, USBCamera

    try:
        homography = FieldHomography.from_file(request.calibration_file)
        camera = USBCamera(index=request.camera_index, width=request.width,
                           height=request.height, fps=request.fps,
                           exposure=request.exposure)
        detector = AprilTagDetector(downscale=2)  # 半分辨率检测：720p→360p 提速约 4 倍
        drift_engine._camera = camera  # 显式持有，stop 时释放（不靠 GC）
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    drift_engine._calibration_file = request.calibration_file
    drift_engine.start_camera_loop(camera, detector, homography, request.tag_id,
                                   heading_offset_deg=request.heading_offset_deg)
    return {"ok": True}


@router.post("/camera/stop")
async def camera_stop():
    drift_engine.stop_camera_loop()
    try:
        import drift_webrtc
        await drift_webrtc.close_all()  # 预览流随相机关闭
    except ImportError:
        pass
    return {"ok": True}


@router.post("/webrtc/offer")
async def webrtc_offer(request: dict):
    """WebRTC 预览信令：浏览器 offer → answer（drift_webrtc 推 60fps 流）。"""
    try:
        import drift_webrtc
        return await drift_webrtc.handle_offer(
            request.get("sdp", ""), request.get("type", "offer"),
            lambda: drift_engine.display_frame)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"aiortc 未安装: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"WebRTC 协商失败: {exc}")


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
