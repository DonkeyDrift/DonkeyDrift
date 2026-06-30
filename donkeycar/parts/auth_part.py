"""
ESP32 eFuse 芯片 ID 身份识别系统 — Donkeycar AuthPart。

通过 Serial2 (/dev/ttyS6) 与 ESP32 固件 AuthService 通信，实现：
- 读取硬件 ID（eFuse MAC，不可变）
- 读取/写入/清空用户 ID（NVS 持久化 UUID）
- 生成 token 供网络模块使用

支持两种运行模式：
  1. 独立模式：自己打开 /dev/ttyS6，直接收发
  2. 代理模式：通过 Serial2Test 实例的 send() + 回调通信，
     避免与 Serial2Test 竞争串口 fd（推荐与 Serial2Test 共存时使用）

惰性初始化：
    Donkeycar 框架不调用 setup()。run() 在首次被 Vehicle 主循环调用时
    自动发送 READ_HW_ID + READ_UID 初始化 token。

配置示例（myconfig.py）：
  AUTH_SERIAL_PORT = "/dev/ttyS6"

  # 独立模式
  from donkeycar.parts.auth_part import AuthPart
  V.add(AuthPart(port=AUTH_SERIAL_PORT), outputs=["auth/token"])

  # 代理模式（与 Serial2Test 共存，推荐）
  V.add(AuthPart(port=AUTH_SERIAL_PORT, delegate=serial2), outputs=["auth/token"])
"""

import logging
import threading
import time

try:
    import serial
except ImportError:
    serial = None

logger = logging.getLogger(__name__)


