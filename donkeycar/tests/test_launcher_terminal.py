"""Launcher 上位机终端（WebSocket ↔ PTY 桥）单元测试。

测试覆盖 donkeycar.launcher.terminal 与 server.py 的路由集成：
- ws_accept_key / build_frame / read_frame：RFC6455 握手与帧编解码
- _default_cwd：默认工作目录优先 ~/projects，目录不存在时回退 ~
- TerminalSession：bash PTY 回显、Ctrl-C 信号投递（控制终端设置正确性）、
  窗口大小调整（TIOCSWINSZ）、初始工作目录、exit 通知与会话清理
- handle_terminal_ws：经真实 ThreadingHTTPServer + 原始 socket 客户端的
  端到端握手、binary 输入/输出桥接、close 帧应答
- 服务端心跳（issue #151）：定期向客户端发 PING；长时间无任何客户端帧
  时主动 shutdown 断开并清理会话
"""

import json
import os
import socket
import struct
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from donkeycar.launcher import terminal
from donkeycar.launcher.terminal import (
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    TerminalSession,
    WsProtocolError,
    build_frame,
    read_frame,
    ws_accept_key,
)


# ===========================================================================
# 工具
# ===========================================================================
def _masked_client_frame(payload: bytes, opcode: int = OP_BINARY) -> bytes:
    """构造客户端→服务端帧（RFC6455 要求客户端帧带掩码）。"""
    mask = b"\x11\x22\x33\x44"
    head = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head.append(0x80 | n)
    elif n <= 0xFFFF:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(head) + mask + masked


class _FakeWriter:
    """收集发送帧的 _WsWriter 替身。"""

    def __init__(self):
        self.frames = []
        self.closed = False
        self._lock = threading.Lock()

    def send(self, payload, opcode=OP_BINARY):
        with self._lock:
            self.frames.append((opcode, payload))
        return True

    def send_json(self, obj):
        return self.send(json.dumps(obj).encode("utf-8"), OP_TEXT)

    def output(self) -> bytes:
        with self._lock:
            return b"".join(p for op, p in self.frames if op == OP_BINARY)

    def json_messages(self):
        with self._lock:
            return [json.loads(p.decode("utf-8"))
                    for op, p in self.frames if op == OP_TEXT]


