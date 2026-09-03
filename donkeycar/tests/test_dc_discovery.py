"""dc_discovery（Drifter Console 局域网发现）单元测试。

不真正发起网络请求：urllib.request.urlopen / 子网扫描的输入全部打桩，
覆盖缓存命中、AP 固定地址优先、/24 网段扫描、特征校验失败等路径。
"""

from unittest.mock import MagicMock

import pytest

from donkeycar.launcher import dc_discovery


@pytest.fixture(autouse=True)
def reset_cache():
    """每个用例前清空模块级缓存，避免用例间互相污染。"""
    dc_discovery._cache["url"] = None
    dc_discovery._cache["expires"] = 0.0
    yield
    dc_discovery._cache["url"] = None
    dc_discovery._cache["expires"] = 0.0


def make_urlopen_response(status=200, text=""):
    """构造可用作 with 语句的伪 HTTP 响应。"""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = text.encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


MUS4_STATUS_TEXT = "version=1.8.65 ap_ip=192.168.4.1 mode=STA"


# ---------------------------------------------------------------------------
# _probe：/api/status 特征校验
# ---------------------------------------------------------------------------


class TestProbe:
    def test_matching_features_returns_url(self, monkeypatch):
        calls = []

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            return make_urlopen_response(text=MUS4_STATUS_TEXT)

        monkeypatch.setattr(dc_discovery.urllib.request, "urlopen", fake_urlopen)

        assert dc_discovery._probe("192.168.3.46") == "http://192.168.3.46/"
        assert calls == ["http://192.168.3.46/api/status"]

    def test_missing_feature_returns_none(self, monkeypatch):
        # 缺 ap_ip= 字段：不是 MUS4 Drifter Console，不能命中
        monkeypatch.setattr(
            dc_discovery.urllib.request, "urlopen",
            lambda url, timeout=None: make_urlopen_response(text="version=1.8.65"),
        )
        assert dc_discovery._probe("192.168.3.46") is None

    def test_no_features_returns_none(self, monkeypatch):
        # 普通路由器/其它设备首页特征：version= / ap_ip= 都没有
        monkeypatch.setattr(
            dc_discovery.urllib.request, "urlopen",
            lambda url, timeout=None: make_urlopen_response(text="<html>router</html>"),
        )
        assert dc_discovery._probe("192.168.3.1") is None

    def test_non_200_status_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            dc_discovery.urllib.request, "urlopen",
            lambda url, timeout=None: make_urlopen_response(status=500, text=MUS4_STATUS_TEXT),
        )
        assert dc_discovery._probe("192.168.3.46") is None

    def test_network_error_returns_none(self, monkeypatch):
        def raise_timeout(url, timeout=None):
            raise TimeoutError("probe timeout")

        monkeypatch.setattr(dc_discovery.urllib.request, "urlopen", raise_timeout)
        assert dc_discovery._probe("10.255.255.1") is None


# ---------------------------------------------------------------------------
# find_drifter_console：缓存 / AP 优先 / 网段扫描
# ---------------------------------------------------------------------------


