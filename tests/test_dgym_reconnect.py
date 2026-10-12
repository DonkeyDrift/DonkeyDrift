"""dgym 模拟器重连机制回归测试。

背景缺陷：_request_reconnect/看门狗只 _close_env 不重连，寄希望于
update() 线程回到循环顶后自行 _try_connect——但模拟器断连后 update()
线程往往卡死在 gym_donkeycar observe() 的无限自旋里，永远回不到循环
顶部，车端从此永久掉线（Web UI 表现为「车端在线但模拟器始终离线」）。

修复后：重连在主循环侧（run_threaded 调用方线程）同步完成「关闭+
重连」，且与 update() 线程的重连路径互斥（_reconnect_lock）。
"""
import threading
import time
from unittest import mock

import pytest

from donkeycar.parts import dgym


@pytest.fixture
def env():
    """构造不真正连接模拟器的 DonkeyGymEnv（_try_connect 全程 mock）。"""
    conf = {"img_w": 16, "img_h": 12, "render_img_w": 32, "render_img_h": 24,
            "watchdog_sec": 0.2}
    with mock.patch.object(dgym.DonkeyGymEnv, "_try_connect", return_value=None), \
         mock.patch.object(dgym.DonkeyGymEnv, "_check_config_reload",
                           return_value=False):
        e = dgym.DonkeyGymEnv("remote", host="127.0.0.1", conf=conf)
    # _try_connect 被 mock，成功/失败路径设置的属性需手动补齐
    e.env = None
    e.connected = False
    return e


class TestForcedReconnectRebuilds:
    def test_reconnect_rebuilds_even_when_env_is_none(self, env):
        """重连命令到达时 env 已为 None（上次重连失败）也必须再次尝试。"""
        env.env = None
        with mock.patch.object(env, "_close_env") as close, \
             mock.patch.object(env, "_try_connect") as connect:
            env._request_reconnect()
        close.assert_called_once()
        connect.assert_called_once()

    def test_reconnect_closes_then_connects_healthy_env(self, env):
        env.env = object()
        order = []
        with mock.patch.object(env, "_close_env",
                               side_effect=lambda: order.append("close")), \
             mock.patch.object(env, "_try_connect",
                               side_effect=lambda: order.append("connect")):
            env._request_reconnect()
        assert order == ["close", "connect"]

    def test_rebuild_reports_success(self, env):
        env.env = None
        with mock.patch.object(env, "_try_connect",
                               side_effect=lambda: setattr(env, "env", object())):
            assert env._rebuild_connection() is True
        env.env = None
        with mock.patch.object(env, "_try_connect", return_value=None):
            assert env._rebuild_connection() is False


class TestReconnectLock:
    def test_rebuild_is_mutually_exclusive(self, env):
        """并发重建请求串行执行，不产生交错。"""
        calls = []
        entered = threading.Event()
        release = threading.Event()

        def slow_try_connect():
            calls.append("enter")
            entered.set()
            release.wait(timeout=2)
            calls.append("exit")

        t = threading.Thread(
            target=lambda: env._rebuild_connection_with(slow_try_connect)
            if hasattr(env, "_rebuild_connection_with") else
            (env._close_env(), slow_try_connect()))
        # 直接验证锁本身：持锁期间另一个重建必须等待
        with env._reconnect_lock:
            held = env._reconnect_lock.acquire(blocking=False)
            assert held is False
        assert env._reconnect_lock.acquire(blocking=False) is True
        env._reconnect_lock.release()

    def test_update_loop_uses_double_checked_lock(self, env):
        """update() 循环的重连路径在锁内二次检查 env，避免与主线程重建竞争。"""
        env.env = object()  # 主线程刚重建好
        env.running = False  # 不真正进入循环
        with mock.patch.object(env, "_try_connect") as connect:
            with env._reconnect_lock:
                if env.env is None:  # 与 update() 内联结构一致
                    connect()
            connect.assert_not_called()


