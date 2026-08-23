"""Launcher 上位机终端（WebSocket ↔ PTY 桥）单元测试。

测试覆盖 donkeycar.launcher.terminal 与 server.py 的路由集成：
- ws_accept_key / build_frame / read_frame：RFC6455 握手与帧编解码
- _default_cwd：默认工作目录优先 ~/projects，目录不存在时回退 ~
- TerminalSession：bash PTY 回显、Ctrl-C 信号投递（控制终端设置正确性）、
  窗口大小调整（TIOCSWINSZ）、初始工作目录、exit 通知与会话清理
- handle_terminal_ws：经真实 ThreadingHTTPServer + 原始 socket 客户端的
  端到端握手、binary 输入/输出桥接、close 帧应答
- 内核 TCP keepalive（issue #173）：连接套接字启用 SO_KEEPALIVE + Linux
  TCP_KEEP* 参数，NAT 保活与死链检测不再误伤"浏览器冻结但链路未死"；
  空闲期间不主动 shutdown 断开
- 会话保持与重连（issue #173）：连接断开后 PTY 会话进入宽限期不销毁，
  ?session=<sid> 重连接回原会话并补发断线期间的输出；宽限期耗尽后由
  清扫线程销毁
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
    sess = TerminalSession()
    with terminal._sessions_lock:
        terminal._sessions[sess.sid] = sess
    writer = _FakeWriter()
    sess.attach(writer)
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
    sess = TerminalSession()
    try:
        writer = _FakeWriter()
        sess.attach(writer)
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


def _open_terminal_ws(session_id=None):
    """启动真实 Launcher 服务器并完成 ws 握手。

    Args:
        session_id: 可选的重连会话 sid（?session=，issue #173）

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
    path = "/terminal/ws" + (f"?session={session_id}" if session_id else "")
    request = (
        f"GET {path} HTTP/1.1\r\n"
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


def _read_json_control(sock_file, timeout=10.0):
    """读到服务端下一条 text 控制帧并解析（跳过 binary/PING）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        opcode, payload = _recv_server_frame(sock_file)
        if opcode == OP_TEXT:
            return json.loads(payload.decode("utf-8"))
    pytest.fail("超时未收到 text 控制帧")


def test_terminal_ws_idle_keeps_connection():
    """空闲（无任何客户端帧，含 PONG）不再判死断连（issue #173）。

    旧实现（issue #151）用应用层 PONG 超时判死，会把"浏览器冻结但链路
    未死"误判为断线；改为内核 TCP keepalive 后，服务端空闲期间不主动
    shutdown，命令仍能正常往返。
    """
    server, sock, sock_file = _open_terminal_ws()
    try:
        _read_json_control(sock_file)  # 收掉 session 帧
        # 静默一段时间，不发送任何客户端帧（含 PONG）
        time.sleep(0.5)
        # 连接仍应存活：发一条命令能正常得到输出
        sock.sendall(_masked_client_frame(b"echo alive-$((6*7))\n", OP_BINARY))
        deadline = time.monotonic() + 5
        output = b""
        while time.monotonic() < deadline and b"alive-42" not in output:
            opcode, payload = _recv_server_frame(sock_file)
            if opcode == OP_BINARY:
                output += payload
        assert b"alive-42" in output, "空闲后连接被断开，命令无响应"
    finally:
        sock.close()
        server.shutdown()
        server.server_close()


def test_enable_tcp_keepalive_sets_socket_options():
    """_enable_tcp_keepalive 启用 SO_KEEPALIVE 并设置 Linux TCP_KEEP* 参数。"""
    s = socket.socket()
    try:
        terminal._enable_tcp_keepalive(s)
        assert s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        try:
            assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == terminal._TCP_KEEP_IDLE
            assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == terminal._TCP_KEEP_INTVL
            assert s.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == terminal._TCP_KEEP_CNT
        except (OSError, AttributeError):
            pass  # 非 Linux 或常量不可用，仅验证 SO_KEEPALIVE 已启用
    finally:
        s.close()


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


# ===========================================================================
# 会话保持与重连（issue #173）
# ===========================================================================
def test_terminal_ws_sends_session_frame():
    """新连接下发 session 控制帧：含 sid 且 reattached=False。"""
    server, sock, sock_file = _open_terminal_ws()
    try:
        msg = _read_json_control(sock_file)
        assert msg["type"] == "session"
        assert msg["reattached"] is False
        assert msg["id"]
    finally:
        sock.close()
        server.shutdown()
        server.server_close()


def test_terminal_ws_reattach_preserves_session_and_replays_output():
    """断线后 ?session=<sid> 重连接回原 PTY：会话现场保留 + 断线期间输出补发。"""
    server, sock, sock_file = _open_terminal_ws()
    sid = _read_json_control(sock_file)["id"]
    # 会话现场：导出环境变量 + 起一个断线后才输出的后台任务
    sock.sendall(_masked_client_frame(b"export SEED=73\n", OP_BINARY))
    sock.sendall(_masked_client_frame(b"sleep 1; echo late-73\n", OP_BINARY))
    # 等服务端收到输入后断开（不留 close 帧，模拟链路突然死亡）；
    # 先关 makefile 派生流再关 socket，确保真正发 FIN
    time.sleep(0.5)
    sock_file.close()
    sock.close()
    server.shutdown()
    server.server_close()

    # 宽限期内重连：应接回原会话
    server2, sock2, sock_file2 = None, None, None
    try:
        server2, sock2, sock_file2 = _open_terminal_ws(session_id=sid)
        msg = _read_json_control(sock_file2)
        assert msg["type"] == "session" and msg["id"] == sid
        assert msg["reattached"] is True

        # 断线期间（sleep 到点）的输出经回放缓冲补发；环境变量现场仍在
        deadline = time.monotonic() + 15
        output = b""
        got_late = False
        while time.monotonic() < deadline and not got_late:
            opcode, payload = _recv_server_frame(sock_file2)
            if opcode != OP_BINARY:
                continue
            output += payload
            got_late = b"late-73" in output
        assert got_late, "重连后未补发断线期间的输出"

        sock2.sendall(_masked_client_frame(b"echo env-$SEED\n", OP_BINARY))
        got_env = False
        while time.monotonic() < deadline and not got_env:
            opcode, payload = _recv_server_frame(sock_file2)
            if opcode != OP_BINARY:
                continue
            output += payload
            got_env = b"env-73" in output
        assert got_env, "重连后会话现场（环境变量）丢失"
        # 显式销毁，避免宽限期里的会话泄漏到其他测试
        with terminal._sessions_lock:
            sess = terminal._sessions.get(sid)
        if sess:
            sess.close()
    finally:
        if sock2:
            sock2.close()
        if server2:
            server2.shutdown()
            server2.server_close()


def test_terminal_ws_grace_expiry_destroys_session(monkeypatch):
    """宽限期耗尽仍无人重连的会话被清扫销毁（issue #173）。

    直接调用 _sweep_once 验证销毁逻辑：清扫线程是进程级单例、休眠间隔
    固定，monkeypatch 间隔无法叫醒已在 sleep 的旧线程（全量跑测试时该
    线程已被先前用例以默认 30s 间隔启动）。
    """
    monkeypatch.setattr(terminal, "_SESSION_GRACE", 0.3)
    server, sock, sock_file = _open_terminal_ws()
    try:
        sid = _read_json_control(sock_file)["id"]
        # 先关 makefile 派生流再关 socket：sock_file 活着时 sock.close()
        # 不会真正关闭 fd、不发 FIN，服务端就收不到 EOF（CPython _io_refs）
        sock_file.close()
        sock.close()
        # 服务端 detach 是异步的，先等会话进入宽限期
        assert _wait_until(
            lambda: terminal._sessions.get(sid) is not None
            and terminal._sessions[sid]._writer is None, timeout=5)
        # 宽限期内清扫不销毁
        terminal._sweep_once()
        assert terminal._sessions.get(sid) is not None, "宽限期内会话被误销毁"
        # 宽限期耗尽后清扫销毁
        time.sleep(0.3)
        terminal._sweep_once()
        assert terminal._sessions.get(sid) is None, "宽限期耗尽后会话未被销毁"
    finally:
        server.shutdown()
        server.server_close()
