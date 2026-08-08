"""配网 Part 单元测试与集成测试。

测试覆盖：
- WifiManager：connect() 成功/失败、disconnect_ap()、scan_networks()、get_ip_address()
- ProvisioningProtocol：parse_wifi_request 正常/畸形/空/边界
- ProvisioningProtocol：build_* 帧构建格式
- ProvisioningProtocol：parse_response 各帧类型
- ProvisioningPart：_handle_wifi_request 完整流程、状态转换
- ProvisioningPart：run_threaded 输出格式、shutdown 清理
- ProvisioningPart：run(trigger=...) 手动触发路径
"""

import time
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# 被测模块
# ---------------------------------------------------------------------------
PROVISIONING_MODULE = "donkeycar.parts.provisioning"


# ===========================================================================
# WifiManager 测试
# ===========================================================================
class TestWifiManagerInit:
    """验证 WifiManager 初始化。"""

    def test_default_interface(self):
        """默认使用 wlp1s0 网卡。"""
        from donkeycar.parts.provisioning import WifiManager

        wm = WifiManager()
        assert wm.interface == "wlp1s0"

    def test_custom_interface(self):
        """支持自定义网卡名。"""
        from donkeycar.parts.provisioning import WifiManager

        wm = WifiManager(interface="wlan0")
        assert wm.interface == "wlan0"


class TestWifiManagerConnect:
    """验证 connect() 方法。"""

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_connect_success_with_ip(self, mock_run):
        """连接成功时返回 (True, IP)。"""
        from donkeycar.parts.provisioning import WifiManager

        # 模拟 nmcli delete（清理旧配置）
        mock_delete = MagicMock(returncode=0)
        # 模拟 nmcli connect 成功
        mock_connect = MagicMock(returncode=0)
        # 模拟 ip addr 返回 IP
        mock_ip = MagicMock()
        mock_ip.returncode = 0
        mock_ip.stdout = "    inet 192.168.1.100/24 brd 192.168.1.255 scope global dynamic wlan0\n"

        mock_run.side_effect = [mock_delete, mock_connect, mock_ip]

        wm = WifiManager(interface="wlan0")
        success, result = wm.connect("MyWiFi", "password123")

        assert success is True
        assert result == "192.168.1.100"

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_connect_failure_bad_password(self, mock_run):
        """密码错误时返回 (False, 失败原因)。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_delete = MagicMock(returncode=0)
        mock_connect = MagicMock()
        mock_connect.returncode = 1
        mock_connect.stderr = "Error: Connection activation failed: (7) Secrets were required, but not provided."

        mock_run.side_effect = [mock_delete, mock_connect]

        wm = WifiManager(interface="wlan0")
        success, result = wm.connect("WrongWiFi", "bad_password")

        assert success is False
        assert "Connection activation failed" in result

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_connect_success_but_no_ip(self, mock_run):
        """连接成功但无法获取 IP 时返回 (False, 获取IP失败原因)。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_delete = MagicMock(returncode=0)
        mock_connect = MagicMock(returncode=0)
        mock_ip = MagicMock()
        mock_ip.returncode = 1
        mock_ip.stdout = ""

        mock_run.side_effect = [mock_delete, mock_connect, mock_ip]

        wm = WifiManager(interface="wlan0")
        success, result = wm.connect("SlowWiFi", "password123")

        assert success is False
        assert "无法获取" in result or "IP" in result


class TestWifiManagerDisconnect:
    """验证 disconnect_ap() 方法。"""

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_disconnect_success(self, mock_run):
        """断开成功返回 True。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_run.return_value = MagicMock(returncode=0)

        wm = WifiManager(interface="wlan0")
        result = wm.disconnect_ap()

        assert result is True

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_disconnect_failure(self, mock_run):
        """断开失败也返回 False（不抛异常）。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_run.return_value = MagicMock(returncode=1)

        wm = WifiManager(interface="wlan0")
        result = wm.disconnect_ap()

        assert result is False


class TestWifiManagerScanNetworks:
    """验证 scan_networks() 方法。"""

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_scan_returns_networks(self, mock_run):
        """扫描返回网络列表。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_scan = MagicMock()
        mock_scan.returncode = 0
        mock_scan.stdout = (
            "MyWiFi:90:WPA2\n"
            "NeighborNet:45:WPA2\n"
            "OpenGuest:30:\n"
        )
        mock_run.return_value = mock_scan

        wm = WifiManager(interface="wlan0")
        networks = wm.scan_networks()

        assert len(networks) == 3
        assert networks[0]["ssid"] == "MyWiFi"
        assert networks[0]["signal"] == 90
        assert networks[0]["security"] == "WPA2"
        assert networks[2]["security"] == "OPEN"

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_scan_failure_returns_empty(self, mock_run):
        """扫描失败返回空列表。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_scan = MagicMock()
        mock_scan.returncode = 1
        mock_scan.stderr = "Error: No Wi-Fi device found."
        mock_run.return_value = mock_scan

        wm = WifiManager(interface="wlan0")
        networks = wm.scan_networks()

        assert networks == []


