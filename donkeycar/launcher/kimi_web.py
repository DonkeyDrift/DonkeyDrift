#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/launch/kimi-code-web 的自动化实现：在独立 PTY bash 会话里启动
kimi TUI 并注入 /web，从 PTY 输出捕获 Kimi Code Web 的 URL。

流程（复用 terminal.TerminalSession，writer 换成本模块的缓冲 writer，
不触碰现有 WebSocket 桥逻辑）：
    1. 新建 TerminalSession（bash login shell；cwd 由请求方指定，缺省为
       上位机用户主目录；cwd 不存在直接报错，绝不回退到其它目录）
    2. 注入 ``kimi`` 回车，等 TUI 启动完成——判据：输出里出现过
       alternate-screen 进入序列（\\x1b[?1049h，TUI 已拉起）且输出静默
       超过 READY_SILENCE_S 秒（首屏渲染完毕）
    3. 注入 ``/web`` 回车：TUI 退出，当前进程原地变为前台 web server，
       终端打出 ready banner（含 ``Local:``/``Network:``/``Session:`` 行，
       URL 的 #token= 片段以独立颜色渲染，剥 ANSI 后自然拼接完整）
    4. 从注入点之后的输出剥 ANSI，优先捕获 ``Session:`` 深链（直达当前
       会话），其次 ``Local:``/``URL:``/``Network:`` 行，最后兜底任意
       http(s) URL

这是长请求：kimi 冷启动可达数十秒，整体超时默认 DEFAULT_TIMEOUT_S=120s，
客户端超时必须 ≥120s（超时错误信息里也带了这条提示）。
"""

import logging
import re
import threading
import time
from pathlib import Path

from donkeycar.launcher.terminal import OP_BINARY, TerminalSession

logger = logging.getLogger(__name__)

# 整体超时（秒）：客户端（DD 按钮 / D 菜单 / DC 按钮）超时必须 ≥ 此值
DEFAULT_TIMEOUT_S = 120.0
# 等 TUI 启动的最长时间（秒）；超时但见过 alternate-screen 仍放行注入 /web
TUI_READY_TIMEOUT_S = 60.0
# TUI 就绪静默窗口（秒）：首屏渲染完毕后输出应停这么久
READY_SILENCE_S = 2.0
# 轮询间隔（秒）
_POLL_S = 0.2

# TUI 进入 alternate screen 的控制序列（kimi TUI 已拉起的可靠信号）
_ALT_SCREEN_ENTER = "\x1b[?1049h"

# /web 之后输出里的失败特征 → 提前报错，不用傻等超时
_NO_SESSION_MSG = "No active session"          # TUI 无活动会话（未登录等）
_SERVER_FAIL_MSG = "Failed to start server:"   # 内嵌 server 启动失败

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
    # kimi web ready banner / Session 深链行的标签，按优先级排序：
    # Session 直达当前会话，体验最好；Local/URL 是裸入口；Network 是局域网地址
    re.compile(r"Session:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"Local:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"URL:\s*(https?://" + _URL_CHARS + r"+)"),
    re.compile(r"Network:\s*(https?://" + _URL_CHARS + r"+)"),
)
_ANY_URL_RE = re.compile(r"https?://" + _URL_CHARS + r"+")
# 行文里 URL 后面常见的句读，剥掉（token/路径 normally 不以这些结尾）
_URL_TRAILING_PUNCT = ".,;:!?"


def strip_ansi(text: str) -> str:
    """剥掉文本里的 ANSI 转义序列（CSI/OSC/字符集等），保留可见字符。"""
    return _ANSI_RE.sub("", text)


def extract_web_url(text: str):
    """从（已剥 ANSI 的）终端输出提取 Kimi Code Web 的 URL。

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


class _BufferWriter:
    """TerminalSession 的输出 writer：把 PTY 输出累积进内存缓冲。

    接口对齐 terminal._WsWriter（send/send_json/closed），但帧不进
    WebSocket，只进缓冲区，供 URL 捕获与就绪判定读取。线程安全。
    """

    def __init__(self):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._last_output_at = time.monotonic()
        self.closed = False

    def send(self, payload: bytes, opcode: int = OP_BINARY) -> bool:
        """攒输出；返回 False 会让 TerminalSession 的 reader 线程停摆。"""
        with self._lock:
            if self.closed:
                return False
            self._buf.extend(payload)
            self._last_output_at = time.monotonic()
            return True

    def send_json(self, obj) -> bool:
        # 无客户端可通知（TerminalSession 退出通知帧直接丢弃）
        return not self.closed

    def size(self) -> int:
        with self._lock:
            return len(self._buf)

    def last_output_at(self) -> float:
        with self._lock:
            return self._last_output_at

    def text(self, start: int = 0) -> str:
        """解码缓冲[start:]为文本（边界处可能切坏半个 UTF-8 字符，
        用 replace 容错——URL 是 ASCII，不受影响）。"""
        with self._lock:
            return bytes(self._buf[start:]).decode("utf-8", errors="replace")


def _tail_lines(plain: str, n: int = 3) -> str:
    """取剥净文本的最后 n 行非空行，用于错误信息里的现场快照。"""
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) if lines else "(无输出)"