def _wait_until(predicate, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def session():
    """起一个真实 bash PTY 会话，测试后确保关闭。"""
    writer = _FakeWriter()
    sess = TerminalSession(writer)
    yield sess, writer
    sess.close()


# ===========================================================================
# RFC6455 协议编解码
# ===========================================================================
def test_ws_accept_key_rfc_vector():
    # RFC6455 §4.2.2 示例
    assert ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == \
        "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_build_frame_short_payload():
    frame = build_frame(b"hi", OP_BINARY)
    assert frame[:2] == bytes([0x80 | OP_BINARY, 2])
    assert frame[2:] == b"hi"


def test_build_frame_extended_lengths():
    # 126 ~ 65535：2 字节扩展长度
    payload = b"x" * 300
    frame = build_frame(payload, OP_BINARY)
    assert frame[0] == 0x80 | OP_BINARY
    assert frame[1] == 126
    assert struct.unpack(">H", frame[2:4])[0] == 300
    assert frame[4:] == payload

    # >65535：8 字节扩展长度
    payload = b"y" * 70000
    frame = build_frame(payload, OP_TEXT)
    assert frame[1] == 127
    assert struct.unpack(">Q", frame[2:10])[0] == 70000
    assert frame[10:] == payload


def test_read_frame_masked_roundtrip():
    import io
    payload = "echo 你好\n".encode("utf-8")
    rfile = io.BytesIO(_masked_client_frame(payload, OP_BINARY))
    fin, opcode, got = read_frame(rfile)
    assert fin and opcode == OP_BINARY and got == payload


def test_read_frame_extended_length_roundtrip():
    import io
    payload = os.urandom(1000)
    rfile = io.BytesIO(_masked_client_frame(payload, OP_BINARY))
    _, _, got = read_frame(rfile)
    assert got == payload


def test_read_frame_rejects_unmasked():
    import io
    rfile = io.BytesIO(bytes([0x82, 0x02]) + b"hi")  # 未掩码
    with pytest.raises(WsProtocolError):
        read_frame(rfile)


def test_read_frame_rejects_truncated():
    import io
    rfile = io.BytesIO(_masked_client_frame(b"hello")[:-2])  # 截断
    with pytest.raises(WsProtocolError):
        read_frame(rfile)


# ===========================================================================
# TerminalSession（真实 bash PTY）
# ===========================================================================
def test_session_echo(session):
    sess, writer = session
    sess.on_input(b"echo $((21*2))\n")
    assert _wait_until(lambda: b"42" in writer.output())


def test_session_ctrl_c_interrupts_foreground_process(session):
    """Ctrl-C（\\x03）必须能打断前台进程——验证控制终端设置正确。"""
    sess, writer = session
    sess.on_input(b"sleep 30\n")
    time.sleep(0.5)
    sess.on_input(b"\x03")
    time.sleep(0.3)
    sess.on_input(b"echo alive-$((6*7))\n")
    assert _wait_until(lambda: b"alive-42" in writer.output())


def test_session_resize(session):
    sess, writer = session
    sess.on_resize(123, 45)
    sess.on_input(b"stty size\n")
    assert _wait_until(lambda: b"45 123" in writer.output())


def test_session_resize_clamps_garbage(session):
    sess, writer = session
    sess.on_resize(99999, -3)  # 钳制到合法范围，不应崩溃
    sess.on_resize("abc", None)
    sess.on_input(b"echo still-$((20+22))\n")
    assert _wait_until(lambda: b"still-42" in writer.output())


def test_session_exit_notifies_and_closes(session):
    sess, writer = session
    sess.on_input(b"exit 7\n")
    assert _wait_until(lambda: any(m.get("type") == "exit"
                                   and m.get("code") == 7
                                   for m in writer.json_messages()))
    assert _wait_until(lambda: sess._closed, timeout=5)


# ===========================================================================
# 默认工作目录（~/projects 优先，缺失时回退 ~）
# ===========================================================================
def test_default_cwd_prefers_projects(tmp_path, monkeypatch):
    """~/projects 存在时，默认工作目录指向它。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    assert terminal._default_cwd() == str(tmp_path / "projects")


def test_default_cwd_falls_back_to_home(tmp_path, monkeypatch):
    """~/projects 不存在时，回退到用户主目录 ~。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert terminal._default_cwd() == str(tmp_path)


def test_session_starts_in_default_cwd(tmp_path, monkeypatch):
    """真实 PTY 会话的初始工作目录为 ~/projects（issue #102 端到端验证）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects = tmp_path / "projects"
    projects.mkdir()
    writer = _FakeWriter()
    sess = TerminalSession(writer)
    try:
        sess.on_input(b"pwd\n")
        assert _wait_until(lambda: str(projects).encode() in writer.output())
    finally:
        sess.close()


# ===========================================================================
# 端到端：HTTP 服务器 + 原始 socket 客户端
# ===========================================================================
def _recv_server_frame(sock_file):
    """读一个服务端→客户端帧（无掩码）。"""
    head = sock_file.read(2)
    assert len(head) == 2
    opcode = head[0] & 0x0F
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", sock_file.read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", sock_file.read(8))[0]
    payload = sock_file.read(length)
    assert len(payload) == length
    return opcode, payload


def test_terminal_ws_end_to_end():
    from donkeycar.launcher.server import LauncherHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), LauncherHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        request = (
            "GET /terminal/ws HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        sock_file = sock.makefile("rb")

        # 握手响应
        status = sock_file.readline().decode("latin-1")
        assert "101" in status
        headers = {}
        while True:
            line = sock_file.readline().decode("latin-1").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        assert headers.get("sec-websocket-accept") == ws_accept_key(key)

        # hello 控制帧 + 命令输入
        sock.sendall(_masked_client_frame(
            json.dumps({"type": "hello", "cols": 80, "rows": 24})
            .encode("utf-8"), OP_TEXT))
        sock.sendall(_masked_client_frame(b"echo ws-$((20+22))\n", OP_BINARY))

        # 读到包含 ws-42 的输出帧为止（跳过提示符等输出）
        deadline = time.monotonic() + 15
        output = b""
        while time.monotonic() < deadline and b"ws-42" not in output:
            opcode, payload = _recv_server_frame(sock_file)
            if opcode == OP_BINARY:
                output += payload
        assert b"ws-42" in output

        # ping → pong
        sock.sendall(_masked_client_frame(b"pingdata", OP_PING))
        while True:
            opcode, payload = _recv_server_frame(sock_file)
            if opcode == OP_PONG:
                assert payload == b"pingdata"
                break
            if opcode == OP_BINARY:
                continue  # 跳过 shell 输出
            pytest.fail(f"期望 PONG，收到 opcode={opcode}")

        # close → 服务端回应 close
        sock.sendall(_masked_client_frame(b"", OP_CLOSE))
        while True:
            opcode, _payload = _recv_server_frame(sock_file)
            if opcode == OP_CLOSE:
                break
        sock.close()
    finally:
        server.shutdown()
        server.server_close()


def _open_terminal_ws():
    """启动真实 Launcher 服务器并完成 ws 握手。

    Returns:
        (server, sock, sock_file)；调用方负责关闭 sock 与 server
    """
    from donkeycar.launcher.server import LauncherHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), LauncherHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]),
                                    timeout=10)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    request = (
        "GET /terminal/ws HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    sock_file = sock.makefile("rb")
    status = sock_file.readline().decode("latin-1")
    assert "101" in status
    while True:
        if not sock_file.readline().decode("latin-1").strip():
            break
    return server, sock, sock_file


def test_terminal_ws_server_sends_heartbeat_ping(monkeypatch):
    """服务端按 _PING_INTERVAL 周期主动向客户端发 PING 帧（issue #151）。"""
    monkeypatch.setattr(terminal, "_PING_INTERVAL", 0.2)
    server, sock, sock_file = _open_terminal_ws()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            opcode, _payload = _recv_server_frame(sock_file)
            if opcode == OP_PING:
                return  # 收到服务端心跳
            # 跳过 shell 提示符等 binary 输出
        pytest.fail("超时未收到服务端 PING 心跳")
    finally:
        sock.close()
        server.shutdown()
        server.server_close()


def test_terminal_ws_idle_timeout_disconnects(monkeypatch):
    """超过 _PONG_TIMEOUT 未收到任何客户端帧，服务端主动断开（issue #151）。"""
    monkeypatch.setattr(terminal, "_PING_INTERVAL", 0.1)
    monkeypatch.setattr(terminal, "_PONG_TIMEOUT", 0.3)
    server, sock, _sock_file = _open_terminal_ws()
    try:
        # 不回任何帧（含 PONG），等服务端判死 shutdown → 读到 EOF
        sock.settimeout(0.5)
        deadline = time.monotonic() + 10
        eof = False
        while time.monotonic() < deadline:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if data == b"":
                eof = True
                break
        assert eof, "空闲超时后服务端未主动断开连接"
    finally:
        sock.close()
        server.shutdown()
        server.server_close()


def test_terminal_ws_rejects_bad_handshake():
    from donkeycar.launcher.server import LauncherHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), LauncherHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 普通 GET（无 Upgrade 头）应得到 400
        import urllib.request
        with pytest.raises(Exception) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/terminal/ws",
                                   timeout=5)
        assert "400" in str(exc_info.value)
    finally:
        server.shutdown()
        server.server_close()
