import asyncio
import re
import socket
import subprocess


DISCOVER_TIMEOUT = 0.4
DISCOVER_MAX_CONCURRENT = 64


async def check_host_port(host: str, port: int, timeout: float = DISCOVER_TIMEOUT):
    """Try to open a TCP connection to host:port and return latency info."""
    try:
        loop = asyncio.get_event_loop()
        start = loop.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        latency = (loop.time() - start) * 1000
        return {"ip": host, "port": port, "latency_ms": round(latency, 1), "reachable": True}
    except Exception:
        return None


def get_default_gateway():
    """Return the default gateway IP (WSL2 host or router)."""
    try:
        result = subprocess.run(
            ["ip", "route", "show"], capture_output=True, text=True
        )
        if result.returncode == 0:
            match = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def _extract_subnet(ip: str) -> str | None:
    """从 IPv4 地址提取 /24 子网前缀，仅对 RFC1918 地址返回。"""
    if ip.startswith("127.") or ip.startswith("169.254."):
        return None
    if ip.startswith("192.168.") or ip.startswith("10."):
        parts = ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    if ip.startswith("172."):
        second = int(ip.split(".")[1])
        if 16 <= second <= 31:
            parts = ip.split(".")
            return f"{parts[0]}.{parts[1]}.{parts[2]}"
    return None


def get_local_subnets() -> list[str]:
    """Return all LAN subnet prefixes of non-loopback RFC1918 interfaces."""
    subnets = set()

    # 1. Try psutil
    try:
        import psutil

        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            # 跳过回环接口
            if iface.lower() in ("lo", "loopback"):
                continue
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    subnet = _extract_subnet(addr.address)
                    if subnet:
                        subnets.add(subnet)
    except Exception:
        pass

    # 2. Fallback: parse 'ip route' for RFC1918 source addresses
    try:
        result = subprocess.run(
            ["ip", "route", "show"], capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            match = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", line)
            if match:
                subnet = _extract_subnet(match.group(1))
                if subnet:
                    subnets.add(subnet)
    except Exception:
        pass

    # 3. WSL fallback: use ipconfig.exe
    try:
        result = subprocess.run(["ipconfig.exe"], capture_output=True)
        if result.returncode == 0:
            output = result.stdout
            try:
                text = output.decode("gbk")
            except Exception:
                text = output.decode("utf-8", errors="ignore")
            for line in text.splitlines():
                if "IPv4" in line or "IP Address" in line:
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if match:
                        subnet = _extract_subnet(match.group(1))
                        if subnet:
                            subnets.add(subnet)
    except Exception:
        pass

    return sorted(subnets)


def get_local_subnet() -> str | None:
    """Return the first LAN subnet prefix (backwards compatibility)."""
    subnets = get_local_subnets()
    return subnets[0] if subnets else None


def get_wsl_host_ip():
    """Get the WSL2 Windows host IP from /etc/resolv.conf (nameserver)."""
    try:
        with open("/etc/resolv.conf", "r") as f:
            content = f.read()
            match = re.search(r"nameserver\s+(\d+\.\d+\.\d+\.\d+)", content)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def get_local_ips() -> list[dict]:
    """获取本机非回环 IPv4 地址列表，优先 RFC1918 私有地址。"""
    candidates = []
    try:
        import psutil

        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip.startswith("127."):
                        continue
                    priority = 2
                    if ip.startswith("192.168.") or ip.startswith("10."):
                        priority = 0
                    elif ip.startswith("172."):
                        second = int(ip.split(".")[1])
                        if 16 <= second <= 31:
                            priority = 0
                    elif ip.startswith("169.254."):
                        priority = 1
                    candidates.append({"ip": ip, "interface": iface, "priority": priority})
    except Exception:
        pass
    candidates.sort(key=lambda x: x["priority"])
    return candidates


async def discover_hosts(
    port: int,
    timeout: float = DISCOVER_TIMEOUT,
    max_concurrent: int = DISCOVER_MAX_CONCURRENT,
):
    """Scan common addresses and the local /24 subnet for open ports."""
    candidates = []

    # 1. Always check localhost first
    candidates.append("127.0.0.1")

    # 2. Check default gateway and its /24 subnet
    gw = get_default_gateway()
    if gw and gw not in candidates:
        candidates.append(gw)
        gw_parts = gw.split(".")
        if len(gw_parts) == 4:
            gw_subnet = f"{gw_parts[0]}.{gw_parts[1]}.{gw_parts[2]}"
            for i in range(1, 255):
                ip = f"{gw_subnet}.{i}"
                if ip not in candidates:
                    candidates.append(ip)

    # 3. WSL2 /etc/resolv.conf nameserver
    wsl_host = get_wsl_host_ip()
    if wsl_host and wsl_host not in candidates:
        candidates.append(wsl_host)

    # 4. Scan all local subnets
    subnets = get_local_subnets()
    for subnet in subnets:
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            if ip not in candidates:
                candidates.append(ip)

    # 5. Fallback: scan common home router subnets
    if not subnets:
        common_subnets = [
            "192.168.0",
            "192.168.1",
            "192.168.3",
            "192.168.31",
            "192.168.50",
        ]
        for cs in common_subnets:
            for i in range(1, 255):
                ip = f"{cs}.{i}"
                if ip not in candidates:
                    candidates.append(ip)
            if len(candidates) >= 500:
                break

    # 6. Cap total candidates
    if len(candidates) > 500:
        candidates = candidates[:500]

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _probe(host):
        async with semaphore:
            return await check_host_port(host, port, timeout)

    tasks = [_probe(host) for host in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    found = []
    for r in results:
        if isinstance(r, dict) and r.get("reachable"):
            found.append(r)

    found.sort(key=lambda x: x["latency_ms"])
    return found, len(candidates)
