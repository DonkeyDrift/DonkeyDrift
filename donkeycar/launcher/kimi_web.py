#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/launch/kimi-code-web 的实现（适配 kimi ≥ 0.36）：

优先复用已在运行的 kimi web 实例（kimi TUI 的内嵌 server 也算）；
没有存活实例时才直接拉起 ``kimi web --no-open --host`` 子进程
（绑 0.0.0.0 供局域网访问），从 stdout 的 ready banner 里抓浏览器
入口 URL。

背景与机制（0.36.0 起）：
- TUI 不再进入 alternate-screen（``\\x1b[?1049h``），旧的"PTY 里注入
  ``kimi`` → 注入 ``/web``"自动化永远等不到就绪信号，必然超时；
  改用官方 ``kimi web`` 子命令（``kimi server`` 是其废弃别名），
  无需 PTY、无 TUI 冷启动，就绪只要几秒。
- 任何 kimi server 进程都会把自己登记到
  ``~/.kimi-code/server/instances/*.json``（server_id/pid/host/port/
  heartbeat_at），bearer token 持久化在 ``~/.kimi-code/server.token``；
  浏览器入口 URL 形如 ``http://127.0.0.1:<port>/#token=<token>``
  （token 在 # 片段里，由前端页面读取，不经过网络传输）。
- 复用判定：登记条目 pid 存活 + 心跳新鲜 + 带 token 探测
  ``/api/v1/meta`` 返回 200。
- 局域网可达性（issue #125）：消费方是用户电脑/手机上的浏览器，URL 里
  的 ``localhost``/``127.0.0.1`` 指向浏览器自己当然打不开。因此冷启动
  一律 ``--host 0.0.0.0`` 监听全部网卡，且两条路径返回前都把回环 host
  改写为本机局域网 IP（复用配网模块的 ``detect_lan_ip``，保留端口与
  ``#token=`` 片段）；只绑了回环的存活实例（如 TUI 内嵌 server）对
  局域网 IP 探测不通时视为不可复用，由调用方另拉监听 0.0.0.0 的实例。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# 整体超时（秒）：客户端（DD 按钮 / D 菜单 / DC 按钮）超时必须 ≥ 此值；
# 复用路径毫秒级返回，只有冷启动路径可能用到
DEFAULT_TIMEOUT_S = 120.0
# 等 kimi web 子进程 ready banner 的最长时间（秒）
SPAWN_TIMEOUT_S = 60.0
# 轮询间隔（秒）
_POLL_S = 0.2
# 实例登记心跳的新鲜度预筛（秒）：超过视为僵死，直接跳过
INSTANCE_HEARTBEAT_MAX_AGE_S = 180.0
# 复用探测（/api/v1/meta）的超时（秒）
PROBE_TIMEOUT_S = 3.0

# kimi 用户目录下的固定位置
KIMI_HOME = Path.home() / ".kimi-code"
KIMI_BIN = KIMI_HOME / "bin" / "kimi"
INSTANCES_DIR = KIMI_HOME / "server" / "instances"
TOKEN_PATH = KIMI_HOME / "server.token"

# kimi web banner 里的失败特征 → 提前报错，不用傻等超时
_SERVER_FAIL_MSG = "Failed to start server"

# ANSI 转义序列：CSI（光标/颜色/清屏）、OSC（BEL 或 ST 结束）、
# 字符集/线宽设置、其它两字节转义
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"           # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[()#][0-9A-Za-z]"             # 字符集选择等
    r"|\x1b[@-Z\\-_]"                    # 其它两字节转义
)

# URL 字符集：排除空白与引号/括号等定界符；保留 #（token 在 #token= 片段里）
_URL_CHARS = r"[^\s\"'<>\[\]{}|\\^`]"
_LABELED_URL_RES = (
    # kimi web ready banner 的标签行，按优先级排序：
    # Session 直达当前会话，体验最好；Local/URL 是裸入口；Network 是局域网地址
    re.compile(r"Session:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"Local:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"URL:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"Network:\s*(https?://" + _URL_CHARS + r"+)"),
)
_ANY_URL_RE = re.compile(r"https?://" + _URL_CHARS + r"+")
# 行文里 URL 后面常见的句读，剥掉（token/路径 normally 不以这些结尾）
_URL_TRAILING_PUNCT = ".,;:!?"

# 成功拉起的 kimi web 子进程句柄：保住引用不被 GC，生命周期同 launcher
# （杀掉子进程即关掉对应 web 服务）
_SPAWNED_PROCS = []


def strip_ansi(text: str) -> str:
    """剥掉文本里的 ANSI 转义序列（CSI/OSC/字符集等），保留可见字符。"""
    return _ANSI_RE.sub("", text)


def extract_web_url(text: str):
    """从（已剥 ANSI 的）输出提取 Kimi Code Web 的 URL。

    优先 ``Session:`` 深链（直达当前会话），其次 ``Local:``/``URL:``/
    ``Network:`` 标签行，最后兜底文本里第一个 http(s) URL；
    都找不到返回 None。
    """
    for pattern in _LABELED_URL_RES:
        m = pattern.search(text)
        if m:
            return m.group(1).rstrip(_URL_TRAILING_PUNCT)
    m = _ANY_URL_RE.search(text)
    if m:
        return m.group(0).rstrip(_URL_TRAILING_PUNCT)
    return None


def _tail_lines(plain: str, n: int = 3) -> str:
    """取剥净文本的最后 n 行非空行，用于错误信息里的现场快照。"""
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) if lines else "(无输出)"


def _read_token(token_path=TOKEN_PATH):
    """读持久化 bearer token；文件缺失/为空返回 None。"""
    try:
        return Path(token_path).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _iter_instances(instances_dir=INSTANCES_DIR):
    """读实例登记目录，按心跳从新到旧排序；坏条目直接跳过。"""
    out = []
    try:
        files = list(Path(instances_dir).glob("*.json"))
    except OSError:
        return []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d.get("pid"), int) and d.get("host") \
                and isinstance(d.get("port"), int):
            out.append(d)
    out.sort(key=lambda d: d.get("heartbeat_at", 0), reverse=True)
    return out


def _pid_alive(pid: int) -> bool:
    """pid 是否有存活进程（无权限视为存活，交给后续探测裁决）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_server(host: str, port: int, token, timeout=PROBE_TIMEOUT_S) -> bool:
    """GET /api/v1/meta 带 bearer token，200 视为可复用的 kimi web 实例。"""
    req = urllib.request.Request(f"http://{host}:{port}/api/v1/meta")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _lan_ip():
    """本机局域网 IPv4（复用配网模块的 VPN/TUN 感知探测）；失败返回 None。"""
    try:
        from donkeycar.parts.provisioning import detect_lan_ip
        return detect_lan_ip()
    except Exception:
        return None


def _is_loopback_host(host) -> bool:
    """URL host 是否是上位机本机视角地址（远程浏览器打不开）。

    ``localhost``/``127.x``/``::1`` 是回环；``0.0.0.0`` 是监听通配地址，
    不是浏览器可打开的主机名，同样需要改写。
    """
    if not host:
        return False
    host = host.lower().strip("[]")
    return (host == "localhost" or host == "0.0.0.0" or host == "::1"
            or host.startswith("127."))


def _lan_url(url: str):
    """把 URL 里的回环/通配 host 改写为本机局域网 IP。

    保留端口、路径与 ``#token=`` 片段（token 在 # 片段里由前端页面读取，
    不经过网络传输）。探测不到局域网 IP 或 host 本就远程可达时原样返回。
    """
    lan = _lan_ip()
    if not lan:
        return url
    parts = urllib.parse.urlsplit(url)
    if not _is_loopback_host(parts.hostname):
        return url
    netloc = f"{lan}:{parts.port}" if parts.port else lan
    return urllib.parse.urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _live_instance_url(instances_dir=INSTANCES_DIR, token_path=TOKEN_PATH):
    """找已在运行的 kimi web 实例，返回带 ``#token=`` 的浏览器入口 URL。

    判定链：登记条目心跳新鲜 → pid 存活 → 带持久 token 探测
    ``/api/v1/meta`` 返回 200，且局域网可达（登记 host 是回环时需对
    本机局域网 IP 探测通过）。找不到返回 None。
    """
    token = _read_token(token_path)
    now_ms = time.time() * 1000
    max_age_ms = INSTANCE_HEARTBEAT_MAX_AGE_S * 1000
    for inst in _iter_instances(instances_dir):
        if now_ms - inst.get("heartbeat_at", 0) > max_age_ms:
            continue
        if not _pid_alive(inst["pid"]):
            continue
        host = inst["host"]
        if _is_loopback_host(host):
            # 只绑回环的实例（如 TUI 内嵌 server）远程浏览器访问不到；
            # 对局域网 IP 再探一次：通了说明实际监听 0.0.0.0 只是登记
            # 写的 127.0.0.1，改用局域网 host；不通则跳过
            lan = _lan_ip()
            if not lan or not _probe_server(lan, inst["port"], token):
                continue
            host = lan
        if not _probe_server(host, inst["port"], token):
            continue
        url = f"http://{host}:{inst['port']}/"
        if token:
            url += f"#token={token}"
        return url
    return None


def _resolve_kimi_binary():
    """kimi 可执行文件路径；找不到返回 None。

    优先 ``~/.kimi-code/bin/kimi``——launcher 以 systemd 服务运行时 PATH
    是干净环境（没有该目录），不能依赖 PATH 查找；其次才回退 PATH。
    """
    if os.access(KIMI_BIN, os.X_OK):
        return str(KIMI_BIN)
    return shutil.which("kimi")


def _spawn_and_capture(binary: str, cwd_str, deadline: float, popen_fn=None):
    """拉起 ``kimi web --no-open --host``（绑 0.0.0.0）并等 ready banner
    里的 URL。

    返回 ``(proc, url, None)`` 或 ``(None, None, 错误原因)``；
    失败路径一律杀掉子进程，不留孤儿。
    """
    popen_fn = popen_fn or subprocess.Popen
    env = os.environ.copy()
    env["PATH"] = str(KIMI_BIN.parent) + os.pathsep + env.get("PATH", "")
    env.setdefault("HOME", str(Path.home()))
    try:
        proc = popen_fn(
            # --host 裸传 = 绑 0.0.0.0：消费方是局域网内用户设备上的
            # 浏览器（issue #125），只绑回环它们访问不到
            [binary, "web", "--no-open", "--host"],
            cwd=cwd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except OSError as e:
        return None, None, f"无法启动 kimi web 子进程: {e}"

    buf = []
    lock = threading.Lock()

    def _drain():
        # 持续读空 stdout：既供 URL 捕获，也防管道写满阻塞 kimi；
        # 抓到 URL 后线程继续挂着排水（kimi web 默认不打日志，量极小）
        try:
            for line in proc.stdout:
                with lock:
                    buf.append(line)
        except ValueError:
            pass  # 管道已关闭

    threading.Thread(target=_drain, daemon=True).start()

    def _text() -> str:
        with lock:
            return strip_ansi("".join(buf))

    wait_deadline = min(deadline, time.monotonic() + SPAWN_TIMEOUT_S)
    error = None
    while True:
        plain = _text()
        url = extract_web_url(plain)
        if url:
            return proc, url, None
        if proc.poll() is not None:
            # 进程退出后管道里可能还有未读尽的残余输出，稍等补读再判定
            time.sleep(0.3)
            plain = _text()
            url = extract_web_url(plain)
            if url:
                return proc, url, None
            if _SERVER_FAIL_MSG in plain:
                error = "kimi web server 启动失败；现场: " + _tail_lines(plain)
            else:
                error = (f"kimi web 进程提前退出（码 {proc.returncode}）；"
                         "现场: " + _tail_lines(plain))
            break
        if _SERVER_FAIL_MSG in plain:
            error = "kimi web server 启动失败；现场: " + _tail_lines(plain)
            break
        if time.monotonic() >= wait_deadline:
            error = (f"等待 kimi web 就绪超时（{int(SPAWN_TIMEOUT_S)}s）；"
                     "现场: " + _tail_lines(plain))
            break
        time.sleep(_POLL_S)

    try:
        proc.kill()
    except OSError:
        pass
    return None, None, error


def launch_kimi_code_web(cwd=None, timeout_s=DEFAULT_TIMEOUT_S, *,
                         live_url_fn=None, resolve_binary_fn=None,
                         popen_fn=None):
    """打开 Kimi Code Web：优先复用存活实例，否则拉起 ``kimi web``。

    Args:
        cwd: kimi 运行目录（绝对路径）；None 表示上位机用户主目录。
            目录不存在直接报错，绝不回退到其它目录。
        timeout_s: 整体超时（秒），默认 120；调用方客户端超时应 ≥120s。
            复用路径毫秒级返回，仅冷启动路径可能用满。
        live_url_fn / resolve_binary_fn / popen_fn: 测试钩子，默认
            ``_live_instance_url`` / ``_resolve_kimi_binary`` /
            ``subprocess.Popen``。

    Returns:
        成功 {"status": "ok", "url": <带 #token= 的入口 URL>}；
        失败 {"status": "error", "error": <原因>}。
        URL 的回环 host 已改写为本机局域网 IP（issue #125，远程浏览器
        可达）；成功拉起的子进程保持存活（杀它即关 web 服务）；失败路径
        杀净。
    """
    live_url_fn = live_url_fn or _live_instance_url
    resolve_binary_fn = resolve_binary_fn or _resolve_kimi_binary

    cwd_str = None
    if cwd is not None:
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_dir():
            return {
                "status": "error",
                "error": f"cwd 目录不存在或不是目录: {cwd}（不会回退到其它目录）",
            }
        cwd_str = str(cwd_path)

    # 快路径：已有 kimi 实例在跑（TUI 内嵌 server 或已启动的 kimi web）
    url = live_url_fn()
    if url:
        url = _lan_url(url)
        logger.info("复用已运行的 Kimi Code Web 实例: %s", url)
        return {"status": "ok", "url": url}

    binary = resolve_binary_fn()
    if not binary:
        return {
            "status": "error",
            "error": "未找到 kimi 可执行文件（~/.kimi-code/bin/kimi 与 PATH "
                     "均无），请确认 kimi 已安装",
        }

    deadline = time.monotonic() + timeout_s
    proc, url, error = _spawn_and_capture(binary, cwd_str, deadline,
                                          popen_fn=popen_fn)
    if url:
        _SPAWNED_PROCS.append(proc)
        url = _lan_url(url)
        logger.info("Kimi Code Web 已启动: pid=%s url=%s", proc.pid, url)
        return {"status": "ok", "url": url}

    # 冷启动失败兜底：端口可能被登记滞后的存活实例占用，再试一次复用
    url = live_url_fn()
    if url:
        url = _lan_url(url)
        logger.info("冷启动未果，复用到已运行实例: %s", url)
        return {"status": "ok", "url": url}
    logger.warning("启动 Kimi Code Web 失败: %s", error)
    return {"status": "error", "error": error}
