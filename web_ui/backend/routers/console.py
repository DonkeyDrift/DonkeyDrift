"""Drifter Console（DC）车端 HTTP API 反向代理。

Issue #234：把 Drifter Console 集成进 DonkeyDrifter（DD）前端时，浏览器无法
直接跨域访问车端（ESP32 上 `http://<ip>/api/...`，非 HTTPS 且无 CORS 头）。
本路由在 DD 后端提供一层同源代理，把 `/api/console/proxy/<ip>/<path>` 原样转发
到 `http://<ip>/<path>`，让 React 前端仅与 DD 后端同源通信。
"""
import asyncio
import ipaddress
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()

# DC 车端 HTTP 接口的超时（状态/遥测轮询都很轻量，10s 足够）
PROXY_TIMEOUT = 10

# OTA 固件上传（POST /update）需要传输完整 .bin，耗时明显更长，单独放宽超时。
OTA_TIMEOUT = 300


def _validate_ip(ip: str) -> str:
    """仅允许 IPv4 局域网地址，避免代理被用于任意内网/外网 SSRF。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法的车端 IP 地址") from exc
    if addr.version != 4:
        raise HTTPException(status_code=400, detail="仅支持 IPv4 车端地址")
    return ip


def _forward_sync(
    url: str,
    method: str,
    body: bytes | None,
    content_type: str | None,
    timeout: int = PROXY_TIMEOUT,
) -> tuple[int, dict, bytes]:
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        # 车端返回 4xx/5xx 时也原样透传，不能让浏览器拿到空 500
        return exc.code, dict(exc.headers), exc.read()


async def _forward(ip: str, path: str, method: str, query: str, body: bytes | None, content_type: str | None) -> Response:
    ip = _validate_ip(ip)
    url = f"http://{ip}/{path}"
    if query:
        url += f"?{query}"
    # OTA 上传是大文件传输，走长超时；其余轻量接口保持 10s。
    timeout = OTA_TIMEOUT if path == "update" else PROXY_TIMEOUT
    try:
        status, headers, data = await asyncio.to_thread(
            _forward_sync, url, method, body, content_type, timeout
        )
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"无法连接车端 {ip}: {exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    media_type = headers.get("Content-Type") or headers.get("content-type") or "application/octet-stream"
    # 去掉 charset 等参数交给 Response 自行解析
    media_type = media_type.split(";", 1)[0].strip()
    return Response(content=data, status_code=status, media_type=media_type)


@router.api_route("/proxy/{ip}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_with_path(ip: str, path: str, request: Request) -> Response:
    body = await request.body()
    return await _forward(
        ip,
        path,
        request.method,
        request.url.query,
        body,
        request.headers.get("content-type"),
    )


@router.api_route("/proxy/{ip}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_root(ip: str, request: Request) -> Response:
    body = await request.body()
    return await _forward(
        ip,
        "",
        request.method,
        request.url.query,
        body,
        request.headers.get("content-type"),
    )