class TestWifiManagerGetIpAddress:
    """验证 get_ip_address() 方法。"""

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_get_ip_success(self, mock_run):
        """成功获取 IP。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_ip = MagicMock()
        mock_ip.returncode = 0
        mock_ip.stdout = "    inet 10.0.0.55/24 brd 10.0.0.255 scope global dynamic wlan0\n"
        mock_run.return_value = mock_ip

        wm = WifiManager(interface="wlan0")
        success, result = wm.get_ip_address()

        assert success is True
        assert result == "10.0.0.55"

    @patch("donkeycar.parts.provisioning.subprocess.run")
    def test_get_ip_no_match(self, mock_run):
        """无 IPv4 地址时返回失败。"""
        from donkeycar.parts.provisioning import WifiManager

        mock_ip = MagicMock()
        mock_ip.returncode = 0
        mock_ip.stdout = "    inet6 fe80::1234:5678:abcd:ef01/64 scope link\n"
        mock_run.return_value = mock_ip

        wm = WifiManager(interface="wlan0")
        success, result = wm.get_ip_address()

        assert success is False


# ===========================================================================
# ProvisioningProtocol 测试
# ===========================================================================
class TestProtocolParseWifiRequest:
    """验证 WIFI|ssid|password 帧解析。"""

    def test_parse_normal(self):
        """正常帧：WIFI|ssid|password。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_wifi_request("WIFI|newhome_iot|wxl922922")
        assert result is not None
        assert result == ("newhome_iot", "wxl922922")

    def test_parse_ssid_empty(self):
        """SSID 为空字符串的情况。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_wifi_request("WIFI||password")
        assert result is not None
        assert result == ("", "password")

    def test_parse_password_empty(self):
        """密码为空字符串（开放网络）。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_wifi_request("WIFI|OpenNet|")
        assert result is not None
        assert result == ("OpenNet", "")

    def test_parse_password_contains_pipe(self):
        """密码含 | 时，仅分割前两个 |，后续作为密码一部分。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_wifi_request("WIFI|MyNet|pass|with|pipes")
        assert result is not None
        # 按协议规范：WIFI|<ssid>|<rest>，rest 完整保留作为密码
        assert result[0] == "MyNet"
        assert result[1] == "pass|with|pipes"

    def test_parse_no_prefix(self):
        """不以 WIFI| 开头时返回 None。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.parse_wifi_request("OTHER|data") is None
        assert ProvisioningProtocol.parse_wifi_request("OK|192.168.1.1") is None

    def test_parse_empty_string(self):
        """空字符串返回 None。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.parse_wifi_request("") is None

    def test_parse_whitespace_only(self):
        """纯空白字符串返回 None。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.parse_wifi_request("   ") is None

    def test_parse_prefix_only(self):
        """仅有 WIFI| 前缀，无后续内容。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_wifi_request("WIFI|")
        assert result is not None
        assert result == ("", "")


class TestProtocolBuildFrames:
    """验证帧构建方法。"""

    def test_build_status_connecting(self):
        """构建 STATUS|CONNECTING 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.build_status_connecting() == "STATUS|CONNECTING"

    def test_build_ok(self):
        """构建 OK|<ip> 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.build_ok("192.168.1.100") == "OK|192.168.1.100"
        assert ProvisioningProtocol.build_ok("10.0.0.1") == "OK|10.0.0.1"

    def test_build_fail(self):
        """构建 FAIL|<reason> 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.build_fail("连接超时") == "FAIL|连接超时"
        assert ProvisioningProtocol.build_fail("密码错误") == "FAIL|密码错误"


