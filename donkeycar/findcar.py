# -*- coding: utf-8 -*-
"""一键找车（Find DKC）主机心跳上报核心——纯标准库，由常驻 launcher 调用。

只要主机开机、launcher 服务（donkeydrifter-launcher.service）在跑，就周期性把
本机局域网地址上报到 Cloudflare Pages Functions，网页
https://find-dkc.pages.dev/ 打开即列出本机。去 token 公开上报，无需共享口令。

历史：上报原挂在 DD Web 后端（web_ui/backend，:8000）的 lifespan 上，但 DD Web
按需启动，不开网页主机就从 Find DKC 消失；故迁到开机常驻的 launcher
（donkeycar/launcher/server.py）。配置文件仍由 DD Web 的 /api/findcar/config
接口读写（web_ui/backend/findcar.py，与本模块共用 ~/.donkeycar_findcar.json）。
"""

import http.client
import json
import logging
import socket
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Optional

from donkeycar._version import __version__

logger = logging.getLogger(__name__)

# 配置文件路径（与 connector 的 ~/.donkeycar_web_connector.json 命名惯例一致；
# 与 DD Web 的 /api/findcar/config 接口读写同一份文件）
CONFIG_PATH: Path = Path.home() / ".donkeycar_findcar.json"
# 150s 一跳：网页在线窗口 5.5 分钟（容忍漏跳一次），写入量 576 次/天，
# 与 ESP32 的 ~288 次/天 合计仍在 Cloudflare KV 免费层 1000 写/天 之内。
DEFAULT_INTERVAL_SECONDS = 150
# 下线标记是尽力而为：超时短、失败只记日志，绝不在退出路径上卡住关停。
OFFLINE_TIMEOUT_SECONDS = 3
# DNS 解析失败后的快重试间隔（吸收秒级抖动）；仍失败再走 DoH 兜底。
DNS_RETRY_DELAY_SECONDS = 3
# 上报失败后的快速补跳间隔（launcher 循环用）：不等完整 150s，30s 后补一跳，
# 缩短 DNS/网络抖动的恢复时间。
RETRY_INTERVAL_SECONDS = 30
# DoH 兜底解析端点：按 IP 直连（证书含 IP SAN），系统 DNS 失效时仍可解析。
# 用阿里公共 DNS（223.5.5.5/223.6.6.6，dns-json 协议 /resolve 路径）——
# Cloudflare 的 1.1.1.1/1.0.0.1 在家庭宽带下实测超时不可用（2026-09-20 实测）。
DOH_SERVERS = ("223.5.5.5", "223.6.6.6")
# Cloudflare 会拦截 Python-urllib 默认 UA（403）；伪装成浏览器 UA 才能通过。
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152 Safari/537.36 DonkeyDrift-FindCar/1.0"
)

STATE_ONLINE = "online"
STATE_OFFLINE = "offline"


@dataclass
class FindCarConfig:
    """findcar 配置：Pages Functions 上报地址与开关。"""

    url: str = ""
    enabled: bool = False
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS


def load_config(path: Optional[Path] = None) -> FindCarConfig:
    """读取配置；文件不存在或损坏时返回默认配置，绝不抛异常。"""
    path = path if path is not None else CONFIG_PATH
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                # 旧配置可能残留 token 等已废弃字段，只取认识的字段即可
                return FindCarConfig(
                    url=str(data.get("url") or ""),
                    enabled=bool(data.get("enabled")),
                    interval_seconds=int(
                        data.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS
                    ),
                )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("findcar 配置文件读取失败，使用默认配置", exc_info=True)
    return FindCarConfig()


def is_configured(cfg: FindCarConfig) -> bool:
    """仅当启用且 URL 非空时才认为已配置。"""
    return bool(cfg.enabled and cfg.url.strip())


def _os_name(path: str = "/etc/os-release") -> str:
    """读 os-release 的 PRETTY_NAME（如 Ubuntu 26.04 LTS），取不到返回空串。"""
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _read_dmi(field: str) -> str:
    """读 DMI 字段；无权限/不存在返回空串。"""
    try:
        return (
            Path("/sys/devices/virtual/dmi/id") / field
        ).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _machine_model() -> str:
    """本机型号（网页「类型」列显示用）：优先 DMI 产品名，退回主板名，最后退回架构。

    例：``ADL-N``（迷你主机）、``LENOVO 82RN``（带厂商标识的整机）。
    """
    product = _read_dmi("product_name")
    vendor = _read_dmi("sys_vendor")
    if product and vendor and vendor.lower() not in product.lower():
        return f"{vendor} {product}"
    if product:
        return product
    return _read_dmi("board_name")


def _detect_lan_ip() -> Optional[str]:
    """探测本机局域网 IP（懒加载 provisioning，失败只记日志返回 None）。"""
    try:
        from donkeycar.parts.provisioning import detect_lan_ip
        return detect_lan_ip()
    except Exception:
        logger.warning("findcar 探测局域网 IP 失败", exc_info=True)
        return None


def build_payload(port: int, state: str = STATE_ONLINE) -> dict:
    """构造上报 body（与 Cloudflare Pages Functions 协议一致）。

    ``port`` 由调用方动态取值：DD Web 实例存活时为其实际监听端口（点 IP
    直达 DD 控制台），否则为 launcher 自身端口（点 IP 落到 launcher 菜单页）。
    """
    hostname = socket.gethostname()
    return {
        "device_id": hostname,
        "type": "dd",
        "lan_ip": _detect_lan_ip() or "",
        "port": int(port),
        "hostname": hostname,
        "version": __version__ or "",
        # 主机身份：网页「类型」列显示系统（如 Ubuntu 26.04 LTS 主机），
        # 主板型号（如 ADL-N）只作悬停提示
        "model": _machine_model(),
        "os": _os_name(),
        "state": state,
    }


