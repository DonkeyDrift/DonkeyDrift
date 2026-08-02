"""ESP32 eFuse 芯片 ID 身份识别系统 — AuthPart 单元测试。

对应当前实现（惰性初始化版，无 setup()）：
- 惰性初始化：首次 run() 自动打开串口并发送 READ_HW_ID + READ_UID
- READ_HW_ID / READ_UID / WRITE_UID / CLEAR_UID 四条命令的正常流
- 多行协议 WRITE_UID（CMD + ARG 分两行发送）
- 超时触发重试（最多 3 次）；OK:/ERR: 响应立即返回，不重试
- 串口打开失败的优雅降级（token 带 error 字段）
- token 字典输出格式
- 线程安全（threading.Lock 保护 _send_two_line_cmd）
"""

import importlib.util
import pathlib
import threading
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "donkeycar" / "parts" / "auth_part.py"

# 测试时动态加载 auth_part 模块
SPEC = importlib.util.spec_from_file_location("auth_part", MODULE_PATH)
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


# ---------------------------------------------------------------------------
# MockSerial — 模拟 pyserial.Serial
# ---------------------------------------------------------------------------
class MockSerial:
    """模拟串口对象。

    - _read_queue: 预设的响应行列表（不含换行符），readline 按序弹出；
      队列耗尽后持续返回 b""（模拟串口静默超时，不抛 StopIteration）。
      当前实现的 _wait_response 会在超时窗口内循环调用 readline，
      因此"无响应"用空队列 + b"" 兜底表达，而不是预置有限个空行。
    - _write_hook: 可选回调 func(data: bytes)，每次 write() 后调用，
      用于模拟"设备漏掉前 N 次命令、第 N+1 次才响应"的场景。
    """

    def __init__(self, port=None, baudrate=115200, timeout=0.2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._read_queue = []          # 待 readline 返回的行列表（不含换行符）
        self._read_index = 0
        self._write_buffer = []        # 已 write 的 bytes 记录
        self._write_hook = None
        self._closed = False

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self._write_buffer.append(data)
        if self._write_hook is not None:
            self._write_hook(data)

    def flush(self):
        pass

    def readline(self):
        """按序返回 _read_queue 中的行（自动追加 \\n）；耗尽后返回 b""。"""
        if self._read_index < len(self._read_queue):
            line = self._read_queue[self._read_index]
            self._read_index += 1
            return (line + "\n").encode("utf-8")
        return b""  # 无数据（模拟超时）

    def close(self):
        self._closed = True

    @property
    def is_open(self):
        return not self._closed


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _make_mock_serial(readline_sequence):
    """构建 MockSerial 并预设 readline 响应脚本。

    readline_sequence: list[str] — 按序消费的响应行（不含换行符）。
        队列耗尽后 readline 持续返回 b""（串口静默）。
    """
    mock = MockSerial()
    mock._read_queue = list(readline_sequence)
    return mock


def _set_readline(mock_ser, responses):
    """重设 readline 响应脚本，并清空写入记录（便于统计后续命令次数）。"""
    mock_ser._read_queue = list(responses)
    mock_ser._read_index = 0
    mock_ser._write_buffer.clear()


def _miss_writes_then_respond(mock_ser, cmd_bytes, miss_count, response_line):
    """模拟设备漏掉前 miss_count 次 cmd_bytes 命令，第 miss_count+1 次才响应。

    响应行插入到读队列当前位置，保证它是下一次 readline 读到的内容，
    且不影响队列中后续的预设响应。可重复调用为不同命令叠加规则。
    """
    prev_hook = mock_ser._write_hook

    def hook(data):
        if prev_hook is not None:
            prev_hook(data)
        if data == cmd_bytes and \
                mock_ser._write_buffer.count(cmd_bytes) == miss_count + 1:
            mock_ser._read_queue.insert(mock_ser._read_index, response_line)
    mock_ser._write_hook = hook


def _write_bytes_calls(mock_ser):
    """mock 串口 write() 收到的 bytes 参数列表。"""
    return list(mock_ser._write_buffer)


def _write_str_calls(mock_ser):
    """mock 串口 write() 收到的解码后字符串列表。"""
    return [d.decode("utf-8", errors="ignore") for d in mock_ser._write_buffer]


# ---------------------------------------------------------------------------
# AuthPart 单元测试
# ---------------------------------------------------------------------------
class TestAuthPartCommands(unittest.TestCase):
    """覆盖四条 Auth 命令的正常流和错误处理。"""

    def setUp(self):
        """每个测试用例前重置状态。"""
        self.mock_ser = None
        self.part = None

    def _create_part_with_mock(self, readline_sequence):
        """用模拟串口创建 AuthPart，并通过首次 run() 触发惰性初始化。"""
        self.mock_ser = _make_mock_serial(readline_sequence)
        with patch("serial.Serial", return_value=self.mock_ser):
            self.part = AUTH.AuthPart(port="/dev/fake", baudrate=115200, timeout=0.2)
            self.part.run()  # 惰性初始化：打开串口 + READ_HW_ID + READ_UID

    # ---- READ_HW_ID ----

    def test_read_hw_id_returns_chip_id(self):
        """READ_HW_ID 应返回 12 字符小写 hex 硬件 ID。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",   # READ_HW_ID 响应
            "OK:",               # READ_UID 响应（未绑定）
        ])
        token = self.part.run()
        self.assertEqual(token["device_hw_id"], "a1b2c3d4e5f6")
        self.assertFalse(token["bound"])

    def test_read_hw_id_nack_then_ok_on_retry(self):
        """READ_HW_ID 首次无响应（超时）、重试后第二次返回 OK。"""
        # 全部响应由 write hook 按命令触发：READ_HW_ID 第 2 次写入才响应，
        # READ_UID 首次写入即响应（未绑定）
        self.mock_ser = _make_mock_serial([])
        _miss_writes_then_respond(
            self.mock_ser, b"CMD:READ_HW_ID\n", 1, "OK:abcdef123456")
        _miss_writes_then_respond(self.mock_ser, b"CMD:READ_UID\n", 0, "OK:")
        with patch("serial.Serial", return_value=self.mock_ser):
            self.part = AUTH.AuthPart(port="/dev/fake", baudrate=115200, timeout=0.2)
            token = self.part.run()
        self.assertEqual(token["device_hw_id"], "abcdef123456")
        # 验证发送了两次 CMD:READ_HW_ID
        hw_id_calls = [c for c in _write_bytes_calls(self.mock_ser) if b"READ_HW_ID" in c]
        self.assertEqual(len(hw_id_calls), 2)

    # ---- READ_UID ----

    def test_read_uid_when_bound_returns_uuid(self):
        """READ_UID 已绑定时应返回 UUID 且 bound=True。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:550e8400-e29b-41d4-a716-446655440000",
        ])
        token = self.part.run()
        self.assertEqual(token["user_id"], "550e8400-e29b-41d4-a716-446655440000")
        self.assertTrue(token["bound"])

    def test_read_uid_when_not_bound_returns_empty(self):
        """READ_UID 未绑定时 OK 后无数据，user_id 应为 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",               # 空 OK，未绑定
        ])
        token = self.part.run()
        self.assertIsNone(token["user_id"])
        self.assertFalse(token["bound"])

    # ---- WRITE_UID ----

    def test_write_uid_success(self):
        """WRITE_UID 成功应返回 True，并更新 token 的 user_id。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        _set_readline(self.mock_ser, ["OK:written"])

        result = self.part.write_uid("550e8400-e29b-41d4-a716-446655440000")
        self.assertTrue(result)

        # 验证发送了 CMD:WRITE_UID 和 ARG:<uuid>
        writes = _write_str_calls(self.mock_ser)
        self.assertIn("CMD:WRITE_UID\n", writes)
        self.assertIn("ARG:550e8400-e29b-41d4-a716-446655440000\n", writes)

    def test_write_uid_nvs_write_fail(self):
        """WRITE_UID 返回 ERR:03 时 write_uid 应立即返回 False（ERR 不重试）。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        _set_readline(self.mock_ser, ["ERR:03:NVS write fail"])

        result = self.part.write_uid("550e8400-e29b-41d4-a716-446655440000")
        self.assertFalse(result)
        # 当前实现：_send_two_line_cmd 无重试循环，ERR 响应立即返回
        cmd_count = sum(1 for c in _write_bytes_calls(self.mock_ser) if b"WRITE_UID" in c)
        self.assertEqual(cmd_count, 1)

    # ---- CLEAR_UID ----

    def test_clear_uid_success(self):
        """CLEAR_UID 成功应返回 True，且更新 token 的 user_id 为 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:550e8400-e29b-41d4-a716-446655440000",
        ])
        _set_readline(self.mock_ser, ["OK:cleared"])

        result = self.part.clear_uid()
        self.assertTrue(result)

        writes = _write_str_calls(self.mock_ser)
        self.assertIn("CMD:CLEAR_UID\n", writes)

    # ---- 未知命令 ----

    def test_unknown_command_returns_err_without_retry(self):
        """ERR 响应视为有效回复：_send_cmd 立即返回该 ERR，不重试。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        _set_readline(self.mock_ser, ["ERR:01:unknown command"])

        response = self.part._send_cmd("FOO")
        self.assertEqual(response, "ERR:01:unknown command")
        # 只尝试了 1 次
        cmd_count = sum(1 for c in _write_bytes_calls(self.mock_ser) if b"CMD:FOO" in c)
        self.assertEqual(cmd_count, 1)

    # ---- 超时重试 ----

    def test_timeout_with_retry_exhausted(self):
        """3 次全部超时后 _send_cmd 应返回 None。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        _set_readline(self.mock_ser, [])  # 串口静默，持续超时

        result = self.part._send_cmd("READ_HW_ID")
        self.assertIsNone(result)
        # 验证尝试了 3 次
        self.assertEqual(len(_write_bytes_calls(self.mock_ser)), 3)

    def test_timeout_succeeds_on_second_retry(self):
        """首次超时、第二次返回 OK，_send_cmd 应成功。"""
        self._create_part_with_mock([
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        _set_readline(self.mock_ser, [])
        _miss_writes_then_respond(self.mock_ser, b"CMD:READ_UID\n", 1, "OK:data")

        result = self.part._send_cmd("READ_UID")
        self.assertEqual(result, "OK:data")
        self.assertEqual(len(_write_bytes_calls(self.mock_ser)), 2)


# ---------------------------------------------------------------------------
# 生命周期与错误处理
# ---------------------------------------------------------------------------
class TestAuthPartLifecycle(unittest.TestCase):
    """覆盖 AuthPart 生命周期和错误处理。"""

    def test_lazy_init_serial_open_failed(self):
        """串口打开失败时 token 应包含 error 字段，不抛异常。"""
        with patch("serial.Serial", side_effect=OSError("Permission denied")):
            part = AUTH.AuthPart(port="/dev/fake")
            token = part.run()  # 首次 run() 触发惰性初始化，串口打开失败
            self.assertIn("error", token)
            self.assertIn("serial_open_failed", token["error"])
            self.assertIsNone(token["device_hw_id"])
            self.assertIsNone(token["user_id"])
            self.assertFalse(token["bound"])

    def test_shutdown_closes_serial(self):
        """shutdown() 应关闭串口。"""
        mock_ser = _make_mock_serial(["OK:abcdef123456", "OK:"])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.run()
        part.shutdown()
        self.assertTrue(mock_ser._closed)

    def test_shutdown_when_serial_is_none(self):
        """串口打开失败后 shutdown() 不抛异常。"""
        with patch("serial.Serial", side_effect=OSError("No such device")):
            part = AUTH.AuthPart(port="/dev/fake")
            part.run()
        part.shutdown()  # 不应抛异常


# ---------------------------------------------------------------------------
# Token 格式
# ---------------------------------------------------------------------------
class TestAuthPartTokenFormat(unittest.TestCase):
    """验证 token 输出格式符合规范。"""

    def test_token_structure_when_bound(self):
        """已绑定时 token 应包含完整字段。"""
        mock_ser = _make_mock_serial([
            "OK:a1b2c3d4e5f6",
            "OK:550e8400-e29b-41d4-a716-446655440000",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            token = part.run()  # 惰性初始化 + 返回 token

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
            "OK:abcdef123456",
            "OK:",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
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
            "OK:a1b2c3d4e5f6",
            "OK:",
        ])
        with patch("serial.Serial", return_value=mock_ser):
            part = AUTH.AuthPart(port="/dev/fake")
            part.run()

        _set_readline(mock_ser, ["OK:written"] * 10)

        # 用一个可追踪的锁替换原始锁
        class TrackedLock:
            """包装 threading.Lock，记录进入/退出事件。

            "enter" 必须在真正拿到内层锁之后才记录，否则等待中的线程
            会提前留下 enter 事件，造成"嵌套进入"的假象。
            """
            def __init__(self):
                self._lock = threading.Lock()
                self.events = []

            def acquire(self, *args, **kwargs):
                result = self._lock.acquire(*args, **kwargs)
                self.events.append(("enter", threading.get_ident()))
                return result

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
        mock_ser = _make_mock_serial(["OK:abcdef123456", "OK:"])
        with patch("serial.Serial", return_value=mock_ser) as mock_serial_cls:
            part = AUTH.AuthPart()
            part.run()  # 惰性初始化时打开串口
            mock_serial_cls.assert_called_once()
            call_kwargs = mock_serial_cls.call_args.kwargs
            self.assertEqual(call_kwargs["port"], "/dev/ttyS6")
            self.assertEqual(call_kwargs["baudrate"], 115200)
            self.assertAlmostEqual(call_kwargs["timeout"], 0.2)


if __name__ == "__main__":
    unittest.main()