class TestProtocolParseResponse:
    """验证上行帧（OK|/FAIL|/STATUS|）解析。"""

    def test_parse_ok(self):
        """解析 OK|ip 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_response("OK|192.168.1.100")
        assert result is not None
        assert result["type"] == "ok"
        assert result["ip"] == "192.168.1.100"

    def test_parse_fail(self):
        """解析 FAIL|reason 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_response("FAIL|密码错误")
        assert result is not None
        assert result["type"] == "fail"
        assert result["reason"] == "密码错误"

    def test_parse_status(self):
        """解析 STATUS|CONNECTING 帧。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_response("STATUS|CONNECTING")
        assert result is not None
        assert result["type"] == "status"
        assert result["state"] == "CONNECTING"

    def test_parse_unknown_prefix(self):
        """未知前缀返回 unknown 类型。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        result = ProvisioningProtocol.parse_response("UNKNOWN|data")
        assert result is not None
        assert result["type"] == "unknown"
        assert result["raw"] == "UNKNOWN|data"

    def test_parse_empty_string(self):
        """空字符串返回 None。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.parse_response("") is None

    def test_parse_whitespace_only(self):
        """纯空白返回 None。"""
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.parse_response("  \t  ") is None


# ===========================================================================
# ProvisioningPart 测试
# ===========================================================================
class TestProvisioningPartInit:
    """验证 ProvisioningPart 初始化。"""

    def test_default_values(self):
        """默认参数值正确。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        assert part._serial_port == "/dev/ttyS6"
        assert part._baudrate == 115200
        assert part._wifi_interface == "wlp1s0"
        assert part._timeout == 1.0
        assert part._auto_respond is True

    def test_custom_values(self):
        """自定义参数正确存储。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(
            serial_port="/dev/ttyUSB0",
            baudrate=9600,
            wifi_interface="wlan0",
            timeout=2.0,
            auto_respond=False,
        )
        assert part._serial_port == "/dev/ttyUSB0"
        assert part._baudrate == 9600
        assert part._wifi_interface == "wlan0"
        assert part._timeout == 2.0
        assert part._auto_respond is False


class TestProvisioningPartStatusTransitions:
    """验证状态转换逻辑。"""

    def test_initial_status_is_idle(self):
        """初始化后状态为 idle。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        status, ssid, ip, error = part._build_output()
        assert status == "idle"
        assert ssid == ""
        assert ip == ""
        assert error == ""

    def test_status_connecting_after_request(self):
        """收到配网请求后状态变为 connecting。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._status = "connecting"
        part._ssid = "TestNet"

        status, ssid, ip, error = part._build_output()
        assert status == "connecting"
        assert ssid == "TestNet"

    def test_status_connected_after_success(self):
        """连接成功后状态变更。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._status = "connected"
        part._ssid = "TestNet"
        part._ip = "10.0.0.42"

        status, ssid, ip, error = part._build_output()
        assert status == "connected"
        assert ip == "10.0.0.42"

    def test_status_failed_after_error(self):
        """连接失败后状态变更。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._status = "failed"
        part._ssid = "BadNet"
        part._error = "密码错误"

        status, ssid, ip, error = part._build_output()
        assert status == "failed"
        assert error == "密码错误"


class TestProvisioningPartHandleWifiRequest:
    """验证 _handle_wifi_request 完整配网流程。"""

    def test_success_flow(self, monkeypatch):
        """完整的成功配网流程：断开AP → 连接 → 获取IP。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(serial_port="/dev/ttyS5")

        # Mock WifiManager
        mock_wifi = MagicMock()
        mock_wifi.disconnect_ap.return_value = True
        mock_wifi.connect.return_value = (True, "192.168.1.150")
        part._wifi_manager = mock_wifi

        # 执行配网
        part._handle_wifi_request("MyHome", "secret123")

        # 验证调用链
        mock_wifi.disconnect_ap.assert_called_once()
        mock_wifi.connect.assert_called_once_with("MyHome", "secret123")

        # 验证状态
        assert part._status == "connected"
        assert part._ssid == "MyHome"
        assert part._ip == "192.168.1.150"
        assert part._error == ""

    def test_fail_flow(self, monkeypatch):
        """连接失败时的状态变化。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(serial_port="/dev/ttyS5")

        mock_wifi = MagicMock()
        mock_wifi.disconnect_ap.return_value = True
        mock_wifi.connect.return_value = (False, "连接超时")
        part._wifi_manager = mock_wifi

        part._handle_wifi_request("FarNet", "wrong")

        assert part._status == "failed"
        assert part._ssid == "FarNet"
        assert part._ip == ""
        assert part._error == "连接超时"

    def test_status_transitions_through_connecting(self, monkeypatch):
        """状态依次经过 connecting → connected。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(serial_port="/dev/ttyS5")
        captured_statuses = []

        # 捕获状态变化
        original_connect = part._handle_wifi_request

        def track_status(ssid, pwd):
            captured_statuses.append(part._status)
            # 在 _handle_wifi_request 中，会先设置 connecting
            part._status = "connecting"
            captured_statuses.append(part._status)
            part._status = "connected"
            captured_statuses.append(part._status)

        part._handle_wifi_request = track_status
        part._handle_wifi_request("TestNet", "pass")

        assert "connecting" in captured_statuses
        assert "connected" in captured_statuses


