# -*- coding: utf-8 -*-
"""donkeycar.findcar（Find DKC 主机心跳上报核心）单元测试。

上报核心由常驻 launcher 调用（donkeycar/launcher/server.py 的接线测试见
tests/test_launcher_findcar.py）；本文件覆盖：配置读取容错、payload 构造
（动态端口）、report_once 请求契约、下线标记、主机型号/系统探测。
去 token 公开上报版：配置与上报 body 都不带 token。
"""

import json
import logging
import socket
import urllib.error

import pytest

from donkeycar import findcar


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = findcar.load_config(tmp_path / "nonexistent.json")

    assert cfg.url == ""
    assert cfg.enabled is False
    assert cfg.interval_seconds == 150


def test_load_config_round_trip(tmp_path):
    path = tmp_path / "findcar.json"
    path.write_text(
        json.dumps(
            {
                "url": "https://find-dkc.pages.dev",
                "enabled": True,
                "interval_seconds": 60,
            }
        ),
        encoding="utf-8",
    )

    cfg = findcar.load_config(path)

    assert cfg.url == "https://find-dkc.pages.dev"
    assert cfg.enabled is True
    assert cfg.interval_seconds == 60


def test_load_config_corrupted_falls_back_to_defaults(tmp_path):
    path = tmp_path / "findcar.json"
    path.write_text("{bad json", encoding="utf-8")

    cfg = findcar.load_config(path)

    assert cfg.url == ""
    assert cfg.enabled is False


def test_load_config_ignores_legacy_token_field(tmp_path):
    """旧配置里可能残留 token 字段，加载时应被忽略且不影响解析。"""
    path = tmp_path / "findcar.json"
    path.write_text(
        json.dumps(
            {
                "url": "https://find-dkc.pages.dev",
                "token": "legacy-secret",
                "enabled": True,
                "interval_seconds": 120,
            }
        ),
        encoding="utf-8",
    )

    cfg = findcar.load_config(path)

    assert cfg.url == "https://find-dkc.pages.dev"
    assert cfg.enabled is True
    assert cfg.interval_seconds == 120
    assert not hasattr(cfg, "token")


def test_is_configured_requires_enabled_and_url():
    assert not findcar.is_configured(findcar.FindCarConfig())
    assert not findcar.is_configured(
        findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=False)
    )
    assert not findcar.is_configured(
        findcar.FindCarConfig(url="  ", enabled=True)
    )
    assert findcar.is_configured(
        findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)
    )


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


def test_build_payload_fields(monkeypatch):
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")
    monkeypatch.setattr(findcar, "_machine_model", lambda: "ADL-N")
    monkeypatch.setattr(findcar, "_os_name", lambda: "Ubuntu 26.04 LTS")

    body = findcar.build_payload(8000)

    hostname = socket.gethostname()
    assert body["device_id"] == hostname
    assert body["type"] == "dd"
    assert body["lan_ip"] == "192.168.3.10"
    # 端口由调用方动态取值（存活 DD Web 实例端口或 launcher 自身端口）
    assert body["port"] == 8000
    assert body["hostname"] == hostname
    assert body["version"] == findcar.__version__
    # 主机身份字段：网页「类型」列显示系统、悬停显示型号
    assert body["model"] == "ADL-N"
    assert body["os"] == "Ubuntu 26.04 LTS"
    # 默认心跳显式带上在线状态；离线标记由 report_offline 发
    assert body["state"] == "online"
    # 去 token：body 不含 token
    assert "token" not in body


def test_build_payload_offline_state(monkeypatch):
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    body = findcar.build_payload(8090, state=findcar.STATE_OFFLINE)

    assert body["state"] == "offline"
    assert body["port"] == 8090


def test_build_payload_lan_ip_failure_falls_back_to_empty(monkeypatch):
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: None)

    body = findcar.build_payload(8000)

    assert body["lan_ip"] == ""


# ---------------------------------------------------------------------------
# report_once
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload=b"ok"):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _dns_error():
    """模拟系统 DNS 失效：urllib 把 socket.gaierror 包进 URLError.reason。"""
    return urllib.error.URLError(
        socket.gaierror(-3, "Temporary failure in name resolution")
    )


