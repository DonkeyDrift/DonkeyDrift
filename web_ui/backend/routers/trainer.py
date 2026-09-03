"""
Trainer API Router - exposes training configuration, job management, and SSE log streaming.
"""
import asyncio
import configparser
import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from trainer_engine import job_manager
from mypc_probe import probe_mypc_environment
router = APIRouter()

# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------
class TrainerConfig(BaseModel):
    host: str
    user: str
    remote_dir_base: str
    model_name: str
    python_path: str


class SSHCredentials(BaseModel):
    """SSH 连接凭据，仅在训练请求会话内传递，不落盘、不入库。"""
    host: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    key_filename: Optional[str] = None


class LocalTrainRequest(BaseModel):
    tub: str = "./data"
    model: str
    model_type: str = "linear"
    transfer: Optional[str] = None
    working_dir: Optional[str] = None


class OnlineTrainRequest(BaseModel):
    config_file: str = "train_online.conf"
    working_dir: Optional[str] = None
    ssh: Optional[SSHCredentials] = None


class MyPcTrainRequest(BaseModel):
    config_file: str = "train_my_pc.conf"
    working_dir: Optional[str] = None
    ssh: Optional[SSHCredentials] = None


class MyPcProbeRequest(BaseModel):
    host: str
    user: str
    password: str = ""
    port: int = 22
    remote_dir_base: str = "~/projects"
    python_path: str = ""
    key_path: str = ""


class MyPcInstallRequest(BaseModel):
    """一键安装训练依赖：需要 probe 探测到的 python 路径。"""
    host: str
    user: str
    password: str = ""
    port: int = 22
    python_path: str
    key_path: str = ""


class StopRequest(BaseModel):
    pass


# ------------------------------------------------------------------
# Config endpoints
# ------------------------------------------------------------------
@router.get("/config")
async def get_trainer_config(config_file: str = "train_online.conf"):
    """Read train_online.conf and return as JSON."""
    path = os.path.abspath(config_file)
    if not os.path.exists(path):
        # Auto-create default config using OnlineTrainer logic
        from donkeycar.management.train_online import OnlineTrainer
        # Temporarily instantiate to trigger file creation
        _ = OnlineTrainer(config_file=path)

    config = configparser.ConfigParser()
    config.read(path)
    if "Remote" not in config.sections():
        raise HTTPException(status_code=500, detail="Invalid config file: missing [Remote] section")

    return {
        "path": path,
        "host": config["Remote"].get("host", ""),
        "user": config["Remote"].get("user", ""),
        # 密码不再返回给前端：凭据仅会话内传递，不落盘、不入库。
        "password": "",
        "remote_dir_base": config["Remote"].get("remote_dir_base", "~/projects"),
        "model_name": config["Remote"].get("model_name", "model"),
        "python_path": config["Remote"].get("python_path", "~/miniconda3/envs/donkey/bin/python"),
    }


@router.post("/config")
async def set_trainer_config(cfg: TrainerConfig, config_file: str = "train_online.conf"):
    """Write train_online.conf from JSON payload."""
    path = os.path.abspath(config_file)
    config = configparser.ConfigParser()
    if os.path.exists(path):
        config.read(path)
    if "Remote" not in config.sections():
        config.add_section("Remote")

    config.set("Remote", "host", cfg.host)
    config.set("Remote", "user", cfg.user)
    config.set("Remote", "remote_dir_base", cfg.remote_dir_base)
    config.set("Remote", "model_name", cfg.model_name)
    config.set("Remote", "python_path", cfg.python_path)

    with open(path, "w") as f:
        config.write(f)

    return {"status": True, "path": path}


@router.post("/mypc/probe")
async def probe_mypc(request: MyPcProbeRequest):
    """Pre-flight check for 'This Computer' (mypc) training.

    Connects to the user's computer over SSH and reports whether the target
    OS, Python interpreter, and donkeycar environment are ready, returning
    actionable fix hints for anything that is missing or misconfigured.
    Runs in a worker thread because Paramiko is blocking.
    """
    result = await asyncio.to_thread(
        probe_mypc_environment,
        host=request.host,
        user=request.user,
        password=request.password,
        remote_dir_base=request.remote_dir_base,
        python_path=request.python_path,
        port=request.port,
        key_path=request.key_path,
    )
    return {
        "ok": result.ok,
        "platform": result.platform,
        "shell": result.shell,
        "python_path": result.python_path,
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "message": c.message,
                "hint": c.hint,
            }
            for c in result.checks
        ],
        "suggestions": result.suggestions,
    }