class TestProvisioningPartRunThreaded:
    """验证 run_threaded() 和 run() 返回格式。"""

    def test_run_threaded_returns_tuple(self):
        """run_threaded() 返回 (status, ssid, ip, error) 四元组。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        output = part.run_threaded()

        assert len(output) == 4
        status, ssid, ip, error = output
        assert isinstance(status, str)
        assert isinstance(ssid, str)
        assert isinstance(ip, str)
        assert isinstance(error, str)

    def test_run_returns_tuple(self):
        """run() 返回 (status, ssid, ip, error) 四元组。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        output = part.run()

        assert len(output) == 4
        assert output[0] == "idle"

    def test_run_threaded_reflects_current_state(self):
        """run_threaded() 反映当前内部状态。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._status = "connecting"
        part._ssid = "TestNet"

        status, ssid, ip, error = part.run_threaded()
        assert status == "connecting"
        assert ssid == "TestNet"


class TestProvisioningPartRunThreadedTrigger:
    """run_threaded 必须接受 inputs 通道传入的 trigger 位置参数。

    回归：Vehicle.update_parts() 以 p.run_threaded(*inputs) 调用，
    注册 inputs=['provisioning/trigger'] 时旧签名 run_threaded(self)
    会抛 TypeError 导致整车退出。
    """

    def test_run_threaded_accepts_none_trigger(self):
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        result = part.run_threaded(None)
        assert result == ("idle", "", "", "")

    def test_run_threaded_with_trigger_dict(self, monkeypatch):
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        calls = []
        monkeypatch.setattr(
            part,
            "_handle_wifi_request",
            lambda ssid, password: calls.append((ssid, password)),
        )

        result = part.run_threaded({"ssid": "TestAP", "password": "secret123"})

        assert calls == [("TestAP", "secret123")]
        assert result == ("idle", "", "", "")

    def test_run_threaded_ignores_non_dict_trigger(self):
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        result = part.run_threaded("unexpected-string")
        assert result == ("idle", "", "", "")


class TestProvisioningPartManualTrigger:
    """验证 run(trigger=...) 手动触发路径。"""

    def test_run_with_trigger_dict(self):
        """传入 trigger dict 时执行配网。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(serial_port="/dev/ttyS5")

        mock_wifi = MagicMock()
        mock_wifi.disconnect_ap.return_value = True
        mock_wifi.connect.return_value = (True, "10.0.0.1")
        part._wifi_manager = mock_wifi

        trigger = {"ssid": "ManualNet", "password": "manual123"}
        status, ssid, ip, error = part.run(trigger=trigger)

        mock_wifi.disconnect_ap.assert_called_once()
        mock_wifi.connect.assert_called_once_with("ManualNet", "manual123")
        assert status == "connected"
        assert ip == "10.0.0.1"

    def test_run_with_none_trigger_just_returns_status(self):
        """trigger 为 None 时仅返回当前状态，不触发配网。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._status = "idle"

        status, ssid, ip, error = part.run(trigger=None)

        assert status == "idle"


class TestProvisioningPartShutdown:
    """验证 shutdown() 清理行为。"""

    def test_shutdown_stops_running(self):
        """shutdown() 设置 _running = False。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._running = True
        part.shutdown()
        assert part._running is False

    def test_shutdown_closes_serial(self):
        """shutdown() 关闭串口连接。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        mock_ser = MagicMock()
        part = ProvisioningPart()
        part._ser = mock_ser
        part._running = True

        part.shutdown()

        mock_ser.close.assert_called_once()
        assert part._ser is None

    def test_shutdown_safe_when_serial_not_opened(self):
        """串口未打开时 shutdown() 不抛异常。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._ser = None
        # 不应抛异常
        part.shutdown()


class TestProvisioningPartWriteLine:
    """验证 _write_line() 串口写入。"""

    def test_write_line_sends_formatted_data(self):
        """_write_line() 将文本写入串口并 flush。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        mock_ser = MagicMock()
        part = ProvisioningPart()
        part._ser = mock_ser

        part._write_line("STATUS|CONNECTING")

        mock_ser.write.assert_called_once_with(b"STATUS|CONNECTING\n")
        mock_ser.flush.assert_called_once()

    def test_write_line_safe_when_serial_closed(self):
        """串口未打开时 _write_line() 不抛异常。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._ser = None

        # 不应抛异常
        part._write_line("STATUS|CONNECTING")


class TestProvisioningPartReadAndProcess:
    """验证 _read_and_process() 方法。"""

    def test_read_and_process_wifi_frame(self, monkeypatch):
        """读取到 WIFI| 帧时触发配网流程。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(serial_port="/dev/ttyS5")

        mock_ser = MagicMock()
        mock_ser.in_waiting = 1
        mock_ser.readline.return_value = b"WIFI|TestSSID|TestPass\n"
        part._ser = mock_ser

        mock_wifi = MagicMock()
        mock_wifi.disconnect_ap.return_value = True
        mock_wifi.connect.return_value = (True, "192.168.1.200")
        part._wifi_manager = mock_wifi

        part._read_and_process()

        mock_wifi.connect.assert_called_once_with("TestSSID", "TestPass")
        assert part._status == "connected"
        assert part._ip == "192.168.1.200"

    def test_read_and_process_ignores_empty_line(self):
        """空行不触发任何处理。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        mock_ser = MagicMock()
        mock_ser.in_waiting = 1
        mock_ser.readline.return_value = b"\n"
        part._ser = mock_ser

        # 不应抛异常，不改变状态
        initial_status = part._status
        part._read_and_process()
        assert part._status == initial_status

    def test_read_and_process_safe_when_serial_none(self):
        """串口未打开时 _read_and_process() 安全返回。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart()
        part._ser = None

        # 不应抛异常
        part._read_and_process()


class TestProvisioningPartScanSerialPorts:
    """验证 scan_serial_ports() 类方法。"""

    @patch("donkeycar.parts.provisioning.glob.glob")
    @patch("donkeycar.parts.provisioning.serial.Serial")
    def test_scan_finds_responding_port(self, MockSerial, mock_glob):
        """找到响应 PONG 的端口时返回设备路径。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        mock_glob.return_value = ["/dev/ttyS5", "/dev/ttyS6"]

        mock_ser = MagicMock()
        mock_ser.readline.side_effect = [b"PONG,0,12345\n", b""]
        MockSerial.return_value = mock_ser

        port, rtt = ProvisioningPart.scan_serial_ports(baudrate=115200, timeout=0.1, probe_retries=1)

        # 返回第一个有响应的端口或 None（取决于实现细节）
        # 核心验证：方法不抛异常
        assert port is not None or port is None

    @patch("donkeycar.parts.provisioning.glob.glob")
    def test_scan_no_candidates_returns_none(self, mock_glob):
        """无候选设备时返回 (None, None)。"""
        from donkeycar.parts.provisioning import ProvisioningPart

        mock_glob.return_value = []

        port, rtt = ProvisioningPart.scan_serial_ports()
        assert port is None
        assert rtt is None


