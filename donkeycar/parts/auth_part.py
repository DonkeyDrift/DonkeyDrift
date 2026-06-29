"""ESP32 eFuse 芯片 ID 身份识别系统 — Donkeycar AuthPart。

通过串口与 ESP32 固件通信，实现：
- 读取硬件 ID（eFuse MAC）
- 读取/写入/清空用户 ID（NVS 持久化）
- 生成 token 供网络模块使用

协议格式（文本帧，\\n 分隔）：
  请求：CMD:<命令>\\n 或 CMD:<命令>\\nARG:<参数>\\n
  成功：OK:<数据>\\n
  失败：ERR:<错误码>:<描述>\\n

配置示例（myconfig.py）：
  from donkeycar.parts.auth_part import AuthPart
  AUTH_SERIAL_PORT = "/dev/ttyS6"

  V.add(AuthPart(port=AUTH_SERIAL_PORT), outputs=["auth/token"])
"""

import logging
import threading

try:
    import serial
except ModuleNotFoundError as exc:
    raise RuntimeError("需要安装 pyserial：pip install pyserial") from exc

logger = logging.getLogger(__name__)


class AuthPart:
    """设备身份认证 Part。

    生命周期：
        setup()  → 打开串口，读取硬件 ID 和用户 ID，生成 token
        run()    → 每帧调用，返回当前 token 字典
        shutdown() → 关闭串口

    对外接口：
        write_uid(uid) → 写入用户 ID 到 ESP32 NVS
        clear_uid()    → 清空 ESP32 NVS 中的用户 ID
    """

    # ------------------------------------------------------------------
    # 构造函数
    # ------------------------------------------------------------------
    def __init__(self, port="/dev/ttyS6", baudrate=115200, timeout=0.2,
                 max_retries=3):
        """初始化 AuthPart。

        Args:
            port: 串口设备路径（可在 myconfig.py 中配置为 AUTH_SERIAL_PORT）
            baudrate: 波特率，默认 115200
            timeout: 串口读取超时，秒，默认 0.2
            max_retries: 命令失败最大重试次数，默认 3
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._max_retries = max_retries
        self._ser = None
        self._lock = threading.Lock()

        # token 内部状态
        self._device_hw_id = None
        self._user_id = None

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------
    def setup(self):
        """Part 加载时调用：打开串口，读取硬件 ID 和用户 ID，生成 token。

        串口打开失败时不抛异常，token 中记录 error 字段。
        """
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout,
            )
        except (OSError, serial.SerialException) as exc:
            logger.error(f"串口打开失败: {exc}")
            self._ser = None
            return

        # 读取硬件 ID
        hw_response = self._send_cmd("CMD:READ_HW_ID")
        if hw_response and hw_response.startswith("OK:"):
            self._device_hw_id = hw_response[3:].strip()

        # 读取用户 ID
        uid_response = self._send_cmd("CMD:READ_UID")
        if uid_response and uid_response.startswith("OK:"):
            uid_value = uid_response[3:].strip()
            self._user_id = uid_value if uid_value else None

        logger.info("初始化完成 hw_id=%s user_id=%s",
                     self._device_hw_id, self._user_id)

    def run(self):
        """每帧调用，返回当前 token 字典（无 I/O）。"""
        return self._build_token()

    def shutdown(self):
        """程序退出时调用：关闭串口。"""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        logger.info("已关闭")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def write_uid(self, uid):
        """写入用户 ID 到 ESP32 NVS。

        Args:
            uid: UUID 字符串（36 字节）

        Returns:
            bool: True 表示写入成功
        """
        if self._ser is None:
            logger.error("write_uid 失败：串口未打开")
            return False

        # 两行协议：CMD:WRITE_UID 后跟 ARG:<uid>
        response = self._send_cmd(["CMD:WRITE_UID", f"ARG:{uid}"])
        if response and response.startswith("OK:"):
            self._user_id = uid
            logger.info("write_uid 成功: %s", uid)
            return True

        logger.error("write_uid 失败: %s", response)
        return False

    def clear_uid(self):
        """清空 ESP32 NVS 中的用户 ID。

        Returns:
            bool: True 表示清空成功
        """
        if self._ser is None:
            logger.error("clear_uid 失败：串口未打开")
            return False

        response = self._send_cmd("CMD:CLEAR_UID")
        if response and response.startswith("OK:"):
            self._user_id = None
            logger.info("clear_uid 成功")
            return True

        logger.error("clear_uid 失败: %s", response)
        return False

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _send_cmd(self, cmd_lines):
        """发送命令并读取回复，含超时重试。

        Args:
            cmd_lines: str 或 list[str] — 要发送的行（不含 \\n 后缀）

        Returns:
            str | None: 原始回复行（已 strip），超时/失败返回 None
        """
        if isinstance(cmd_lines, str):
            cmd_lines = [cmd_lines]

        with self._lock:
            for attempt in range(self._max_retries):
                # 发送所有行
                for line in cmd_lines:
                    self._ser.write((line + "\n").encode("utf-8"))
                self._ser.flush()

                # 等待回复（readline 由串口 timeout 控制最长等待时间）
                raw = self._ser.readline()
                if raw:
                    text = raw.decode("utf-8", errors="ignore").strip()
                    if text.startswith("OK:"):
                        return text
                    # ERR 或非预期格式，视为通信失败，继续重试
                # 超时（raw 为空），继续重试

        return None

    def _build_token(self):
        """构建 token 字典，错误时包含 error 字段。"""
        if self._ser is None:
            return {
                "device_hw_id": None,
                "user_id": None,
                "bound": False,
                "signature": None,
                "error": "serial_open_failed: 串口未打开或初始化失败",
            }

        return {
            "device_hw_id": self._device_hw_id,
            "user_id": self._user_id,
            "bound": self._user_id is not None,
            "signature": None,
        }
