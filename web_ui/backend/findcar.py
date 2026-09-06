"""一键找车：把本机 DD 后端局域网地址周期性上报到 Cloudflare Pages Functions。

网页「找小车」通过 Pages Functions 列出本机实例；后端启动后（若已配置 findcar）
立即上报一次，并每 ``interval_seconds`` 秒重复上报，供网页实时发现本机。
"""
import asyncio
import json
import logging
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

import donkeycar
from donkeycar.parts.provisioning import detect_lan_ip

logger = logging.getLogger(__name__)

# 配置文件路径（与 connector 的 ~/.donkeycar_web_connector.json 命名惯例一致）
CONFIG_PATH: Path = Path.home() / ".donkeycar_findcar.json"
DEFAULT_INTERVAL_SECONDS = 300


class FindCarConfig(BaseModel):
    """findcar 配置：Pages Functions 上报地址、共享口令与开关。"""

    url: str = ""
    token: str = ""
    enabled: bool = False
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS


def load_config() -> FindCarConfig:
    """读取配置；文件不存在或损坏时返回默认配置，绝不抛异常。"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return FindCarConfig(**data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("findcar 配置文件读取失败，使用默认配置", exc_info=True)
    return FindCarConfig()


def save_config(cfg: FindCarConfig) -> None:
    """写回配置；写入失败仅记日志，绝不抛异常。"""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(cfg.model_dump(), file, indent=2, ensure_ascii=False)
    except OSError:
        logger.warning("findcar 配置文件写入失败", exc_info=True)


def mask_token(token: str) -> str:
    """脱敏 token：保留首尾各 2 个字符，中间用 ``*`` 打码。"""
    if not token:
        return ""
    if len(token) <= 4:
        return "*" * len(token)
    return f"{token[:2]}{'*' * (len(token) - 4)}{token[-2:]}"


def _is_configured(cfg: FindCarConfig) -> bool:
    """仅当启用且 URL / token 均非空时才认为已配置。"""
    return bool(cfg.enabled and cfg.url.strip() and cfg.token.strip())


def _report_payload(cfg: FindCarConfig) -> dict:
    """构造上报 body（与 Cloudflare Pages Functions 协议严格一致，字段全为字符串）。"""
    try:
        lan_ip = detect_lan_ip()
    except Exception:
        logger.warning("findcar 探测局域网 IP 失败", exc_info=True)
        lan_ip = None
    version = getattr(donkeycar, "__version__", "")
    hostname = socket.gethostname()
    return {
        "token": cfg.token,
        "device_id": hostname,
        "type": "dd",
        "lan_ip": lan_ip or "",
        "port": os.environ.get("DRIVE_WEB_PORT", "8000"),
        "hostname": hostname,
        "version": version or "",
    }


def report_once(cfg: FindCarConfig) -> bool:
    """通过 HTTPS POST 上报一次心跳；成功返回 True，异常返回 False。

    使用标准库 ``urllib.request``，不引入第三方依赖。日志只打印目标 URL，
    绝不打印 token（防止口令泄露）。
    """
    base = cfg.url.strip().rstrip("/")
    if not base:
        logger.warning("findcar 心跳未上报：未配置 Pages Functions URL")
        return False
    url = base + "/report"
    body = json.dumps(_report_payload(cfg), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            # Cloudflare 会拦截 Python-urllib 默认 UA（403）；伪装成浏览器 UA 才能通过。
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152 Safari/537.36 DonkeyDrift-FindCar/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read()
        return True
    except Exception:
        logger.warning("findcar 心跳上报失败（url=%s）", url, exc_info=True)
        return False


async def heartbeat_loop(cfg: FindCarConfig) -> None:
    """周期上报心跳；每轮独立容错，异常不中断循环。"""
    if not _is_configured(cfg):
        return
    interval = cfg.interval_seconds if cfg.interval_seconds > 0 else DEFAULT_INTERVAL_SECONDS
    while True:
        try:
            report_once(cfg)
        except Exception:
            logger.warning("findcar 心跳循环异常", exc_info=True)
        await asyncio.sleep(interval)


def start_heartbeat() -> Optional[asyncio.Task]:
    """读取配置；未启用/未配置返回 None，否则创建后台心跳任务。"""
    cfg = load_config()
    if not _is_configured(cfg):
        return None
    return asyncio.create_task(heartbeat_loop(cfg))