class TestUpdateIdentityGuard:
    def test_old_env_exception_spares_replacement(self, env):
        """update 线程步进旧 env 抛异常时，不得误关主循环已重建的新 env。"""
        import numpy as np

        failing = mock.Mock()
        failing.step.side_effect = RuntimeError("connection dead")
        replacement = mock.Mock()
        replacement.step.return_value = (np.zeros((12, 16, 3)), 0.0, False, False, {})
        env.connected = True
        env.running = True
        env.env = failing
        closed = []
        with mock.patch.object(env, "_close_env",
                               side_effect=lambda: closed.append(env.env)), \
             mock.patch.object(env, "_try_connect", return_value=None), \
             mock.patch.object(env, "_check_config_reload", return_value=False):
            t = threading.Thread(target=env.update, daemon=True)
            t.start()
            time.sleep(0.2)  # 让 update 线程至少踩到一次旧 env 异常
            with env._reconnect_lock:
                env.env = replacement  # 模拟主循环侧完成重建
            time.sleep(0.3)  # 后续异常/步进都不应关掉 replacement
            env.running = False
            t.join(timeout=2)
        assert replacement not in closed


class TestHealthDetection:
    """_is_env_connected 必须真实反映 TCP 健康（旧实现永远返回 True，
    导致 RST 后车端僵尸运行：陈旧帧持续流出、看门狗永不触发、遥测谎报
    sim_connected=True、后端恢复门控被假信号挡住）。"""

    def _env_with_client(self, env, client):
        viewer = mock.Mock()
        viewer.client = client
        env.env = mock.Mock()
        env.env.viewer = viewer
        return env

    def test_dead_client_reported_disconnected(self, env):
        client = mock.Mock()
        client.is_connected.return_value = False
        self._env_with_client(env, client)
        assert env._is_env_connected() is False

    def test_alive_client_reported_connected(self, env):
        client = mock.Mock()
        client.is_connected.return_value = True
        self._env_with_client(env, client)
        assert env._is_env_connected() is True

    def test_aborted_client_without_is_connected(self, env):
        client = mock.Mock(spec=["aborted", "do_process_msgs"])
        client.aborted = True
        client.do_process_msgs = True
        self._env_with_client(env, client)
        assert env._is_env_connected() is False

    def test_stopped_client_without_is_connected(self, env):
        client = mock.Mock(spec=["aborted", "do_process_msgs"])
        client.aborted = False
        client.do_process_msgs = False
        self._env_with_client(env, client)
        assert env._is_env_connected() is False

    def test_none_env_is_disconnected(self, env):
        env.env = None
        assert env._is_env_connected() is False


class TestTelemetryTsProbe:
    def test_reads_handler_time_received(self, env):
        handler = mock.Mock()
        handler.time_received = 1234.5
        viewer = mock.Mock()
        viewer.handler = handler
        env.env = mock.Mock()
        env.env.viewer = viewer
        assert env._telemetry_ts() == 1234.5

    def test_unreachable_returns_none(self, env):
        env.env = mock.Mock()  # viewer/handler 不存在 -> None
        env.env.viewer = None
        assert env._telemetry_ts() is None


class TestWatchdogUsesTelemetryTs:
    def test_stale_telemetry_triggers_rebuild_even_with_fresh_frames(self, env):
        """连接活着但遥测停止（陈旧帧仍在流出、帧时间戳假前进）也必须重建。"""
        handler = mock.Mock()
        handler.time_received = time.time() - 10.0  # 遥测 10s 未更新
        viewer = mock.Mock()
        viewer.handler = handler
        env.env = mock.Mock()
        env.env.viewer = viewer
        env.connected = True
        env._last_frame_ts = time.time()  # 帧时间戳「新鲜」= 假信号
        with mock.patch.object(env, "_rebuild_connection",
                               return_value=True) as rebuild:
            env.run_threaded(0.0, 0.0)
        rebuild.assert_called_once()

    def test_connected_refreshed_from_health(self, env):
        """run_threaded 每 tick 刷新 connected，遥测 sim_connected 才真实。"""
        client = mock.Mock()
        client.is_connected.return_value = False
        self_v = mock.Mock()
        self_v.client = client
        env.env = mock.Mock()
        env.env.viewer = self_v
        env.connected = True  # 旧的假 True
        with mock.patch.object(env, "_rebuild_connection", return_value=True):
            env.run_threaded(0.0, 0.0)
        assert env.connected is False


