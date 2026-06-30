"""ESP32 WiFi 配网 Part。

通过 Linux 串口与 ESP32 配网固件通信，接收 WiFi 凭据并通过 nmcli 连接目标网络。
支持两种运行模式：
    1. Donkeycar Part 模式 — 通过 Vehicle.add(threaded=True) 注册
    2. 独立守护进程模式 — python -m donkeycar.parts.provisioning

配置示例（myconfig.py）：
    from donkeycar.parts.provisioning import ProvisioningPart
    PROVISIONING_ENABLED = True
    PROVISIONING_SERIAL_PORT = "/dev/ttyS4"
    V.add(ProvisioningPart(serial_port=PROVISIONING_SERIAL_PORT),
          outputs=['provisioning/status', 'provisioning/ssid',
                   'provisioning/ip', 'provisioning/error'],
          threaded=True)

协议：
    下行（ESP32 → Linux）: WIFI|<ssid>|<password>\\n
    上行（Linux → ESP32）: STATUS|CONNECTING\\n / OK|<ip>\\n / FAIL|<reason>\\n

ESP32 固件保持不变，独立运行在 ESP32 上。
"""

import logging
import re
import subprocess
import threading
import time

try:
    import serial
except ImportError:
    serial = None  # type: ignore[assignment]

try:
    import glob
except ImportError:
    glob = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ===========================================================================
# WifiManager — nmcli 封装
# ===========================================================================
class WifiManager:
    """Linux WiFi 连接管理，封装 nmcli 和 ip 命令。

    负责：
    - 断开当前热点连接（nmcli device disconnect）
    - 连接目标 WiFi（nmcli device wifi connect）
    - 查询 DHCP 分配的 IPv4 地址（ip -4 addr show）
    - 扫描附近 WiFi 网络（nmcli dev wifi list）
    """

    def __init__(self, interface: str = "wlp1s0"):
        """初始化 WifiManager。

        Args:
            interface: 无线网卡名称，如 wlan0 / wlp1s0
        """
        self.interface = interface
        self._logger = logging.getLogger("WifiManager")

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def disconnect_ap(self) -> bool:
        """断开当前热点连接。

        Returns:
            True 表示断开成功
        """
        cmd = f"nmcli device disconnect {self.interface}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            self._logger.warning("断开连接失败: %s", res.stderr.strip())
        return res.returncode == 0

    def connect(self, ssid: str, password: str):
        """连接目标 WiFi 网络。

        执行流程：
        1. 删除可能存在的旧连接配置（nmcli connection delete）
        2. 连接目标网络（nmcli device wifi connect）
        3. 获取 DHCP 分配的 IPv4 地址

        Args:
            ssid: 目标 WiFi SSID
            password: WiFi 密码（开放网络传空字符串）

        Returns:
            (True, ip_address)  — 连接成功
            (False, 失败原因)   — 连接失败或无法获取 IP
        """
        self._logger.info("正在连接 WiFi: %s", ssid)

        # 1. 删除可能存在的旧配置（忽略返回值）
        subprocess.run(
            f"nmcli connection delete '{ssid}'",
            shell=True, capture_output=True, text=True,
        )

        # 2. 连接新网络
        cmd = (
            f"nmcli device wifi connect '{ssid}' "
            f"password '{password}' ifname {self.interface}"
        )
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if res.returncode != 0:
            err = res.stderr.strip() if res.stderr else "连接失败或超时"
            self._logger.error("WiFi 连接失败: %s", err)
            return False, err

        # 3. 获取 IP 地址
        return self.get_ip_address()

    def get_ip_address(self):
        """获取当前网卡的 IPv4 地址。

        Returns:
            (True, ip_address)    — 成功获取
            (False, 错误信息)     — 未找到 IPv4 地址
        """
        cmd = f"ip -4 addr show {self.interface}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if res.returncode == 0:
            match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', res.stdout)
            if match:
                ip = match.group(1)
                self._logger.info("获取到 IP 地址: %s", ip)
                return True, ip

        return False, "无法获取 IP 地址"

    # ------------------------------------------------------------------
    # 网络扫描
    # ------------------------------------------------------------------
    def scan_networks(self):
        """扫描附近 WiFi 网络。

        Returns:
            [{"ssid": str, "signal": int, "security": str}, ...]
            扫描失败时返回空列表
        """
        cmd = "nmcli -t -f ssid,signal,security dev wifi list"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if res.returncode != 0:
            self._logger.error("WiFi 扫描失败: %s", res.stderr.strip())
            return []

        networks = []
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) >= 2:
                ssid = parts[0] if parts[0] else ""
                try:
                    signal = int(parts[1]) if parts[1] else 0
                except ValueError:
                    signal = 0
                security = parts[2] if len(parts) > 2 and parts[2] else "OPEN"
                networks.append({
                    "ssid": ssid,
                    "signal": signal,
                    "security": security,
                })

        return networks


