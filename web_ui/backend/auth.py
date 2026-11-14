# -*- coding: utf-8 -*-
"""Web 后端访问控制（P0 安全补强，2026-10-12）。

与 launcher/auth.py 同一威胁模型（两服务各自独立部署，策略保持一致）：

- 默认只绑定 127.0.0.1（main.__main__ / donkey web --backend-host 默认）；
  对外监听必须显式 ``--backend-host 0.0.0.0`` 或设 ``DRIVE_WEB_HOST``。
- 回环 TCP 客户端 + 本机 Host + 干净 Origin 直接放行：本机浏览器、Vite
  dev 代理、curl、Starlette TestClient 均不受影响。
- 非回环客户端（手机遥控浏览器、车端 DriveApiBridge）必须携带令牌：
  ``?token=`` 查询串 / ``Authorization: Bearer`` / ``X-Donkey-Token`` 头 /
  Cookie ``dd_drive_token``。页面 GET 的 ``?token=`` 命中后种 Cookie 并 302
  去掉查询串，之后同源请求凭 Cookie 通行；``/api/*`` 与 WS 握手不跳转。
- 跨站 Origin（CSRF）或 Host 非本机名（DNS rebinding）时，免令牌路径一律
  拒绝；仅凭 Cookie 通行同样要求本机 Host + 同源。显式 ``?token=``/Bearer
  是持有密钥，不受 Origin 限制（车端 WS、DC 页面、curl 用）。
- ``DRIVE_API_AUTH=off`` 整体关闭鉴权（兼容旧部署的逃生舱）。

令牌来源优先级：``DRIVE_API_TOKEN`` 环境变量 > ``~/.donkeycar/drive_api.token``
（0600）> 首次生成并落盘。车端经 ``DRIVE_API_TOKEN`` 或同一令牌文件注入
``?token=`` 连回本后端（见 parts/drive_api_bridge._with_token）。
"""

import hmac
import os
import secrets
import socket
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

TOKEN_ENV = "DRIVE_API_TOKEN"
AUTH_ENV = "DRIVE_API_AUTH"
HOST_ENV = "DRIVE_WEB_HOST"
COOKIE_NAME = "dd_drive_token"
QUERY_KEY = "token"
TOKEN_FILE = Path.home() / ".donkeycar" / "drive_api.token"

# Starlette TestClient 伪造的 TCP 对端与 Host 头；真实 HTTP 客户端不可能
# 呈现这些值（测试兼容口，见 launcher/auth.py 同名机制）。
_TEST_CLIENT_HOSTS = ("testclient",)
_TEST_HOST_NAMES = ("testserver", "testclient")


def auth_enabled() -> bool:
    """DRIVE_API_AUTH=off/0/false/no 时关闭鉴权，其余情况开启。"""
    raw = os.environ.get(AUTH_ENV, "on").strip().lower()
    return raw not in ("off", "0", "false", "no")


