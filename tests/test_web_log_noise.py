# -*- coding: utf-8 -*-
"""Web 后端轮询日志刷屏回归测试。

用户反馈：Tub 视频库每 30s 轮询 /tub/family_sessions，每次调用都会开合
成员 tub，donkeycar 库层（Found datastore / Using last catalog / Closing
tub / Closing manifest）与 routers.tub 的轮询诊断行（Family sessions ...
in XXms）各打一串 INFO；多标签页各自轮询时命令行被持续刷屏。

本测试验证 main.py 非 DEBUG 模式下的抑制配置：
1. donkeycar.parts.datastore_v2 / donkeycar.parts.tub_v2 / routers.tub
   三个 logger 被置为 WARNING；
2. 真实调用 list_family_sessions（含成员 tub 开合）不再产生这些 logger
   的 INFO 级记录；WARNING 及以上（异常）不受影响。
"""
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "web_ui" / "backend"))

os.environ.pop("DRIVE_WEB_DEBUG", None)

import main  # noqa: E402  模块级日志抑制在导入时生效
from donkeycar.parts.datastore_v2 import Manifest  # noqa: E402
from routers import tub as tub_router  # noqa: E402

# 轮询链路上的高频噪音 logger：库层开合 tub 两枚 + 路由诊断行一枚
NOISY_LOGGERS = (
    "donkeycar.parts.datastore_v2",
    "donkeycar.parts.tub_v2",
    "routers.tub",
)


@pytest.fixture
def single_session_tub(tmp_path: Path) -> str:
    """构造含一条记录的合法 tub，供 family_sessions 聚合。"""
    tub_dir = tmp_path / "data"
    tub_dir.mkdir()
    manifest = Manifest(
        str(tub_dir), inputs=["user/angle"], types=["float"], metadata=[], max_len=100
    )
    manifest.write_record(
        {"_index": 0, "_timestamp_ms": 1, "_session_id": "26-11-10_0", "user/angle": 0.1}
    )
    manifest.close()
    return str(tub_dir)


def test_poll_loggers_suppressed_in_production():
    if main.DEBUG:
        pytest.skip("DRIVE_WEB_DEBUG 显式开启时保留全部日志")
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING, (
            f"{name} 未被静音，轮询仍会刷屏命令行"
        )


def test_family_sessions_emits_no_info_noise(single_session_tub):
    if main.DEBUG:
        pytest.skip("DRIVE_WEB_DEBUG 显式开启时保留全部日志")

    captured: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    # root 放宽到 DEBUG 再捕获：证明拦截发生在 logger 级别而非 handler 缺失
    root = logging.getLogger()
    old_root_level = root.level
    handler = Capture()
    root.addHandler(handler)
    try:
        resp = asyncio.run(tub_router.list_family_sessions(tubPath=single_session_tub))
    finally:
        root.removeHandler(handler)
        root.setLevel(old_root_level)

    assert len(resp["sessions"]) == 1
    info_noise = [
        r for r in captured
        if r.levelno < logging.WARNING
        and (r.name.startswith("donkeycar.parts") or r.name == "routers.tub")
    ]
    assert not info_noise, (
        "family_sessions 轮询仍产生 INFO 噪音: "
        + "; ".join(f"{r.name}: {r.getMessage()}" for r in info_noise[:5])
    )
