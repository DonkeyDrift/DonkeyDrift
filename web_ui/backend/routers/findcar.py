"""findcar 配置接口：网页里设置 Pages Functions 上报地址（去 token）。"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import findcar

router = APIRouter()


class FindCarConfigUpdate(BaseModel):
    url: str = ""
    enabled: bool = False
    interval_seconds: Optional[int] = None


@router.get("/config")
async def get_config():
    return {"config": findcar.load_config().model_dump()}


@router.post("/config")
async def set_config(payload: FindCarConfigUpdate):
    existing = findcar.load_config()
    interval = (
        payload.interval_seconds
        if payload.interval_seconds is not None
        else existing.interval_seconds
    )
    cfg = findcar.FindCarConfig(
        url=payload.url,
        enabled=payload.enabled,
        interval_seconds=interval,
    )
    findcar.save_config(cfg)
    return {"config": cfg.model_dump()}
