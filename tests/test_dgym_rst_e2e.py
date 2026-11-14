"""dgym 全链路 RST 自愈 E2E（假模拟器 + 真实 socket/协议/RST）。

线上「车端僵尸运行」死亡螺旋的完整回归。此前 mock 测试的盲区：mock.Mock
任意属性自动放行，表达不了 gymnasium wrapper 把 viewer 藏成 None 的缺陷；
这里用 gym.make 的真实包装链、真实 TCP、真实 RST 把整条链锁死：

  1. 健康检查必须穿透 gymnasium wrapper 看见底层 client（.unwrapped）；
  2. 对端 RST 后 client 收尾：发出 aborted 通知、socket FD 真正关闭
     （旧代码泄漏悬挂 FD，lsof 可见 CLOSED 僵尸句柄）；
  3. update()/看门狗在 watchdog 内「关闭+重连」，遥测时间戳恢复前进
     （旧代码看门狗永不触发、100% CPU 空转、遥测谎报 sim_connected）。

假模拟器讲最小 sim 协议：连接即发 car_loaded，之后周期发 telemetry/image，
可随时对当前会话发 RST。不接真 DonkeySim：每个新连接都会触发 load_scene，
会扰动用户正在跑的模拟器场景。
"""
import base64
import io
import json
import socket
import struct
import threading
import time

import numpy as np
import pytest
from PIL import Image

from donkeycar.parts import dgym

_TELEMETRY_PERIOD = 0.03


def _b64_png(w=32, h=24):
    buf = io.BytesIO()
    Image.fromarray(np.zeros((h, w, 3), dtype=np.uint8)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _FakeSim:
    """最小 sim 协议假模拟器：car_loaded + 周期 telemetry，可对会话发 RST。"""

    def __init__(self):
        self._telemetry = (
            json.dumps({"msg_type": "telemetry", "image": _b64_png()}) + "\n"
        ).encode()
        self._car_loaded = b'{"msg_type": "car_loaded"}\n'
        self.sessions = 0
        self._stop = False
        self._lock = threading.Lock()
        self._cur = None
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            self.sessions += 1
            with self._lock:
                self._cur = conn
            threading.Thread(target=self._session, args=(conn,), daemon=True).start()

    def _session(self, conn):
        try:
            conn.sendall(self._car_loaded)
            conn.settimeout(_TELEMETRY_PERIOD)
            while not self._stop:
                try:
                    data = conn.recv(65536)
                    if not data:
                        return
                except socket.timeout:
                    pass
                except OSError:
                    return
                conn.sendall(self._telemetry)
        except OSError:
            pass

    def rst_current(self):
        """对当前会话发 RST（SO_LINGER 关闭），模拟模拟器侧强制复位。"""
        with self._lock:
            conn = self._cur
        if conn is None:
            raise AssertionError("假模拟器当前没有会话")
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            struct.pack("ii", 1, 0))
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def close(self):
        self._stop = True
        with self._lock:
            conn = self._cur
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        self._srv.close()


def _wait_until(cond, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def fake_sim():
    sim = _FakeSim()
    yield sim
    sim.close()


def test_rst_self_heals_end_to_end(fake_sim):
    conf = {"img_w": 32, "img_h": 24, "render_img_w": 32, "render_img_h": 24,
            "watchdog_sec": 1.0}
    env = dgym.DonkeyGymEnv("remote", host="127.0.0.1", port=fake_sim.port,
                            env_name="donkey-generated-track-v0", conf=conf)
    # update 线程 = 车端步进线程；run_threaded 线程 = 车辆主循环（看门狗所在）
    update_th = threading.Thread(target=env.update, daemon=True)
    update_th.start()
    stop_loop = threading.Event()

    def vehicle_loop():
        while not stop_loop.is_set():
            env.run_threaded(0.0, 0.0)
            time.sleep(0.05)

    loop_th = threading.Thread(target=vehicle_loop, daemon=True)
    loop_th.start()
    try:
        # 1) 初始连接：真实 wrapper 链下健康检查必须看得见底层 client
        assert env.env is not None, "初始连接应成功"
        import gymnasium
        assert isinstance(env.env, gymnasium.Wrapper), "前提：gym.make 返回 wrapper"
        assert getattr(env.env, "viewer", None) is None, \
            "前提：wrapper 把 viewer 藏成 None（本组测试的意义所在）"
        assert env._env_client() is not None, \
            "必须穿透 gymnasium wrapper 找到底层 client"
        assert env._is_env_connected() is True
        assert _wait_until(lambda: env._telemetry_ts() is not None), \
            "应开始收到遥测"
        ts1 = env._telemetry_ts()
        assert _wait_until(lambda: (env._telemetry_ts() or 0.0) > ts1), \
            "遥测应持续前进"

        for round_no in (1, 2):
            old_client = env._env_client()
            assert old_client is not None
            sessions_before = fake_sim.sessions
            ts_before = env._telemetry_ts() or 0.0

            # 2) RST：模拟器侧强制复位
            fake_sim.rst_current()

            # 3) 自愈：自动重连假模拟器（watchdog_sec=1.0 + 重连）
            assert _wait_until(
                lambda: fake_sim.sessions > sessions_before), \
                f"第 {round_no} 次 RST 后应自动重连假模拟器"
            assert _wait_until(lambda: env._is_env_connected() is True), \
                f"第 {round_no} 次 RST 后健康检查应恢复"
            assert _wait_until(
                lambda: (env._telemetry_ts() or 0.0) > ts_before), \
                f"第 {round_no} 次 RST 后遥测应恢复前进"
            # 重建窗口内 connected 暂为 False 是正确语义，等它收敛
            assert _wait_until(lambda: env.connected, timeout=5.0), \
                f"第 {round_no} 次 RST 后遥测 sim_connected 应恢复为真"
            # 重建必须一次性完成：不许把刚建好的健康连接再拆掉重建（重建风暴）
            time.sleep(0.5)
            assert fake_sim.sessions == sessions_before + 1, \
                (f"第 {round_no} 次 RST 后应恰好重建一次，"
                 f"实际新增 {fake_sim.sessions - sessions_before} 个会话")
            # 旧 client 的 socket 必须被 aborted 通知 → stop() 真正关闭
            assert _wait_until(lambda: old_client.s.fileno() == -1, timeout=5.0), \
                f"第 {round_no} 次 RST 后旧 client socket FD 应关闭（曾泄漏悬挂 FD）"
    finally:
        stop_loop.set()
        env.running = False
        update_th.join(timeout=3)
        loop_th.join(timeout=3)
        env.shutdown()
