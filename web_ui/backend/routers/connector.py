import asyncio
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from connector_engine import connector_job_manager
from network_utils import get_local_ips, discover_hosts
from remote_car_client import ConnectorConfig, RemoteCarClient, validate_remote_path


router = APIRouter()


class ConnectorConfigPayload(BaseModel):
    host: str = ""
    user: str = "pi"
    port: int = Field(default=22, ge=1, le=65535)
    car_dir: str = "~/mycar"
    key_path: Optional[str] = None
    # 自动同步 Tub 数据：连接建立后自动增量拉取车端数据
    auto_sync: bool = False
    auto_sync_tub: str = "data"
    auto_sync_local_path: str = "./data"
    # 最近一次自动同步结果（由后端自动写入）
    last_sync_at: Optional[str] = None
    last_sync_result: Optional[str] = None


class PullTubRequest(BaseModel):
    remote_tub: str
    local_data_path: str = "./data"
    create_new_dir: bool = False
    car_dir: Optional[str] = None


class PushPilotsRequest(BaseModel):
    local_models_path: str = "./models"
    formats: list[str] = Field(default_factory=list)
    car_dir: Optional[str] = None


class ListRemoteRequest(BaseModel):
    path: Optional[str] = None


class DriveStartRequest(BaseModel):
    model_type: Optional[str] = None
    pilot: Optional[str] = None
    bridge_server_url: Optional[str] = None
    car_dir: Optional[str] = None


class DriveStopRequest(BaseModel):
    pid: Optional[int] = None
    car_dir: Optional[str] = None


def _get_config_path() -> Path:
    return Path(os.path.expanduser("~/.donkeycar_web_connector.json"))


def _default_config() -> ConnectorConfigPayload:
    return ConnectorConfigPayload()


def _load_payload() -> ConnectorConfigPayload:
    path = _get_config_path()
    if not path.exists():
        return _default_config()
    try:
        with open(path, "r", encoding="utf-8") as file:
            return ConnectorConfigPayload(**json.load(file))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Connector 配置文件无效: {exc}") from exc


def _payload_data(payload: ConnectorConfigPayload) -> dict:
    return payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()


def _save_payload(payload: ConnectorConfigPayload) -> None:
    path = _get_config_path()
    with open(path, "w", encoding="utf-8") as file:
        json.dump(_payload_data(payload), file, indent=2, ensure_ascii=False)


def _to_config(payload: ConnectorConfigPayload, car_dir: Optional[str] = None) -> ConnectorConfig:
    if not payload.host.strip():
        raise HTTPException(status_code=400, detail="请先配置车端主机地址")
    directory = car_dir or payload.car_dir
    try:
        validate_remote_path(directory)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConnectorConfig(
        host=payload.host.strip(),
        user=payload.user.strip(),
        port=payload.port,
        car_dir=directory,
        key_path=payload.key_path,
    )


def _auto_sync_key(config: ConnectorConfig) -> str:
    """自动同步防抖 key：同一 SSH 目标 + 车端目录视为同一连接。"""
    return f"{config.user}@{config.host}:{config.port}:{config.car_dir}"


def _record_last_sync(job) -> None:
    """自动同步结束后把 last_sync_at/last_sync_result 写回连接器配置（沿用现有持久化）。"""
    try:
        payload = _load_payload()
    except HTTPException:
        return
    payload.last_sync_at = datetime.now().isoformat()
    if job.status == "completed":
        stats = job.transfer_stats or {}
        payload.last_sync_result = (
            f"同步成功：已传输 {stats.get('transferred_files', 0)}/{stats.get('total_files', 0)} 个文件，"
            f"{stats.get('transferred_bytes', 0)}/{stats.get('total_size', 0)} 字节"
        )
    elif job.status == "stopped":
        payload.last_sync_result = "同步已停止"
    else:
        payload.last_sync_result = f"同步失败：{job.error_message or '未知错误'}"
    _save_payload(payload)


@router.get("/config")
async def get_config():
    return {"config": _payload_data(_load_payload())}