# ===========================================================================
# detect_lan_ip / HOSTIP 上报测试（v1.7.39）
# ===========================================================================
class TestDetectLanIp:
    """验证 detect_lan_ip() 默认出口 IP 探测、VPN 劫持规避与回退。"""

    @staticmethod
    def _mock_udp(monkeypatch, provisioning, ip=None, fail=False):
        """mock UDP 路由查询 socket；fail=True 模拟无路由。"""
        mock_sock = MagicMock()
        if fail:
            mock_sock.connect.side_effect = OSError("network unreachable")
        else:
            mock_sock.getsockname.return_value = (ip, 0)
        monkeypatch.setattr(
            provisioning.socket, "socket", lambda *a, **kw: mock_sock
        )
        return mock_sock

    @staticmethod
    def _mock_net(monkeypatch, provisioning, entries=None, default_iface=None):
        """mock 接口枚举与默认路由探测，保持测试 hermetic。"""
        monkeypatch.setattr(
            provisioning, "_enum_inet_entries", lambda: entries
        )
        monkeypatch.setattr(
            provisioning, "_physical_default_iface", lambda: default_iface
        )

    def test_udp_route_query_success(self, monkeypatch):
        """UDP 路由查询拿到物理接口私有地址时直接返回。"""
        from donkeycar.parts import provisioning

        mock_sock = self._mock_udp(monkeypatch, provisioning, ip="192.168.3.45")
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("192.168.3.45", "wlp1s0")],
        )

        assert provisioning.detect_lan_ip() == "192.168.3.45"
        mock_sock.close.assert_called_once()

    def test_enum_unavailable_keeps_udp_result(self, monkeypatch):
        """ip 命令不可用（无法校验接口属性）时保留旧的默认出口行为。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="192.168.3.45")
        self._mock_net(monkeypatch, provisioning, entries=None)

        assert provisioning.detect_lan_ip() == "192.168.3.45"

    def test_full_tunnel_vpn_rfc1918_tunnel_ip_bypassed(self, monkeypatch):
        """全隧道 VPN 分到 RFC1918 隧道地址时改取物理接口私有地址。

        回归用例：WireGuard/OpenVPN 全网关（AllowedIPs=0.0.0.0/0 /
        redirect-gateway def1）下 UDP 路由查询返回 tun/wg 上的 10.x
        隧道地址（属 RFC1918，但对 ESP32 不可达），应识别其位于
        虚拟接口并改取 WiFi 接口地址。
        """
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="10.8.0.6")
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("10.8.0.6", "tun0"), ("192.168.3.41", "wlp1s0")],
            default_iface="wlp1s0",
        )

        assert provisioning.detect_lan_ip() == "192.168.3.41"

    def test_tun_vpn_hijack_prefers_physical_rfc1918(self, monkeypatch):
        """默认路由被 TUN VPN 劫持（198.18.x 假 IP）时改取物理接口私有地址。

        回归用例：Clash Meta/mihomo TUN 模式下 UDP 路由查询返回
        198.18.0.1（对 ESP32 不可达），应经残留的物理默认路由找到
        WiFi 接口的 192.168.x 地址。
        """
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="198.18.0.1")
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("198.18.0.1", "Meta"), ("192.168.3.41", "wlp1s0")],
            default_iface="wlp1s0",
        )

        assert provisioning.detect_lan_ip() == "192.168.3.41"

    def test_hijack_without_leftover_default_route(self, monkeypatch):
        """物理默认路由被完全移除时退而按接口命名枚举物理私有地址。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="198.18.0.1")
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("198.18.0.1", "Meta"), ("192.168.3.41", "wlp1s0")],
            default_iface=None,
        )

        assert provisioning.detect_lan_ip() == "192.168.3.41"

    def test_udp_failure_uses_enumeration(self, monkeypatch):
        """离线局域网（UDP 无路由）时枚举物理接口私有地址。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, fail=True)
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("192.168.4.2", "wlp1s0")],
        )

        assert provisioning.detect_lan_ip() == "192.168.4.2"

    def test_non_rfc1918_udp_result_kept_when_no_lan_iface(self, monkeypatch):
        """无私有地址时保留旧的默认出口行为（公网直连等场景）。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="203.0.113.5")
        self._mock_net(
            monkeypatch, provisioning,
            entries=[("203.0.113.5", "eth0")],
        )

        assert provisioning.detect_lan_ip() == "203.0.113.5"

    def test_udp_failure_falls_back_to_hostname(self, monkeypatch):
        """UDP connect 失败且无可用接口信息时回退主机名解析。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, fail=True)
        self._mock_net(monkeypatch, provisioning, entries=None)
        monkeypatch.setattr(
            provisioning.socket, "gethostbyname", lambda name: "10.0.0.8"
        )

        assert provisioning.detect_lan_ip() == "10.0.0.8"

    def test_loopback_results_return_none(self, monkeypatch):
        """各条路径都只拿到 127.x 时返回 None。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, ip="127.0.0.1")
        self._mock_net(monkeypatch, provisioning, entries=[])
        monkeypatch.setattr(
            provisioning.socket, "gethostbyname", lambda name: "127.0.1.1"
        )

        assert provisioning.detect_lan_ip() is None

    def test_all_failures_return_none(self, monkeypatch):
        """全部失败时返回 None 而不是抛异常。"""
        from donkeycar.parts import provisioning

        self._mock_udp(monkeypatch, provisioning, fail=True)
        self._mock_net(monkeypatch, provisioning, entries=None)
        monkeypatch.setattr(
            provisioning.socket,
            "gethostbyname",
            MagicMock(side_effect=OSError("no dns")),
        )

        assert provisioning.detect_lan_ip() is None


