"""Serial2 双向联通验证 Part 单元测试。

测试覆盖：
- PING 帧格式生成
- PONG 帧解析（seq、ms 提取）
- BEAT 帧解析
- ECHO 帧解析
- RTT 计算精度
- 断连检测（>3 秒无数据）
- seq uint16 回绕
- status 输出格式
"""

import time
import pytest
from unittest.mock import MagicMock, call


# ---------------------------------------------------------------------------
# 被测模块 — 直接从 parts 导入（在实现后可用）
# ---------------------------------------------------------------------------
SERIAL2_TEST_MODULE = "donkeycar.parts.serial2_test"


class TestPingFrameFormat:
    """验证 PING 帧生成格式。"""

    def test_ping_format_basic(self):
        """PING 帧应为 'PING,<seq>\\n' 格式。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        frame = part._build_ping(seq=0)
        assert frame == b"PING,0\n"

    def test_ping_seq_increments(self):
        """seq 按调用参数递增。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        assert part._build_ping(seq=42) == b"PING,42\n"

    def test_ping_seq_uint16_max(self):
        """seq 达到 65535 (uint16 最大值) 时格式正确。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        frame = part._build_ping(seq=65535)
        assert frame == b"PING,65535\n"


class TestPongParsing:
    """验证 PONG 帧解析。"""

    def test_pong_normal(self):
        """正常 PONG 帧：'PONG,<seq>,<ms>\\n'。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("PONG,5,123456")
        assert result is not None
        assert result["type"] == "pong"
        assert result["seq"] == 5
        assert result["ms"] == 123456

    def test_pong_zero_values(self):
        """seq 和 ms 可以为 0。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("PONG,0,0")
        assert result is not None
        assert result["type"] == "pong"
        assert result["seq"] == 0
        assert result["ms"] == 0

    def test_pong_large_ms(self):
        """ms 可达 uint32 范围（millis() 约 49 天回绕）。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("PONG,100,4294967295")
        assert result is not None
        assert result["seq"] == 100
        assert result["ms"] == 4294967295

    def test_pong_malformed_returns_none(self):
        """格式错误时返回 None。"""
        from donkeycar.parts.serial2_test import Serial2Test

        assert Serial2Test._parse_line("PONG,abc,123") is None
        assert Serial2Test._parse_line("PONG,1") is None
        assert Serial2Test._parse_line("PONG") is None
        assert Serial2Test._parse_line("PONG,") is None
        assert Serial2Test._parse_line("") is None

    def test_pong_negative_seq_returns_none(self):
        """seq 为负数视为无效。"""
        from donkeycar.parts.serial2_test import Serial2Test

        assert Serial2Test._parse_line("PONG,-1,100") is None


class TestBeatParsing:
    """验证 BEAT 帧解析。"""

    def test_beat_normal(self):
        """正常 BEAT 帧：'BEAT,<ms>\\n'。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("BEAT,999888")
        assert result is not None
        assert result["type"] == "beat"
        assert result["ms"] == 999888

    def test_beat_zero(self):
        """ms 为 0 合法。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("BEAT,0")
        assert result is not None
        assert result["type"] == "beat"

    def test_beat_malformed_returns_none(self):
        """格式错误时返回 None。"""
        from donkeycar.parts.serial2_test import Serial2Test

        assert Serial2Test._parse_line("BEAT") is None
        assert Serial2Test._parse_line("BEAT,") is None
        assert Serial2Test._parse_line("BEAT,xyz") is None


class TestEchoParsing:
    """验证 ECHO 帧解析。"""

    def test_echo_simple(self):
        """ECHO 帧原样返回发送内容。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("ECHO,hello world")
        assert result is not None
        assert result["type"] == "echo"
        assert result["data"] == "hello world"

    def test_echo_empty_body(self):
        """ECHO 后允许无内容。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("ECHO,")
        assert result is not None
        assert result["type"] == "echo"
        assert result["data"] == ""

    def test_echo_malformed(self):
        """无逗号分隔符返回 None。"""
        from donkeycar.parts.serial2_test import Serial2Test

        assert Serial2Test._parse_line("ECHO") is None


