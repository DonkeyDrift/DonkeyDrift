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

AuthPart 代理模式支持：
    当 AuthPart 与 Serial2Test 使用同一串口时，AuthPart 通过 Serial2Test 的
    send() + set_line_callback() 收发数据，避免竞争串口 fd。
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
        update() → 线程主循环：打开串口，周期性发送 PING，接收并解析响应
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
        self._line_callback = None  # 外部行回调：callable(line: str) 或 None

        # 状态字段
        self._seq = 0                       # 下一个 PING 序列号 (uint16)
        self._last_pong_seq = -1            # 上一次收到 PONG 的序列号（-1 表示尚未收到）
        self._last_data_time = 0.0          # 最后一次收到数据的时间 (monotonic)
        self._rtt_ms = 0.0                  # 最新往返延迟 (ms)
        self._lost_packets = 0              # 累计丢包数
        self._last_ping_send_time = {}      # seq → monotonic 发送时间映射

    # ------------------------------------------------------------------
    # 回调注册（供 AuthPart 代理模式使用）
    # ------------------------------------------------------------------
    def set_line_callback(self, callback):
        """注册行回调：Serial2 收到的每一行都会调用 callback(line)。

        AuthPart 可通过此机制捕获 OK:/ERR: 响应。
        callback 签名: callable(str) -> None，传 None 取消注册。
        """
        self._line_callback = callback

    @property
    def serial(self):
        """暴露串口对象，供外部查询状态。"""
        return self._ser

    @property
    def lock(self):
        """暴露串口锁。"""
        return self._lock

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
                return None
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
                return None
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
                return None
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
        """构建 PING 帧字节串。"""
        return f"PING,{seq}\n".encode("ascii")

    # ------------------------------------------------------------------
    # 内部状态更新方法
    # ------------------------------------------------------------------
    def _record_ping_send(self, seq: int):
        """记录 PING 发送时间并递增序列号。"""
        self._last_ping_send_time[seq] = time.monotonic()
        # 清理旧映射，防止内存泄漏（保留最近 64 个）
        if len(self._last_ping_send_time) > 64:
            stale = sorted(self._last_ping_send_time.keys())[:-64]
            for k in stale:
                del self._last_ping_send_time[k]
        # seq 递增并 uint16 回绕
        self._seq = (seq + 1) & 0xFFFF

    def _handle_pong(self, seq: int, esp_ms: int):
        """处理收到的 PONG 帧：计算 RTT，更新丢包统计。"""
        send_time = self._last_ping_send_time.pop(seq, None)
        if send_time is not None:
            self._rtt_ms = (time.monotonic() - send_time) * 1000.0

        # 丢包统计
        if self._last_pong_seq >= 0:
            gap = (seq - self._last_pong_seq - 1) & 0xFFFF
            if gap < 32768:
                self._lost_packets += gap
        self._last_pong_seq = seq

    def _process_line(self, line: str):
        """处理一行接收数据，更新内部状态。"""
        # 先通知外部回调（如 AuthPart 的响应等待器）
        if self._line_callback is not None:
            try:
                self._line_callback(line)
            except Exception:
                pass

        parsed = self._parse_line(line)
        if parsed is None:
            return

        self._last_data_time = time.monotonic()

        if parsed["type"] == "pong":
            self._handle_pong(parsed["seq"], parsed["ms"])
        elif parsed["type"] == "beat":
            pass  # 心跳仅更新时间戳
        elif parsed["type"] == "echo":
            logger.info("Serial2 ECHO: %s", parsed["data"])
        # unknown 类型也仅更新时间戳

    # ------------------------------------------------------------------
    # 串口扫描工具
    # ------------------------------------------------------------------
    @staticmethod
    def scan_ports(baudrate=115200, timeout=0.3, probe_retries=2):
        """扫描所有可用串口，找到 ESP32 Serial2 所在的设备。"""
        import glob

        candidates = []
        for pattern in ["/dev/ttyS*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
            candidates.extend(sorted(glob.glob(pattern)))

        if not candidates:
            logger.warning("未找到任何候选串口设备")
            return None, None

        exclude = {"/dev/ttyS4"}
        candidates = [c for c in candidates if c not in exclude]

        logger.info("Serial2 扫描：候选设备 %d 个（排除 %s）",
                     len(candidates), ", ".join(sorted(exclude)))

        scanned = 0
        for device in candidates:
            logger.info("Serial2 扫描：正在探测 %s ...", device)
            try:
                ser = serial.Serial(port=device, baudrate=baudrate, timeout=timeout)
            except (OSError, serial.SerialException) as exc:
                logger.warning("Serial2 扫描：跳过 %s（打开失败: %s）", device, exc)
                continue

            scanned += 1
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()

                for attempt in range(probe_retries):
                    ping_seq = (device.encode("utf-8", errors="ignore").__hash__()
                                & 0xFFFF) + attempt
                    ser.write(f"PING,{ping_seq}\n".encode("ascii"))
                    ser.flush()

                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        raw = ser.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="ignore").strip()
                            if line and line.startswith("PONG,"):
                                _, seq_str, ms_str = line.split(",", 2)
                                rtt = (time.monotonic() - (
                                    time.monotonic() - timeout)) * 1000
                                ser.close()
                                logger.info("Serial2 扫描：找到设备 %s", device)
                                return device, rtt
            except Exception as exc:
                logger.warning("Serial2 扫描：%s 通信异常 (%s)", device, exc)
                try:
                    ser.close()
                except Exception:
                    pass

        logger.warning("Serial2 扫描：已探测 %d 个端口，均无响应", scanned)
        return None, None

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------
    def update(self):
        """线程主循环：打开串口，周期性发送 PING，接收并解析响应。"""
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
            return

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

    def run_threaded(self):
        """线程模式：由 Vehicle 主循环调用，返回最新状态。"""
        return self._build_output()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def send(self, data: str):
        """向 ESP32 Serial2 发送任意文本行。

        Args:
            data: 要发送的文本（自动追加 \\n，无需手动添加）
        """
        if self._ser is None:
            logger.warning("Serial2 发送失败：串口未打开")
            return
        with self._lock:
            try:
                text = data.rstrip("\n") + "\n"
                self._ser.write(text.encode("ascii", errors="ignore"))
                self._ser.flush()
            except (OSError, serial.SerialException) as exc:
                logger.error("Serial2 发送失败: %s", exc)

    def shutdown(self):
        """关闭串口和线程。"""
        self._running = False
        if self._ser is not None and self._ser.is_open:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        logger.info("Serial2 已关闭")

    def _build_output(self):
        """构建当前状态输出。"""
        if self._ser is None:
            return ("disconnected", 0.0, 0)
        if time.monotonic() - self._last_data_time > self._disconnect_timeout:
            return ("timeout", self._rtt_ms, self._lost_packets)
        if self._rtt_ms > 0:
            return ("connected", self._rtt_ms, self._lost_packets)
        return ("waiting", 0.0, 0)