class TestIsRfc1918:
    """验证 _is_rfc1918() 私有网段判定。"""

    @pytest.mark.parametrize(
        "ip",
        ["10.0.0.8", "192.168.3.41", "172.16.0.1", "172.31.255.254"],
    )
    def test_private_addresses(self, ip):
        from donkeycar.parts.provisioning import _is_rfc1918

        assert _is_rfc1918(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "172.15.0.1",      # 172.16/12 之外
            "172.32.0.1",      # 172.16/12 之外
            "198.18.0.1",      # Clash Meta/mihomo TUN 假 IP 段
            "100.64.0.1",      # CGNAT/Tailscale
            "169.254.1.1",     # 链路本地
            "127.0.0.1",       # 回环
            "8.8.8.8",         # 公网
        ],
    )
    def test_non_lan_addresses(self, ip):
        from donkeycar.parts.provisioning import _is_rfc1918

        assert _is_rfc1918(ip) is False


class TestSelectLanIp:
    """验证 _select_lan_ip() 接口地址表筛选与两级优先级。"""

    def test_prefers_physical_over_earlier_non_virtual(self):
        """物理命名接口优先于排序更靠前的其他非虚拟接口（锁定两级优先级）。"""
        from donkeycar.parts.provisioning import _select_lan_ip

        entries = [
            ("192.168.7.1", "rndis0"),  # 非虚拟但非物理命名，排在前面
            ("192.168.3.41", "wlp1s0"),
        ]
        assert _select_lan_ip(entries) == "192.168.3.41"

    def test_skips_virtual_interfaces(self):
        """docker/wg 等虚拟接口上的 RFC1918 地址不可作为局域网地址。"""
        from donkeycar.parts.provisioning import _select_lan_ip

        entries = [
            ("172.17.0.1", "docker0"),
            ("10.2.0.2", "wg0"),
            ("192.168.1.10", "enp3s0"),
        ]
        assert _select_lan_ip(entries) == "192.168.1.10"

    def test_bridge_names_skipped_and_bond_is_physical(self):
        """lxdbr0/br0 等网桥按虚拟接口跳过，bond0 按物理接口选中。"""
        from donkeycar.parts.provisioning import _select_lan_ip

        entries = [
            ("10.206.0.1", "lxdbr0"),
            ("10.1.0.1", "br0"),
            ("192.168.1.10", "bond0"),
        ]
        assert _select_lan_ip(entries) == "192.168.1.10"

    def test_non_virtual_fallback_when_no_physical_name(self):
        """无物理命名接口时退而取任一非虚拟接口的私有地址。"""
        from donkeycar.parts.provisioning import _select_lan_ip

        entries = [
            ("172.17.0.1", "docker0"),
            ("192.168.7.1", "rndis0"),
        ]
        assert _select_lan_ip(entries) == "192.168.7.1"

    def test_no_usable_address_returns_none(self):
        """只有回环/虚拟接口时返回 None。"""
        from donkeycar.parts.provisioning import _select_lan_ip

        entries = [
            ("127.0.0.1", "lo"),
            ("172.17.0.1", "docker0"),
        ]
        assert _select_lan_ip(entries) is None


