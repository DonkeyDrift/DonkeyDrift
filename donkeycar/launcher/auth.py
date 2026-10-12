# -*- coding: utf-8 -*-
"""Launcher HTTP 访问控制（P0 安全补强，2026-10-12）。

取代 2026-08-14 "整车免密" 的无鉴权设计（见 launcher/terminal.py 旧安全说明）。
威胁模型与策略：

- 默认只绑定 127.0.0.1（见 server.run_server / __main__），对外监听必须
  显式传 ``--host 0.0.0.0`` 或设 ``DONKEY_LAUNCHER_HOST``。
- 回环客户端 + 干净 Origin（无 Origin/Referer，或与 Host 同源）直接放行：
  本机浏览器/curl、DD 后端转发（requests 无 Origin）体验不变。
- 非回环客户端（局域网设备、DC 浏览器页面）必须携带令牌，取其一即可：
  ``?token=`` 查询串 / ``Authorization: Bearer`` / ``X-Donkey-Token`` 头 /
  Cookie ``dd_launcher_token``。``?token=`` 命中时由处理器种 Cookie 并 302
  去掉查询串，之后同源请求凭 Cookie 通行。
- 浏览器跨站请求（恶意网页的 fetch/XHR/表单/iframe 导航）携带敌对
  Origin，不能凭本机地址或 Cookie 免令牌通行——这是 DNS rebinding 与
  CSRF 的主要防线；Origin 判定只信任 TCP 对端地址（client_address），
  不采信任何可伪造头。显式 ?token=/Bearer 持有密钥本身，不受 Origin 限。
- ``DONKEY_LAUNCHER_AUTH=off`` 可整体关闭（测试/兼容旧部署），此时若绑定
  非回环地址由 run_server 打印醒目警告。

令牌来源优先级：``DONKEY_LAUNCHER_TOKEN`` 环境变量 >
``~/.donkeycar/launcher.token``（0600）> 首次生成并落盘。
"""

import hmac
import os
import secrets
import socket
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

TOKEN_ENV = "DONKEY_LAUNCHER_TOKEN"
AUTH_ENV = "DONKEY_LAUNCHER_AUTH"
HOST_ENV = "DONKEY_LAUNCHER_HOST"
COOKIE_NAME = "dd_launcher_token"
QUERY_KEY = "token"
TOKEN_FILE = Path.home() / ".donkeycar" / "launcher.token"

# 与 Starlette TestClient 兼容：它以 ("testclient", 50000) 伪造 client，
# 无法从 TCP 对端判定本地；真实 HTTP 客户端不可能呈现该地址。
_TEST_CLIENT_HOSTS = ("testclient",)


def auth_enabled() -> bool:
    """DONKEY_LAUNCHER_AUTH=off/0/false/no 时关闭鉴权，其余情况开启。"""
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
        # 先写临时文件再替换，权限 0600（仅属主可读）
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
    """显式携带的令牌（Authorization / X-Donkey-Token / ?token=），不含 Cookie。

    显式令牌是调用方确实持有的密钥（curl、车端 WS、DC 页面），不受
    Origin 限制；Cookie 则是浏览器自动附带的，跨站导航也可能携带。
    """
    auth_header = headers.get("Authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    custom = headers.get("X-Donkey-Token")
    if custom:
        return custom.strip()
    if isinstance(query, dict):
        q = query.get(QUERY_KEY)
    else:
        q = query  # 已解析的单值
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


def is_local_client(client_address) -> bool:
    """TCP 对端是否为回环/测试客户端（不可伪造，安全判定基准）。"""
    if not client_address:
        return False
    host = client_address[0] if isinstance(client_address, (tuple, list)) else str(client_address)
    host = str(host)
    if host in ("127.0.0.1", "::1", "localhost") or host in _TEST_CLIENT_HOSTS:
        return True
    # 其余 127.0.0.0/8 与 IPv6 回环缩写
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
    """Host 头主机名是否为本机名字（防 DNS rebinding 的 Host 钳制）。

    恶意域名解析到车机后，请求的 Host 会是攻击者域名——它不在本机名字
    集合里即拒绝；本机浏览器用 127.0.0.1 / localhost / 主机名 / 本网卡
    IP 访问均照常放行。
    """
    raw = (headers.get("Host") or "").strip().lower()
    if not raw:
        return False
    if raw.startswith("["):
        end = raw.find("]")
        host = raw[1:end] if end != -1 else raw
    else:
        host = raw.split(":")[0]
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    if host in _hostname_variants():
        return True
    return host in _local_ips()


def is_authorized(headers, query, client_address) -> bool:
    """请求是否放行：关闭鉴权 / 回环+本机 Host+干净 Origin / 显式令牌 /
    Cookie+本机 Host+同源。

    回环判定放前面：纯本机流量（本机浏览器、DD 后端转发、测试）不触碰
    令牌文件，也就不会因请求副作用凭空生成 ~/.donkeycar/launcher.token。
    两条免令牌路径都要求 Host 是本机名字（防 DNS rebinding）且 Origin
    干净（防 CSRF）；仅凭 Cookie 通行同样受这两条约束——跨站导航会自动
    带 Cookie，POST 侧另有 SameSite=Lax 挡截。
    """
    if not auth_enabled():
        return True
    if (
        is_local_client(client_address)
        and _host_is_self(headers)
        and _origin_clean(headers)
    ):
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