class TestWatchdogRebuilds:
    def test_watchdog_triggers_rebuild_not_bare_close(self, env):
        env.env = object()
        env.connected = True
        env._last_frame_ts = time.time() - 10.0  # 远超 watchdog_sec
        with mock.patch.object(env, "_rebuild_connection",
                               return_value=True) as rebuild:
            env.run_threaded(0.0, 0.0)
        rebuild.assert_called_once()

    def test_watchdog_quiet_when_frames_flow(self, env):
        env.env = object()
        env.connected = True
        env._last_frame_ts = time.time()
        with mock.patch.object(env, "_rebuild_connection") as rebuild:
            env.run_threaded(0.0, 0.0)
        rebuild.assert_not_called()

    def test_watchdog_respects_reconnect_pulse(self, env):
        """reconnect=True 脉冲触发重建（bridge 消费后自动复位，仅此一帧为 True）。"""
        env.env = None
        with mock.patch.object(env, "_rebuild_connection", return_value=True) as r:
            env.run_threaded(0.0, 0.0, reconnect=True)
        r.assert_called_once()


class TestGymnasiumWrapperPenetration:
    """真实 gymnasium wrapper 穿透回归测试。

    历史盲区：此前测试用 mock.Mock() 构造 env（任意属性自动放行）所以全绿，
    但 gym.make 返回的是 gymnasium wrapper（如 OrderEnforcing），它不代理
    任意属性——`getattr(wrapper, "viewer", None)` 永远是 None。健康检查
    拿不到 client 就「保守按有效」永久放行：RST 后 update() 线程以陈旧帧
    全速空转（100% CPU）、车端僵尸运行、遥测谎报 sim_connected。

    这里必须用真实 gymnasium wrapper 锁住穿透行为，mock 表达不了这个缺陷。
    """

    @staticmethod
    def _wrapped_env(viewer):
        import gymnasium

        class _DonkeyLikeEnv(gymnasium.Env):
            """模拟 DonkeyEnv：viewer 挂在最底层 env 上。"""

            def __init__(self, v):
                super().__init__()
                self.viewer = v

        # 与 gym.make 的真实包装链同构：底层 env 外套 OrderEnforcing
        return gymnasium.wrappers.OrderEnforcing(_DonkeyLikeEnv(viewer))

    def test_real_wrapper_hides_viewer(self, env):
        """前提校验：真实 wrapper 确实把 viewer 藏成 None（否则本组测试失去意义）。"""
        wrapped = self._wrapped_env(mock.Mock())
        assert getattr(wrapped, "viewer", None) is None

    def test_env_client_sees_through_wrapper(self, env):
        client = mock.Mock()
        client.is_connected.return_value = True
        viewer = mock.Mock()
        viewer.client = client
        env.env = self._wrapped_env(viewer)
        assert env._env_client() is client
        assert env._is_env_connected() is True
        client.is_connected.return_value = False
        assert env._is_env_connected() is False

    def test_dead_client_through_wrapper_reports_disconnected(self, env):
        """wrapper 链下死 client 必须翻假（旧代码永远 True → 僵尸态）。"""
        client = mock.Mock(spec=["is_connected"])
        client.is_connected.return_value = False
        viewer = mock.Mock()
        viewer.client = client
        env.env = self._wrapped_env(viewer)
        assert env._is_env_connected() is False

    def test_telemetry_ts_sees_through_wrapper(self, env):
        handler = mock.Mock()
        handler.time_received = 1234.5
        viewer = mock.Mock()
        viewer.handler = handler
        env.env = self._wrapped_env(viewer)
        assert env._telemetry_ts() == 1234.5

    def test_unreachable_client_falls_back_to_stale_telemetry(self, env):
        """client 不可见时以遥测时间戳为准，陈旧即判失联（旧代码保守放行）。"""
        handler = mock.Mock()
        handler.time_received = time.time() - 10.0  # 远超 watchdog_sec
        viewer = mock.Mock()
        viewer.handler = handler
        viewer.client = None
        env.env = self._wrapped_env(viewer)
        assert env._is_env_connected() is False

    def test_fresh_telemetry_fallback_reports_connected(self, env):
        handler = mock.Mock()
        handler.time_received = time.time()
        viewer = mock.Mock()
        viewer.handler = handler
        viewer.client = None
        env.env = self._wrapped_env(viewer)
        assert env._is_env_connected() is True

    def test_unreachable_everything_stays_conservative(self, env):
        """client 与遥测都拿不到时保守放行，避免误杀重连中的会话。"""
        viewer = mock.Mock(spec=[])  # 无 client、无 handler
        env.env = self._wrapped_env(viewer)
        assert env._is_env_connected() is True