# ===========================================================================
# ProvisioningProtocol — 串口协议解析/构建
# ===========================================================================
class ProvisioningProtocol:
    """ESP32 配网串口协议解析与帧构建（纯函数，无状态）。

    协议格式：
        下行（ESP32 → Linux）: WIFI|<ssid>|<password>
        上行（Linux → ESP32）: STATUS|CONNECTING / OK|<ip> / FAIL|<reason>
    """

    # ------------------------------------------------------------------
    # 下行帧解析（ESP32 → Linux）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_wifi_request(line: str):
        """解析 WIFI|<ssid>|<password> 帧。

        Args:
            line: 去除首尾空白后的单行文本

        Returns:
            (ssid, password)  — 解析成功
            None              — 格式无效（不以 WIFI| 开头、空行等）

        Note:
            密码中可包含 | 字符（按 : 分割时仅取前 2 个分隔符，剩余作为密码）。
        """
        line = line.strip()
        if not line:
            return None

        if not line.startswith("WIFI|"):
            return None

        # 去掉前缀 "WIFI|"，按 | 分割最多 2 次（剩余部分作为密码）
        payload = line[5:]  # len("WIFI|") == 5
        parts = payload.split("|", 1)
        ssid = parts[0] if len(parts) > 0 else ""
        password = parts[1] if len(parts) > 1 else ""

        return ssid, password

    # ------------------------------------------------------------------
    # 上行帧构建（Linux → ESP32）
    # ------------------------------------------------------------------
    @staticmethod
    def build_status_connecting() -> str:
        """构建 STATUS|CONNECTING 帧。"""
        return "STATUS|CONNECTING"

    @staticmethod
    def build_ok(ip: str) -> str:
        """构建 OK|<ip> 帧。

        Args:
            ip: DHCP 分配的 IPv4 地址
        """
        return f"OK|{ip}"

    @staticmethod
    def build_fail(reason: str) -> str:
        """构建 FAIL|<reason> 帧。

        Args:
            reason: 失败原因描述
        """
        return f"FAIL|{reason}"

    # ------------------------------------------------------------------
    # 上行帧解析（用于调试/日志）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_response(line: str):
        """解析上行响应帧（OK|/FAIL|/STATUS|）。

        Args:
            line: 去除首尾空白后的单行文本

        Returns:
            {"type": "ok", "ip": "..."}
            {"type": "fail", "reason": "..."}
            {"type": "status", "state": "..."}
            {"type": "unknown", "raw": "..."}
            None  — 空行
        """
        line = line.strip()
        if not line:
            return None

        if line.startswith("OK|"):
            ip = line[3:]  # len("OK|") == 3
            return {"type": "ok", "ip": ip}
        elif line.startswith("FAIL|"):
            reason = line[5:]  # len("FAIL|") == 5
            return {"type": "fail", "reason": reason}
        elif line.startswith("STATUS|"):
            state = line[7:]  # len("STATUS|") == 7
            return {"type": "status", "state": state}
        else:
            return {"type": "unknown", "raw": line}


