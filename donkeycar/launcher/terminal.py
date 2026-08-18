#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上位机 Web 终端：WebSocket ↔ PTY 桥（Drifter Console "Serial" 目标的后端）。

浏览器打开 http://<上位机>:8090/terminal 得到终端页面（xterm.js），页面再连
ws://<上位机>:8090/terminal/ws；本模块把这条 WebSocket 桥到一个 bash login
shell 的 PTY 上，体验与本机终端一致（可交互运行 kimi / claude / codex /
donkey 等 TUI 程序）。之所以走局域网 WebSocket 而不是 Serial2 串口透传：
串口仅 115200 波特（约 11KB/s），全屏 TUI 每帧重绘数 KB，会卡到不可用。

帧协议（按 WebSocket opcode 区分，无 in-band 转义）：
    客户端 → 服务端 binary(0x2)：原始终端输入字节流，直接写 PTY
    客户端 → 服务端 text(0x1)  ：JSON 控制帧
        {"type":"hello","cols":C,"rows":R}  建连后首帧，设定初始窗口大小
        {"type":"resize","cols":C,"rows":R} 窗口尺寸变化（TIOCSWINSZ）
    服务端 → 客户端 binary(0x2)：PTY 原始输出字节流（xterm.js term.write）
    服务端 → 客户端 text(0x1)  ：JSON 控制帧
        {"type":"session","id":"<sid>","reattached":bool} 建连后告知会话标识
            与是否接回了既有会话
        {"type":"exit","code":N} shell 退出

会话保持与重连（issue #173）：PTY 会话与 WebSocket 连接解耦。连接 URL 可
带 ?session=<sid>，命中存活会话则接回原 PTY（断线期间的输出从回放缓冲补
发）；未命中则新开会话。连接断开（任何原因，含 TCP keepalive 判死）后
会话保留 _SESSION_GRACE 秒的宽限期，期间重连均可找回现场，宽限期过后才
销毁。

每个 WebSocket 连接同一时间只挂在一个会话上；shell 自然退出（用户输入
exit）时会话立即销毁。浏览器对小输入帧不分片，binary 输入按帧直写 PTY
（字节流语义，分片也安全）；text 控制帧极小，不会被分片。

