"""
Drive API Router - 实车驾驶控制、摄像头回传、参数管理
"""
import os
import io
import asyncio
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ------------------------------------------------------------------
# 全局状态
# ------------------------------------------------------------------
class DriveState:
    """车端全局状态缓存，所有客户端共享"""

    def __init__(self):
        # 控制量（客户端 -> 车端）
        self.angle: float = 0.0
        self.throttle: float = 0.0
        self.drive_mode: str = "user"
        self.recording: bool = False
        self.buttons: Dict[str, bool] = {}

        # 车端状态（车端 -> 客户端）
        self.num_records: int = 0
        self.last_frame_timestamp: float = 0.0
        self.last_frame: Optional[bytes] = None  # JPEG 二进制帧缓存

        # 心跳
        self.car_last_seen: Optional[datetime] = None

        # 连接管理
        self.car_ws: Optional[WebSocket] = None
        self.client_ws: List[WebSocket] = []

    async def broadcast_to_clients(self, data: dict):
        """向所有已连接的客户端广播消息"""
        payload = json.dumps(data)
        dead: List[WebSocket] = []
        for ws in self.client_ws:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.client_ws.remove(ws)

    async def send_to_car(self, data: dict):
        """向车端发送控制指令"""
        if self.car_ws is None:
            return False
        try:
            await self.car_ws.send_text(json.dumps(data))
            return True
        except Exception:
            self.car_ws = None
            return False

    def car_online(self) -> bool:
        """车端是否在线（心跳超时 5 秒视为离线）"""
        if self.car_last_seen is None:
            return False
        return datetime.now() - self.car_last_seen < timedelta(seconds=5)


drive_state = DriveState()


# ------------------------------------------------------------------
# Pydantic 模型
# ------------------------------------------------------------------
class DriveParams(BaseModel):
    pid: Dict[str, float]
    recenterRate: float
    steerRate: float
    accelRate: float
    brakeRate: float


class SaveParamsRequest(BaseModel):
    params: DriveParams


