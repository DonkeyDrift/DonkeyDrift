"""
Drive API Router - 实车驾驶控制、摄像头回传、参数管理
"""
import os
import io
import asyncio
import time
import json
import logging
import uuid
from collections import deque
from pathlib import Path
from typing import Optional, List, Dict, Literal, Any
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
        self.frame_timestamps = deque(maxlen=120)

        # 心跳
        self.car_last_seen: Optional[datetime] = None

        # WebRTC 信令状态
        self.webrtc_session: Optional[dict] = None
        self.webrtc_stats = {
            "source_fps": 0.0,
            "sent_fps": 0.0,
            "browser_fps": 0.0,
            "browser_p95_frame_interval_ms": 0.0,
            "inbound_fps": 0.0,
            "frames_dropped": 0,
            "jitter_ms": 0.0,
            "jitter_buffer_delay_ms": 0.0,
            "disconnect_count": 0,
            "stale_frames": 0,
            "peer_connection_state": None,
            "ice_connection_state": None,
            "ice_gathering_state": None,
            "local_description_error": None,
            "local_description_elapsed_ms": None,
            "answer_sent_elapsed_ms": None,
            "local_candidates_sent": 0,
            "offer_to_answer_elapsed_ms": None,
            "last_offer_at": None,
            "last_answer_at": None,
            "last_client_ice_at": None,
            "last_car_ice_at": None,
            "degraded": False,
        }

        # 连接管理
        self.car_ws: Optional[WebSocket] = None
        self.client_ws: Dict[str, WebSocket] = {}

    async def broadcast_to_clients(self, data: dict):
        """向所有已连接的客户端广播消息，失败时关闭并清理失效连接。"""
        payload = json.dumps(data)
        dead: List[str] = []
        for client_id, ws in list(self.client_ws.items()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(client_id)
                try:
                    await ws.close()
                except Exception:
                    pass
        for client_id in dead:
            self.client_ws.pop(client_id, None)

    async def send_to_client(self, client_id: str, data: dict):
        """向指定浏览器客户端发送信令。"""
        ws = self.client_ws.get(client_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(data))
            return True
        except Exception:
            self.client_ws.pop(client_id, None)
            return False

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

    def video_fps(self) -> int:
        """根据最近帧时间戳估算视频 FPS。"""
        if len(self.frame_timestamps) < 2:
            return 0
        elapsed = self.frame_timestamps[-1] - self.frame_timestamps[0]
        if elapsed <= 0:
            return 0
        return round((len(self.frame_timestamps) - 1) / elapsed)

    def apply_car_webrtc_stats(self, data: dict):
        """应用车端上报的 WebRTC 视频统计。"""
        session = self.webrtc_session
        if not session or data.get("session_id") != session.get("session_id"):
            return
        for key in (
            "source_fps",
            "sent_fps",
            "stale_frames",
            "peer_connection_state",
            "ice_connection_state",
            "ice_gathering_state",
            "local_description_error",
            "local_description_elapsed_ms",
            "answer_sent_elapsed_ms",
            "local_candidates_sent",
        ):
            if key in data:
                self.webrtc_stats[key] = data[key]


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


class WebRtcSessionRequest(BaseModel):
    client_id: str


class WebRtcSessionDescription(BaseModel):
    session_id: str
    sdp: str
    type: Literal["offer", "answer"]


class WebRtcIceRequest(BaseModel):
    session_id: str
    source: Literal["client", "car"]
    candidate: Dict[str, Any]


class WebRtcBrowserStatsRequest(BaseModel):
    session_id: str
    browser_fps: float
    browser_p95_frame_interval_ms: float
    inbound_fps: Optional[float] = None
    frames_dropped: Optional[int] = None
    jitter_ms: Optional[float] = None
    jitter_buffer_delay_ms: Optional[float] = None


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
# WebRTC 信令接口
# ------------------------------------------------------------------
def _require_webrtc_session(session_id: str) -> dict:
    session = drive_state.webrtc_session
    if not session or session.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="WebRTC 会话不存在或已过期")
    return session


@router.post("/webrtc/session")
async def create_webrtc_session(request: WebRtcSessionRequest):
    """创建单客户端 WebRTC 视频会话。"""
    if not drive_state.car_online():
        raise HTTPException(status_code=400, detail="车端未连接，无法创建 WebRTC 会话")

    session_id = str(uuid.uuid4())
    drive_state.webrtc_session = {
        "session_id": session_id,
        "client_id": request.client_id,
        "created_at": time.time(),
    }
    drive_state.webrtc_stats.update({
        "source_fps": 0.0,
        "sent_fps": 0.0,
        "browser_fps": 0.0,
        "browser_p95_frame_interval_ms": 0.0,
        "disconnect_count": 0,
        "stale_frames": 0,
        "peer_connection_state": None,
        "ice_connection_state": None,
        "ice_gathering_state": None,
        "local_description_error": None,
        "local_description_elapsed_ms": None,
        "answer_sent_elapsed_ms": None,
        "local_candidates_sent": 0,
        "offer_to_answer_elapsed_ms": None,
        "last_offer_at": None,
        "last_answer_at": None,
        "last_client_ice_at": None,
        "last_car_ice_at": None,
        "degraded": False,
    })
    return {"success": True, "session_id": session_id, "single_client": True}