class AuthPart:
    """设备身份认证 Part。

    生命周期（Donkeycar 框架）：
        run()     → 每帧调用。首次调用时自动初始化 token。
        shutdown() → 清理回调/关闭串口

    对外接口：
        write_uid(uid) → 写入用户 ID 到 ESP32 NVS
        clear_uid()    → 清空 ESP32 NVS 中的用户 ID
    """

    # ------------------------------------------------------------------
    # 常量
    # ------------------------------------------------------------------
    _RETRY_MAX = 3
    _RETRY_TIMEOUT_MS = 200
    _TWO_LINE_DELAY_S = 0.01
    _INIT_WAIT_MAX_S = 5.0     # 代理模式下等待 Serial2Test 串口就绪的最长时间

    # ------------------------------------------------------------------
    # 构造函数
    # ------------------------------------------------------------------
    def __init__(self, port="/dev/ttyS6", baudrate=115200, timeout=0.2,
                 max_retries=3, delegate=None):
        """初始化 AuthPart。

        Args:
            port: 串口设备路径
            baudrate: 波特率（独立模式使用）
            timeout: 串口读取超时，秒（独立模式使用）
            max_retries: 命令失败最大重试次数
            delegate: Serial2Test 实例（可选）。提供后进入代理模式。
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._max_retries = max_retries
        self._delegate = delegate
        self._ser = None
        self._lock = threading.Lock()
        self._resp_event = threading.Event()
        self._resp_line = None
        self._initialized = False
        self._init_deadline = 0.0

        # token 内部状态
        self._device_hw_id = None
        self._user_id = None
        self._error = None

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------
    def run(self):
        """每帧调用。首次调用时自动初始化 token（惰性初始化）。"""
        if not self._initialized:
            self._lazy_init()
        return self._build_token()

    def _lazy_init(self):
        """惰性初始化：发送 READ_HW_ID + READ_UID 填充 token。"""
        if serial is None:
            self._error = "pyserial not installed"
            logger.error("AuthPart: pyserial 未安装")
            self._initialized = True
            return

        if self._delegate is not None:
            # 代理模式：等待 Serial2Test 线程打开串口
            if self._init_deadline == 0.0:
                self._init_deadline = time.monotonic() + self._INIT_WAIT_MAX_S
                self._delegate.set_line_callback(self._on_line)
                logger.info("AuthPart: 代理模式，等待 Serial2Test 串口就绪...")

            if self._delegate.serial is None:
                if time.monotonic() < self._init_deadline:
                    return  # 继续等
                self._error = "delegate_serial_not_ready"
                logger.error("AuthPart: 代理模式超时：Serial2Test 串口未就绪")
                self._initialized = True
                return

            logger.info("AuthPart: 代理模式就绪，开始初始化 token")
        else:
            # 独立模式：自己打开串口
            try:
                self._ser = serial.Serial(
                    port=self._port,
                    baudrate=self._baudrate,
                    timeout=self._timeout,
                )
                self._ser.reset_input_buffer()
                logger.info("AuthPart: 串口 %s 初始化成功", self._port)
            except (OSError, serial.SerialException) as exc:
                self._error = f"serial_open_failed: {exc}"
                logger.error("AuthPart: 串口 %s 打开失败: %s", self._port, exc)
                self._initialized = True
                return

        # 发送 READ_HW_ID + READ_UID
        hw_response = self._send_cmd("READ_HW_ID")
        if hw_response and hw_response.startswith("OK:") and len(hw_response) > 3:
            self._device_hw_id = hw_response[3:]
            logger.info("AuthPart: 硬件 ID = %s", self._device_hw_id)
        else:
            self._error = "read_hw_id_failed"
            logger.error("AuthPart: 读取硬件 ID 失败")

        uid_response = self._send_cmd("READ_UID")
        if uid_response and uid_response.startswith("OK:"):
            uid_value = uid_response[3:]
            self._user_id = uid_value if uid_value else None
            logger.info("AuthPart: 用户 ID = %s, bound=%s",
                        self._user_id or "(未绑定)", self._user_id is not None)

        self._initialized = True

    def shutdown(self):
        """程序退出时调用：清理回调（代理模式）或关闭串口（独立模式）。"""
        if self._delegate is not None:
            self._delegate.set_line_callback(None)
        if self._ser is not None and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        logger.info("AuthPart: 已关闭")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def write_uid(self, uid):
        """写入用户 ID 到 ESP32 NVS。"""
        if self._delegate is None and self._ser is None:
            logger.error("AuthPart: write_uid 失败：串口未打开")
            return False

        if not self._is_valid_uuid(uid):
            logger.error("AuthPart: UUID 格式无效: %s", uid)
            return False

        response = self._send_two_line_cmd("WRITE_UID", uid)
        if response and response.startswith("OK:written"):
            self._user_id = uid
            logger.info("AuthPart: write_uid 成功: %s", uid)
            return True

        logger.error("AuthPart: write_uid 失败: %s", response)
        return False

    def clear_uid(self):
        """清空 ESP32 NVS 中的用户 ID。"""
        if self._delegate is None and self._ser is None:
            logger.error("AuthPart: clear_uid 失败：串口未打开")
            return False

        response = self._send_cmd("CLEAR_UID")
        if response and response.startswith("OK:cleared"):
            self._user_id = None
            logger.info("AuthPart: clear_uid 成功")
            return True

        logger.error("AuthPart: clear_uid 失败: %s", response)
        return False

    # ------------------------------------------------------------------
    # 回调（代理模式）
    # ------------------------------------------------------------------
    def _on_line(self, line):
        """Serial2Test 行回调：捕获 OK:/ERR: 响应并通知等待者。"""
        if line.startswith("OK:") or line.startswith("ERR:"):
            self._resp_line = line
            self._resp_event.set()

    # ------------------------------------------------------------------
    # 发送命令
    # ------------------------------------------------------------------
    def _send_raw(self, text):
        """发送一行文本（不含 \\n）。"""
        if self._delegate is not None:
            self._delegate.send(text)
        elif self._ser is not None:
            try:
                self._ser.write((text + "\n").encode("utf-8"))
                self._ser.flush()
            except Exception as exc:
                logger.error("AuthPart: 串口写入失败: %s", exc)

    def _wait_response(self, timeout_ms):
        """等待 OK: 或 ERR: 响应到达。"""
        if self._delegate is not None:
            self._resp_line = None
            self._resp_event.clear()
            if self._resp_event.wait(timeout_ms / 1000.0):
                return self._resp_line
            return None

        # 独立模式：轮询串口，过滤噪声
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            try:
                raw = self._ser.readline()
            except Exception as exc:
                logger.error("AuthPart: 串口读取异常: %s", exc)
                return None

            if not raw:
                time.sleep(0.001)
                continue

            try:
                line = raw.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue

            if not line or line.startswith(("BEAT,", "PONG,", "ECHO,")):
                continue

            if line.startswith("OK:") or line.startswith("ERR:"):
                return line

        return None

    def _send_cmd(self, cmd):
        """发送单行命令，含重试。"""
        for attempt in range(self._max_retries):
            self._send_raw(f"CMD:{cmd}")
            resp = self._wait_response(self._RETRY_TIMEOUT_MS)
            if resp is not None:
                return resp
            logger.warning("AuthPart: CMD:%s 第 %d/%d 次超时",
                           cmd, attempt + 1, self._max_retries)

        logger.error("AuthPart: CMD:%s 全部 %d 次重试耗尽", cmd, self._max_retries)
        return None

    def _send_two_line_cmd(self, cmd, arg):
        """发送两行命令（用于 WRITE_UID）。"""
        with self._lock:
            self._send_raw(f"CMD:{cmd}")
            time.sleep(self._TWO_LINE_DELAY_S)
            self._send_raw(f"ARG:{arg}")
            return self._wait_response(self._RETRY_TIMEOUT_MS)

    # ------------------------------------------------------------------
    # UUID 格式校验
    # ------------------------------------------------------------------
    @staticmethod
    def _is_valid_uuid(s):
        if len(s) != 36:
            return False
        for i, c in enumerate(s):
            if i in (8, 13, 18, 23):
                if c != "-":
                    return False
            else:
                if not (("0" <= c <= "9") or ("a" <= c <= "f") or ("A" <= c <= "F")):
                    return False
        return True

    # ------------------------------------------------------------------
    # token 构建
    # ------------------------------------------------------------------
    def _build_token(self):
        token = {
            "device_hw_id": self._device_hw_id,
            "user_id": self._user_id,
            "bound": self._user_id is not None,
            "signature": None,
        }
        if self._error:
            token["error"] = self._error
        return token
