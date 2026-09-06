"""findcar 配置接口：网页里设置 Pages Functions URL 与共享口令。"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import findcar

router = APIRouter()


class FindCarConfigUpdate(BaseModel):
    url: str = ""
    token: str = ""
    enabled: bool = False
    interval_seconds: Optional[int] = None


def _masked_config(cfg: findcar.FindCarConfig) -> dict:
    """序列化配置，token 返回脱敏值，避免把共享口令原样吐回前端。"""
    data = cfg.model_dump()
    data["token"] = findcar.mask_token(cfg.token)
    return data


@router.get("/config")
async def get_config():
    return {"config": _masked_config(findcar.load_config())}


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
        token=payload.token,
        enabled=payload.enabled,
        interval_seconds=interval,
    )
    findcar.save_config(cfg)
    return {"config": _masked_config(cfg)}
