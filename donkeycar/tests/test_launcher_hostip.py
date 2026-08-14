"""Launcher HOSTIP 串口上报单元测试。

测试覆盖 donkeycar.launcher.server 的 HOSTIP 上报链路：
- _get_local_ip：复用配网模块 detect_lan_ip（VPN/TUN 感知）
- _report_hostip_to_esp32：候选端口顺序回退、每次发送前显式设置
  115200 8N1（防 ModemManager 等外部进程篡改 termios）、帧格式、
  失败静默
"""

import types
from unittest.mock import MagicMock


LAUNCHER_MODULE = "donkeycar.launcher.server"


def _make_fake_os(open_behavior):
    """构造 server.os 替身。

    Args:
        open_behavior: dict，port → "ok" 或 OSError 实例

    Returns:
        (fake_os, records) — records 记录 open/write/close 调用
    """
    records = {"open": [], "write": [], "close": []}

    def fake_open(path, flags):
        records["open"].append(path)
        behavior = open_behavior.get(path)
        if isinstance(behavior, OSError):
            raise behavior
        if behavior is None:
            raise OSError("No such file or directory")
        return 100 + len(records["open"])  # 伪 fd

    def fake_write(fd, data):
        records["write"].append((fd, data))
        return len(data)

    def fake_close(fd):
        records["close"].append(fd)

    fake_os = types.SimpleNamespace(
        open=fake_open,
        write=fake_write,
        close=fake_close,
        O_WRONLY=1,
        O_NOCTTY=256,
        O_NONBLOCK=2048,
    )
    return fake_os, records


def _make_fake_termios():
    """构造 server.termios 替身，记录 tcsetattr 并回读设置的属性。"""
    fake = types.SimpleNamespace()
    fake.TCSANOW = 0
    fake.B115200 = 4098
    fake.CSIZE = 0x30
    fake.CS8 = 0x30
    fake.PARENB = 0x100
    fake.CSTOPB = 0x200
    fake.CLOCAL = 0x800
    fake.CREAD = 0x80
    fake.ONLCR = 0x4
    fake.setattrs = []

    def fake_tcgetattr(fd):
        # [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
        return [0, fake.ONLCR, fake.PARENB, 0, 0, 0, []]

    def fake_tcsetattr(fd, when, attrs):
        fake.setattrs.append(list(attrs))

    def fake_tcdrain(fd):
        pass

    fake.tcgetattr = fake_tcgetattr
    fake.tcsetattr = fake_tcsetattr
    fake.tcdrain = fake_tcdrain
    return fake


class TestGetLocalIp:
    """验证 _get_local_ip() 委托配网模块探测。"""

    def test_delegates_to_detect_lan_ip(self, monkeypatch):
        from donkeycar.launcher import server
        from donkeycar.parts import provisioning

        monkeypatch.setattr(
            provisioning, "detect_lan_ip", lambda: "192.168.3.45"
        )
        assert server._get_local_ip() == "192.168.3.45"

    def test_returns_none_on_failure(self, monkeypatch):
        from donkeycar.launcher import server
        from donkeycar.parts import provisioning

        def _boom():
            raise RuntimeError("no network")

        monkeypatch.setattr(provisioning, "detect_lan_ip", _boom)
        assert server._get_local_ip() is None