@router.post("/webrtc/offer")
async def send_webrtc_offer(request: WebRtcSessionDescription):
    """浏览器 offer 转发给车端。"""
    _require_webrtc_session(request.session_id)
    drive_state.webrtc_stats["last_offer_at"] = time.time()
    ok = await drive_state.send_to_car({
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": request.session_id,
        "sdp": request.sdp,
        "description_type": request.type,
    })
    if not ok:
        raise HTTPException(status_code=500, detail="发送 WebRTC offer 到车端失败")
    return {"success": True}


@router.post("/webrtc/answer")
async def send_webrtc_answer(request: WebRtcSessionDescription):
    """车端 answer 转发给浏览器。"""
    session = _require_webrtc_session(request.session_id)
    drive_state.webrtc_stats["last_answer_at"] = time.time()
    last_offer_at = drive_state.webrtc_stats.get("last_offer_at")
    if last_offer_at is not None:
        drive_state.webrtc_stats["offer_to_answer_elapsed_ms"] = (
            drive_state.webrtc_stats["last_answer_at"] - last_offer_at
        ) * 1000.0
    await drive_state.send_to_client(session["client_id"], {
        "type": "webrtc_signal",
        "signal_type": "answer",
        "session_id": request.session_id,
        "sdp": request.sdp,
        "description_type": request.type,
    })
    return {"success": True}


@router.post("/webrtc/ice")
async def send_webrtc_ice(request: WebRtcIceRequest):
    """按来源转发 ICE candidate。"""
    session = _require_webrtc_session(request.session_id)
    payload = {
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": request.session_id,
        "candidate": request.candidate,
    }
    if request.source == "client":
        drive_state.webrtc_stats["last_client_ice_at"] = time.time()
        ok = await drive_state.send_to_car(payload)
        if not ok:
            raise HTTPException(status_code=500, detail="发送 ICE candidate 到车端失败")
    else:
        drive_state.webrtc_stats["last_car_ice_at"] = time.time()
        await drive_state.send_to_client(session["client_id"], payload)
    return {"success": True}


@router.post("/webrtc/browser-stats")
async def update_webrtc_browser_stats(request: WebRtcBrowserStatsRequest):
    """接收浏览器端真实渲染 FPS 与 P95 帧间隔。"""
    _require_webrtc_session(request.session_id)
    drive_state.webrtc_stats["browser_fps"] = request.browser_fps
    drive_state.webrtc_stats["browser_p95_frame_interval_ms"] = request.browser_p95_frame_interval_ms
    for key in ("inbound_fps", "frames_dropped", "jitter_ms", "jitter_buffer_delay_ms"):
        value = getattr(request, key)
        if value is not None:
            drive_state.webrtc_stats[key] = value
    return {"success": True}


@router.get("/webrtc/stats")
async def webrtc_stats():
    """返回 WebRTC 视频链路统计。"""
    session = drive_state.webrtc_session
    return {
        "active": session is not None,
        "session_id": session.get("session_id") if session else None,
        "webrtc_available": True,
        "source_fps": drive_state.webrtc_stats["source_fps"],
        "sent_fps": drive_state.webrtc_stats["sent_fps"],
        "browser_fps": drive_state.webrtc_stats["browser_fps"],
        "browser_p95_frame_interval_ms": drive_state.webrtc_stats["browser_p95_frame_interval_ms"],
        "inbound_fps": drive_state.webrtc_stats["inbound_fps"],
        "frames_dropped": drive_state.webrtc_stats["frames_dropped"],
        "jitter_ms": drive_state.webrtc_stats["jitter_ms"],
        "jitter_buffer_delay_ms": drive_state.webrtc_stats["jitter_buffer_delay_ms"],
        "disconnect_count": drive_state.webrtc_stats["disconnect_count"],
        "stale_frames": drive_state.webrtc_stats["stale_frames"],
        "peer_connection_state": drive_state.webrtc_stats["peer_connection_state"],
        "ice_connection_state": drive_state.webrtc_stats["ice_connection_state"],
        "ice_gathering_state": drive_state.webrtc_stats["ice_gathering_state"],
        "local_description_error": drive_state.webrtc_stats["local_description_error"],
        "local_description_elapsed_ms": drive_state.webrtc_stats["local_description_elapsed_ms"],
        "answer_sent_elapsed_ms": drive_state.webrtc_stats["answer_sent_elapsed_ms"],
        "local_candidates_sent": drive_state.webrtc_stats["local_candidates_sent"],
        "offer_to_answer_elapsed_ms": drive_state.webrtc_stats["offer_to_answer_elapsed_ms"],
        "last_offer_at": drive_state.webrtc_stats["last_offer_at"],
        "last_answer_at": drive_state.webrtc_stats["last_answer_at"],
        "last_client_ice_at": drive_state.webrtc_stats["last_client_ice_at"],
        "last_car_ice_at": drive_state.webrtc_stats["last_car_ice_at"],
        "transport": "webrtc",
        "degraded": drive_state.webrtc_stats["degraded"],
    }