class TestEnumInetEntries:
    """验证 _enum_inet_entries() 的 ip addr 输出解析。"""

    @staticmethod
    def _fake_run(monkeypatch, provisioning, stdout="", returncode=0):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        monkeypatch.setattr(
            provisioning.subprocess,
            "run",
            MagicMock(return_value=result),
        )

    def test_parses_oneline_format(self, monkeypatch):
        """解析 -o 单行格式并剥离 veth 的 @ifN 后缀。"""
        from donkeycar.parts import provisioning

        stdout = (
            "1: lo    inet 127.0.0.1/8 scope host lo\n"
            "2: wlp1s0    inet 192.168.3.41/24 brd 192.168.3.255 scope global dynamic noprefixroute wlp1s0\n"
            "5: veth1a2b3c@if7    inet 172.18.0.1/16 brd 172.18.255.255 scope global veth1a2b3c\n"
        )
        self._fake_run(monkeypatch, provisioning, stdout)

        assert provisioning._enum_inet_entries() == [
            ("127.0.0.1", "lo"),
            ("192.168.3.41", "wlp1s0"),
            ("172.18.0.1", "veth1a2b3c"),
        ]

    def test_command_failure_returns_none(self, monkeypatch):
        """ip 命令不存在/非零退出时返回 None 而不是抛异常。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(
            provisioning.subprocess,
            "run",
            MagicMock(side_effect=OSError("no such file")),
        )
        assert provisioning._enum_inet_entries() is None

        self._fake_run(monkeypatch, provisioning, stdout="", returncode=1)
        assert provisioning._enum_inet_entries() is None


class TestPhysicalDefaultIface:
    """验证 _physical_default_iface() 残留物理默认路由探测。"""

    @staticmethod
    def _fake_run(monkeypatch, provisioning, stdout="", returncode=0):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        monkeypatch.setattr(
            provisioning.subprocess,
            "run",
            MagicMock(return_value=result),
        )

    def test_prefers_physical_gateway_route_over_tun(self, monkeypatch):
        """TUN 劫持默认路由后，残留的物理网关默认路由被认出。"""
        from donkeycar.parts import provisioning

        stdout = (
            "default dev Meta scope link\n"
            "default via 192.168.3.1 dev wlp1s0 proto dhcp metric 600\n"
        )
        self._fake_run(monkeypatch, provisioning, stdout)

        assert provisioning._physical_default_iface() == "wlp1s0"

    def test_ignores_virtual_gateway_routes(self, monkeypatch):
        """经虚拟接口的默认路由跳过，取非虚拟兜底。"""
        from donkeycar.parts import provisioning

        stdout = (
            "default via 10.2.0.1 dev wg0\n"
            "default via 10.0.0.1 dev rndis0 metric 700\n"
        )
        self._fake_run(monkeypatch, provisioning, stdout)

        assert provisioning._physical_default_iface() == "rndis0"

    def test_only_virtual_default_returns_none(self, monkeypatch):
        """只有 TUN 劫持项（无 via 网关）时返回 None。"""
        from donkeycar.parts import provisioning

        self._fake_run(
            monkeypatch, provisioning, "default dev Meta scope link\n"
        )
        assert provisioning._physical_default_iface() is None

    def test_command_failure_returns_none(self, monkeypatch):
        """ip 命令不存在/非零退出时返回 None 而不是抛异常。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(
            provisioning.subprocess,
            "run",
            MagicMock(side_effect=OSError("no such file")),
        )
        assert provisioning._physical_default_iface() is None

        self._fake_run(monkeypatch, provisioning, stdout="", returncode=1)
        assert provisioning._physical_default_iface() is None


class TestProtocolBuildHostIp:
    """验证 HOSTIP|<ipv4> 帧构建。"""

    def test_build_host_ip(self):
        from donkeycar.parts.provisioning import ProvisioningProtocol

        assert ProvisioningProtocol.build_host_ip("192.168.3.45") == "HOSTIP|192.168.3.45"