@router.post("/config")
async def set_config(payload: ConnectorConfigPayload):
    try:
        validate_remote_path(payload.car_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_payload(payload)
    return {"config": _payload_data(payload)}


class AutoSyncRequest(BaseModel):
    enabled: bool


@router.post("/auto_sync")
async def set_auto_sync(request: AutoSyncRequest):
    """读取/设置自动同步开关（其余自动同步参数随 /config 保存）。"""
    payload = _load_payload()
    payload.auto_sync = request.enabled
    _save_payload(payload)
    return {
        "auto_sync": {"enabled": payload.auto_sync},
        "last_sync": {"at": payload.last_sync_at, "result": payload.last_sync_result},
    }


@router.post("/status")
async def check_status():
    payload = _load_payload()
    config = _to_config(payload)
    online, message = RemoteCarClient(config).check_connection()
    auto_sync_triggered = False
    # 连接测试成功且开启自动同步且当前无 pull 任务在跑 → 自动入队增量同步（防抖：同一连接不重复触发）
    if online and payload.auto_sync:
        key = _auto_sync_key(config)
        if connector_job_manager.try_begin_auto_sync(key):
            auto_sync_triggered = True
            asyncio.create_task(
                connector_job_manager.run_auto_sync(
                    key,
                    config,
                    payload.auto_sync_tub,
                    payload.auto_sync_local_path,
                    on_finished=_record_last_sync,
                )
            )
    return {
        "online": online,
        "message": message,
        "auto_sync": {"enabled": payload.auto_sync, "triggered": auto_sync_triggered},
        "last_sync": {"at": payload.last_sync_at, "result": payload.last_sync_result},
    }


@router.post("/remote/list")
async def list_remote(request: ListRemoteRequest):
    payload = _load_payload()
    config = _to_config(payload)
    path = request.path or payload.car_dir
    try:
        items = RemoteCarClient(config).list_remote_dir(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items}


@router.get("/remote/tubs")
async def list_tubs():
    config = _to_config(_load_payload())
    try:
        return {"items": RemoteCarClient(config).list_tubs()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/remote/models")
async def list_models():
    config = _to_config(_load_payload())
    try:
        return {"items": RemoteCarClient(config).list_models()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tub/pull")
async def pull_tub(request: PullTubRequest):
    config = _to_config(_load_payload(), request.car_dir)
    job = connector_job_manager.create_job("pull_tub")
    asyncio.create_task(
        connector_job_manager.run_pull_tub(
            job,
            config,
            request.remote_tub,
            request.local_data_path,
            request.create_new_dir,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/pilots/push")
async def push_pilots(request: PushPilotsRequest):
    config = _to_config(_load_payload(), request.car_dir)
    job = connector_job_manager.create_job("push_pilots")
    asyncio.create_task(
        connector_job_manager.run_push_pilots(
            job,
            config,
            request.local_models_path,
            request.formats,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/drive/start")
async def start_drive(request: DriveStartRequest):
    config = _to_config(_load_payload(), request.car_dir)
    job = connector_job_manager.create_job("drive_start")
    asyncio.create_task(
        connector_job_manager.run_drive_start(
            job,
            config,
            request.model_type,
            request.pilot,
            request.bridge_server_url,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/drive/stop")
async def stop_drive(request: DriveStopRequest):
    config = _to_config(_load_payload(), request.car_dir)
    job = connector_job_manager.create_job("drive_stop")
    asyncio.create_task(connector_job_manager.run_drive_stop(job, config, request.pid))
    return {"job_id": job.id, "status": job.status}


@router.get("/drive/status")
async def get_drive_status():
    return {"pid": connector_job_manager.drive_pid}


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    job = connector_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs[-200:],
        "error": job.error_message,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    await connector_job_manager.stop_job(job_id)
    return {"status": True}


@router.get("/jobs/{job_id}/events")
async def stream_job_events(job_id: str):
    job = connector_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_stream():
        while True:
            message = await job.log_queue.get()
            yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
            if message.get("type") == "status" and message.get("status") in {"completed", "failed", "stopped"}:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/local_ips")
async def list_local_ips():
    """返回本机可用于局域网通信的 IPv4 地址列表（优先 RFC1918 私有地址）。"""
    ips = get_local_ips()
    return {"ips": ips, "count": len(ips)}


async def _check_drifter_console(ip: str) -> dict | None:
    try:
        def _fetch():
            req = urllib.request.Request(f"http://{ip}/", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                html = resp.read(4096).decode("utf-8", errors="ignore")
                return "Drifter Console" in html
        is_console = await asyncio.to_thread(_fetch)
        if is_console:
            return {"ip": ip, "port": 80, "reachable": True}
    except Exception:
        pass
    return None


@router.post("/discover_console")
async def discover_consoles():
    try:
        found, scanned = await discover_hosts(port=80)
        tasks = [_check_drifter_console(h["ip"]) for h in found]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        consoles = [r for r in results if isinstance(r, dict)]
        message = ""
        if not consoles:
            message = f"扫描了 {scanned} 个地址，未在局域网中发现 Drifter Console 设备。请确认 ESP32 已开机并与本机处于同一网络。"
        else:
            message = f"发现 {len(consoles)} 个 Drifter Console 设备。"
        return {"status": True, "found": consoles, "count": len(consoles), "scanned": scanned, "message": message}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
