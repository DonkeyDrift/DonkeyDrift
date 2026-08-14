"""Drifter Console（ESP32 Web Console）局域网发现。

固件 v1.7.14 起默认禁用 mDNS/NetBIOS/LLMNR 名称发现
（`DISABLE_WIFI_NAME_DISCOVERY`），无法依赖 `mus4-esp.local` 主机名；
本模块通过探测 `/api/status` 的 MUS4 特征字段（`version=` / `ap_ip=`）
在局域网内定位车辆。仅依赖标准库，供 launcher server 与 tui 共用。
"""

import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_AP_GATEWAY = "192.168.4.1"  # 车辆 AP 模式下的固定地址
_CACHE_TTL_S = 60.0          # 发现结果缓存秒数，避免每次点击都全网扫描
_PROBE_TIMEOUT_S = 0.6
_SCAN_WORKERS = 48

_cache = {"url": None, "expires": 0.0}
_cache_lock = threading.Lock()


def _local_lan_ip():
    """获取本机局域网 IP（优先 192.168.x.x，排除 VPN/TUN 接口）。"""
    import subprocess
    try:
        result = subprocess.check_output(
            ["hostname", "-I"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        ips = result.split()
        for ip in ips:
            if ip.startswith("192.168."):
                return ip
        for ip in ips:
            if not ip.startswith("127.") and not ip.startswith("198.18."):
                return ip
    except Exception:
        pass
    return None


def _probe(ip):
    """探测 http://<ip>/api/status 是否为 MUS4 Drifter Console，是则返回首页 URL。"""
    try:
        with urllib.request.urlopen(
            f"http://{ip}/api/status", timeout=_PROBE_TIMEOUT_S
        ) as resp:
            if resp.status != 200:
                return None
            text = resp.read(4096).decode("utf-8", "ignore")
        if "version=" in text and "ap_ip=" in text:
            return f"http://{ip}/"
    except Exception:
        pass
    return None


def _scan_subnet():
    """并行扫描本机所在 /24 网段，返回首个命中的 Drifter Console URL。"""
    local_ip = _local_lan_ip()
    if not local_ip:
        return None
    prefix = local_ip.rsplit(".", 1)[0]
    candidates = [
        f"{prefix}.{i}" for i in range(1, 255)
        if f"{prefix}.{i}" != local_ip
    ]
    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
        for url in pool.map(_probe, candidates):
            if url:
                return url
    return None


def find_drifter_console(force=False):
    """定位 Drifter Console，返回其 URL（如 http://192.168.3.46/），找不到返回 None。

    顺序：60 秒缓存 → 车辆 AP 固定地址 192.168.4.1 → 本机所在 /24 网段并行扫描。
    """
    now = time.monotonic()
    with _cache_lock:
        if not force and _cache["url"] and now < _cache["expires"]:
            return _cache["url"]

    # 先探车辆 AP 固定地址（连接车辆 AP 时立即命中，免全网扫描），
    # 未命中再并行扫描本机所在 /24 网段（车辆连家用 Wi-Fi 走 DHCP 的场景）
    url = _probe(_AP_GATEWAY)
    if url is None:
        url = _scan_subnet()

    if url:
        with _cache_lock:
            _cache["url"] = url
            _cache["expires"] = time.monotonic() + _CACHE_TTL_S
    return url
