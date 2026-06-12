"""
Tests for DonkeyGymEnv simulator connection resilience.

验证当底层模拟器连接断开时，DonkeyGymEnv 能够捕获异常、
关闭当前环境并在后台持续尝试重连，而不是让 update() 线程崩溃。
"""

import threading
import time
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from donkeycar.parts.dgym import DonkeyGymEnv


class FakeEnv:
    """A fake gym env that raises after N successful steps."""

    def __init__(self, fail_after=3):
        self.fail_after = fail_after
        self.step_count = 0
        self.closed = False

    def reset(self):
        return np.zeros((120, 160, 3), dtype=np.uint8), {}

    def step(self, action):
        self.step_count += 1
        if self.step_count > self.fail_after:
            raise ConnectionResetError("Sim connection lost")
        obs = np.zeros((120, 160, 3), dtype=np.uint8)
        return obs, 0.0, False, False, {}

    def close(self):
        self.closed = True


@pytest.fixture
def mock_gym_make():
    """Patch gym.make so we can inject FakeEnv instances."""
    with patch("donkeycar.parts.dgym.gym.make") as m:
        yield m


def test_update_survives_step_exception_and_reconnects(mock_gym_make):
    """
    模拟 step() 在运行一段时间后抛出异常（如 TCP 断开）。
    期望 DonkeyGymEnv.update() 捕获异常、关闭 env，然后继续循环重连。
    """
    # 第一个 FakeEnv 在 3 步后失败
    fake_env_1 = FakeEnv(fail_after=3)
    # 第二个 FakeEnv 永不失败（用于重连）
    fake_env_2 = FakeEnv(fail_after=9999)

    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return fake_env_1
        return fake_env_2

    mock_gym_make.side_effect = side_effect

    # 使用 remote 模式，跳过本地可执行文件检查
    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )

    # 启动 update 线程
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    # 等待 update 线程运行足够长的时间：
    # - 前几步正常（约 0ms）
    # - 第 4 步触发异常
    # - 异常后关闭 env、sleep 1s、重连到 fake_env_2
    # - 再给 fake_env_2 几步运行时间
    time.sleep(2.0)

    # 验证第一个 env 已经因为异常被关闭
    assert fake_env_1.closed, "第一个 FakeEnv 应该在异常后被 close()"

    # 验证 gym.make 被调用了两次（初始连接 + 重连）
    assert call_count[0] >= 2, f"期望至少重连一次，实际调用次数: {call_count[0]}"

    # 验证 update 线程仍在运行（没有因为未捕获异常而崩溃）
    assert thread.is_alive(), "update() 线程应该在异常后仍然存活"

    # 清理
    gym_env.shutdown()
    thread.join(timeout=2.0)
    assert not thread.is_alive(), "shutdown 后线程应该退出"


def test_update_sets_env_none_on_step_failure(mock_gym_make):
    """
    验证 step() 抛出异常后，self.env 被设为 None，
    以便下一次循环进入重连逻辑。
    """
    fake_env = FakeEnv(fail_after=1)
    mock_gym_make.return_value = fake_env

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )

    # 启动 update 线程
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    # 等待足够时间让 step 失败并被处理
    time.sleep(0.4)

    # 验证 env 已经被关闭（设为 None）
    assert gym_env.env is None, "异常后 env 应该被设为 None"
    assert gym_env.connected is False, "connected 应该被设为 False"
    assert fake_env.closed, "FakeEnv 应该被 close()"

    # 清理
    gym_env.shutdown()
    thread.join(timeout=2.0)


class FakeClient:
    def __init__(self, connected=True):
        self._connected = connected

    def is_connected(self):
        return self._connected


class FakeViewer:
    def __init__(self, connected=True):
        self.client = FakeClient(connected)


class FakeEnvWithDisconnectedClient(FakeEnv):
    """模拟底层 TCP 已断开但 step() 尚未抛出的 env。"""

    def __init__(self):
        super().__init__(fail_after=9999)
        self.connected = True
        self.viewer = FakeViewer(connected=True)

    def step(self, action):
        # 不抛出异常，但报告连接已断开
        self.step_count += 1
        if not self.connected:
            # 模拟卡住：不再返回新帧
            time.sleep(0.05)
        # 保持 viewer.client.is_connected() 与 self.connected 一致
        self.viewer.client._connected = self.connected
        obs = np.zeros((120, 160, 3), dtype=np.uint8)
        return obs, 0.0, False, False, {}


def test_update_detects_disconnect_and_reconnects(mock_gym_make):
    """
    验证当底层 client.is_connected() 返回 False 时，
    DonkeyGymEnv 能主动关闭 env 并重连。
    """
    fake_env_1 = FakeEnvWithDisconnectedClient()
    fake_env_2 = FakeEnv(fail_after=9999)

    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return fake_env_1
        return fake_env_2

    mock_gym_make.side_effect = side_effect

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )

    # 模拟底层连接在若干步后断开
    def toggle_connection():
        time.sleep(0.15)
        fake_env_1.connected = False

    toggle_thread = threading.Thread(target=toggle_connection, daemon=True)
    toggle_thread.start()

    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    # 等待健康检查检测到断开并重连
    time.sleep(2.0)

    # 第一个 env 应该被关闭
    assert fake_env_1.closed, "底层连接断开后 FakeEnv 应该被 close()"
    # 应该至少重连一次
    assert call_count[0] >= 2, f"期望至少重连一次，实际调用次数: {call_count[0]}"
    # update 线程仍然存活
    assert thread.is_alive(), "update() 线程应该在健康检查后仍然存活"

    gym_env.shutdown()
    thread.join(timeout=2.0)
    assert not thread.is_alive(), "shutdown 后线程应该退出"


def test_run_threaded_reconnect_closes_env(mock_gym_make):
    """验证 run_threaded 收到 reconnect=True 时会关闭当前 env。"""
    fake_env = FakeEnv(fail_after=9999)
    mock_gym_make.return_value = fake_env

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )

    # 通过 run_threaded 请求重连
    gym_env.run_threaded(0.0, 0.0, 0.0, reconnect=True)

    # update 线程会在下一次循环中关闭 env 并重连
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    time.sleep(0.3)

    assert fake_env.closed, "收到重连请求后 env 应该被关闭"
    assert gym_env.env is None, "env 应该被设为 None"

    gym_env.shutdown()
    thread.join(timeout=2.0)