@router.post("/mypc/install")
async def install_mypc(request: MyPcInstallRequest):
    """One-click dependency install for 'This Computer' (mypc) training.

    Requires a python path discovered by a prior /mypc/probe call; runs
    ``<python> -m pip install --upgrade "donkeydrifter[pc]"`` over SSH as a
    job whose logs stream through the shared /train/{job_id}/logs SSE
    endpoint (the job mode is 'mypc_install').
    """
    if not request.python_path or not request.python_path.strip():
        raise HTTPException(
            status_code=400,
            detail="缺少 Python 解释器路径，请先运行环境检测。",
        )

    job = job_manager.create_job("mypc_install")
    asyncio.create_task(
        job_manager.run_mypc_install(
            job,
            host=request.host,
            user=request.user,
            password=request.password,
            python_path=request.python_path,
            port=request.port,
            key_path=request.key_path,
        )
    )
    return {"job_id": job.id, "status": job.status}


# ------------------------------------------------------------------
# Model / Backup listing
# ------------------------------------------------------------------
def _get_dir_size(path: str) -> int:
    """Recursively calculate total size of a directory."""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


@router.get("/tubs")
async def list_tubs(working_dir: Optional[str] = None):
    """List candidate tub directories for local training.

    Scans <working_dir>/data itself plus every subdirectory of it that has a
    manifest.json (covers data/tub_xxx unpacked archives), and sibling
    <working_dir>/data* directories. Returns relative (./data style) and
    absolute paths plus the currently loaded tub path, so the Trainer page
    can pre-select the right tub automatically.
    """
    cwd = working_dir or os.getcwd()
    tubs: List[dict] = []

    def _add_tub(full_path: str):
        rel = os.path.relpath(full_path, cwd)
        display = "./" + rel if not rel.startswith(".") else rel
        tubs.append({
            "name": os.path.basename(full_path) or full_path,
            "relative_path": display,
            "absolute_path": os.path.abspath(full_path),
        })

    def _is_tub(path: str) -> bool:
        return os.path.isfile(os.path.join(path, "manifest.json"))

    candidates: List[str] = []
    data_dir = os.path.join(cwd, "data")
    if os.path.isdir(data_dir):
        candidates.append(data_dir)
        try:
            for name in sorted(os.listdir(data_dir)):
                sub = os.path.join(data_dir, name)
                if os.path.isdir(sub):
                    candidates.append(sub)
        except OSError:
            pass
    if os.path.isdir(cwd):
        try:
            for name in sorted(os.listdir(cwd)):
                full = os.path.join(cwd, name)
                if name != "data" and name.startswith("data") and os.path.isdir(full):
                    candidates.append(full)
        except OSError:
            pass

    seen = set()
    for path in candidates:
        if _is_tub(path):
            key = os.path.abspath(path)
            if key not in seen:
                seen.add(key)
                _add_tub(path)

    from routers.tub import current_tub_path

    return {
        "tubs": tubs,
        "current_tub_path": current_tub_path,
    }


@router.get("/models")
async def list_models(working_dir: Optional[str] = None):
    """List local .tflite models in ./models directory.

    Only .tflite files are shown. Training loss charts (.png) are hidden
    from the list but linked to their corresponding model via previewPath.
    """
    cwd = working_dir or os.getcwd()
    models_dir = os.path.join(cwd, "models")
    items: List[dict] = []
    if not os.path.isdir(models_dir):
        return {"models": items}

    # Build a set of existing .png files for quick lookup
    png_files = {
        n for n in os.listdir(models_dir)
        if n.endswith(".png") and os.path.isfile(os.path.join(models_dir, n))
    }

    for name in sorted(os.listdir(models_dir)):
        full = os.path.join(models_dir, name)
        # Only show .tflite model files
        if not (os.path.isfile(full) and name.endswith(".tflite")):
            continue

        stem = os.path.splitext(name)[0]
        preview_name = f"{stem}.png"
        preview_path = (
            os.path.abspath(os.path.join(models_dir, preview_name))
            if preview_name in png_files
            else None
        )

        # Read loss metadata if available
        meta_path = os.path.join(models_dir, f"{stem}_meta.json")
        loss_info = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r") as f:
                    loss_info = json.load(f)
            except Exception:
                pass

        stat = os.stat(full)
        items.append({
            "name": name,
            "type": "file",
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "path": os.path.abspath(full),
            "previewPath": preview_path,
            "finalLoss": loss_info.get("final_loss"),
            "bestLoss": loss_info.get("best_loss"),
        })
    return {"models": items}