class TestDisconnectDetection:
    """验证断连检测逻辑。"""

    def test_initial_status_disconnected(self):
        """初始状态应为 disconnected（尚未收到任何数据）。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5", disconnect_timeout=3.0)
        status, rtt_ms, lost = part._build_output()
        assert status == "disconnected"

    def test_stays_connected_within_timeout(self, monkeypatch):
        """在超时窗口内持续收到数据时 status=connected。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5", disconnect_timeout=3.0)

        # 模拟刚收到数据
        fake_now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_now)
        part._last_data_time = fake_now

        # 2.9 秒后仍应 connected
        monkeypatch.setattr(time, "monotonic", lambda: 1002.9)
        status, rtt_ms, lost = part._build_output()
        assert status == "connected"

    def test_disconnected_after_timeout(self, monkeypatch):
        """超过超时窗口无数据时 status=disconnected。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5", disconnect_timeout=3.0)

        fake_now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_now)
        part._last_data_time = fake_now

        # 3.1 秒后应 disconnected
        monkeypatch.setattr(time, "monotonic", lambda: 1003.1)
        status, rtt_ms, lost = part._build_output()
        assert status == "disconnected"


class TestRttCalculation:
    """验证 RTT 计算。"""

    def test_rtt_correct(self, monkeypatch):
        """RTT = PONG 到达时间 - PING 发送时间。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")

        # 模拟发送 PING #0 的时间
        monkeypatch.setattr(time, "monotonic", lambda: 5000.0)
        part._record_ping_send(seq=0)

        # 模拟 3.2ms 后收到 PONG
        monkeypatch.setattr(time, "monotonic", lambda: 5000.0032)
        part._handle_pong(seq=0, esp_ms=12345)

        status, rtt_ms, lost = part._build_output()
        assert rtt_ms == pytest.approx(3.2, abs=0.1)

    def test_rtt_stale_pong_ignored(self, monkeypatch):
        """只保留最新的 RTT，旧 PONG 不覆盖。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")

        # 发送 PING #0
        monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
        part._record_ping_send(seq=0)

        # 收到 PONG #0, RTT=5ms
        monkeypatch.setattr(time, "monotonic", lambda: 1000.005)
        part._handle_pong(seq=0, esp_ms=1)

        # 发送 PING #1
        monkeypatch.setattr(time, "monotonic", lambda: 2000.0)
        part._record_ping_send(seq=1)

        # 收到 PONG #1, RTT=2ms
        monkeypatch.setattr(time, "monotonic", lambda: 2000.002)
        part._handle_pong(seq=1, esp_ms=2)

        status, rtt_ms, lost = part._build_output()
        assert rtt_ms == pytest.approx(2.0, abs=0.1)


class TestSeqOverflow:
    """验证 seq uint16 回绕处理。"""

    def test_seq_wraps_at_65536(self):
        """seq 达到 65535 后回绕到 0。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        # 模拟 seq 已在 65535
        part._seq = 65535
        part._record_ping_send(seq=65535)
        assert part._seq == 0  # 下次应为 0（回绕后递增）

    def test_rtt_tracks_wrapped_seq(self, monkeypatch):
        """回绕后 RTT 仍能正确计算。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        part._seq = 65535

        monkeypatch.setattr(time, "monotonic", lambda: 3000.0)
        part._record_ping_send(seq=65535)

        monkeypatch.setattr(time, "monotonic", lambda: 3000.004)
        part._handle_pong(seq=65535, esp_ms=999)

        status, rtt_ms, lost = part._build_output()
        assert rtt_ms == pytest.approx(4.0, abs=0.1)


class TestLostPacketCounting:
    """验证丢包计数。"""

    def test_lost_packets_increments_on_skip(self, monkeypatch):
        """当收到的 PONG seq 大于期望值时，中间 seq 计为丢包。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")

        # 发送 PING 0,1,2,3
        for seq in range(4):
            monkeypatch.setattr(time, "monotonic", lambda s=seq: 1000.0 + s)
            part._record_ping_send(seq=seq)

        # 只收到 PONG 0 和 PONG 3（1,2 丢失）
        monkeypatch.setattr(time, "monotonic", lambda: 1000.001)
        part._handle_pong(seq=0, esp_ms=1)
        monkeypatch.setattr(time, "monotonic", lambda: 1003.001)
        part._handle_pong(seq=3, esp_ms=4)

        status, rtt_ms, lost = part._build_output()
        assert lost == 2


