"""DD 前端 → launcher（:8090）的 launch 转发路由。

"打开 Kimi Code Web / DeepSeek Harness" 的自动化端点
（POST /api/launch/kimi-code-web、/api/launch/dsh）
实现在 launcher 服务（donkeycar/launcher/server.py，默认 :8090）上；
DD 前端与后端同源，相对路径 POST /api/launch/<端点名> 到达本后端，由
本路由原样转发给 launcher，浏览器侧无跨域问题。launcher 侧的 CORS 头
是为 DC（ESP32 origin 直连 :8090）准备的，与本转发路径无关。
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# launcher 服务地址（donkeycar/launcher，与后端同机运行）
LAUNCHER_BASE_URL = "http://localhost:8090"
# kimi 冷启动可达数十秒，launcher 端整体超时 120s，转发超时留足余量
FORWARD_TIMEOUT_S = 125.0


def _post_to_launcher(path: str, body: bytes) -> tuple[int, bytes]:
    """同步转发 POST 到 launcher，返回 (HTTP 状态码, 响应体)。"""
    req = urllib.request.Request(
        f"{LAUNCHER_BASE_URL}{path}",
        data=body if body else None,
        method="POST",
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT_S) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        # launcher 的业务错误（400/500）同样带 JSON 体，原样透传
        return e.code, e.read()


@router.post("/kimi-code-web")
async def launch_kimi_code_web(request: Request):
    """转发 POST /api/launch/kimi-code-web 到 launcher 并回传其 JSON 响应。"""
    return await _forward_launch(request, "/api/launch/kimi-code-web")


@router.post("/dsh")
async def launch_dsh(request: Request):
    """转发 POST /api/launch/dsh（DeepSeek Harness）到 launcher 并回传其 JSON 响应。"""
    return await _forward_launch(request, "/api/launch/dsh")


async def _forward_launch(request: Request, launcher_path: str) -> JSONResponse:
    """把 DD 前端的 launch 请求原样转发给 launcher 并回传其 JSON 响应。"""
    body = await request.body()
    try:
        status, payload = await asyncio.to_thread(
            _post_to_launcher, launcher_path, body
        )
    except Exception as e:
        logger.error("转发 launcher %s 失败: %s", launcher_path, e)
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "error": f"无法连接 launcher（{LAUNCHER_BASE_URL}），"
                         "请确认 Donkey 菜单页服务已启动",
            },
        )
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            status_code=502,
            content={"status": "error", "error": "launcher 返回了非 JSON 响应"},
        )
    return JSONResponse(status_code=status, content=data)