安全说明：本服务无认证（与整车免密策略一致，2026-08-14 用户决策）。Launcher
监听 0.0.0.0:8090，任何能访问该局域网端口的设备都可获得本机 dkc 用户的
shell。仅供家庭/实验室可信网络使用。
"""

import base64
import fcntl
import hashlib
import json
import logging
import os
import pty
import socket
import struct
import subprocess
import termios
import threading
import time
import uuid
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

DEFAULT_COLS = 80
DEFAULT_ROWS = 24
MAX_COLS_ROWS = 500
_MAX_FRAME_PAYLOAD = 1 << 20  # 1 MiB，防御畸形帧耗尽内存
_READ_CHUNK = 65536

# TCP keepalive（issue #173，替代 issue #151 的应用层 PING 判死）：浏览器
# 标签页被冻结 / 手机锁屏时应用层 PONG 会停，但内核 TCP 栈仍在；PING 判死
# 会把"冻结但链路未死"误判为断线。改由内核 TCP keepalive 在链路层保活与判死：
#   - keepalive 探测包刷新 NAT 表项，空闲连接不再被中间设备悄悄断开；
#   - 只有对端内核也收不到探测（真正的死链）才会在超时后让 socket 报错，
#     从而触发会话 detach；冻结的浏览器内核照常 ACK 探测，不会被误断开。
_TCP_KEEP_IDLE = 30     # 连接空闲 30s 后发首个探测包
_TCP_KEEP_INTVL = 15    # 之后每 15s 一个探测包
_TCP_KEEP_CNT = 3       # 连续 3 个探测无 ACK 判死（约 30+45=75s）

# 会话保持（issue #173）：连接断开后 PTY 会话保留的宽限期，期间重连可接回
# 原会话；宽限期过后销毁（后台低频线程清扫）。断线期间的 PTY 输出缓存在
# 回放缓冲里，重连时补发，现场不丢。
_SESSION_GRACE = 900.0  # 15 分钟
_REPLAY_CAP = 1 << 20  # 回放缓冲上限 1 MiB，防止长期 TUI 输出无限膨胀

_sessions = {}  # sid -> TerminalSession
_sessions_lock = threading.Lock()


class WsProtocolError(Exception):
    """WebSocket 帧解析错误（对端不遵守 RFC6455 或连接中途断开）。"""


def ws_accept_key(client_key: str) -> str:
    """计算 Sec-WebSocket-Accept（RFC6455 §4.2.2）。"""
    digest = hashlib.sha1((client_key.strip() + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def build_frame(payload: bytes, opcode: int = OP_BINARY) -> bytes:
    """构建服务端→客户端帧（服务端帧按 RFC6455 不掩码）。"""
    header = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n <= 0xFFFF:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


def _read_exact(rfile, n: int) -> bytes:
    data = rfile.read(n)
    if data is None or len(data) < n:
        raise WsProtocolError("连接在帧中途断开")
    return data


def read_frame(rfile):
    """从 rfile 读一个客户端帧（RFC6455 要求客户端帧必须带掩码）。

    Args:
        rfile: 二进制缓冲读流（如 BaseHTTPRequestHandler.rfile）

    Returns:
        (fin, opcode, payload) 元组

    Raises:
        WsProtocolError: 帧格式非法或连接断开
    """
    head = _read_exact(rfile, 2)
    fin = bool(head[0] & 0x80)
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _read_exact(rfile, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read_exact(rfile, 8))[0]
    if length > _MAX_FRAME_PAYLOAD:
        raise WsProtocolError(f"帧超长: {length}")
    if not masked:
        raise WsProtocolError("客户端帧必须带掩码")
    mask = _read_exact(rfile, 4)
    payload = bytearray(_read_exact(rfile, length))
    for i in range(length):
        payload[i] ^= mask[i % 4]
    return fin, opcode, bytes(payload)


class _WsWriter:
    """线程安全的 WebSocket 帧发送器。

    PTY 读线程（输出帧）与主读循环（pong/close 帧）可能并发写同一条
    连接，所有发送都经过同一把锁。
    """

    def __init__(self, wfile):
        self._wfile = wfile
        self._lock = threading.Lock()
        self.closed = False

    def send(self, payload: bytes, opcode: int = OP_BINARY) -> bool:
        """发送一帧。连接已关闭或写失败时返回 False。"""
        with self._lock:
            if self.closed:
                return False
            try:
                self._wfile.write(build_frame(payload, opcode))
                self._wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.closed = True
                return False

    def send_json(self, obj) -> bool:
        return self.send(json.dumps(obj).encode("utf-8"), OP_TEXT)


def _default_cwd() -> str:
    """新会话的默认工作目录：~/projects（工作区主文件夹），不存在时回退 ~。"""
    projects = os.path.expanduser("~/projects")
    if os.path.isdir(projects):
        return projects
    return os.path.expanduser("~")


class TerminalSession:
    """一个 bash PTY 会话（与 WebSocket 连接解耦，issue #173）。

    生命周期：
        创建      — openpty + 起 bash login shell（ctty 正确设置，支持
                    任务控制与 Ctrl-C），注册进 _sessions
        attach    — 挂上一个 WS 连接：补发断线期间的回放缓冲
        on_input  — 客户端输入字节直写 PTY master
        on_resize — TIOCSWINSZ 调整窗口大小
        detach    — 连接断开（任何原因）时解除挂载，会话进入宽限期，
                    期间 PTY 输出继续累积进回放缓冲，等待重连接回
        close     — 杀子进程、关 master、从 _sessions 注销，幂等
    子进程自然退出（用户输入 exit）时由 waiter 线程通知客户端并 close。
    宽限期耗尽仍无人重连的会话由 _sessions_sweeper 后台线程清扫。
    """

    def __init__(self, shell=("/bin/bash", "-l"), cwd=None, env=None):
        self.sid = uuid.uuid4().hex[:12]
        self._writer = None
        self._detached_at = None
        self._replay = bytearray()
        self._replay_lock = threading.Lock()
        self._master = None
        self._proc = None
        self._closed = False
        self._close_lock = threading.Lock()
        self._spawn(shell, cwd, env)
        self._reader = threading.Thread(target=self._reader_loop, daemon=True,
                                        name="terminal-pty-reader")
        self._reader.start()
        self._waiter = threading.Thread(target=self._waiter_loop, daemon=True,
                                        name="terminal-pty-waiter")
        self._waiter.start()

    # ------------------------------------------------------------------
    def _spawn(self, shell, cwd, env):
        master, slave = pty.openpty()
        self._set_winsize_fd(slave, DEFAULT_ROWS, DEFAULT_COLS)
        child_env = dict(os.environ if env is None else env)
        child_env["TERM"] = "xterm-256color"
        child_env["COLORTERM"] = "truecolor"

        def _become_tty_leader():
            # preexec_fn 在子进程 exec 前、stdin/stdout/stderr 已 dup2 到位
            # 且 cwd 已切换之后运行：先 setsid 再 TIOCSCTTY，让 slave 成为
            # 控制终端（任务控制、Ctrl-C 信号投递都依赖它）
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self._proc = subprocess.Popen(
            list(shell),
            stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=_become_tty_leader,
            cwd=cwd or _default_cwd(),
            env=child_env,
            close_fds=True,
        )
        os.close(slave)
        self._master = master
        logger.info("终端会话已建立: pid=%d", self._proc.pid)

    # ------------------------------------------------------------------
    def on_input(self, data: bytes):
        """客户端输入字节流写入 PTY。"""
        if self._closed or self._master is None:
            return
        try:
            os.write(self._master, data)
        except OSError:
            pass

    def on_resize(self, cols, rows):
        """调整 PTY 窗口大小（防御性钳制，避免畸形值打爆行缓存）。"""
        try:
            cols = max(1, min(MAX_COLS_ROWS, int(cols)))
            rows = max(1, min(MAX_COLS_ROWS, int(rows)))
        except (TypeError, ValueError):
            return
        if self._closed or self._master is None:
            return
        self._set_winsize_fd(self._master, rows, cols)

    @staticmethod
    def _set_winsize_fd(fd, rows, cols):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    @property
    def pid(self):
        return self._proc.pid if self._proc else None

    # ------------------------------------------------------------------
    def attach(self, writer: _WsWriter):
        """挂上 WS 连接并补发断线期间缓存的输出（issue #173 重连接回）。"""
        with self._replay_lock:
            replay = bytes(self._replay)
        self._detached_at = None
        self._writer = writer
        if replay:
            writer.send(replay, OP_BINARY)
        logger.info("终端会话已挂载: sid=%s pid=%d 补发 %d 字节",
                    self.sid, self.pid or -1, len(replay))

    def detach(self, writer=None):
        """解除 WS 连接挂载：会话进入宽限期，等待重连接回。

        Args:
            writer: 调用方自己持有的 writer。传入时仅当会话当前挂载的
                正是它才解除——旧连接线程的收尾 detach 可能在新连接
                attach 之后才执行，不带判断会误清新 writer（竞态）。
                不传（None）则无条件强制解除（重连抢占时用）。

        幂等；由主读循环 finally、reader 发送失败时调用。
        """
        if writer is not None and self._writer is not writer:
            return  # 过期的收尾 detach，当前已挂上别的连接，忽略
        w, self._writer = self._writer, None
        if w is not None and self._detached_at is None:
            self._detached_at = time.monotonic()
            logger.info("终端会话进入宽限期: sid=%s", self.sid)

    def _stash(self, data: bytes):
        """断线期间的 PTY 输出累积进回放缓冲（有界，超出截旧留新）。"""
        with self._replay_lock:
            self._replay += data
            if len(self._replay) > _REPLAY_CAP:
                del self._replay[:len(self._replay) - _REPLAY_CAP]

    # ------------------------------------------------------------------
    def _reader_loop(self):
        """读 PTY 输出并转发：已挂载则发 WS binary 帧，未挂载则入回放缓冲。

        正常退出（bash exit → slave 关闭 → EIO）时的通知与清理由 waiter
        线程统一负责（它握有退出码）；发送失败（链路断开）时只解除挂载，
        会话留给宽限期，不销毁。
        """
        try:
            while not self._closed:
                data = os.read(self._master, _READ_CHUNK)
                if not data:
                    break
                writer = self._writer
                if writer is None:
                    self._stash(data)
                elif not writer.send(data, OP_BINARY):
                    self.detach(writer)
                    self._stash(data)
        except OSError:
            # EIO：slave 侧全部关闭（子进程退出）；EBADF：close() 关了 master
            pass

    def _waiter_loop(self):
        """等子进程退出；退出后通知客户端并收尾。"""
        code = self._proc.wait()
        if not self._closed:
            # 给 reader 一个短窗口把残留输出尽量发完
            time.sleep(0.3)
            writer = self._writer
            if writer is not None and not writer.closed:
                writer.send_json({"type": "exit", "code": code})
        self.close()

    # ------------------------------------------------------------------
    def close(self):
        """关闭会话：杀子进程、关 master、注销。幂等。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        with _sessions_lock:
            if _sessions.get(self.sid) is self:
                del _sessions[self.sid]
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()  # SIGHUP 由关 master 产生，这里补 SIGTERM
            except OSError:
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None
        logger.info("终端会话已销毁: sid=%s pid=%s", self.sid,
                    proc.pid if proc else None)


# ---------------------------------------------------------------------------
# 会话注册表：按 sid 获取/新建会话，后台清扫宽限期耗尽的会话（issue #173）
# ---------------------------------------------------------------------------
_SWEEP_INTERVAL = 30.0
_sweeper_started = False


def _acquire_session(requested_sid: str):
    """按 sid 接回存活会话；未提供或已失效则新开会话。

    Returns:
        (session, reattached) 元组，reattached 表示是否接回了既有会话
    """
    _ensure_sweeper()
    with _sessions_lock:
        sess = _sessions.get(requested_sid) if requested_sid else None
        if sess is not None and not sess._closed:
            # 极端情况：旧链路判死前新连接先到——先踢掉旧 writer，避免双写
            sess.detach()
            reattached = True
        else:
            sess = TerminalSession()
            _sessions[sess.sid] = sess
            reattached = False
    return sess, reattached


def _ensure_sweeper():
    """惰性启动会话清扫线程（首次建立会话时起，daemon，进程退出不阻拦）。"""
    global _sweeper_started
    with _sessions_lock:
        if _sweeper_started:
            return
        _sweeper_started = True
    threading.Thread(target=_sessions_sweeper, daemon=True,
                     name="terminal-session-sweeper").start()


def _sweep_once(now=None):
    """销毁一批宽限期耗尽仍无人重连的会话（有挂载连接的不动）。"""
    if now is None:
        now = time.monotonic()
    with _sessions_lock:
        doomed = [s for s in _sessions.values()
                  if s._writer is None and s._detached_at is not None
                  and now - s._detached_at > _SESSION_GRACE]
    for s in doomed:
        s.close()


def _sessions_sweeper():
    """周期性清扫（线程体）：每 _SWEEP_INTERVAL 秒跑一批 _sweep_once。"""
    while True:
        time.sleep(_SWEEP_INTERVAL)
        _sweep_once()


def _enable_tcp_keepalive(sock):
    """在连接套接字上启用内核 TCP keepalive（NAT 保活 + 死链检测，issue #173）。

    keepalive 探测包由内核发送、对端内核 ACK，与应用层无关：浏览器标签页被
    冻结 / 手机锁屏时内核仍会 ACK，因此不会被误判为断线；只有真正的死链
    （对端内核也收不到探测）才会在超时后让 socket 报错，触发会话 detach。

    Linux 专属的 TCP_KEEP* 常量不可用时回退到仅启用 SO_KEEPALIVE（使用系统
    默认探测参数）。
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _TCP_KEEP_IDLE)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _TCP_KEEP_INTVL)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _TCP_KEEP_CNT)
    except (OSError, AttributeError):
        pass


