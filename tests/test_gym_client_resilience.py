"""gym_donkeycar SDClient 断连韧性回归测试。

背景缺陷（线上日志实锤）：模拟器侧复位连接（Connection reset by peer）后，
proc_msg 的通用异常分支调用 on_msg_recv({"msg_type":"aborted"}) →
handler.on_abort → client.stop() → th.join() 作用于当前线程，抛
RuntimeError: cannot join current thread，读线程整个崩掉、socket 不关闭、
aborted 状态不一致——上层（dgym）从此再也检测不到失联，车端永久掉线。

修复后：stop() 幂等可重入（不 join 自己）、socket 先关、select 带超时；
RST/断连统一收敛为 aborted=True + do_process_msgs=False + 读线程退出；
is_connected() 成为权威健康信号。
"""
import socket
import struct
import time

import pytest

from gym_donkeycar.core.client import SDClient


class _RstServer:
    """接受一条连接后可选发送欢迎消息，随后以 RST 方式断开。"""

    def __init__(self, greet: bytes = b""):
        self.greet = greet
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]

    def accept_and_rst(self):
        conn, _ = self.sock.accept()
        if self.greet:
            conn.sendall(self.greet)
            time.sleep(0.05)
        # SO_LINGER(1, 0) + close => 发送 RST 而非 FIN，模拟模拟器侧强制复位
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                        struct.pack("ii", 1, 0))
        conn.close()

    def close(self):
        self.sock.close()


def _wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestIsConnected:
    def test_true_after_connect(self):
        srv = _RstServer()
        try:
            client = SDClient("127.0.0.1", srv.port)
            try:
                assert client.is_connected() is True
            finally:
                client.stop()
        finally:
            srv.close()

    def test_false_after_clean_stop(self):
        srv = _RstServer()
        try:
            client = SDClient("127.0.0.1", srv.port)
            client.stop()
            assert client.is_connected() is False
        finally:
            srv.close()


class TestResetRecovery:
    def test_rst_marks_disconnected_without_thread_crash(self):
        """对端 RST 后：读线程安静退出、is_connected 翻假、stop() 不抛。"""
        srv = _RstServer()
        try:
            client = SDClient("127.0.0.1", srv.port)
            srv.accept_and_rst()
            assert _wait_until(lambda: not client.is_connected()), \
                "RST 后 is_connected 应翻为 False"
            assert _wait_until(lambda: not client.th.is_alive()), \
                "读线程应自行退出"
            # 幂等清理不得抛异常（旧代码在此 RuntimeError）
            client.stop()
            client.stop()
        finally:
            srv.close()

    def test_stop_from_reader_thread_is_safe(self):
        """模拟 on_abort 路径：在读线程上下文里调 stop() 不得 RuntimeError。"""
        srv = _RstServer()
        errors = []

        class StopOnAbort(SDClient):
            def on_msg_recv(self, j):
                if j.get("msg_type") == "aborted":
                    try:
                        self.stop()  # 旧代码：th.join() 当前线程 -> RuntimeError
                    except Exception as e:  # pragma: no cover
                        errors.append(e)

        try:
            client = StopOnAbort("127.0.0.1", srv.port)
            srv.accept_and_rst()
            assert _wait_until(lambda: not client.th.is_alive()), \
                "读线程应退出（而不是被 RuntimeError 击穿）"
            assert errors == [], f"stop() 在读线程内调用不应抛异常: {errors}"
            assert client.is_connected() is False
        finally:
            srv.close()

    def test_recv_error_path_sets_aborted(self):
        srv = _RstServer()
        try:
            client = SDClient("127.0.0.1", srv.port)
            srv.accept_and_rst()
            assert _wait_until(lambda: client.aborted), "RST 应置 aborted"
        finally:
            srv.close()

    def test_recv_error_path_notifies_aborted(self):
        """RST 接收错误必须发 {"msg_type":"aborted"} 通知（on_abort 路径）。

        旧代码只置标志就 break：handler 收不到失联信号、socket FD 悬挂，
        上层（dgym）只能靠 wrapper 穿不透的健康检查瞎猜——僵尸态一环。
        """
        srv = _RstServer()
        received = []

        class Recording(SDClient):
            def on_msg_recv(self, j):
                received.append(j)

        try:
            client = Recording("127.0.0.1", srv.port)
            srv.accept_and_rst()
            assert _wait_until(
                lambda: any(j.get("msg_type") == "aborted" for j in received)
            ), f"recv 错误路径应发出 aborted 通知，实际收到: {received}"
            assert client.aborted is True
            assert client.is_connected() is False
        finally:
            srv.close()

    def test_rst_on_abort_stop_closes_socket(self):
        """on_abort → stop() 后 socket FD 必须真正关闭（曾泄漏悬挂 FD）。"""
        srv = _RstServer()

        class StopOnAbort(SDClient):
            def on_msg_recv(self, j):
                if j.get("msg_type") == "aborted":
                    self.stop()

        try:
            client = StopOnAbort("127.0.0.1", srv.port)
            srv.accept_and_rst()
            assert _wait_until(lambda: client.s.fileno() == -1), \
                "aborted 通知触发 stop() 后 socket 应已关闭"
        finally:
            srv.close()

    def test_graceful_fin_converges_to_aborted(self):
        """对端正常关闭（FIN）也不得 busy-spin，须收敛为 aborted + 读线程退出。

        旧代码 recv 返回空串后继续循环：select 立刻返回 readable、recv 返回
        空，读线程 100% CPU 空转且 aborted 永不置位。
        """
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        received = []

        class Recording(SDClient):
            def on_msg_recv(self, j):
                received.append(j)

        try:
            client = Recording("127.0.0.1", srv.getsockname()[1])
            conn, _ = srv.accept()
            conn.close()  # 正常 FIN 关闭，不发 RST
            assert _wait_until(lambda: client.aborted), \
                "FIN 关闭后应置 aborted"
            assert _wait_until(lambda: not client.th.is_alive()), \
                "FIN 关闭后读线程应退出"
            assert any(j.get("msg_type") == "aborted" for j in received), \
                f"FIN 关闭也应发出 aborted 通知，实际收到: {received}"
        finally:
            srv.close()
