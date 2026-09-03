"""network_utils 局域网发现底层扫描算法直接单测。

不真正发起网络/系统调用：psutil、subprocess.run、asyncio.open_connection
全部打桩，只验证候选地址构造、并发探测、超时/异常吞掉与 500 地址上限。
"""

import asyncio
import socket
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import network_utils  # noqa: E402


# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------


def make_addr(address, family=socket.AF_INET):
    return types.SimpleNamespace(family=family, address=address)


def install_fake_psutil(monkeypatch, ifaces):
    """把伪 psutil 注入 sys.modules（get_local_subnets 内部 import psutil）。"""
    fake = types.SimpleNamespace(
        net_if_addrs=lambda: {
            name: addrs for name, addrs in ifaces.items()
        }
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)


def no_subprocess(monkeypatch):
    """让 subprocess.run 一律失败，屏蔽 ip route / ipconfig.exe 回退路径。"""
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError(args[0] if args else "cmd")

    monkeypatch.setattr(network_utils.subprocess, "run", raise_missing)


# ---------------------------------------------------------------------------
# get_local_subnets
# ---------------------------------------------------------------------------


class TestGetLocalSubnets:
    def test_collects_rfc1918_subnets_sorted(self, monkeypatch):
        install_fake_psutil(monkeypatch, {
            "wlan0": [make_addr("192.168.3.10")],
            "eth0": [make_addr("10.0.0.5")],
            "docker0": [make_addr("172.20.1.5")],
        })
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == [
            "10.0.0", "172.20.1", "192.168.3",
        ]

    def test_skips_loopback_and_link_local(self, monkeypatch):
        install_fake_psutil(monkeypatch, {
            "lo": [make_addr("127.0.0.1")],
            "wlan0": [make_addr("192.168.3.10"), make_addr("169.254.7.7")],
        })
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == ["192.168.3"]

    def test_skips_loopback_interface(self, monkeypatch):
        install_fake_psutil(monkeypatch, {
            "lo": [make_addr("192.168.99.1")],  # 回环接口即使挂私网地址也跳过
            "wlan0": [make_addr("192.168.3.10")],
        })
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == ["192.168.3"]

    def test_172_outside_rfc1918_range_excluded(self, monkeypatch):
        install_fake_psutil(monkeypatch, {
            "eth0": [make_addr("172.32.1.5")],
            "wlan0": [make_addr("172.16.1.5")],
        })
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == ["172.16.1"]

    def test_ignores_non_ipv4_families(self, monkeypatch):
        install_fake_psutil(monkeypatch, {
            "wlan0": [
                make_addr("fe80::1a2b", family=socket.AF_INET6),
                make_addr("192.168.3.10"),
            ],
        })
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == ["192.168.3"]

    def test_psutil_failure_falls_back_to_ip_route(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil 抛 ImportError

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ip":
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=(
                        "default via 192.168.3.1 dev wlan0\n"
                        "192.168.3.0/24 dev wlan0 proto kernel scope link src 192.168.3.10\n"
                    ),
                )
            raise FileNotFoundError(cmd[0])  # ipconfig.exe 不存在

        monkeypatch.setattr(network_utils.subprocess, "run", fake_run)

        assert network_utils.get_local_subnets() == ["192.168.3"]

    def test_no_sources_returns_empty(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psutil", None)
        no_subprocess(monkeypatch)

        assert network_utils.get_local_subnets() == []


# ---------------------------------------------------------------------------
# check_host_port（discover_hosts 的探测原语）
# ---------------------------------------------------------------------------


class TestCheckHostPort:
    def test_success_returns_reachable_with_latency(self, monkeypatch):
        class FakeWriter:
            def close(self):
                pass

            async def wait_closed(self):
                pass

        async def fake_open_connection(host, port):
            return ("reader", FakeWriter())

        monkeypatch.setattr(network_utils.asyncio, "open_connection", fake_open_connection)

        result = asyncio.run(network_utils.check_host_port("192.168.3.46", 80, timeout=0.5))
        assert result == {
            "ip": "192.168.3.46", "port": 80,
            "latency_ms": result["latency_ms"], "reachable": True,
        }
        assert result["latency_ms"] >= 0

    def test_timeout_returns_none(self, monkeypatch):
        async def slow_connect(host, port):
            await asyncio.sleep(5)

        monkeypatch.setattr(network_utils.asyncio, "open_connection", slow_connect)

        assert asyncio.run(
            network_utils.check_host_port("10.255.255.1", 80, timeout=0.05)
        ) is None

    def test_connection_refused_returns_none(self, monkeypatch):
        async def refused(host, port):
            raise ConnectionRefusedError()

        monkeypatch.setattr(network_utils.asyncio, "open_connection", refused)

        assert asyncio.run(network_utils.check_host_port("127.0.0.1", 9999)) is None


# ---------------------------------------------------------------------------
# discover_hosts
# ---------------------------------------------------------------------------


def patch_topology(monkeypatch, *, gateway=None, wsl_host=None, subnets=()):
    monkeypatch.setattr(network_utils, "get_default_gateway", lambda: gateway)
    monkeypatch.setattr(network_utils, "get_wsl_host_ip", lambda: wsl_host)
    monkeypatch.setattr(network_utils, "get_local_subnets", lambda: list(subnets))


class TestDiscoverHosts:
    def test_found_sorted_by_latency(self, monkeypatch):
        patch_topology(monkeypatch, gateway="192.168.3.1", subnets=["192.168.3"])

        async def fake_check(host, port, timeout):
            table = {
                "127.0.0.1": 8.0,
                "192.168.3.46": 1.2,
                "192.168.3.10": 5.0,
            }
            if host in table:
                return {"ip": host, "port": port, "latency_ms": table[host], "reachable": True}
            return None

        monkeypatch.setattr(network_utils, "check_host_port", fake_check)

        found, scanned = asyncio.run(network_utils.discover_hosts(80))

        assert scanned == 1 + 254  # 127.0.0.1 + 网关 /24 网段（子网重复不重复计）
        assert [f["ip"] for f in found] == ["192.168.3.46", "192.168.3.10", "127.0.0.1"]
        assert all(f["port"] == 80 for f in found)

    def test_candidate_order_localhost_gateway_wsl_first(self, monkeypatch):
        patch_topology(
            monkeypatch,
            gateway="192.168.1.1",
            wsl_host="172.30.0.1",
            subnets=["192.168.1"],
        )
        seen = []

        async def fake_check(host, port, timeout):
            seen.append(host)
            return None

        monkeypatch.setattr(network_utils, "check_host_port", fake_check)

        _, scanned = asyncio.run(network_utils.discover_hosts(80))

        assert scanned == 1 + 254 + 1  # localhost + 网关 /24 + WSL 宿主
        assert seen[0] == "127.0.0.1"
        assert seen[1] == "192.168.1.1"
        assert seen[2] == "192.168.1.2"
        assert "172.30.0.1" in seen

    def test_exception_from_probe_is_swallowed(self, monkeypatch):
        patch_topology(monkeypatch, subnets=["192.168.3"])

        async def flaky_check(host, port, timeout):
            if host == "192.168.3.46":
                return {"ip": host, "port": port, "latency_ms": 1.0, "reachable": True}
            if host == "192.168.3.50":
                raise RuntimeError("probe crashed")
            return None

        monkeypatch.setattr(network_utils, "check_host_port", flaky_check)

        found, scanned = asyncio.run(network_utils.discover_hosts(80))

        assert scanned == 1 + 254
        assert [f["ip"] for f in found] == ["192.168.3.46"]

    def test_candidates_capped_at_500(self, monkeypatch):
        # 网关 /24（255）+ 三个不重叠子网（各 254）远超上限，只扫前 500 个
        patch_topology(
            monkeypatch,
            gateway="192.168.1.1",
            subnets=["192.168.1", "192.168.2", "192.168.4"],
        )
        probed = []

        async def fake_check(host, port, timeout):
            probed.append(host)
            return None

        monkeypatch.setattr(network_utils, "check_host_port", fake_check)

        _, scanned = asyncio.run(network_utils.discover_hosts(80))

        assert scanned == 500
        assert len(probed) == 500
        assert len(set(probed)) == 500  # 无重复地址

    def test_no_subnet_falls_back_to_common_home_subnets(self, monkeypatch):
        patch_topology(monkeypatch, gateway=None, wsl_host=None, subnets=[])

        async def fake_check(host, port, timeout):
            if host == "192.168.1.100":
                return {"ip": host, "port": port, "latency_ms": 2.0, "reachable": True}
            return None

        monkeypatch.setattr(network_utils, "check_host_port", fake_check)

        found, scanned = asyncio.run(network_utils.discover_hosts(80))

        # localhost + 常用家用网段，达到 500 即止
        assert scanned == 500
        assert [f["ip"] for f in found] == ["192.168.1.100"]

    def test_no_sources_still_probes_localhost(self, monkeypatch):
        patch_topology(monkeypatch, gateway=None, wsl_host=None, subnets=[])
        # 覆盖上面的网段回退：连回退网段也不扫（构造 500 个不可达即可，此处直接断言 localhost 在列）
        probed = []

        async def fake_check(host, port, timeout):
            probed.append(host)
            return None

        monkeypatch.setattr(network_utils, "check_host_port", fake_check)

        _, scanned = asyncio.run(network_utils.discover_hosts(8080))

        assert "127.0.0.1" in probed
        assert scanned >= 1
