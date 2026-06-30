"""ESP32 Serial2 双向联通验证 Part。

通过 Linux 串口与 ESP32 Serial2（GPIO18/19）通信，验证物理链路通畅。
协议：
  下行（Host → ESP32）: PING,<seq>\\n
  上行（ESP32 → Host）: PONG,<seq>,<ms>\\n  |  BEAT,<ms>\\n  |  ECHO,<原文>\\n

配置示例（myconfig.py）：
    from donkeycar.parts.serial2_test import Serial2Test
    SERIAL2_PORT = "/dev/ttyS5"
    V.add(Serial2Test(port=SERIAL2_PORT), outputs=[
        'serial2/status', 'serial2/rtt_ms', 'serial2/lost_packets',
    ], threaded=True)
"""

import logging
import time
import threading

try:
    import serial
except ModuleNotFoundError as exc:
    raise RuntimeError("需要安装 pyserial：pip install pyserial") from exc

logger = logging.getLogger(__name__)


class Serial2Test:
    """Serial2 双向联通验证 Part。

    生命周期：
        setup()  → 打开串口
        update() → 线程主循环：周期性发送 PING，接收并解析响应
        run()    → 返回最新状态（兼容非线程模式）
        shutdown() → 关闭串口
    """

    # ------------------------------------------------------------------
    # 构造函数
    # ------------------------------------------------------------------
    def __init__(self, port="/dev/ttyS5", baudrate=115200, timeout=0.1,
                 ping_interval=1.0, disconnect_timeout=3.0):
        """初始化 Serial2Test Part。

        Args:
            port: 串口设备路径
            baudrate: 波特率，默认 115200
            timeout: 串口读取超时，秒，默认 0.1
            ping_interval: PING 发送间隔，秒，默认 1.0
            disconnect_timeout: 断连判定超时，秒，默认 3.0
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ping_interval = ping_interval
        self._disconnect_timeout = disconnect_timeout

        self._ser = None
        self._lock = threading.Lock()
        self._running = False

        # 状态字段
        self._seq = 0                       # 下一个 PING 序列号 (uint16)
        self._last_pong_seq = -1            # 上一次收到 PONG 的序列号（-1 表示尚未收到）
        self._last_data_time = 0.0          # 最后一次收到数据的时间 (monotonic)
        self._rtt_ms = 0.0                  # 最新往返延迟 (ms)
        self._lost_packets = 0              # 累计丢包数
        self._last_ping_send_time = {}      # seq → monotonic 发送时间映射

    # ------------------------------------------------------------------
    # 静态解析方法
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_line(line: str) -> dict | None:
        """解析一行文本，返回结构化 dict 或 None（格式无效）。

        Returns:
            {'type': 'pong', 'seq': int, 'ms': int}
            {'type': 'beat', 'ms': int}
            {'type': 'echo', 'data': str}
            {'type': 'unknown', 'raw': str}
            None  — 空行或格式无效
        """
        line = line.strip()
        if not line:
            return None

        # PONG,<seq>,<ms>
        if line.startswith("PONG"):
            if not line.startswith("PONG,"):
                return None  # "PONG" 无逗号 → 无效
            parts = line.split(",", 2)
            if len(parts) != 3:
                return None
            try:
                seq = int(parts[1])
                ms = int(parts[2])
                if seq < 0:
                    return None
                return {"type": "pong", "seq": seq, "ms": ms}
            except ValueError:
                return None

        # BEAT,<ms>
        if line.startswith("BEAT"):
            if not line.startswith("BEAT,"):
                return None  # "BEAT" 无逗号 → 无效
            parts = line.split(",", 1)
            if len(parts) != 2:
                return None
            try:
                ms = int(parts[1])
                return {"type": "beat", "ms": ms}
            except ValueError:
                return None

        # ECHO,<data>
        if line.startswith("ECHO"):
            if not line.startswith("ECHO,"):
                return None  # "ECHO" 无逗号 → 无效
            parts = line.split(",", 1)
            data = parts[1] if len(parts) == 2 else ""
            return {"type": "echo", "data": data}

        # 未知格式
        return {"type": "unknown", "raw": line}

    # ------------------------------------------------------------------
    # 帧构建
    # ------------------------------------------------------------------
    @staticmethod
    def _build_ping(seq: int) -> bytes:
        """构建 PING 帧字节串。

        Args:
            seq: 序列号 (0-65535)

        Returns:
            b"PING,<seq>\\n"
        """
        return f"PING,{seq}\n".encode("ascii")

    # ------------------------------------------------------------------
    # 内部状态更新方法
    # ------------------------------------------------------------------
    def _record_ping_send(self, seq: int):
        """记录 PING 发送时间并递增序列号。

        Args:
            seq: 当前发送的序列号
        """
        self._last_ping_send_time[seq] = time.monotonic()
        # 清理旧映射，防止内存泄漏（保留最近 64 个）
        if len(self._last_ping_send_time) > 64:
            stale = sorted(self._last_ping_send_time.keys())[:-64]
            for k in stale:
                del self._last_ping_send_time[k]
        # seq 递增并 uint16 回绕
        self._seq = (seq + 1) & 0xFFFF

    def _handle_pong(self, seq: int, esp_ms: int):
        """处理收到的 PONG 帧：计算 RTT，更新丢包统计。

        Args:
            seq: ESP32 回传的序列号
            esp_ms: ESP32 侧的 millis() 时间戳
        """
        send_time = self._last_ping_send_time.pop(seq, None)
        if send_time is not None:
            self._rtt_ms = (time.monotonic() - send_time) * 1000.0

        # 丢包统计：基于上一次收到的 PONG seq 计算跳跃
        if self._last_pong_seq >= 0:
            gap = (seq - self._last_pong_seq - 1) & 0xFFFF
            if gap < 32768:  # 正向跳跃（非回绕）
                self._lost_packets += gap
        self._last_pong_seq = seq

    def _process_line(self, line: str):
        """处理一行接收数据，更新内部状态。

        Args:
            line: 去除首尾空白后的单行文本
        """
        parsed = self._parse_line(line)
        if parsed is None:
            return

        self._last_data_time = time.monotonic()

        if parsed["type"] == "pong":
            self._handle_pong(parsed["seq"], parsed["ms"])
        elif parsed["type"] == "beat":
            pass  # 心跳仅更新时间戳，已在上面更新
        elif parsed["type"] == "echo":
            logger.info("Serial2 ECHO: %s", parsed["data"])
        # unknown 类型也仅更新时间戳

    def _build_output(self) -> dict:
        """构建当前状态输出 dict。

        Returns:
            {'status': 'connected'|'disconnected',
             'rtt_ms': float,
             'lost_packets': int}
        """
        connected = (
            self._last_data_time > 0
            and (time.monotonic() - self._last_data_time) < self._disconnect_timeout
        )
        return {
            "status": "connected" if connected else "disconnected",
            "rtt_ms": round(self._rtt_ms, 2),
            "lost_packets": self._lost_packets,
        }

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------
    def setup(self):
        """Part 加载时调用：打开串口。"""
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout,
            )
            logger.info("Serial2 串口已打开: %s @ %d baud",
                         self._port, self._baudrate)
        except (OSError, serial.SerialException) as exc:
            logger.error("Serial2 串口打开失败: %s", exc)
            self._ser = None

    def update(self):
        """线程主循环：周期性发送 PING，接收并解析响应。"""
        self._running = True
        last_ping_time = 0.0

        while self._running:
            now = time.monotonic()

            # 发送 PING
            if now - last_ping_time >= self._ping_interval:
                if self._ser is not None:
                    try:
                        current_seq = self._seq
                        self._ser.write(self._build_ping(current_seq))
                        self._ser.flush()
                        self._record_ping_send(current_seq)
                    except (OSError, serial.SerialException) as exc:
                        logger.error("Serial2 PING 发送失败: %s", exc)
                last_ping_time = now

            # 读取响应
            if self._ser is not None:
                try:
                    while self._ser.in_waiting > 0:
                        raw = self._ser.readline()
                        if raw:
                            try:
                                line = raw.decode("utf-8", errors="ignore").strip()
                            except UnicodeDecodeError:
                                continue
                            if line:
                                self._process_line(line)
                except (OSError, serial.SerialException) as exc:
                    logger.error("Serial2 读取失败: %s", exc)

            time.sleep(0.01)  # ~100Hz 轮询

    def run(self):
        """非线程模式：返回最新状态。"""
        return self._build_output()

    def shutdown(self):
        """程序退出时调用：关闭串口。"""
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        logger.info("Serial2 已关闭")
