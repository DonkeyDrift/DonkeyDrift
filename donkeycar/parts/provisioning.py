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
                          HOSTIP|<ipv4>\\n（周期上报本机局域网 IP）

ESP32 固件保持不变，独立运行在 ESP32 上。
"""

import logging
import re
import socket
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


def _is_rfc1918(ip: str) -> bool:
    """判断 IPv4 地址是否属于 RFC1918 私有网段（10/8、172.16/12、192.168/16）。

    ESP32 与上位机同处一个局域网，只有私有地址才可能被 ESP32 访问到；
    198.18.0.0/15（Clash Meta/mihomo TUN 假 IP 段）、100.64.0.0/10（CGNAT/
    Tailscale）、169.254/16（链路本地）等虽可能出现在本机接口上，但对
    局域网内的 ESP32 不可达，一律不视为局域网地址。
    """
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    return False


# 常见虚拟接口命名（VPN/TUN、容器网桥、虚拟机网卡等），其上的地址
# 对局域网内的 ESP32 不可达，枚举时跳过
_VIRTUAL_IFACE_RE = re.compile(
    r"^(lo|docker|br(?:-|\d)|lxdbr|veth|virbr|vnet|tun|tap|utun|wg|"
    r"tailscale|ts-|meta|cni-|flannel|kube|vboxnet|vmnet|zt|ppp|clash|"
    r"mihomo|sing-box|ovs|vxlan|gre)",
    re.IGNORECASE,
)

# 物理网卡常见命名前缀（无线 wl*/wlan*、有线 en*/eth*、USB 网卡 usb*、
# 链路聚合 bond*）
_PHYSICAL_IFACE_PREFIXES = ("wl", "en", "eth", "usb", "bond")


def _enum_inet_entries():
    """枚举本机全部 IPv4 接口地址。

    解析 ``ip -4 -o addr show`` 输出为 ``[(ip, iface), ...]``（含回环与
    虚拟接口，由调用方按需过滤）。

    Returns:
        list — ``(ipv4, iface)`` 元组列表
        None — ``ip`` 命令不可用或执行失败
    """
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None

    entries = []
    for line in result.stdout.splitlines():
        # -o 单行格式：
        # "2: wlp1s0    inet 192.168.3.41/24 brd 192.168.3.255 scope global ..."
        parts = line.split()
        if len(parts) < 4 or parts[2] != "inet":
            continue
        iface = parts[1].split("@")[0].rstrip(":")
        ip = parts[3].split("/")[0]
        entries.append((ip, iface))
    return entries


def _select_lan_ip(entries):
    """从接口地址表中选出局域网 IP（绕过被 VPN/TUN 劫持的默认路由）。

    跳过回环与常见虚拟接口（docker/bridge/tun/tap/wg/Clash Meta 等）；
    优先返回物理命名接口（wl*/en*/eth*/usb*/bond*）上的 RFC1918 地址，
    其次任一非虚拟接口的 RFC1918 地址。

    Args:
        entries: ``_enum_inet_entries()`` 返回的 ``[(ip, iface), ...]``

    Returns:
        str  — 物理/非虚拟接口上的 RFC1918 IPv4 地址
        None — 找不到
    """
    fallback = None
    for ip, iface in entries:
        if not _is_rfc1918(ip):
            continue
        if _VIRTUAL_IFACE_RE.match(iface):
            continue
        if iface.startswith(_PHYSICAL_IFACE_PREFIXES):
            return ip
        if fallback is None:
            fallback = ip
    return fallback


def _physical_default_iface():
    """从 ``ip route show default`` 找经物理网关的默认路由接口。

    TUN 模式 VPN 劫持默认路由时，原物理默认路由通常以更高 metric 残留
    （mihomo/Clash auto-route、OpenVPN redirect-gateway def1、wg-quick
    策略路由均如此），其接口即真实局域网出口。只认经网关（via）的路由
    ——TUN 的 ``default dev <iface>`` 无网关，正是需要绕过的劫持项。

    Returns:
        str  — 非虚拟默认路由接口名（优先物理命名）
        None — 找不到或 ``ip`` 命令不可用
    """
    try:
        result = subprocess.run(
            ["ip", "-4", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None

    fallback = None
    for line in result.stdout.splitlines():
        # "default via 192.168.3.1 dev wlp1s0 proto dhcp metric 600"
        parts = line.split()
        if not parts or parts[0] != "default" or "via" not in parts:
            continue
        try:
            iface = parts[parts.index("dev") + 1]
        except (ValueError, IndexError):
            continue
        if _VIRTUAL_IFACE_RE.match(iface):
            continue
        if iface.startswith(_PHYSICAL_IFACE_PREFIXES):
            return iface
        if fallback is None:
            fallback = iface
    return fallback


def detect_lan_ip():
    """探测本机局域网 IPv4 地址（供 ESP32 经同一局域网访问上位机）。

    探测顺序：
        1. UDP socket connect 外部地址做路由查询（不实际发包）取默认出口
           IP；是 RFC1918 私有地址且不位于虚拟接口上时直接返回
           （无 VPN / 分流 VPN 的常见情况）。``ip`` 命令不可用时无法
           校验接口属性，保留旧行为直接返回。
        2. 默认出口被 VPN 劫持（TUN 假 IP，或全隧道 VPN 分在 tun/wg 上
           的 RFC1918 隧道地址）或 UDP 查询失败（离线局域网）时：
           a. 从 ``ip route show default`` 找经物理网关残留的默认路由，
              取其接口上的 RFC1918 地址；
           b. 否则枚举全部接口，优先物理命名接口的 RFC1918 地址，其次
              任一非虚拟接口的 RFC1918 地址。
        3. 仍无结果时保留旧行为返回默认出口地址（公网直连等场景兼容）。
        4. 最后回退主机名解析；均失败返回 None。

    Returns:
        str  — 非 127.x 的 IPv4 地址
        None — 无法确定（无网络等）
    """
    udp_ip = None
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            udp_ip = ip
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()

    entries = _enum_inet_entries()

    if udp_ip and _is_rfc1918(udp_ip):
        if entries is None:
            return udp_ip
        iface = next((ifc for addr, ifc in entries if addr == udp_ip), None)
        if iface is None or not _VIRTUAL_IFACE_RE.match(iface):
            return udp_ip
        # 默认出口是虚拟接口上的私有地址（全隧道 WireGuard/OpenVPN 的
        # tun/wg 常分到 10.x 隧道地址）——对 ESP32 不可达，继续物理探测

    if entries:
        default_iface = _physical_default_iface()
        if default_iface:
            for addr, ifc in entries:
                if ifc == default_iface and _is_rfc1918(addr):
                    return addr
        lan_ip = _select_lan_ip(entries)
        if lan_ip:
            return lan_ip

    if udp_ip:
        return udp_ip

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


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
                              HOSTIP|<ipv4>（周期上报本机局域网 IP）
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
    def build_host_ip(ip: str) -> str:
        """构建 HOSTIP|<ipv4> 帧（周期上报本机局域网 IP 给 ESP32 显示）。

        Args:
            ip: 本机局域网 IPv4 地址
        """
        return f"HOSTIP|{ip}"

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
        host_ip_report: bool = True,
        host_ip_report_interval: float = 10.0,
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
            host_ip_report: True 时周期向 ESP32 上报本机局域网 IP
                （HOSTIP|<ipv4> 帧，ESP32 Web Console Network 卡片 HOST 分页显示）
            host_ip_report_interval: 上报间隔（秒），默认 10 秒
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

        # 上位机 IP 周期上报
        self._host_ip_report = host_ip_report
        self._host_ip_report_interval = host_ip_report_interval
        self._last_host_ip_report_ts = 0.0

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

    def _maybe_report_host_ip(self):
        """按间隔节流，向 ESP32 上报本机局域网 IP（HOSTIP|<ipv4> 帧）。

        每次上报前重新探测 IP（UDP 路由查询，代价极低且不发包），
        DHCP 换地址或 ESP32 重启丢失运行时状态后可在下一个周期自愈。
        """
        if not self._host_ip_report:
            return
        now = time.monotonic()
        if now - self._last_host_ip_report_ts < self._host_ip_report_interval:
            return
        self._last_host_ip_report_ts = now
        ip = detect_lan_ip()
        if ip:
            self._write_line(ProvisioningProtocol.build_host_ip(ip))

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
                self._maybe_report_host_ip()
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
            self._maybe_report_host_ip()
            time.sleep(0.1)  # ~10Hz 轮询，配网对实时性要求不高

    def run_threaded(self, trigger=None):
        """Vehicle 主循环调用，返回最新配网状态。

        Args:
            trigger: 可选 dict{'ssid': str, 'password': str}，手动触发配网。
                来自 inputs=['provisioning/trigger'] 通道，通常为 None。

        Returns:
            (status, ssid, ip, error) 四元组，对应 outputs 列表顺序
        """
        if trigger and isinstance(trigger, dict):
            ssid = trigger.get("ssid", "")
            password = trigger.get("password", "")
            if ssid:
                self._handle_wifi_request(ssid, password)

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
