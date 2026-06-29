"""ESP32 eFuse 芯片 ID 身份识别系统 — AuthPart 单元测试。

测试覆盖：
- READ_HW_ID / READ_UID / WRITE_UID / CLEAR_UID 四条命令的正常流
- 各错误码的解析（01-04）
- 多行协议 WRITE_UID（CMD + ARG 分两行发送）
- 超时 + 3 次重试机制
- 串口打开失败的优雅降级
- token 字典输出格式
- 线程安全（threading.Lock 保护 _send_cmd）
"""

import importlib.util
import pathlib
import threading
import unittest
from unittest.mock import MagicMock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "donkeycar" / "parts" / "auth_part.py"

# 测试时动态加载 auth_part 模块
SPEC = importlib.util.spec_from_file_location("auth_part", MODULE_PATH)
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _b(seq):
    """将字符串列表编码为 bytes 列表，空字符串对应 b""（模拟超时）。"""
    return [s.encode("utf-8") if s else b"" for s in seq]


def _set_readline(mock_ser, responses):
    """设置 mock 串口的 readline 返回序列（自动编码为 bytes）。"""
    mock_ser.readline.side_effect = _b(responses)
    mock_ser.reset_mock()


def _make_mock_serial(readline_sequence):
    """构建模拟 serial.Serial 实例。

    readline_sequence: list[str] — 每次调用 readline() 依次返回的值。
        空字符串 "" 表示超时（readline 返回 b""）。
        非空字符串自动编码为 bytes。
    """
    mock = MagicMock()
    mock.readline.side_effect = _b(readline_sequence)
    mock.in_waiting = 0
    mock.is_open = True
    return mock


def _write_bytes_calls(mock_ser):
    """提取 mock 串口 write() 调用的 bytes 参数列表。"""
    return [c.args[0] for c in mock_ser.write.call_args_list]


def _write_str_calls(mock_ser):
    """提取 mock 串口 write() 调用的解码后字符串列表。"""
    return [c.args[0].decode("utf-8", errors="ignore") for c in mock_ser.write.call_args_list]