def _wait_tui_ready(writer: _BufferWriter, deadline: float,
                    silence_s: float):
    """等 kimi TUI 启动完成。返回 (True, None) 或 (False, 错误原因)。"""
    while True:
        now = time.monotonic()
        raw = writer.text()
        plain = strip_ansi(raw)
        if "command not found" in plain:
            return False, ("未找到 kimi 命令（command not found），"
                           "请确认 kimi 已安装且在上位机 PATH 中")
        if "Trust this folder" in plain:
            return False, ("kimi 弹出了目录信任确认（Trust this folder），"
                           "请先在终端手动运行一次 kimi 完成信任设置")
        alt_seen = _ALT_SCREEN_ENTER in raw
        if alt_seen and now - writer.last_output_at() >= silence_s:
            return True, None
        if now >= deadline:
            if alt_seen:
                # TUI 已拉起但输出一直不停（如有周期重绘），直接放行
                return True, None
            return False, ("等待 kimi TUI 启动超时；现场: "
                           + _tail_lines(plain))
        time.sleep(_POLL_S)


def _wait_web_url(writer: _BufferWriter, mark: int, deadline: float):
    """从注入 /web 之后的输出里等 URL。返回 (url, None) 或 (None, 错误原因)。"""
    while True:
        plain = strip_ansi(writer.text(mark))
        if _SERVER_FAIL_MSG in plain:
            return None, ("kimi 内嵌 server 启动失败；现场: "
                          + _tail_lines(plain))
        if _NO_SESSION_MSG in plain:
            return None, ("kimi 无活动会话（No active session），"
                          "请先在终端运行 kimi 并用 /login 登录")
        url = extract_web_url(plain)
        if url:
            return url, None
        if time.monotonic() >= deadline:
            return None, (
                f"等待 Kimi Code Web URL 超时（整体 {int(DEFAULT_TIMEOUT_S)}s"
                " 上限）；客户端超时需 ≥120s，可直接重试；现场: "
                + _tail_lines(plain))
        time.sleep(_POLL_S)


def launch_kimi_code_web(cwd=None, timeout_s=DEFAULT_TIMEOUT_S, *,
                         ready_silence_s=READY_SILENCE_S,
                         session_factory=TerminalSession):
    """启动 kimi 并注入 /web，捕获 Kimi Code Web URL。

    Args:
        cwd: kimi 运行目录（绝对路径）；None 表示上位机用户主目录。
            目录不存在直接报错，绝不回退到其它目录。
        timeout_s: 整体超时（秒），默认 120；调用方客户端超时应 ≥120s。
        ready_silence_s: TUI 就绪静默窗口（秒），测试可调小加速。
        session_factory: 测试钩子，默认 terminal.TerminalSession。

    Returns:
        成功 {"status": "ok", "url": <URL>}；
        失败 {"status": "error", "error": <原因>}。
        成功时会话保持存活（kimi server 以前台任务挂在该 PTY 上，杀掉
        会话即杀掉 web 服务）；失败路径一律 close 会话，不留孤儿进程。
    """
    cwd_str = None
    if cwd is not None:
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_dir():
            return {
                "status": "error",
                "error": f"cwd 目录不存在或不是目录: {cwd}（不会回退到其它目录）",
            }
        cwd_str = str(cwd_path)

    writer = _BufferWriter()
    try:
        session = session_factory(writer, cwd=cwd_str)
    except Exception as e:
        return {"status": "error", "error": f"创建终端会话失败: {e}"}

    deadline = time.monotonic() + timeout_s
    url = None
    error = None
    try:
        # 加宽 PTY：banner 的 Session 深链行（含 #token=）轻松超过 80 列，
        # 默认 80 列会把 URL 折行插进 \r\n，导致捕获失败
        session.on_resize(500, 24)
        session.on_input(b"kimi\r")
        ready_deadline = min(deadline, time.monotonic() + TUI_READY_TIMEOUT_S)
        ok, error = _wait_tui_ready(writer, ready_deadline, ready_silence_s)
        if ok:
            # 只从注入点之后捕获，避免 TUI 滚屏里历史消息的 URL 被误抓
            mark = writer.size()
            session.on_input(b"/web\r")
            url, error = _wait_web_url(writer, mark, deadline)
    except Exception as e:
        error = f"自动化过程异常: {e}"
    finally:
        if url is None:
            session.close()

    if url is not None:
        logger.info("Kimi Code Web 已启动: pid=%s url=%s", session.pid, url)
        return {"status": "ok", "url": url}
    logger.warning("启动 Kimi Code Web 失败: %s", error)
    return {"status": "error", "error": error}