# ------------------------------------------------------------------
# WebSocket 主通道
# ------------------------------------------------------------------
@router.websocket("/ws")
async def drive_ws(
    websocket: WebSocket,
    role: str = Query("client", description="连接角色: car 或 client"),
    client_id: Optional[str] = Query(None, description="浏览器客户端标识"),
):
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

                # 处理车端 WebRTC 视频统计
                if msg.get("type") == "webrtc_stats":
                    drive_state.apply_car_webrtc_stats(msg)
                    continue

                # 车端状态更新（录制条数、模式等）可能随任意消息携带，优先提取
                state_changed = False
                if msg.get("num_records") is not None:
                    new_num_records = int(msg["num_records"])
                    if new_num_records != drive_state.num_records:
                        drive_state.num_records = new_num_records
                        state_changed = True
                if msg.get("drive_mode") is not None:
                    new_drive_mode = msg["drive_mode"]
                    if new_drive_mode != drive_state.drive_mode:
                        drive_state.drive_mode = new_drive_mode
                        state_changed = True
                if msg.get("recording") is not None:
                    new_recording = bool(msg["recording"])
                    if new_recording != drive_state.recording:
                        drive_state.recording = new_recording
                        state_changed = True

                # 处理车端发来的图像帧 (base64)
                if msg.get("type") == "frame" and msg.get("data"):
                    import base64
                    try:
                        frame_bytes = base64.b64decode(msg["data"])
                        drive_state.last_frame = frame_bytes
                        drive_state.last_frame_timestamp = time.time()
                        drive_state.frame_timestamps.append(drive_state.last_frame_timestamp)
                    except Exception as e:
                        logger.warning(f"解码帧失败: {e}")

                # 车端状态变更广播给所有客户端
                if state_changed:
                    await drive_state.broadcast_to_clients({
                        "type": "car_state",
                        "drive_mode": drive_state.drive_mode,
                        "recording": drive_state.recording,
                        "num_records": drive_state.num_records,
                    })
        except (WebSocketDisconnect, RuntimeError):
            logger.info("车端连接断开")
            drive_state.car_ws = None
            await drive_state.broadcast_to_clients({
                "type": "car_connection",
                "online": False,
            })

    else:
        # 客户端连接（浏览器）
        client_id = client_id or str(uuid.uuid4())
        old_ws = drive_state.client_ws.get(client_id)
        if old_ws is not None and old_ws is not websocket:
            try:
                await old_ws.close()
            except Exception:
                pass
        drive_state.client_ws[client_id] = websocket
        logger.info(f"新客户端连接，当前在线: {len(drive_state.client_ws)}")

        # 推送初始状态；如果发送失败说明连接已不可用，直接清理返回
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
            drive_state.client_ws.pop(client_id, None)
            logger.info(f"客户端初始状态推送失败，已清理，当前在线: {len(drive_state.client_ws)}")
            return

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
        except (WebSocketDisconnect, RuntimeError):
            if drive_state.client_ws.get(client_id) is websocket:
                drive_state.client_ws.pop(client_id, None)
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


@router.get("/stats")
async def drive_stats():
    """返回驾驶视频流统计信息。"""
    last_seen_age = None
    if drive_state.car_last_seen is not None:
        last_seen_age = (datetime.now() - drive_state.car_last_seen).total_seconds()
    return {
        "online": drive_state.car_online(),
        "fps": drive_state.video_fps(),
        "car_ws_connected": drive_state.car_ws is not None,
        "last_seen_age_sec": last_seen_age,
    }


@router.get("/video")
async def video_stream():
    """MJPEG 流媒体接口，浏览器 <img src> 直接渲染"""
    return StreamingResponse(
        _frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=--donkeyframe",
    )