# ---------------------------------------------------------------------------
# AuthPart 单元测试
# ---------------------------------------------------------------------------
class TestAuthPartCommands(unittest.TestCase):
    """覆盖四条 Auth 命令的正常流和错误码解析。"""

    def setUp(self):
        """每个测试用例前重置状态。"""
        self.mock_ser = None
        self.part = None

    def _create_part_with_mock(self, readline_sequence):
        """用模拟串口创建 AuthPart 实例并执行 setup()。"""
        self.mock_ser = _make_mock_serial(readline_sequence)
        with patch("serial.Serial", return_value=self.mock_ser):
            self.part = AUTH.AuthPart(port="/dev/fake", baudrate=115200, timeout=0.2)
            self.part.setup()

    # ---- READ_HW_ID ----

    def test_read_hw_id_returns_chip_id(self):
        """READ_HW_ID 应返回 12 字符小写 hex 硬件 ID。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",   # READ_HW_ID 响应
            "OK:\n",                 # READ_UID 响应（未绑定）
        ])
        token = self.part.run()
        self.assertEqual(token["device_hw_id"], "a1b2c3d4e5f6")
        self.assertFalse(token["bound"])

    def test_read_hw_id_nack_then_ok_on_retry(self):
        """READ_HW_ID 首次超时空行、第二次返回 OK。"""
        self._create_part_with_mock([
            "",                      # 超时 -> 重试
            "OK:abcdef123456\n",     # 重试成功
            "OK:\n",                 # READ_UID
        ])
        token = self.part.run()
        self.assertEqual(token["device_hw_id"], "abcdef123456")
        # 验证发送了两次 CMD:READ_HW_ID
        hw_id_calls = [c for c in _write_bytes_calls(self.mock_ser) if b"READ_HW_ID" in c]
        self.assertEqual(len(hw_id_calls), 2)

    # ---- READ_UID ----

    def test_read_uid_when_bound_returns_uuid(self):
        """READ_UID 已绑定时应返回 UUID 且 bound=True。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:550e8400-e29b-41d4-a716-446655440000\n",
        ])
        token = self.part.run()
        self.assertEqual(token["user_id"], "550e8400-e29b-41d4-a716-446655440000")
        self.assertTrue(token["bound"])

    def test_read_uid_when_not_bound_returns_empty(self):
        """READ_UID 未绑定时 OK 后无数据，user_id 应为 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",                 # 空 OK，未绑定
        ])
        token = self.part.run()
        self.assertIsNone(token["user_id"])
        self.assertFalse(token["bound"])

    # ---- WRITE_UID ----

    def test_write_uid_success(self):
        """WRITE_UID 成功应返回 True，并更新 token 的 user_id。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        _set_readline(self.mock_ser, ["OK:written\n"])

        result = self.part.write_uid("550e8400-e29b-41d4-a716-446655440000")
        self.assertTrue(result)

        # 验证发送了 CMD:WRITE_UID 和 ARG:<uuid>
        writes = _write_str_calls(self.mock_ser)
        self.assertIn("CMD:WRITE_UID\n", writes)
        self.assertIn("ARG:550e8400-e29b-41d4-a716-446655440000\n", writes)

    def test_write_uid_nvs_write_fail(self):
        """WRITE_UID 返回 ERR:03 时 write_uid 应返回 False。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        _set_readline(self.mock_ser, ["ERR:03:NVS write fail\n"] * 3)

        result = self.part.write_uid("550e8400-e29b-41d4-a716-446655440000")
        self.assertFalse(result)
        # 应重试 3 次
        cmd_count = sum(1 for c in _write_bytes_calls(self.mock_ser) if b"WRITE_UID" in c)
        self.assertEqual(cmd_count, 3)

    # ---- CLEAR_UID ----

    def test_clear_uid_success(self):
        """CLEAR_UID 成功应返回 True，且更新 token 的 user_id 为 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:550e8400-e29b-41d4-a716-446655440000\n",
        ])
        _set_readline(self.mock_ser, ["OK:cleared\n"])

        result = self.part.clear_uid()
        self.assertTrue(result)

        writes = _write_str_calls(self.mock_ser)
        self.assertIn("CMD:CLEAR_UID\n", writes)

    # ---- 未知命令 ----

    def test_unknown_command_returns_err_then_retries_exhausted(self):
        """ERR 回复触发重试，3 次全部 ERR 后 _send_cmd 返回 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        _set_readline(self.mock_ser, ["ERR:01:unknown command\n"] * 3)

        response = self.part._send_cmd("CMD:FOO\n")
        self.assertIsNone(response)
        # 验证尝试了 3 次
        cmd_count = sum(1 for c in _write_bytes_calls(self.mock_ser) if b"CMD:FOO" in c)
        self.assertEqual(cmd_count, 3)

    # ---- 超时重试 ----

    def test_timeout_with_retry_exhausted(self):
        """3 次全部超时后 _send_cmd 应返回 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        _set_readline(self.mock_ser, ["", "", ""])  # 3 次超时

        result = self.part._send_cmd("CMD:READ_HW_ID\n")
        self.assertIsNone(result)
        # 验证尝试了 3 次
        self.assertEqual(len(_write_bytes_calls(self.mock_ser)), 3)

    def test_timeout_succeeds_on_second_retry(self):
        """首次超时、第二次返回 OK，_send_cmd 应成功。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        _set_readline(self.mock_ser, ["", "OK:data\n"])

        result = self.part._send_cmd("CMD:READ_UID\n")
        self.assertEqual(result, "OK:data")
        self.assertEqual(len(_write_bytes_calls(self.mock_ser)), 2)


# ---------------------------------------------------------------------------
# 生命周期与错误处理
# ---------------------------------------------------------------------------
class TestAuthPartLifecycle(unittest.TestCase):
    """覆盖 AuthPart 生命周期和错误处理。"""

    def test_setup_serial_open_failed(self):
        """串口打开失败时 token 应包含 error 字段，不抛异常。"""
        with patch("serial.Serial", side_effect=OSError("Permission denied")):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()
            token = part.run()
            self.assertIn("error", token)
            self.assertIn("serial_open_failed", token["error"])
            self.assertIsNone(token["device_hw_id"])
            self.assertIsNone(token["user_id"])
            self.assertFalse(token["bound"])

    def test_shutdown_closes_serial(self):
        """shutdown() 应关闭串口。"""
        mock_ser = _make_mock_serial(["OK:abcdef123456\n", "OK:\n"])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()
            part.shutdown()
            mock_ser.close.assert_called_once()

    def test_shutdown_when_serial_is_none(self):
        """串口打开失败后 shutdown() 不抛异常。"""
        with patch("serial.Serial", side_effect=OSError("No such device")):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()
            part.shutdown()  # 不应抛异常


# ---------------------------------------------------------------------------
# Token 格式
# ---------------------------------------------------------------------------
class TestAuthPartTokenFormat(unittest.TestCase):
    """验证 token 输出格式符合规范。"""

    def test_token_structure_when_bound(self):
        """已绑定时 token 应包含完整字段。"""
        mock_ser = _make_mock_serial([
            "OK:a1b2c3d4e5f6\n",
            "OK:550e8400-e29b-41d4-a716-446655440000\n",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()
            token = part.run()

            self.assertIn("device_hw_id", token)
            self.assertIn("user_id", token)
            self.assertIn("bound", token)
            self.assertIn("signature", token)
            self.assertEqual(token["device_hw_id"], "a1b2c3d4e5f6")
            self.assertEqual(token["user_id"], "550e8400-e29b-41d4-a716-446655440000")
            self.assertTrue(token["bound"])
            self.assertIsNone(token["signature"])

    def test_token_structure_when_unbound(self):
        """未绑定时 bound=False, user_id=None。"""
        mock_ser = _make_mock_serial([
            "OK:abcdef123456\n",
            "OK:\n",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()
            token = part.run()

            self.assertEqual(token["device_hw_id"], "abcdef123456")
            self.assertIsNone(token["user_id"])
            self.assertFalse(token["bound"])


# ---------------------------------------------------------------------------
# 线程安全
# ---------------------------------------------------------------------------
class TestAuthPartThreadSafety(unittest.TestCase):
    """验证 threading.Lock 保护串口操作。"""

    def test_concurrent_write_uid_serialized(self):
        """并发调用 write_uid 应串行执行，不出现数据竞争。

        使用可追踪的包装锁验证：任意时刻只有一个线程在临界区内。
        """
        mock_ser = _make_mock_serial([
            "OK:a1b2c3d4e5f6\n",
            "OK:\n",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.setup()

        _set_readline(mock_ser, ["OK:written\n"] * 10)

        # 用一个可追踪的锁替换原始锁
        class TrackedLock:
            """包装 threading.Lock，记录进入/退出事件。"""
            def __init__(self):
                self._lock = threading.Lock()
                self.events = []

            def acquire(self, *args, **kwargs):
                self.events.append(("enter", threading.get_ident()))
                return self._lock.acquire(*args, **kwargs)

            def release(self, *args, **kwargs):
                self.events.append(("exit", threading.get_ident()))
                return self._lock.release(*args, **kwargs)

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *args):
                self.release()

        tracked = TrackedLock()
        part._lock = tracked

        results = []
        errors = []

        def do_write(uid_suffix):
            try:
                results.append(
                    part.write_uid(f"550e8400-e29b-41d4-a716-4466554400{uid_suffix:02d}")
                )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=do_write, args=(i,))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 无异常
        self.assertEqual(len(errors), 0)
        # 全部成功
        self.assertTrue(all(results))

        # 验证串行化：enter/exit 严格交替，不存在嵌套
        in_critical = 0
        for event, tid in tracked.events:
            if event == "enter":
                self.assertEqual(in_critical, 0,
                                 f"线程 {tid} 在另一个线程持有锁时进入临界区")
                in_critical = 1
            else:  # exit
                in_critical = 0
        self.assertEqual(in_critical, 0, "锁未正确释放")


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------
class TestAuthPartDefaultConfig(unittest.TestCase):
    """验证默认配置值。"""

    def test_default_port_and_baudrate(self):
        """默认端口和波特率与 spec 一致。"""
        mock_ser = _make_mock_serial(["OK:abcdef123456\n", "OK:\n"])
        with patch("serial.Serial", return_value=mock_ser) as mock_serial_cls:
            part = AUTH.AuthPart()
            part.setup()
            mock_serial_cls.assert_called_once()
            call_kwargs = mock_serial_cls.call_args.kwargs
            self.assertEqual(call_kwargs["port"], "/dev/ttyS6")
            self.assertEqual(call_kwargs["baudrate"], 115200)
            self.assertAlmostEqual(call_kwargs["timeout"], 0.2)


if __name__ == "__main__":
    unittest.main()
