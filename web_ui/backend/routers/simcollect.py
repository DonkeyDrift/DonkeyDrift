"""模拟器采集路由：启动/状态/停止/SSE。"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from simcollect_engine import simcollect_job_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class SimCollectStartRequest(BaseModel):
    steps: int = Field(default=1500, ge=1, le=20000)
    kp: float = Field(default=0.55, ge=0.0, le=5.0)
    kd: float = Field(default=0.8, ge=0.0, le=5.0)
    throttle: float = Field(default=0.30, ge=0.0, le=1.0)
    min_throttle: float = Field(default=0.15, ge=0.0, le=1.0)
    keep_sim: bool = False


@router.post("/start")
async def start_sim_collect(request: SimCollectStartRequest):
    try:
        job = simcollect_job_manager.create_job(
            steps=request.steps,
            kp=request.kp,
            kd=request.kd,
            throttle=request.throttle,
            min_throttle=request.min_throttle,
            keep_sim=request.keep_sim,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    asyncio.create_task(
        simcollect_job_manager.run(
            job,
            steps=request.steps,
            kp=request.kp,
            kd=request.kd,
            throttle=request.throttle,
            min_throttle=request.min_throttle,
            keep_sim=request.keep_sim,
        )
    )
    return {"job_id": job.id, "status": job.status}


def _job_or_404(job_id: str):
    job = simcollect_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="采集任务不存在")
    return job


@router.get("/{job_id}/status")
async def get_status(job_id: str):
    job = _job_or_404(job_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "step": job.step,
        "steps_total": job.steps_total,
        "cte": job.cte,
        "speed": job.speed,
        "result": job.result,
        "error": job.error,
        "logs": job.logs[-200:],
    }


@router.post("/{job_id}/stop")
async def stop_sim_collect(job_id: str):
    job = _job_or_404(job_id)
    if job.status not in ("pending", "running"):
        return {"job_id": job.id, "status": job.status}
    await simcollect_job_manager.stop_job(job_id)
    return {"job_id": job.id, "status": "stopped"}


@router.get("/{job_id}/events")
async def stream_events(job_id: str):
    job = _job_or_404(job_id)

    async def event_stream():
        # 先补一帧当前状态，方便晚连上的客户端
        yield f'data: {json.dumps({"type": "status", "status": job.status}, ensure_ascii=False)}\n\n'
        if job.status in ("done", "error", "stopped"):
            return
        while True:
            try:
                message = await asyncio.wait_for(job.log_queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
            if message.get("type") == "status" and message.get("status") in {"done", "error", "stopped"}:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")
