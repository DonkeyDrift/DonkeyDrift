import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from connector_engine import connector_job_manager
from remote_car_client import ConnectorConfig, RemoteCarClient, validate_remote_path


router = APIRouter()


class ConnectorConfigPayload(BaseModel):
    host: str = ""
    user: str = "pi"
    port: int = Field(default=22, ge=1, le=65535)
    car_dir: str = "~/mycar"
    key_path: Optional[str] = None


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


@router.post("/status")
async def check_status():
    config = _to_config(_load_payload())
    online, message = RemoteCarClient(config).check_connection()
    return {"online": online, "message": message}


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