# ------------------------------------------------------------------
# 参数持久化
# ------------------------------------------------------------------
def _get_params_path() -> Path:
    config_dir = Path(os.path.expanduser("~/mycar/"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "drive_params.json"


DEFAULT_PARAMS = {
    "pid": {"kp": 0.8, "ki": 0.0, "kd": 0.05},
    "recenterRate": 0.35,
    "steerRate": 1.2,
    "accelRate": 1.0,
    "brakeRate": 1.2,
}


# ------------------------------------------------------------------
# 参数 HTTP 接口
# ------------------------------------------------------------------
@router.get("/params")
async def get_params():
    """加载驾驶参数，文件不存在则返回默认值"""
    path = _get_params_path()
    if not path.exists():
        return {"success": True, "params": DEFAULT_PARAMS, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return {"success": True, "params": data.get("params", DEFAULT_PARAMS), "timestamp": data.get("timestamp")}
    except Exception as e:
        logger.warning(f"加载参数失败，回退默认值: {e}")
        return {"success": True, "params": DEFAULT_PARAMS, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}


@router.post("/params")
async def save_params(request: SaveParamsRequest):
    """保存驾驶参数到磁盘"""
    path = _get_params_path()
    try:
        data = {
            "version": "2.0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "params": request.params.dict(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return {"success": True, "message": "Parameters saved", "timestamp": data["timestamp"]}
    except Exception as e:
        logger.error(f"保存参数失败: {e}")
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")


class LoadModelRequest(BaseModel):
    model_path: str
    working_dir: Optional[str] = None


@router.post("/load_model")
async def load_model(request: LoadModelRequest):
    """通知车端加载指定模型"""
    if not drive_state.car_online():
        raise HTTPException(status_code=400, detail="车端未连接，无法加载模型")

    ok = await drive_state.send_to_car({
        "type": "load_model",
        "model_path": request.model_path,
    })
    if not ok:
        raise HTTPException(status_code=500, detail="发送到车端失败")
    return {"success": True, "message": "模型加载指令已下发"}


class CalibrateRequest(BaseModel):
    STEERING_LEFT_PWM: Optional[int] = None
    STEERING_RIGHT_PWM: Optional[int] = None
    THROTTLE_FORWARD_PWM: Optional[int] = None
    THROTTLE_STOPPED_PWM: Optional[int] = None
    THROTTLE_REVERSE_PWM: Optional[int] = None
    save: Optional[bool] = False


@router.post("/calibrate")
async def calibrate(request: CalibrateRequest):
    """下发校准参数到车端，可选保存到配置"""
    if not drive_state.car_online():
        raise HTTPException(status_code=400, detail="车端未连接，无法校准")

    payload = {"type": "calibrate", **request.dict(exclude_none=True)}
    ok = await drive_state.send_to_car(payload)
    if not ok:
        raise HTTPException(status_code=500, detail="发送到车端失败")
    return {"success": True, "message": "校准参数已下发"}


# ------------------------------------------------------------------
# WebSocket 主通道
# ------------------------------------------------------------------
@router.websocket("/ws")
async def drive_ws(websocket: WebSocket, role: str = Query("client", description="连接角色: car 或 client")):
    await websocket.accept()

    if role == "car":
        # 车端连接
        if drive_state.car_ws is not None:
            try:
                await drive_state.car_ws.close()
            except Exception:
                pass
        drive_state.car_ws = websocket
        drive_state.car_last_seen = datetime.now()
        logger.info("车端连接建立")

        # 立即推送给所有客户端车端上线状态
        await drive_state.broadcast_to_clients({
            "type": "car_connection",
            "online": True,
        })

        try:
            while True:
                raw = await websocket.receive_text()
                drive_state.car_last_seen = datetime.now()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # 处理车端心跳
                if msg.get("type") == "heartbeat":
                    continue

                # 处理车端发来的图像帧 (base64)
                if msg.get("type") == "frame" and msg.get("data"):
                    import base64
                    try:
                        frame_bytes = base64.b64decode(msg["data"])
                        drive_state.last_frame = frame_bytes
                        drive_state.last_frame_timestamp = time.time()
                    except Exception as e:
                        logger.warning(f"解码帧失败: {e}")
                    continue

                # 处理车端状态更新（录制条数、模式等）
                if "num_records" in msg:
                    drive_state.num_records = int(msg["num_records"])
                if "drive_mode" in msg:
                    drive_state.drive_mode = msg["drive_mode"]
                if "recording" in msg:
                    drive_state.recording = bool(msg["recording"])

                # 车端状态变更广播给所有客户端
                await drive_state.broadcast_to_clients({
                    "type": "car_state",
                    "drive_mode": drive_state.drive_mode,
                    "recording": drive_state.recording,
                    "num_records": drive_state.num_records,
                })
        except WebSocketDisconnect:
            logger.info("车端连接断开")
            drive_state.car_ws = None
            await drive_state.broadcast_to_clients({
                "type": "car_connection",
                "online": False,
            })

    else:
        # 客户端连接（浏览器）
        drive_state.client_ws.append(websocket)
        logger.info(f"新客户端连接，当前在线: {len(drive_state.client_ws)}")

        # 推送初始状态
        try:
            await websocket.send_text(json.dumps({
                "type": "car_connection",
                "online": drive_state.car_online(),
            }))
            await websocket.send_text(json.dumps({
                "type": "car_state",
                "drive_mode": drive_state.drive_mode,
                "recording": drive_state.recording,
                "num_records": drive_state.num_records,
            }))
        except Exception:
            pass

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # 心跳回执
                if msg.get("type") == "heartbeat":
                    continue

                # 客户端发来的控制指令，转发给车端
                control_fields = ["angle", "throttle", "drive_mode", "recording", "buttons"]
                if any(k in msg for k in control_fields):
                    if "angle" in msg:
                        drive_state.angle = float(msg["angle"])
                    if "throttle" in msg:
                        drive_state.throttle = float(msg["throttle"])
                    if "drive_mode" in msg:
                        drive_state.drive_mode = msg["drive_mode"]
                    if "recording" in msg:
                        drive_state.recording = bool(msg["recording"])
                    if "buttons" in msg:
                        drive_state.buttons.update(msg["buttons"])

                    # 转发给车端
                    await drive_state.send_to_car(msg)

                    # 同步给其他所有客户端（多端状态一致）
                    await drive_state.broadcast_to_clients({
                        "type": "car_state",
                        "drive_mode": drive_state.drive_mode,
                        "recording": drive_state.recording,
                        "num_records": drive_state.num_records,
                    })
        except WebSocketDisconnect:
            if websocket in drive_state.client_ws:
                drive_state.client_ws.remove(websocket)
            logger.info(f"客户端断开，当前在线: {len(drive_state.client_ws)}")


# ------------------------------------------------------------------
# MJPEG 视频流
# ------------------------------------------------------------------
async def _frame_generator():
    """帧生成器，逐帧输出 multipart 分片"""
    boundary = b"--donkeyframe"
    last_sent_ts = 0.0
    min_interval = 1.0 / 25.0  # 最高 25fps 发送

    while True:
        if drive_state.last_frame is None or not drive_state.car_online():
            # 无帧时输出占位符（后续替换为默认占位图）
            await asyncio.sleep(0.1)
            continue

        now = time.time()
        if now - last_sent_ts < min_interval:
            await asyncio.sleep(min_interval / 2)
            continue

        frame = drive_state.last_frame
        last_sent_ts = now
        yield (
            boundary + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
            + frame + b"\r\n"
        )


@router.get("/video")
async def video_stream():
    """MJPEG 流媒体接口，浏览器 <img src> 直接渲染"""
    return StreamingResponse(
        _frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=--donkeyframe",
    )