# ===========================================================================
# ProvisioningPart — Donkeycar Part
# ===========================================================================
class ProvisioningPart:
    """ESP32 配网 Donkeycar Part。

    生命周期：
        update()        — 后台线程：打开串口，持续监听 WIFI| 帧，自动执行配网
        run_threaded()  — Vehicle 主循环：返回最新状态元组
        run(trigger)    — 同步模式：支持手动触发配网
        shutdown()      — 关闭串口，清理资源

    Memory 通道（outputs）：
        provisioning/status  — 'idle' | 'connecting' | 'connected' | 'failed'
        provisioning/ssid    — 目标 SSID
        provisioning/ip      — DHCP 分配的 IP 地址
        provisioning/error   — 失败原因
    """

    def __init__(
        self,
        serial_port: str = "/dev/ttyS6",
        baudrate: int = 115200,
        wifi_interface: str = "wlp1s0",
        timeout: float = 1.0,
        auto_respond: bool = True,
        arduino_controller=None,
    ):
        """初始化配网 Part。

        Args:
            serial_port: 串口设备路径（当 arduino_controller 为 None 时使用）
            baudrate: 波特率，默认 115200
            wifi_interface: 无线网卡名称
            timeout: 串口读取超时（秒）
            auto_respond: True 时 update() 自动响应 WIFI| 帧
            arduino_controller: 可选的 Arduino 控制器实例。
                当提供时，复用 Arduino 的共享串口设备，不独立打开串口。
        """
        self._serial_port = serial_port
        self._baudrate = baudrate
        self._wifi_interface = wifi_interface
        self._timeout = timeout
        self._auto_respond = auto_respond

        # 串口
        self._ser = None  # type: serial.Serial | None
        self._lock = threading.Lock()
        self._running = False

        # Arduino 控制器引用（用于共享串口）
        self._arduino_controller = arduino_controller

        # WiFi 管理
        self._wifi_manager = WifiManager(interface=wifi_interface)

        # 状态字段
        self._status = "idle"       # idle / connecting / connected / failed
        self._ssid = ""             # 当前连接目标 SSID
        self._ip = ""               # DHCP IP 地址
        self._error = ""            # 失败原因

    # ------------------------------------------------------------------
    # 静态方法：串口扫描
    # ------------------------------------------------------------------
    @staticmethod
    def scan_serial_ports(baudrate=115200, timeout=0.3, probe_retries=2):
        """扫描所有可用串口，找到配网 ESP32 设备。

        对每个候选串口发送 PING 帧，等待 PONG 响应。
        找到第一个响应的端口即返回。

        Args:
            baudrate: 波特率，默认 115200
            timeout: 单个端口读取超时（秒）
            probe_retries: 每个端口探测次数

        Returns:
            (port_name, rtt_ms)  — 成功找到
            (None, None)         — 所有端口无响应
        """
        if serial is None:
            logger.warning("未安装 pyserial，无法扫描串口")
            return None, None

        if glob is None:
            logger.warning("无法导入 glob 模块")
            return None, None

        # 候选设备列表
        candidates = []
        for pattern in ["/dev/ttyS*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
            try:
                candidates.extend(sorted(glob.glob(pattern)))
            except Exception:
                pass

        if not candidates:
            logger.warning("未找到任何候选串口设备")
            return None, None

        # 排除已用于 Arduino 控制的常见串口（Serial1: /dev/ttyS4）
        exclude = {"/dev/ttyS4"}
        candidates = [c for c in candidates if c not in exclude]

        logger.info("配网串口扫描：候选设备 %d 个（排除 %s）",
                     len(candidates), ", ".join(sorted(exclude)))

        scanned = 0
        for device in candidates:
            logger.info("配网串口扫描：正在探测 %s ...", device)

            try:
                ser = serial.Serial(port=device, baudrate=baudrate,
                                    timeout=timeout)
            except (OSError, serial.SerialException) as exc:
                logger.warning("配网串口扫描：跳过 %s（打开失败: %s）", device, exc)
                continue

            scanned += 1
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()

                for attempt in range(probe_retries):
                    ping_seq = (hash(device) & 0xFFFF) + attempt
                    ser.write(f"PING,{ping_seq}\n".encode("ascii"))
                    ser.flush()

                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        raw = ser.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="ignore").strip()
                            # 复用 Serial2Test 的 PONG 协议探测
                            if line.startswith("PONG,"):
                                rtt = (time.monotonic()
                                       - (deadline - timeout)) * 1000.0
                                logger.info("配网串口扫描：找到设备 %s（RTT %.1f ms）",
                                             device, rtt)
                                ser.close()
                                return device, rtt
                ser.close()
                logger.info("配网串口扫描：%s 无响应", device)
            except (OSError, serial.SerialException) as exc:
                logger.warning("配网串口扫描：%s 通信异常 (%s)", device, exc)
                try:
                    ser.close()
                except Exception:
                    pass

        logger.warning("配网串口扫描：已探测 %d 个端口，均无响应", scanned)
        return None, None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _handle_wifi_request(self, ssid: str, password: str):
        """执行完整配网流程：断开当前 AP → 连接目标网络 → 通知 ESP32。

        Args:
            ssid: 目标 WiFi SSID
            password: WiFi 密码
        """
        self._ssid = ssid
        self._status = "connecting"
        self._ip = ""
        self._error = ""

        logger.info("收到配网请求: SSID=%s", ssid)

        # 若串口可用则发送状态更新
        self._write_line(ProvisioningProtocol.build_status_connecting())

        # 断开当前 AP 连接，释放网卡
        self._wifi_manager.disconnect_ap()
        time.sleep(1)  # 等待网卡状态切换

        # 连接新 WiFi
        success, result = self._wifi_manager.connect(ssid, password)

        if success:
            self._status = "connected"
            self._ip = result
            self._error = ""
            logger.info("配网成功，IP: %s", result)
            self._write_line(ProvisioningProtocol.build_ok(result))
        else:
            self._status = "failed"
            self._ip = ""
            self._error = result
            logger.error("配网失败: %s", result)
            self._write_line(ProvisioningProtocol.build_fail(result))

    def _write_line(self, data: str):
        """线程安全的串口写入。

        Args:
            data: 待发送文本（自动追加 \\n）

        若使用 Arduino 共享串口，则通过 Arduino.ard_device 发送；
        否则使用独立串口 _ser。
        """
        # 确定使用的串口：优先 Arduino 共享设备，其次独立串口
        ser = None
        if self._arduino_controller is not None:
            from donkeycar.parts.actuator import Arduino
            ser = Arduino.ard_device
        else:
            ser = self._ser

        if ser is None:
            return
        try:
            text = data.rstrip("\n") + "\n"
            ser.write(text.encode("utf-8", errors="ignore"))
            ser.flush()
            logger.debug("TX: %s", data)
        except (OSError, serial.SerialException) as exc:
            logger.error("串口发送失败: %s", exc)

    def _read_and_process(self):
        """从串口读取一行，匹配 WIFI| 帧并自动处理。

        仅在 _auto_respond=True 时触发自动配网。
        """
        if self._ser is None:
            return

        try:
            if self._ser.in_waiting > 0:
                raw = self._ser.readline()
                if raw:
                    try:
                        line = raw.decode("utf-8", errors="ignore").strip()
                    except UnicodeDecodeError:
                        return

                    if line:
                        logger.debug("RX: %s", line)
                        if self._auto_respond:
                            parsed = ProvisioningProtocol.parse_wifi_request(line)
                            if parsed is not None:
                                ssid, password = parsed
                                self._handle_wifi_request(ssid, password)
        except (OSError, serial.SerialException) as exc:
            logger.error("串口读取失败: %s", exc)

    def _build_output(self):
        """构建当前状态输出元组。

        Returns:
            (status, ssid, ip, error) 四元组
        """
        return (self._status, self._ssid, self._ip, self._error)

    # ------------------------------------------------------------------
    # 生命周期方法
    # ------------------------------------------------------------------
    def update(self):
        """后台线程主循环：持续监听配网指令。

        在 Donkeycar 框架中，若 threaded=True，此方法在独立 daemon 线程中执行。
        若通过 arduino_controller 共享串口，则从 Arduino.wifi_provisioning 读取请求。
        """
        # Arduino 共享串口模式：不需要打开串口，仅轮询 wifi_provisioning
        if self._arduino_controller is not None:
            self._ser = None  # 使用 Arduino 的共享串口
            self._running = True
            logger.info("配网 Part 运行于 Arduino 共享串口模式")

            while self._running:
                # 检查 Arduino 控制器是否有新的配网请求
                wifi_req = self._arduino_controller.wifi_provisioning
                if wifi_req and wifi_req.get('ssid'):
                    ssid = wifi_req['ssid']
                    password = wifi_req.get('password', '')
                    # 清空已处理的请求，防止重复处理
                    self._arduino_controller.wifi_provisioning = {}
                    self._handle_wifi_request(ssid, password)
                time.sleep(0.5)  # 配网对实时性要求不高
            return

        # 独立串口模式：打开串口并监听
        if serial is None:
            logger.warning("未安装 pyserial，配网 Part 运行于 Mock 模式")
            self._ser = None
            return

        try:
            self._ser = serial.Serial(
                port=self._serial_port,
                baudrate=self._baudrate,
                timeout=self._timeout,
            )
            logger.info("配网串口已打开: %s @ %d baud",
                         self._serial_port, self._baudrate)
        except (OSError, serial.SerialException) as exc:
            logger.error("配网串口打开失败: %s", exc)
            self._ser = None
            return

        self._running = True

        while self._running:
            self._read_and_process()
            time.sleep(0.1)  # ~10Hz 轮询，配网对实时性要求不高

    def run_threaded(self):
        """Vehicle 主循环调用，返回最新配网状态。

        Returns:
            (status, ssid, ip, error) 四元组，对应 outputs 列表顺序
        """
        return self._build_output()

    def run(self, trigger=None):
        """非线程模式：返回当前状态，或手动触发配网。

        Args:
            trigger: 可选 dict{'ssid': str, 'password': str}，手动触发配网

        Returns:
            (status, ssid, ip, error) 四元组
        """
        if trigger and isinstance(trigger, dict):
            ssid = trigger.get("ssid", "")
            password = trigger.get("password", "")
            if ssid:
                self._handle_wifi_request(ssid, password)

        return self._build_output()

    # ------------------------------------------------------------------
    # 资源清理
    # ------------------------------------------------------------------
    def shutdown(self):
        """程序退出时调用：关闭串口（仅独立串口模式），停止线程。"""
        self._running = False
        # Arduino 共享串口模式下不关闭串口（由 Arduino 类管理）
        if self._arduino_controller is not None:
            logger.info("配网 Part 已关闭（Arduino 共享模式）")
            return
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        logger.info("配网 Part 已关闭")


# ===========================================================================
# 独立守护进程入口
# ===========================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="DonkeyDrift 配网代理守护进程（独立运行模式）",
    )
    parser.add_argument("--port", default="/dev/ttyS6",
                        help="串口设备路径（默认 /dev/ttyS6，对应 ESP32 Serial2）")
    parser.add_argument("--baud", type=int, default=115200,
                        help="串口波特率（默认 115200）")
    parser.add_argument("--interface", default="wlp1s0",
                        help="无线网卡名称（默认 wlp1s0）")
    parser.add_argument("--no-auto", action="store_true",
                        help="禁用自动响应模式")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    part = ProvisioningPart(
        serial_port=args.port,
        baudrate=args.baud,
        wifi_interface=args.interface,
        auto_respond=not args.no_auto,
    )
    logger.info("配网代理守护进程启动，监听 %s ...", args.port)
    part.update()
