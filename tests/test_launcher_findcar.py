# -*- coding: utf-8 -*-
"""Launcher 的 Find DKC 主机心跳接线测试（donkeycar/launcher/server.py）。

主机（type=dd）上报挂在常驻 launcher 上：只要开机、launcher 服务在跑，
Find DKC 就能找到本机，不再依赖按需启动的 DD Web。覆盖：
- _findcar_report_once：未配置不上报；DD Web 实例存活时报其实际端口，
  否则回退 launcher 自身端口
- _findcar_reporter_loop：启动立即上报、按配置间隔重复、异常不中断
- _report_findcar_offline：关停补发下线标记、异常吞掉
- SIGTERM 处理器与 run_server 接线（起心跳线程、退出路径补发下线标记）

上报核心本身（payload/请求契约）的测试见 tests/test_findcar.py。
"""

import signal

import pytest

from donkeycar import findcar
from donkeycar.launcher import server as launcher_server


_CONFIGURED = findcar.FindCarConfig(
    url="https://find-dkc.pages.dev", enabled=True, interval_seconds=1
)
_CONFIGURED_SLOW = findcar.FindCarConfig(
    url="https://find-dkc.pages.dev", enabled=True, interval_seconds=300
)


# ---------------------------------------------------------------------------
# _findcar_report_once：端口动态取值
# ---------------------------------------------------------------------------


def test_findcar_report_once_uses_live_instance_port(monkeypatch):
    """DD Web 实例存活时上报其 backend_port（点 IP 直达 DD 控制台）。"""
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED)
    monkeypatch.setattr(
        launcher_server,
        "find_live_instance",
        lambda: {"pid": 123, "backend_port": 8000, "frontend_port": 8000},
    )
    reported = []
    monkeypatch.setattr(
        findcar,
        "report_once",
        lambda cfg, port: reported.append(port) or True,
    )

    launcher_server._findcar_report_once(8090)

    assert reported == [8000]


def test_findcar_report_once_falls_back_to_launcher_port(monkeypatch):
    """无存活 DD Web 实例时回退 launcher 自身端口（点 IP 落到菜单页）。"""
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED)
    monkeypatch.setattr(launcher_server, "find_live_instance", lambda: None)
    reported = []
    monkeypatch.setattr(
        findcar,
        "report_once",
        lambda cfg, port: reported.append(port) or True,
    )

    launcher_server._findcar_report_once(8090)

    assert reported == [8090]


def test_findcar_report_once_skips_when_not_configured(monkeypatch):
    """未配置时不探测实例、不上报，直接返回。"""
    monkeypatch.setattr(findcar, "load_config", findcar.FindCarConfig)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("未配置时不应探测实例或上报")

    monkeypatch.setattr(launcher_server, "find_live_instance", must_not_be_called)
    monkeypatch.setattr(findcar, "report_once", must_not_be_called)

    assert launcher_server._findcar_report_once(8090) is None


def test_findcar_report_once_returns_success_flag(monkeypatch):
    """上报成败标志透传给循环（False 触发快速补跳，True/None 按正常间隔）。"""
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED)
    monkeypatch.setattr(launcher_server, "find_live_instance", lambda: None)
    monkeypatch.setattr(findcar, "report_once", lambda cfg, port: False)

    assert launcher_server._findcar_report_once(8090) is False


# ---------------------------------------------------------------------------
# _findcar_reporter_loop：周期与容错
# ---------------------------------------------------------------------------


class _StopLoop(Exception):
    pass


def _fake_event_factory(waits, stop_after):
    class _FakeEvent:
        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) >= stop_after:
                raise _StopLoop()
            return False

    return _FakeEvent


def test_findcar_reporter_loop_reports_immediately_and_repeats(monkeypatch):
    """启动立即上报一次，随后按配置间隔重复；每轮重新读配置拿间隔。"""
    reports = []
    monkeypatch.setattr(
        launcher_server, "_findcar_report_once", lambda port: reports.append(port)
    )
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED)

    waits = []
    monkeypatch.setattr(
        launcher_server.threading, "Event", _fake_event_factory(waits, 3)
    )

    with pytest.raises(_StopLoop):
        launcher_server._findcar_reporter_loop(8090)

    assert reports == [8090, 8090, 8090]
    # 间隔来自配置（_CONFIGURED.interval_seconds == 1）
    assert waits == [1, 1, 1]


