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

pytest.importorskip("gym_donkeycar")

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


def _wait_until(predicate, timeout=3.0, interval=0.05):
    """轮询等待后台线程达成的状态（重建由专用线程异步完成，不能同步断言）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


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
def test_run_threaded_reconnect_rebuilds_in_background(mock_gym_make):
    """run_threaded(reconnect=True) 只投递请求立即返回，后台线程完成「关闭+重建」。

    重建（close+gym.make+reset，含模拟器 load_scene）耗时数秒，同步执行会
    卡住车辆主循环、转向/油门断供。契约：run_threaded 零阻塞、旧 env 被
    close、新 env 接管、connected 恢复 True。
    """
    old_env = FakeEnv(fail_after=9999)
    new_env = FakeEnv(fail_after=9999)
    made = [old_env, new_env]
    mock_gym_make.side_effect = lambda *a, **k: made.pop(0)

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )
    assert gym_env.env is old_env

    t0 = time.perf_counter()
    gym_env.run_threaded(0.0, 0.0, 0.0, reconnect=True)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"run_threaded 应立即返回，实际耗时 {elapsed:.3f}s"

    assert _wait_until(lambda: gym_env.env is new_env), "后台线程应完成重建并切换到新 env"
    assert old_env.closed, "重建时应关闭旧 env"
    assert gym_env.connected is True, "新连接建立后 connected 应为 True"

    gym_env.shutdown()


def test_run_threaded_watchdog_rebuilds_when_stale(mock_gym_make):
    """看门狗：遥测停更超窗时投递后台重建（关闭旧 env、换新 env），主循环不阻塞。

    旧契约「看门狗只 _close_env 置 None」会让车端永久掉线（update 线程常已
    卡死，没人重连）；现行契约是「关闭+重连」由后台线程一次完成。
    """
    old_env = FakeEnv(fail_after=9999)
    new_env = FakeEnv(fail_after=9999)
    made = [old_env, new_env]
    mock_gym_make.side_effect = lambda *a, **k: made.pop(0)

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160, "watchdog_sec": 5.0},
    )
    assert gym_env.env is old_env
    assert gym_env.connected is True

    # 伪造「长时间无新帧」：把看门狗时间戳拨到很久以前
    gym_env._last_frame_ts = time.time() - 10.0

    t0 = time.perf_counter()
    gym_env.run_threaded(0.0, 0.0, 0.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"看门狗只投递请求，run_threaded 不应被重建阻塞，实际 {elapsed:.3f}s"

    assert _wait_until(lambda: gym_env.env is new_env), "后台线程应完成重建并切换到新 env"
    assert old_env.closed, "重建时应关闭旧 env"
    assert gym_env.connected is True

    gym_env.shutdown()


def test_update_refreshes_last_frame_ts_on_successful_step(mock_gym_make):
    """验证 update() 每次成功 step 后都会刷新看门狗时间戳。"""
    fake_env = FakeEnv(fail_after=9999)
    mock_gym_make.return_value = fake_env

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160, "watchdog_sec": 5.0},
    )

    before = gym_env._last_frame_ts
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()
    time.sleep(0.4)

    assert gym_env._last_frame_ts > before, "成功 step 后看门狗时间戳应被刷新"

    gym_env.shutdown()
    thread.join(timeout=2.0)


class WedgedEnv(FakeEnv):
    """模拟 observe() 永久自旋：若干步后 step() 永不返回。"""

    def step(self, action):
        self.step_count += 1
        if self.step_count > 2:
            while True:
                time.sleep(0.05)
        obs = np.zeros((120, 160, 3), dtype=np.uint8)
        return obs, 0.0, False, False, {}


def test_watchdog_rebuilds_while_update_thread_wedged(mock_gym_make):
    """
    模拟器断连且 step() 卡死（gym_donkeycar observe 自旋）时，
    后台重建线程仍能换掉死 env：卡死的 update 线程永远回不到重连分支，
    看门狗投递的重建是唯一能救活连接的路径，且不阻塞 Vehicle 主循环。
    """
    wedged_env = WedgedEnv(fail_after=10**12)
    new_env = FakeEnv(fail_after=9999)
    made = [wedged_env, new_env]
    mock_gym_make.side_effect = lambda *a, **k: made.pop(0)

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )
    gym_env._watchdog_sec = 0.2

    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    # 等 update 线程进入卡死的 step
    time.sleep(0.3)

    # 模拟 Vehicle 主循环周期性调用 run_threaded
    for _ in range(40):
        gym_env.run_threaded(0.0, 0.0)
        if gym_env.env is new_env:
            break
        time.sleep(0.05)

    assert wedged_env.closed, "后台重建应 close() 卡死的 env"
    assert gym_env.env is new_env, "重建后应由新 env 接管"
    assert gym_env.connected is True, "新连接建立后 connected 应回到 True"

    gym_env.shutdown()


def test_watchdog_does_not_fire_on_healthy_env(mock_gym_make):
    """帧持续更新时看门狗不应误触发。"""
    fake_env = FakeEnv(fail_after=10**12)
    mock_gym_make.return_value = fake_env

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )
    gym_env._watchdog_sec = 0.3

    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    for _ in range(20):
        gym_env.run_threaded(0.0, 0.0)
        time.sleep(0.05)

    assert gym_env.env is fake_env, "健康 env 不应被看门狗关闭"
    assert not fake_env.closed

    gym_env.shutdown()
    thread.join(timeout=2.0)