def _post_report(url: str, body: bytes, timeout: int) -> None:
    """经系统 DNS 常规 POST 一次心跳；成功静默返回，失败抛异常由调用方分类。"""
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _is_dns_failure(err: BaseException) -> bool:
    """异常链（URLError.reason / __cause__ / __context__）里是否是 DNS 解析失败。"""
    seen = set()
    current = err
    while current is not None and id(current) not in seen:
        if isinstance(current, socket.gaierror):
            return True
        seen.add(id(current))
        if not isinstance(current, BaseException):
            break  # URLError.reason 可能是字符串等非异常对象
        reason = getattr(current, "reason", None)
        if reason is not None:
            current = reason
        else:
            current = current.__cause__ or current.__context__
    return False


def _resolve_via_doh(hostname: str, timeout: int) -> Optional[str]:
    """系统 DNS 失效时的兜底解析：按 IP 直连阿里 DoH（dns-json）取 A 记录，失败返回 None。"""
    for server in DOH_SERVERS:
        url = f"https://{server}/resolve?name={hostname}&type=A"
        request = urllib.request.Request(
            url, headers={"Accept": "application/dns-json", "User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.warning("findcar DoH 兜底解析失败（server=%s）", server, exc_info=True)
            continue
        for answer in data.get("Answer", []):
            if answer.get("type") != 1:
                continue
            candidate = str(answer.get("data", "")).strip()
            try:
                return str(IPv4Address(candidate))
            except ValueError:
                continue
    return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """直连指定 IP 的 HTTPS 连接：TCP 拨 IP，TLS SNI 与 Host 头保持原域名。

    Cloudflare 是 anycast：系统 DNS 失效时按 DoH 解析出的 IP 直连，SNI 带上
    原域名即可正确路由，证书校验也仍按原域名进行。
    """

    def __init__(self, sni_host: str, ip: str, timeout: int):
        super().__init__(ip, timeout=timeout)
        self._sni_host = sni_host

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._sni_host)


def _post_report_via_ip(parsed: urllib.parse.SplitResult, ip: str, body: bytes, timeout: int) -> None:
    """DoH 兜底路径：直连 IP 完成 POST；非 2xx 或传输异常都抛出。"""
    host = parsed.hostname
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn = _PinnedHTTPSConnection(host, ip, timeout)
    try:
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                "Host": host,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        response = conn.getresponse()
        response.read()
        if response.status >= 400:
            raise OSError(f"HTTP {response.status}")
    finally:
        conn.close()


def report_once(
    cfg: FindCarConfig, port: int, state: str = STATE_ONLINE, timeout: int = 8
) -> bool:
    """通过 HTTPS POST 上报一次心跳；成功返回 True，异常返回 False。

    在线心跳对 DNS 抖动有韧性：系统 DNS 解析失败时先隔几秒快重试一次，
    仍失败则走 DoH 兜底解析 + 按 IP 直连（SNI/Host 保持原域名）再试——
    「网络通、只是本机 DNS 坏」时心跳仍能送达。下线标记（state=offline）
    保持尽力而为的单发，不在退出路径上拖延关停。
    """
    base = cfg.url.strip().rstrip("/")
    if not base:
        logger.warning("findcar 心跳未上报：未配置 Pages Functions URL")
        return False
    url = base + "/report"
    body = json.dumps(build_payload(port, state), ensure_ascii=False).encode("utf-8")

    try:
        _post_report(url, body, timeout)
        return True
    except Exception as err:
        if state != STATE_ONLINE or not _is_dns_failure(err):
            logger.warning("findcar 心跳上报失败（url=%s）", url, exc_info=True)
            return False

    # 系统 DNS 失败：先快重试一次，吸收秒级抖动
    logger.warning(
        "findcar 心跳 DNS 解析失败（url=%s），%ds 后重试一次",
        url,
        DNS_RETRY_DELAY_SECONDS,
    )
    time.sleep(DNS_RETRY_DELAY_SECONDS)
    try:
        _post_report(url, body, timeout)
        return True
    except Exception as err:
        if not _is_dns_failure(err):
            logger.warning("findcar 心跳上报失败（url=%s）", url, exc_info=True)
            return False

    # 系统 DNS 仍不可用：DoH 兜底解析 + 直连 IP
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    ip = _resolve_via_doh(host, timeout) if host and parsed.scheme == "https" else None
    if not ip:
        logger.warning("findcar 心跳上报失败：DoH 兜底也解析不出 %s", host)
        return False
    try:
        _post_report_via_ip(parsed, ip, body, timeout)
        logger.info("findcar 心跳经 DoH 兜底直连 %s（%s）上报成功", host, ip)
        return True
    except Exception:
        logger.warning(
            "findcar 心跳 DoH 兜底直连失败（%s -> %s）", host, ip, exc_info=True
        )
        return False


def report_offline(cfg: Optional[FindCarConfig] = None, port: int = 8090) -> bool:
    """关停时上报一次下线标记（尽力而为，失败不影响关停）。"""
    try:
        cfg = cfg if cfg is not None else load_config()
        if not is_configured(cfg):
            return False
        return report_once(
            cfg, port, state=STATE_OFFLINE, timeout=OFFLINE_TIMEOUT_SECONDS
        )
    except Exception:
        logger.warning("findcar 下线标记上报异常", exc_info=True)
        return False
