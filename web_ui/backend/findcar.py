"""一键找车（Find DKC）配置读写：供 /api/findcar/config 接口使用。

主机心跳上报运行在常驻 launcher（donkeycar/launcher/server.py →
donkeycar/findcar.py）上——只要开机、launcher 服务在跑，Find DKC 就能找到
本机，不再依赖按需启动的 DD Web。本模块只保留配置文件的读写，与 launcher
侧共用同一份配置（~/.donkeycar_findcar.json）：网页改配置后 launcher
下一跳即生效，无需重启。
"""
import json
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 配置文件路径（与 connector 的 ~/.donkeycar_web_connector.json 命名惯例一致；
# 与 launcher 侧 donkeycar.findcar.CONFIG_PATH 指向同一份文件）
CONFIG_PATH: Path = Path.home() / ".donkeycar_findcar.json"
# 与 donkeycar.findcar.DEFAULT_INTERVAL_SECONDS 保持一致
DEFAULT_INTERVAL_SECONDS = 150


class FindCarConfig(BaseModel):
    """findcar 配置：Pages Functions 上报地址与开关。"""

    url: str = ""
    enabled: bool = False
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS


def load_config() -> FindCarConfig:
    """读取配置；文件不存在或损坏时返回默认配置，绝不抛异常。"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                # 旧配置可能残留 token 字段，忽略即可
                data.pop("token", None)
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