def test_findcar_reporter_loop_survives_exceptions(monkeypatch):
    """上报或配置读取抛异常不中断循环，间隔退回默认值。"""
    calls = []

    def flaky(port):
        calls.append(port)
        if len(calls) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(launcher_server, "_findcar_report_once", flaky)
    monkeypatch.setattr(
        findcar,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    waits = []
    monkeypatch.setattr(
        launcher_server.threading, "Event", _fake_event_factory(waits, 2)
    )

    with pytest.raises(_StopLoop):
        launcher_server._findcar_reporter_loop(8090)

    # 首轮上报抛异常未中断循环，第二轮仍继续上报
    assert calls == [8090, 8090]
    # 配置读取失败时间隔退回默认值
    assert waits == [findcar.DEFAULT_INTERVAL_SECONDS] * 2


def test_findcar_reporter_loop_retries_quickly_after_failure(monkeypatch):
    """上报失败不睡满整个间隔：30s 后补一跳；恢复成功后回到配置间隔。"""
    results = [False, True]
    monkeypatch.setattr(
        launcher_server, "_findcar_report_once", lambda port: results.pop(0)
    )
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED_SLOW)

    waits = []
    monkeypatch.setattr(
        launcher_server.threading, "Event", _fake_event_factory(waits, 2)
    )

    with pytest.raises(_StopLoop):
        launcher_server._findcar_reporter_loop(8090)

    assert waits == [findcar.RETRY_INTERVAL_SECONDS, 300]


def test_findcar_reporter_loop_not_configured_keeps_normal_interval(monkeypatch):
    """未配置（返回 None）不算失败，按正常间隔走，不触发快速补跳。"""
    monkeypatch.setattr(launcher_server, "_findcar_report_once", lambda port: None)
    monkeypatch.setattr(findcar, "load_config", lambda: _CONFIGURED_SLOW)

    waits = []
    monkeypatch.setattr(
        launcher_server.threading, "Event", _fake_event_factory(waits, 2)
    )

    with pytest.raises(_StopLoop):
        launcher_server._findcar_reporter_loop(8090)

    assert waits == [300, 300]


# ---------------------------------------------------------------------------
# 下线标记与 SIGTERM
# ---------------------------------------------------------------------------


def test_report_findcar_offline_delegates_with_port(monkeypatch):
    calls = []
    monkeypatch.setattr(
        findcar,
        "report_offline",
        lambda cfg=None, port=0: calls.append(port) or True,
    )

    launcher_server._report_findcar_offline(8090)

    assert calls == [8090]


def test_report_findcar_offline_swallows_errors(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(findcar, "report_offline", boom)

    launcher_server._report_findcar_offline(8090)  # 不抛异常


def test_sigterm_handler_raises_keyboard_interrupt():
    """SIGTERM（systemd stop / 关机）转成 KeyboardInterrupt，走统一退出路径。"""
    with pytest.raises(KeyboardInterrupt):
        launcher_server._sigterm_raise_keyboard_interrupt(signal.SIGTERM, None)


# ---------------------------------------------------------------------------
# run_server 接线
# ---------------------------------------------------------------------------


def test_run_server_starts_reporter_and_sends_offline_on_exit(monkeypatch):
    """run_server 启动 findcar 心跳线程；退出路径补发下线标记。"""
    started = []
    offline = []
    monkeypatch.setattr(launcher_server, "_start_hostip_reporter", lambda: None)
    monkeypatch.setattr(
        launcher_server, "_start_findcar_reporter", lambda port: started.append(port)
    )
    monkeypatch.setattr(
        launcher_server, "_report_findcar_offline", lambda port: offline.append(port)
    )

    class _FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt  # 模拟立即收到退出信号

        def shutdown(self):
            pass

    monkeypatch.setattr(
        launcher_server.http.server, "ThreadingHTTPServer", _FakeServer
    )

    # run_server 会在主线程注册 SIGTERM 处理器，测试后恢复原样
    previous = signal.getsignal(signal.SIGTERM)
    try:
        launcher_server.run_server(port=18099)
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert started == [18099]
    assert offline == [18099]
