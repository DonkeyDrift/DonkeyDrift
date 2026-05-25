"""
Drive API Router - 实车驾驶控制、摄像头回传、参数管理
"""
import os
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
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

        # 连接管理
        self.car_ws: Optional[WebSocket] = None
        self.client_ws: List[WebSocket] = []


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


# ------------------------------------------------------------------
# WebSocket 主通道（M2 实现，预留位置）
# ------------------------------------------------------------------
@router.websocket("/ws")
async def drive_ws(websocket: WebSocket, role: str = Query("client", description="连接角色: car 或 client")):
    await websocket.accept()
    # M2: 完整实现连接管理、消息广播、心跳检测
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


# ------------------------------------------------------------------
# MJPEG 视频流（M2 实现，预留位置）
# ------------------------------------------------------------------
@router.get("/video")
async def video_stream():
    # M2: 实现 multipart MJPEG 输出
    raise HTTPException(status_code=501, detail="Video stream not implemented yet")