@router.get("/models/preview")
async def get_model_preview(path: str = Query(..., description="Absolute path to the .png preview image")):
    """Serve a model training loss chart (.png) for preview in the UI."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Preview file not found")
    if not path.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only .png previews are supported")
    return FileResponse(path, media_type="image/png")


@router.get("/models/download")
async def download_model(path: str = Query(..., description="Absolute path to the model file")):
    """Download a model file as attachment."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Model file not found")
    if not path.lower().endswith(".tflite"):
        raise HTTPException(status_code=400, detail="Only .tflite model files are supported")
    filename = os.path.basename(path)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
    )


@router.delete("/models")
async def delete_model(path: str = Query(..., description="Absolute path to the model file")):
    """Delete a model file and its associated preview image and metadata."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Model file not found")
    if not path.lower().endswith(".tflite"):
        raise HTTPException(status_code=400, detail="Only .tflite model files are supported")

    # Remove the main model file
    os.remove(path)

    # Remove associated files (preview .png and _meta.json) if they exist
    stem = os.path.splitext(path)[0]
    for suffix in (".png", "_meta.json"):
        associated_path = f"{stem}{suffix}"
        if os.path.isfile(associated_path):
            try:
                os.remove(associated_path)
            except Exception:
                pass

    return {"status": True, "path": path}


@router.get("/backups")
async def list_backups(working_dir: Optional[str] = None):
    """List data backup archives in ./data_cache."""
    cwd = working_dir or os.getcwd()
    cache_dir = os.path.join(cwd, "data_cache")
    items: List[dict] = []
    if os.path.isdir(cache_dir):
        for name in sorted(os.listdir(cache_dir)):
            if name.endswith(".tar.gz"):
                full = os.path.join(cache_dir, name)
                stat = os.stat(full)
                items.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "path": os.path.abspath(full),
                })
    return {"backups": items}


# ------------------------------------------------------------------
# Job management
# ------------------------------------------------------------------
@router.post("/train/local")
async def start_local_train(request: LocalTrainRequest):
    job = job_manager.create_job("local")
    asyncio.create_task(
        job_manager.run_local(
            job,
            tub=request.tub,
            model=request.model,
            model_type=request.model_type,
            transfer=request.transfer,
            working_dir=request.working_dir,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/train/online")
async def start_online_train(request: OnlineTrainRequest):
    job = job_manager.create_job("online")
    asyncio.create_task(
        job_manager.run_online(
            job,
            config_file=request.config_file,
            working_dir=request.working_dir,
            ssh_credentials=request.ssh.model_dump() if request.ssh else None,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/train/mypc")
async def start_mypc_train(request: MyPcTrainRequest):
    """Train on the user's own computer via SSH callback (train_my_pc.conf)."""
    job = job_manager.create_job("mypc")
    asyncio.create_task(
        job_manager.run_mypc(
            job,
            config_file=request.config_file,
            working_dir=request.working_dir,
            ssh_credentials=request.ssh.model_dump() if request.ssh else None,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.get("/train/{job_id}/status")
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "mode": job.mode,
        "status": job.status,
        "progress": {
            "currentEpoch": job.progress.current_epoch,
            "totalEpochs": job.progress.total_epochs,
            "currentStep": job.progress.current_step,
            "totalSteps": job.progress.total_steps,
            "loss": job.progress.loss,
            "globalPercent": job.progress.global_percent,
        },
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error_message,
    }


@router.post("/train/{job_id}/stop")
async def stop_train(job_id: str):
    job_manager.stop_job(job_id)
    return {"job_id": job_id, "status": "stopped"}


# ------------------------------------------------------------------
# SSE log streaming
# ------------------------------------------------------------------
async def _sse_event_generator(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
        return

    # Yield initial status
    yield f"data: {json.dumps({'type': 'status', 'status': job.status})}\n\n"

    while True:
        try:
            msg = await asyncio.wait_for(job.log_queue.get(), timeout=1.0)
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("type") == "status" and msg.get("status") in ("completed", "failed", "stopped"):
                break
        except asyncio.TimeoutError:
            # Send keep-alive heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            # If job finished while we were waiting, exit
            if job.status in ("completed", "failed", "stopped"):
                break


@router.get("/train/{job_id}/logs")
async def stream_logs(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return StreamingResponse(
        _sse_event_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