def test_report_once_posts_json_and_returns_true(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev/", enabled=True)
    result = findcar.report_once(cfg, 8000)

    assert result is True
    req = captured["req"]
    # URL 末尾斜杠应被剥掉再拼 /report
    assert req.full_url == "https://find-dkc.pages.dev/report"
    assert req.get_method() == "POST"
    assert captured["timeout"] == 8
    content_type = next(
        (value for key, value in req.headers.items() if key.lower() == "content-type"),
        None,
    )
    assert content_type == "application/json"
    # Cloudflare 会拦截 Python-urllib 默认 UA（403），必须伪装成浏览器 UA
    user_agent = next(
        (value for key, value in req.headers.items() if key.lower() == "user-agent"),
        "",
    )
    assert "DonkeyDrift-FindCar" in user_agent
    assert "Python-urllib" not in user_agent

    body = json.loads(req.data.decode("utf-8"))
    assert body["device_id"] == socket.gethostname()
    assert body["type"] == "dd"
    assert body["lan_ip"] == "192.168.3.10"
    assert body["port"] == 8000
    assert body["state"] == "online"
    assert "token" not in body


def test_report_once_returns_false_on_urlerror(monkeypatch, caplog):
    def raise_urlopen(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(findcar.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev/", enabled=True)
    with caplog.at_level(logging.WARNING, logger="donkeycar.findcar"):
        result = findcar.report_once(cfg, 8000)

    assert result is False


def test_report_once_empty_url_returns_false(monkeypatch, caplog):
    result = findcar.report_once(
        findcar.FindCarConfig(url="", enabled=True), 8000
    )

    assert result is False


# ---------------------------------------------------------------------------
# DNS 抖动韧性（快重试 + DoH 兜底直连）
# ---------------------------------------------------------------------------


def test_is_dns_failure_recognizes_gaierror_in_chain():
    dns_err = urllib.error.URLError(
        socket.gaierror(-3, "Temporary failure in name resolution")
    )
    assert findcar._is_dns_failure(dns_err) is True
    assert findcar._is_dns_failure(socket.gaierror(-2, "Name or service not known")) is True
    assert findcar._is_dns_failure(urllib.error.URLError("boom")) is False
    assert findcar._is_dns_failure(urllib.error.URLError(TimeoutError("timed out"))) is False


def test_report_once_dns_failure_quick_retry_succeeds(monkeypatch):
    """系统 DNS 秒级抖动：快重试一次即恢复，不触发 DoH 兜底。"""
    calls = []

    def flaky_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise _dns_error()
        return _FakeResponse()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(findcar.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)
    assert findcar.report_once(cfg, 8000) is True
    # 首发 + 快重试共两次，未走 DoH
    assert calls == ["https://find-dkc.pages.dev/report"] * 2


def test_report_once_dns_failure_recovers_via_doh(monkeypatch):
    """系统 DNS 持续失效：DoH 兜底解析 + 直连 IP（SNI/Host 保持原域名）上报成功。"""
    report_calls = []

    def urlopen(req, timeout=None):
        if "/resolve?" in req.full_url:
            payload = json.dumps(
                {"Answer": [{"type": 1, "data": "104.21.36.120"}]}
            ).encode("utf-8")
            return _FakeResponse(payload)
        report_calls.append(req.full_url)
        raise _dns_error()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(findcar.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    connections = []

    class _FakeConn:
        def __init__(self, sni_host, ip, timeout):
            self.sni_host = sni_host
            self.ip = ip
            connections.append(self)

        def request(self, method, path, body=None, headers=None):
            self.method = method
            self.path = path
            self.headers = headers

        def getresponse(self):
            class _Resp:
                status = 200

                def read(self):
                    return b""

            return _Resp()

        def close(self):
            pass

    monkeypatch.setattr(findcar, "_PinnedHTTPSConnection", _FakeConn)

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)
    assert findcar.report_once(cfg, 8000) is True

    # 常规路径首发 + 快重试都 DNS 失败，随后走 DoH 直连
    assert report_calls == ["https://find-dkc.pages.dev/report"] * 2
    assert len(connections) == 1
    conn = connections[0]
    assert conn.sni_host == "find-dkc.pages.dev"
    assert conn.ip == "104.21.36.120"
    assert conn.method == "POST"
    assert conn.path == "/report"
    assert conn.headers["Host"] == "find-dkc.pages.dev"


def test_report_once_dns_failure_all_fallbacks_fail_returns_false(monkeypatch):
    """系统 DNS 与 DoH 兜底都失败：返回 False、不抛异常（循环下一跳再试）。"""
    def raise_urlopen(req, timeout=None):
        raise _dns_error()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setattr(findcar.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)
    assert findcar.report_once(cfg, 8000) is False


def test_report_once_offline_state_skips_dns_retry(monkeypatch):
    """下线标记保持尽力而为单发：DNS 失败不重试、不走 DoH，绝不拖延关停。"""
    calls = []

    def raise_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise _dns_error()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)
    result = findcar.report_once(cfg, 8090, state=findcar.STATE_OFFLINE, timeout=1)

    assert result is False
    assert calls == ["https://find-dkc.pages.dev/report"]  # 只发一次


# ---------------------------------------------------------------------------
# 下线标记（关停时立即显示「离线」）
# ---------------------------------------------------------------------------


def test_report_offline_posts_offline_state_with_short_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(findcar.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(findcar, "_detect_lan_ip", lambda: "192.168.3.10")

    cfg = findcar.FindCarConfig(url="https://find-dkc.pages.dev", enabled=True)

    assert findcar.report_offline(cfg, port=8090) is True
    assert captured["body"]["state"] == "offline"
    assert captured["body"]["port"] == 8090
    assert captured["timeout"] == findcar.OFFLINE_TIMEOUT_SECONDS


def test_report_offline_returns_false_when_not_configured(monkeypatch):
    def fail_urlopen(req, timeout=None):  # pragma: no cover - 不应被调用
        raise AssertionError("未配置时不应发起请求")

    monkeypatch.setattr(findcar.urllib.request, "urlopen", fail_urlopen)

    assert (
        findcar.report_offline(findcar.FindCarConfig(url="", enabled=False))
        is False
    )


def test_report_offline_swallows_errors(monkeypatch):
    monkeypatch.setattr(
        findcar,
        "load_config",
        lambda path=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert findcar.report_offline() is False


# ---------------------------------------------------------------------------
# 主机身份（型号 / 系统）——网页「类型」列显示用
# ---------------------------------------------------------------------------


def test_machine_model_uses_dmi_product_name(monkeypatch):
    monkeypatch.setattr(
        findcar,
        "_read_dmi",
        lambda field: {
            "product_name": "ADL-N",
            "sys_vendor": "",
            "board_name": "ADL-N",
        }.get(field, ""),
    )

    assert findcar._machine_model() == "ADL-N"


def test_machine_model_prefixes_vendor_when_not_in_product(monkeypatch):
    monkeypatch.setattr(
        findcar,
        "_read_dmi",
        lambda field: {"product_name": "82RN", "sys_vendor": "LENOVO"}.get(field, ""),
    )

    assert findcar._machine_model() == "LENOVO 82RN"


def test_machine_model_keeps_product_when_vendor_already_included(monkeypatch):
    monkeypatch.setattr(
        findcar,
        "_read_dmi",
        lambda field: {
            "product_name": "LENOVO ThinkPad X1",
            "sys_vendor": "LENOVO",
        }.get(field, ""),
    )

    assert findcar._machine_model() == "LENOVO ThinkPad X1"


def test_machine_model_falls_back_to_board_name(monkeypatch):
    monkeypatch.setattr(
        findcar,
        "_read_dmi",
        lambda field: {"board_name": "ADL-N"}.get(field, ""),
    )

    assert findcar._machine_model() == "ADL-N"


def test_machine_model_empty_when_dmi_unavailable(monkeypatch):
    """DMI 读不到（非 x86 / 无权限）时不抛异常，返回空串，网页再退回主机名。"""
    monkeypatch.setattr(findcar, "_read_dmi", lambda field: "")

    assert findcar._machine_model() == ""


def test_os_name_reads_pretty_name(tmp_path):
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04 LTS"\nVERSION_ID="26.04"\n',
        encoding="utf-8",
    )

    assert findcar._os_name(str(os_release)) == "Ubuntu 26.04 LTS"


def test_os_name_missing_file_returns_empty(tmp_path):
    assert findcar._os_name(str(tmp_path / "nope")) == ""