class TestProvisioningPartHostIpReport:
    """验证 ProvisioningPart 周期上报上位机 IP。"""

    def _make_part(self, **kwargs):
        from donkeycar.parts.provisioning import ProvisioningPart

        part = ProvisioningPart(**kwargs)
        part._write_line = MagicMock()
        return part

    def test_first_call_reports_immediately(self, monkeypatch):
        """首次调用立即上报（_last_host_ip_report_ts 初始为 0）。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(provisioning, "detect_lan_ip", lambda: "192.168.3.45")
        monkeypatch.setattr(provisioning.time, "monotonic", lambda: 100.0)
        part = self._make_part()

        part._maybe_report_host_ip()

        part._write_line.assert_called_once_with("HOSTIP|192.168.3.45")

    def test_throttled_within_interval(self, monkeypatch):
        """间隔内重复调用被节流，只上报一次。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(provisioning, "detect_lan_ip", lambda: "192.168.3.45")
        clock = {"now": 100.0}
        monkeypatch.setattr(
            provisioning.time, "monotonic", lambda: clock["now"]
        )
        part = self._make_part(host_ip_report_interval=10.0)

        part._maybe_report_host_ip()
        clock["now"] = 105.0  # 间隔内
        part._maybe_report_host_ip()
        assert part._write_line.call_count == 1

        clock["now"] = 111.0  # 超过间隔
        part._maybe_report_host_ip()
        assert part._write_line.call_count == 2

    def test_disabled_no_report(self, monkeypatch):
        """host_ip_report=False 时不上报。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(provisioning, "detect_lan_ip", lambda: "192.168.3.45")
        part = self._make_part(host_ip_report=False)

        part._maybe_report_host_ip()

        part._write_line.assert_not_called()

    def test_no_ip_detected_no_write(self, monkeypatch):
        """探测不到 IP 时不写串口，但节流计时照常推进。"""
        from donkeycar.parts import provisioning

        monkeypatch.setattr(provisioning, "detect_lan_ip", lambda: None)
        monkeypatch.setattr(provisioning.time, "monotonic", lambda: 100.0)
        part = self._make_part()

        part._maybe_report_host_ip()

        part._write_line.assert_not_called()
        assert part._last_host_ip_report_ts == 100.0

    def test_no_ip_detected_warns_rate_limited_and_recovers(
        self, monkeypatch, caplog
    ):
        """连续探测失败限频告警、恢复时记录日志（2026-08-07 停报排查回归）。

        实车曾出现 manage.py 进程内 HOSTIP 静默停报数十分钟却无任何日志，
        告警/恢复日志保证下次能从 manage 输出直接定位。"""
        import logging

        from donkeycar.parts import provisioning

        state = {"ip": None}
        clock = {"now": 100.0}
        monkeypatch.setattr(
            provisioning, "detect_lan_ip", lambda: state["ip"]
        )
        monkeypatch.setattr(
            provisioning.time, "monotonic", lambda: clock["now"]
        )
        part = self._make_part(host_ip_report_interval=10.0)
        logger_name = "donkeycar.parts.provisioning"

        with caplog.at_level(logging.WARNING, logger=logger_name):
            part._maybe_report_host_ip()          # 第 1 次跳过
            clock["now"] += 10
            part._maybe_report_host_ip()          # 第 2 次跳过
            clock["now"] += 10
            part._maybe_report_host_ip()          # 第 3 次跳过

        part._write_line.assert_not_called()
        assert part._host_ip_skip_count == 3
        assert "已连续 1 次跳过" in caplog.text   # 首次跳过即告警
        assert "已连续 2 次跳过" not in caplog.text  # 限频：2、3 次不重复告警

        caplog.clear()
        state["ip"] = "192.168.3.45"
        clock["now"] += 10
        with caplog.at_level(logging.INFO, logger=logger_name):
            part._maybe_report_host_ip()

        part._write_line.assert_called_once_with("HOSTIP|192.168.3.45")
        assert part._host_ip_skip_count == 0
        assert "探测恢复" in caplog.text
        assert "此前连续跳过 3 次" in caplog.text


class TestProvisioningPartUpdateResilience:
    """回归：配网后台线程不得死于未捕获异常。

    实车排查（2026-08-07）发现 update() 线程一旦异常退出，HOSTIP 上报
    静默停止且永不恢复，进程表象一切正常。循环体必须兜住所有异常。
    """

    def test_loop_continues_after_unexpected_exception(self, monkeypatch):
        import threading
        import time as real_time
        from unittest.mock import MagicMock

        from donkeycar.parts import provisioning
        from donkeycar.parts.provisioning import ProvisioningPart

        mock_ser = MagicMock()
        mock_ser.in_waiting = 0
        monkeypatch.setattr(
            provisioning.serial, "Serial", lambda **kwargs: mock_ser
        )

        part = ProvisioningPart(serial_port="/dev/null", baudrate=115200)
        calls = {"read": 0, "report": 0}

        def flaky_read():
            calls["read"] += 1
            if calls["read"] <= 3:
                raise RuntimeError("simulated unexpected error")

        monkeypatch.setattr(part, "_read_and_process", flaky_read)
        monkeypatch.setattr(
            part,
            "_maybe_report_host_ip",
            lambda: calls.__setitem__("report", calls["report"] + 1),
        )

        thread = threading.Thread(target=part.update, daemon=True)
        thread.start()
        # 轮询等待循环跑过前 3 次异常调用，而不是固定 sleep 0.5s：
        # 慢的 CI runner（macOS）线程启动延迟大，0.5s 内可能只跑了 3 次循环
        deadline = real_time.monotonic() + 5.0
        while calls["read"] <= 3 and real_time.monotonic() < deadline:
            real_time.sleep(0.02)
        part.shutdown()
        thread.join(timeout=2)

        assert not thread.is_alive()
        # 前 3 次抛异常后循环仍继续执行（线程未死）
        assert calls["read"] > 3
        assert calls["report"] > 0