class TestOutputFormat:
    """验证 run() 输出格式。"""

    def test_output_tuple_format(self):
        """输出应为 (status, rtt_ms, lost_packets) 三元组。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        output = part._build_output()
        assert len(output) == 3
        status, rtt_ms, lost = output
        assert status in ("connected", "disconnected")

    def test_output_types(self):
        """验证输出值类型正确。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        status, rtt_ms, lost = part._build_output()
        assert isinstance(status, str)
        assert isinstance(rtt_ms, (int, float))
        assert isinstance(lost, int)

    def test_run_returns_tuple(self, monkeypatch):
        """run() 返回 (status, rtt_ms, lost) 元组。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        # 模拟收到 BEAT
        monkeypatch.setattr(time, "monotonic", lambda: 500.0)
        part._last_data_time = 500.0

        status, rtt_ms, lost = part.run()
        assert status == "connected"

    def test_run_threaded_returns_tuple(self, monkeypatch):
        """run_threaded() 返回 (status, rtt_ms, lost) 元组。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        monkeypatch.setattr(time, "monotonic", lambda: 500.0)
        part._last_data_time = 500.0

        status, rtt_ms, lost = part.run_threaded()
        assert status == "connected"

class TestSendMethod:
    """验证 send() 对外接口。"""

    def test_send_writes_to_serial(self):
        """send() 将文本写入串口并 flush。"""
        from donkeycar.parts.serial2_test import Serial2Test

        mock_ser = MagicMock()
        part = Serial2Test(port="/dev/ttyS5")
        part._ser = mock_ser

        part.send("test message")
        mock_ser.write.assert_called_once_with(b"test message\n")
        mock_ser.flush.assert_called_once()

    def test_send_safe_when_serial_closed(self):
        """串口未打开时 send() 打印警告但不抛异常。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        part._ser = None
        # 不应抛异常
        part.send("should not crash")

    def test_send_non_ascii_ignored(self):
        """非 ASCII 字符被静默丢弃。"""
        from donkeycar.parts.serial2_test import Serial2Test

        mock_ser = MagicMock()
        part = Serial2Test(port="/dev/ttyS5")
        part._ser = mock_ser

        part.send("hello 中文 🌍")
        # 中文字符和 emoji 被 ignore 处理
        mock_ser.write.assert_called_once_with(b"hello  \n")


class TestShutdown:
    """验证 shutdown 清理行为。"""

    def test_shutdown_closes_serial(self):
        """shutdown() 应关闭串口连接。"""
        from donkeycar.parts.serial2_test import Serial2Test

        mock_ser = MagicMock()
        part = Serial2Test(port="/dev/ttyS5")
        part._ser = mock_ser

        part.shutdown()
        mock_ser.close.assert_called_once()
        assert part._ser is None

    def test_shutdown_safe_when_not_opened(self):
        """串口未打开时 shutdown 不抛异常。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        part._ser = None
        # 不应抛异常
        part.shutdown()


class TestUnknownLine:
    """验证未知行处理。"""

    def test_unknown_line_returns_unknown_type(self):
        """不符合任何已知格式的行返回 type='unknown'。"""
        from donkeycar.parts.serial2_test import Serial2Test

        result = Serial2Test._parse_line("SOME_RANDOM_DATA")
        assert result is not None
        assert result["type"] == "unknown"
        assert result["raw"] == "SOME_RANDOM_DATA"

    def test_unknown_line_still_updates_data_time(self, monkeypatch):
        """收到未知行也应更新 _last_data_time（维持 connected）。"""
        from donkeycar.parts.serial2_test import Serial2Test

        part = Serial2Test(port="/dev/ttyS5")
        fake_now = 5000.0
        monkeypatch.setattr(time, "monotonic", lambda: fake_now)

        part._process_line("UNKNOWN_FRAME")
        assert part._last_data_time == fake_now
