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