def _handle_control_frame(session: TerminalSession, payload: bytes):
    """解析 text 控制帧并执行（hello/resize）。无法解析的帧直接忽略。"""
    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(msg, dict):
        return
    if msg.get("type") in ("hello", "resize"):
        session.on_resize(msg.get("cols", DEFAULT_COLS),
                          msg.get("rows", DEFAULT_ROWS))


def handle_terminal_ws(handler):
    """在 LauncherHandler 请求线程内完成 WebSocket 握手并运行桥接循环。

    Args:
        handler: donkeycar.launcher.server.LauncherHandler 实例（其 rfile/
            wfile/headers 被直接接管；返回后连接不再参与 HTTP keep-alive）

    连接 URL 可带 ?session=<sid>：命中存活会话则接回原 PTY（补发断线期间
    的输出），否则新开会话；建连后向客户端发 {"type":"session",...} 告知
    sid 与是否接回（issue #173）。连接断开只会话进入宽限期，不销毁。

    本函数直到 WebSocket 断开才返回（ThreadingHTTPServer 每连接一线程，
    阻塞是预期行为）。
    """
    key = handler.headers.get("Sec-WebSocket-Key")
    upgrade = handler.headers.get("Upgrade", "").lower()
    version = handler.headers.get("Sec-WebSocket-Version", "")
    if not key or upgrade != "websocket" or version != "13":
        handler.send_error(400, "Bad WebSocket Request")
        return

    handler.log_request(101)
    # BaseHTTPRequestHandler 默认回 HTTP/1.0 状态行，严格的 ws 客户端会拒绝
    # （RFC6455 要求 101 响应为 HTTP/1.1），因此手写状态行与响应头
    handler.wfile.write((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {ws_accept_key(key)}\r\n"
        "\r\n"
    ).encode("ascii"))
    handler.wfile.flush()
    handler.close_connection = True  # 连接被 ws 接管

    qs = parse_qs(urlparse(handler.path).query)
    requested_sid = (qs.get("session") or [""])[0]
    writer = _WsWriter(handler.wfile)
    _enable_tcp_keepalive(handler.connection)
    session, reattached = _acquire_session(requested_sid)
    session.attach(writer)
    writer.send_json({"type": "session", "id": session.sid,
                      "reattached": reattached})
    try:
        while not writer.closed:
            _fin, opcode, payload = read_frame(handler.rfile)
            if opcode == OP_CLOSE:
                writer.send(b"", OP_CLOSE)
                break
            if opcode == OP_PING:
                writer.send(payload, OP_PONG)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_BINARY:
                session.on_input(payload)
            elif opcode == OP_TEXT:
                _handle_control_frame(session, payload)
    except (WsProtocolError, BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        session.detach(writer)
