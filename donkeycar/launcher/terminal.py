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
    服务端 → 客户端 text(0x1)  ：{"type":"exit","code":N} shell 退出

每个 WebSocket 连接对应一个独立的 bash 会话；连接断开（任何方向）即杀掉
对应子进程。浏览器对小输入帧不分片，binary 输入按帧直写 PTY（字节流语义，
分片也安全）；text 控制帧极小，不会被分片。

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

# 服务端心跳（issue #151）：每 _PING_INTERVAL 秒向客户端发一个 WebSocket
# PING 帧，浏览器会在协议层自动回 PONG；超过 _PONG_TIMEOUT 秒未收到任何
# 客户端帧（含 PONG）则判定链路死亡，主动断开并清理 PTY 会话
_PING_INTERVAL = 25.0
_PONG_TIMEOUT = 60.0


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
    """一个 WebSocket 连接对应的 bash PTY 会话。

    生命周期：
        创建      — openpty + 起 bash login shell（ctty 正确设置，支持
                    任务控制与 Ctrl-C）
        on_input  — 客户端输入字节直写 PTY master
        on_resize — TIOCSWINSZ 调整窗口大小
        close     — 杀子进程、关 master，幂等
    子进程自然退出（用户输入 exit）时由 waiter 线程通知客户端并 close。
    """

    def __init__(self, writer: _WsWriter, shell=("/bin/bash", "-l"),
                 cwd=None, env=None):
        self._writer = writer
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
    def _reader_loop(self):
        """读 PTY 输出并转发为 ws binary 帧，直到 EOF/断开。

        正常退出（bash exit → slave 关闭 → EIO）时的通知与清理由 waiter
        线程统一负责（它握有退出码）；只有当浏览器侧断开（writer 关闭）
        而 shell 还活着时，reader 才主动 close() 杀掉会话。
        """
        try:
            while not self._closed:
                data = os.read(self._master, _READ_CHUNK)
                if not data:
                    break
                if not self._writer.send(data, OP_BINARY):
                    break
        except OSError:
            # EIO：slave 侧全部关闭（子进程退出）；EBADF：close() 关了 master
            pass
        finally:
            if self._writer.closed:
                self.close()

    def _waiter_loop(self):
        """等子进程退出；退出后通知客户端并收尾。

        子进程退出但孙进程仍持有 slave（如 shell 里 nohup 的后台任务）时
        reader 不会收到 EIO，因此必须靠 waiter 主动 close() 收掉会话。
        """
        code = self._proc.wait()
        if not self._closed:
            # 给 reader 一个短窗口把残留输出尽量发完
            time.sleep(0.3)
            self._writer.send_json({"type": "exit", "code": code})
        self.close()

    # ------------------------------------------------------------------
    def close(self):
        """关闭会话：杀子进程、关 master。幂等。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
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
        logger.info("终端会话已关闭: pid=%s", proc.pid if proc else None)


def _heartbeat_loop(writer, sock, last_rx, stop):
    """服务端心跳线程：定期发 PING 保活，链路死亡时主动断开（issue #151）。

    Args:
        writer: _WsWriter，用于发 PING 帧与标记关闭
        sock: 底层 TCP 套接字，判死后 shutdown 以唤醒阻塞的主读循环
        last_rx: {"t": monotonic} 字典，主读循环每收到一帧就刷新 t
        stop: threading.Event，连接结束时由主流程置位以退出本线程

    浏览器收到 PING 会自动回 PONG，无需前端配合；周期性帧同时刷新链路上
    的 NAT 表项，空闲连接不再被中间设备悄悄断开。
    """
    while not stop.wait(_PING_INTERVAL):
        if writer.closed:
            return
        if time.monotonic() - last_rx["t"] > _PONG_TIMEOUT:
            writer.closed = True
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if not writer.send(b"", OP_PING):
            return


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

    writer = _WsWriter(handler.wfile)
    session = TerminalSession(writer)
    last_rx = {"t": time.monotonic()}
    stop_hb = threading.Event()
    threading.Thread(
        target=_heartbeat_loop,
        args=(writer, handler.connection, last_rx, stop_hb),
        daemon=True, name="terminal-ws-heartbeat").start()
    try:
        while not writer.closed:
            _fin, opcode, payload = read_frame(handler.rfile)
            last_rx["t"] = time.monotonic()
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
        stop_hb.set()
        session.close()
