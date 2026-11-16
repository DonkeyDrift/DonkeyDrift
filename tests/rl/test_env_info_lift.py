"""D0(M2):active_node/total_nodes 提升 + node 法 progress 激活回归。

背景(M2 订单已核事实 1):fork viewer 解析并持有 active_node/total_nodes
(donkey_sim.py:797-799),但 observe() 组装 info 时不含这两个键——M1 的
node 法 progress 是死代码。修复 = env._build_info 从 viewer 属性提升;
本测试守住提升逻辑与 node 法在真实形状 info 上的激活。
"""

import gymnasium as gym
import numpy as np
import pytest

from donkeydrifter.rl.env import DonkeyDriftEnv
from donkeydrifter.rl.rewards import DecomposedRewardWrapper, RewardConfig, reward


class _FakeHandler:
    """镜像真实结构:状态在 handler(DonkeyUnitySimHandler)上。"""

    def __init__(self, active_node=0, total_nodes=1):
        self.active_node = active_node
        self.total_nodes = total_nodes
        self.is_game_over = lambda: False
        self.calc_reward = lambda done: 0.0


class _FakeViewer:
    """壳类 DonkeyUnitySimContoller:仅 handler 委托,无状态。"""

    def __init__(self, active_node=0, total_nodes=1):
        self.handler = _FakeHandler(active_node, total_nodes)


def _make_env(monkeypatch, active_node=None, total_nodes=None):
    """构造不连 sim 的 env(sim down 时安全,见 M1),注入假 viewer。"""
    env = DonkeyDriftEnv(sim_path="remote")
    if active_node is not None:
        viewer = _FakeViewer(active_node, total_nodes)
        monkeypatch.setattr(env, "_sim_viewer", lambda: viewer)
    else:
        monkeypatch.setattr(env, "_sim_viewer", lambda: None)  # viewer 不可达
    return env


def test_lift_none_when_viewer_unreachable(monkeypatch):
    """viewer 不可达(未连接)→ 提升值 None,不伪造 0。"""
    env = _make_env(monkeypatch, None)
    info = env._build_info()
    assert info["active_node"] is None
    assert info["total_nodes"] is None


def test_lift_from_viewer(monkeypatch):
    """viewer 属性被提升进 info(修 M1 死代码)。"""
    env = _make_env(monkeypatch, active_node=42, total_nodes=100)
    info = env._build_info()
    assert info["active_node"] == 42
    assert info["total_nodes"] == 100


def test_node_method_activates_on_real_info_shape():
    """node 法在真实形状 info(含提升后的 node 字段)上激活——M1 回归。"""
    prev = {"pos": (1.0, 0.5, 2.0), "speed": 3.0, "cte": 0.1,
            "vel": (0.0, 0.0, 3.0), "active_node": 41, "total_nodes": 100}
    cur = {"pos": (1.0, 0.5, 3.0), "speed": 3.0, "cte": 0.1,
           "vel": (0.0, 0.0, 3.0), "active_node": 42, "total_nodes": 100}
    total, comps = reward(prev, cur, cfg=RewardConfig())
    assert comps["progress_method"] == "node"
    assert comps["progress"] == pytest.approx(1.0)


def test_node_method_falls_back_without_fields():
    """无 node 字段(M1 死代码期形态)→ 位移法回退,不报错。"""
    prev = {"pos": (1.0, 0.5, 1.0), "speed": 3.0, "cte": 0.1, "vel": (0.0, 0.0, 3.0)}
    cur = {"pos": (1.0, 0.5, 2.0), "speed": 3.0, "cte": 0.1, "vel": (0.0, 0.0, 3.0)}
    _, comps = reward(prev, cur, cfg=RewardConfig())
    assert comps["progress_method"] == "displacement"


def test_node_method_falls_back_on_degenerate_total():
    """total_nodes=1(sim 未发字段时的 viewer 初始值)→ 守卫退回位移法。"""
    prev = {"pos": (1.0, 0.5, 1.0), "speed": 3.0, "cte": 0.1,
            "vel": (0.0, 0.0, 3.0), "active_node": 0, "total_nodes": 1}
    cur = {"pos": (1.0, 0.5, 2.0), "speed": 3.0, "cte": 0.1,
           "vel": (0.0, 0.0, 3.0), "active_node": 0, "total_nodes": 1}
    _, comps = reward(prev, cur, cfg=RewardConfig())
    assert comps["progress_method"] == "displacement"


class _DummyEnv(gym.Env):
    """最小 gym env,驱动 DecomposedRewardWrapper(零 sim)。"""

    action_space = gym.spaces.Box(-1, 1, (2,), np.float32)
    observation_space = gym.spaces.Box(-np.inf, np.inf, (4,), np.float32)
    metadata = {}

    def __init__(self, info_fn):
        self._info_fn = info_fn
        self._i = 0

    def reset(self, *, seed=None, options=None):
        self._i = 0
        return np.zeros(4, np.float32), self._info_fn(0)

    def step(self, action):
        self._i += 1
        return (np.zeros(4, np.float32), 0.5, False, False, self._info_fn(self._i))


def test_wrapper_records_progress_method(monkeypatch):
    """wrapper 链路:info 带 node 字段时 components 记录 node 法(M2 验收点)。"""
    state = {"n": 0}

    def info_fn(i):
        state["n"] += 1
        return {"pos": (0.0, 0.0, float(i)), "speed": 3.0, "cte": 0.0,
                "vel": (0.0, 0.0, 3.0),
                "active_node": 10 + i, "total_nodes": 100}

    dummy = _DummyEnv(info_fn)
    wrapped = DecomposedRewardWrapper(dummy, cfg=RewardConfig())
    wrapped.reset()
    _, rew, _, _, info = wrapped.step(np.zeros(2, np.float32))
    comps = info["reward_components"]
    assert comps["progress_method"] == "node"
    assert comps["progress"] == pytest.approx(1.0)
    assert info["raw_reward"] == 0.5