def load_or_create_token() -> str:
    """解析访问令牌：环境变量 > 令牌文件 > 生成并以 0600 落盘。"""
    env_token = os.environ.get(TOKEN_ENV, "").strip()
    if env_token:
        return env_token
    try:
        file_token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if file_token:
            return file_token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TOKEN_FILE.with_suffix(".token.tmp")
        tmp.write_text(token, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(TOKEN_FILE)
    except OSError:
        # 落盘失败（只读文件系统等）时退回仅环境变量模式
        pass
    return token


def token_matches(candidate) -> bool:
    """常数时间比较候选令牌与本机令牌。"""
    if not candidate:
        return False
    try:
        return hmac.compare_digest(str(candidate), load_or_create_token())
    except Exception:
        return False


def _cookie_token(headers) -> str:
    """仅从 Cookie 提取令牌（跨站导航会自动携带，不能单凭它越过 Origin 判定）。"""
    cookie_header = headers.get("Cookie") or ""
    if not cookie_header:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:
        return ""
    morsel = jar.get(COOKIE_NAME)
    if morsel is not None:
        return (morsel.value or "").strip()
    return ""


def _explicit_token(headers, query) -> str:
    """显式携带的令牌（Authorization / X-Donkey-Token / ?token=），不含 Cookie。"""
    auth_header = headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    custom = headers.get("X-Donkey-Token")
    if custom:
        return custom.strip()
    if isinstance(query, dict):
        q = query.get(QUERY_KEY)
    else:
        q = query
    if q:
        if isinstance(q, (list, tuple)):
            q = q[0] if q else None
        if q:
            return str(q).strip()
    return ""


def extract_token(headers, query) -> str:
    """从请求头/查询串/Cookie 提取候选令牌，取到即返回。"""
    explicit = _explicit_token(headers, query)
    if explicit:
        return explicit
    return _cookie_token(headers)


def is_local_client(client) -> bool:
    """TCP 对端是否为回环/测试客户端（不可伪造，安全判定基准）。

    client 为 ASGI scope 的 (host, port) 元组/列表；None（unix socket 或
    进程内 ASGI 调用）视为本机。
    """
    if client is None:
        return True
    host = client[0] if isinstance(client, (tuple, list)) else str(client)
    host = str(host)
    if host in ("127.0.0.1", "::1", "localhost") or host in _TEST_CLIENT_HOSTS:
        return True
    return host.startswith("127.") or host == "::ffff:127.0.0.1"


def _origin_clean(headers) -> bool:
    """Origin/Referer 缺失或与 Host 同源视为干净（同源导航/本机 curl）。"""
    raw = headers.get("Origin") or headers.get("Referer") or ""
    raw = raw.strip()
    if not raw or raw == "null":
        return True
    origin_netloc = urlsplit(raw).netloc
    host = (headers.get("Host") or "").strip()
    if not origin_netloc or not host:
        return False
    return origin_netloc.lower() == host.lower()


def _hostname_variants() -> set:
    """本机主机名的常见写法（全名/短名 + .local 变体）。"""
    names = {"localhost"}
    try:
        full = socket.gethostname().strip().lower()
    except OSError:
        full = ""
    if full:
        short = full.split(".")[0]
        names.update((full, short, f"{short}.local", f"{full}.local"))
    return names


_LOCAL_IP_CACHE = {"ts": 0.0, "ips": frozenset()}


def _local_ips() -> frozenset:
    """本机网卡 IP 集合（60s 缓存）。

    首选配网模块的 VPN/TUN 感知探测（与 kimi_web._lan_ip 同源），另加
    gethostbyname_ex 与 UDP connect 探测（不发包）兜底。
    """
    now = time.monotonic()
    if now - _LOCAL_IP_CACHE["ts"] < 60.0:
        return _LOCAL_IP_CACHE["ips"]
    ips = set()
    try:
        from donkeycar.parts.provisioning import detect_lan_ip
        lan = detect_lan_ip()
        if lan:
            ips.add(lan)
    except Exception:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    _LOCAL_IP_CACHE["ts"] = now
    _LOCAL_IP_CACHE["ips"] = frozenset(ips)
    return _LOCAL_IP_CACHE["ips"]


def _host_is_self(headers) -> bool:
    """Host 头主机名是否为本机名字（防 DNS rebinding 的 Host 钳制）。"""
    raw = (headers.get("Host") or "").strip().lower()
    if not raw:
        return False
    if raw.startswith("["):
        end = raw.find("]")
        host = raw[1:end] if end != -1 else raw
    else:
        host = raw.split(":")[0]
    if host in ("127.0.0.1", "::1", "localhost") or host in _TEST_HOST_NAMES:
        return True
    if host in _hostname_variants():
        return True
    return host in _local_ips()


def is_authorized(headers, query, client) -> bool:
    """请求是否放行：关闭鉴权 / 回环+本机 Host+干净 Origin / 显式令牌 /
    Cookie+本机 Host+同源。

    两条免令牌路径都要求 Host 是本机名字（防 DNS rebinding）且 Origin
    干净（防 CSRF）；仅凭 Cookie 通行同样受这两条约束——跨站导航会自动
    带 Cookie，POST 侧另有 SameSite=Lax 挡截。
    """
    if not auth_enabled():
        return True
    if is_local_client(client) and _host_is_self(headers) and _origin_clean(headers):
        return True
    if token_matches(_explicit_token(headers, query)):
        return True
    return (
        token_matches(_cookie_token(headers))
        and _host_is_self(headers)
        and _origin_clean(headers)
    )


def query_token_valid(query) -> bool:
    """查询串里的 ?token= 是否命中（用于处理器种 Cookie + 302）。"""
    if isinstance(query, dict):
        q = query.get(QUERY_KEY)
        if isinstance(q, (list, tuple)):
            q = q[0] if q else None
    else:
        q = query
    return bool(q) and token_matches(str(q).strip())