class TestReportHostipToEsp32:
    """验证 _report_hostip_to_esp32() 串口上报。"""

    def _patch(self, monkeypatch, server, open_behavior, with_termios=True):
        monkeypatch.setattr(
            server, "_get_local_ip", lambda: "192.168.3.45"
        )
        fake_os, records = _make_fake_os(open_behavior)
        monkeypatch.setattr(server, "os", fake_os)
        fake_termios = _make_fake_termios() if with_termios else None
        monkeypatch.setattr(server, "termios", fake_termios)
        return records, fake_termios

    def test_writes_to_ttyS6_first(self, monkeypatch):
        """优先写 /dev/ttyS6（车上 UART 直连），成功后不再尝试其余端口。"""
        from donkeycar.launcher import server

        records, _ = self._patch(
            monkeypatch, server, {"/dev/ttyS6": "ok"}
        )
        server._report_hostip_to_esp32()

        assert records["open"] == ["/dev/ttyS6"]
        assert records["write"] == [
            (records["close"][0], b"HOSTIP|192.168.3.45\n")
        ]
        assert len(records["close"]) == 1

    def test_falls_back_to_usb_ports(self, monkeypatch):
        """ttyS6 不存在时回退到 ttyACM0。"""
        from donkeycar.launcher import server

        records, _ = self._patch(
            monkeypatch, server, {"/dev/ttyACM0": "ok"}
        )
        server._report_hostip_to_esp32()

        assert records["open"] == [
            "/dev/ttyS6", "/dev/ttyACM0",
        ]
        assert records["write"][0][1] == b"HOSTIP|192.168.3.45\n"

    def test_sets_baud_115200_8n1(self, monkeypatch):
        """每次发送前显式 tcsetattr：115200、8N1、无校验、CLOCAL|CREAD。"""
        from donkeycar.launcher import server

        records, fake_termios = self._patch(
            monkeypatch, server, {"/dev/ttyS6": "ok"}
        )
        server._report_hostip_to_esp32()

        assert len(fake_termios.setattrs) == 1
        attrs = fake_termios.setattrs[0]
        assert attrs[4] == fake_termios.B115200  # ispeed
        assert attrs[5] == fake_termios.B115200  # ospeed
        cflag = attrs[2]
        assert cflag & fake_termios.CS8 == fake_termios.CS8
        assert not (cflag & fake_termios.PARENB)
        assert not (cflag & fake_termios.CSTOPB)
        assert cflag & fake_termios.CLOCAL
        assert cflag & fake_termios.CREAD
        assert not (attrs[1] & fake_termios.ONLCR)  # 无输出换行翻译

    def test_no_ip_no_serial_access(self, monkeypatch):
        """探测不到本机 IP 时不触碰任何串口。"""
        from donkeycar.launcher import server

        monkeypatch.setattr(server, "_get_local_ip", lambda: None)
        fake_os, records = _make_fake_os({})
        monkeypatch.setattr(server, "os", fake_os)

        server._report_hostip_to_esp32()

        assert records["open"] == []

    def test_all_ports_missing_silent(self, monkeypatch):
        """所有候选端口都不存在时静默返回、不抛异常。"""
        from donkeycar.launcher import server

        records, _ = self._patch(monkeypatch, server, {})
        server._report_hostip_to_esp32()  # 不应抛异常

        assert records["open"] == list(server._HOSTIP_SERIAL_PORTS)
        assert records["write"] == []

    def test_write_error_tries_next_port(self, monkeypatch):
        """写第一个端口失败时尝试下一个。"""
        from donkeycar.launcher import server

        records, fake_termios = self._patch(
            monkeypatch, server,
            {"/dev/ttyS6": "ok", "/dev/ttyACM0": "ok"},
        )
        # 让 ttyS6 的 write 抛 OSError
        original_write = server.os.write

        def flaky_write(fd, data):
            if len(records["open"]) == 1:
                raise OSError("io error")
            return original_write(fd, data)

        monkeypatch.setattr(server.os, "write", flaky_write)
        server._report_hostip_to_esp32()

        assert records["open"] == ["/dev/ttyS6", "/dev/ttyACM0"]
        assert records["write"][-1][1] == b"HOSTIP|192.168.3.45\n"

    def test_without_termios_still_writes(self, monkeypatch):
        """非 POSIX 平台（termios=None）跳过波特率设置但仍写帧。"""
        from donkeycar.launcher import server

        records, _ = self._patch(
            monkeypatch, server, {"/dev/ttyS6": "ok"},
            with_termios=False,
        )
        server._report_hostip_to_esp32()

        assert records["write"][0][1] == b"HOSTIP|192.168.3.45\n"


class TestHostipReporterLoop:
    """验证后台线程启动。"""

    def test_start_hostip_reporter_spawns_daemon_thread(self, monkeypatch):
        from donkeycar.launcher import server

        started = []

        class FakeThread:
            def __init__(self, target=None, daemon=None):
                self.target = target
                self.daemon = daemon

            def start(self):
                started.append(self)

        monkeypatch.setattr(server.threading, "Thread", FakeThread)
        server._start_hostip_reporter()

        assert len(started) == 1
        assert started[0].target is server._hostip_reporter_loop
        assert started[0].daemon is True