class TestFindDrifterConsole:
    def test_cache_hit_skips_probing(self, monkeypatch):
        dc_discovery._cache["url"] = "http://192.168.3.46/"
        dc_discovery._cache["expires"] = dc_discovery.time.monotonic() + 60.0

        probe = MagicMock()
        monkeypatch.setattr(dc_discovery, "_probe", probe)

        assert dc_discovery.find_drifter_console() == "http://192.168.3.46/"
        probe.assert_not_called()

    def test_expired_cache_probes_again(self, monkeypatch):
        dc_discovery._cache["url"] = "http://192.168.3.46/"
        dc_discovery._cache["expires"] = dc_discovery.time.monotonic() - 1.0  # 已过期

        monkeypatch.setattr(
            dc_discovery, "_probe",
            lambda ip: "http://192.168.4.1/" if ip == "192.168.4.1" else None,
        )

        assert dc_discovery.find_drifter_console() == "http://192.168.4.1/"
        assert dc_discovery._cache["url"] == "http://192.168.4.1/"

    def test_force_bypasses_cache(self, monkeypatch):
        dc_discovery._cache["url"] = "http://192.168.3.46/"
        dc_discovery._cache["expires"] = dc_discovery.time.monotonic() + 60.0

        monkeypatch.setattr(
            dc_discovery, "_probe",
            lambda ip: "http://192.168.4.1/" if ip == "192.168.4.1" else None,
        )

        assert dc_discovery.find_drifter_console(force=True) == "http://192.168.4.1/"

    def test_ap_gateway_probed_before_subnet_scan(self, monkeypatch):
        """连车辆 AP 时 192.168.4.1 直接命中，不做全网段扫描。"""
        probed = []

        def fake_probe(ip):
            probed.append(ip)
            if ip == dc_discovery._AP_GATEWAY:
                return "http://192.168.4.1/"
            return None

        monkeypatch.setattr(dc_discovery, "_probe", fake_probe)
        scan = MagicMock()
        monkeypatch.setattr(dc_discovery, "_scan_subnet", scan)

        assert dc_discovery.find_drifter_console() == "http://192.168.4.1/"
        assert probed == ["192.168.4.1"]
        scan.assert_not_called()
        assert dc_discovery._cache["url"] == "http://192.168.4.1/"

    def test_falls_back_to_subnet_scan(self, monkeypatch):
        """AP 地址未命中时扫描本机 /24 网段，按地址序返回首个命中。"""
        probed = []

        def fake_probe(ip):
            probed.append(ip)
            if ip == "192.168.3.46":
                return "http://192.168.3.46/"
            return None

        monkeypatch.setattr(dc_discovery, "_probe", fake_probe)
        monkeypatch.setattr(dc_discovery, "_local_lan_ip", lambda: "192.168.3.45")

        assert dc_discovery.find_drifter_console() == "http://192.168.3.46/"
        assert probed[0] == "192.168.4.1"  # AP 固定地址先探
        assert "192.168.3.46" in probed
        assert "192.168.3.45" not in probed  # 不探本机地址
        assert dc_discovery._cache["url"] == "http://192.168.3.46/"
        assert dc_discovery._cache["expires"] > dc_discovery.time.monotonic()

    def test_scan_skips_local_ip_candidates(self, monkeypatch):
        """网段扫描候选不包含本机地址。"""
        monkeypatch.setattr(dc_discovery, "_local_lan_ip", lambda: "192.168.3.45")
        pool_ctx = MagicMock()
        pool_ctx.__enter__ = MagicMock(return_value=pool_ctx)
        pool_ctx.__exit__ = MagicMock(return_value=False)
        # 候选地址由 pool.map 的入参捕获
        pool_ctx.map = MagicMock(side_effect=lambda fn, candidates: iter([]))

        class FakeThreadPool:
            def __init__(self, max_workers=None):
                pass

            def __enter__(self):
                return pool_ctx

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(
            dc_discovery, "ThreadPoolExecutor",
            lambda max_workers=None: FakeThreadPool(),
        )

        dc_discovery._scan_subnet()
        candidates = pool_ctx.map.call_args[0][1]
        assert len(candidates) == 253
        assert "192.168.3.45" not in candidates
        assert "192.168.3.1" in candidates
        assert "192.168.3.254" in candidates

    def test_no_local_ip_no_scan(self, monkeypatch):
        monkeypatch.setattr(dc_discovery, "_probe", lambda ip: None)
        monkeypatch.setattr(dc_discovery, "_local_lan_ip", lambda: None)

        assert dc_discovery.find_drifter_console() is None
        # 未命中不写缓存
        assert dc_discovery._cache["url"] is None
        assert dc_discovery._cache["expires"] == 0.0

    def test_not_found_does_not_cache(self, monkeypatch):
        monkeypatch.setattr(dc_discovery, "_probe", lambda ip: None)
        monkeypatch.setattr(dc_discovery, "_local_lan_ip", lambda: "192.168.3.45")

        assert dc_discovery.find_drifter_console() is None
        assert dc_discovery._cache["url"] is None
