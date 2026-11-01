"""D1:DonkeyDrift RL 环境封装(gymnasium API)。

设计边界(工作订单 2026-11-01):
- 构造路径与 templates 完全同款:``donkeydrifter.parts.dgym.DonkeyGymEnv``
  (内部 gym.make → gym_donkeycar DonkeyEnv → SimClient),**不**拉起
  donkeycar Vehicle;
- 断线容忍**复用** dgym 既有看门狗/后台重建线程(本模块零重写),只做
  状态暴露;模板里由 Vehicle 框架承担的两条驱动线(``update()`` 线程步进
  sim + ``run_threaded()`` 轮询喂动作/触发看门狗)由本模块补齐;
- reward 一律放 wrapper 层(rewards.DecomposedRewardWrapper),本环境
  step 的 reward 返回 sim 原始 reward(info['raw_reward'] 对账)。

与 sim 的同步语义(诚实声明):
- dgym 把 ``frame_skip`` 钉死为 1(dgym.py:_try_connect),本环境的
  ``frame_skip`` 是 **wrapper 级 action repeat**:每步对同一动作连续取
  frame_skip 帧新遥测(默认 1);
- 异步协议固有控制死时间:本步发出的动作由 sim 下一次遥测帧消费,
  观测相对动作存在 ≥1 帧滞后;state obs 含上一步动作供策略推断;
- 步进对齐用 sim 侧遥测计数 ``frame_id``(次选 cam.frame 对象身份),
  每步等待「新帧到达」——n 条 control ↔ n 帧遥测由此构造性成立,
  等待超时则标 info['rl/stale'](不抛异常,连接健康由看门狗负责)。

reset 语义:
- 默认走订单指定通道 ``reset_to_nearest``(就近复位,无随机出生);
- 可选随机出生(上报过的矛盾点,见 rl-m1-report):``reset(options=
  {'spawn_cfg': {...}})`` 经同一 SimClient 直发 ``reset_car``+字段
  (node_index/lateral_offset/heading_noise/seed,sdsim 协议),sim 二进制
  是否支持由 smoke 探针实测;不用时不发任何扩展字段。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
import numpy as np

from donkeydrifter.parts.dgym import DonkeyGymEnv

logger = logging.getLogger(__name__)

__all__ = ["DonkeyDriftEnv"]

# state obs 的分量与缩放(声明式,单测可校验维度;fork state_obs 的 cte/2、
# speed/10、gyro_z/90 口径沿用)
_STATE_SCALES = {
    "cte": 2.0,
    "speed": 10.0,
    "forward_vel": 10.0,
    "vel": 5.0,
    "gyro": 90.0,      # deg/s
    "accel": 10.0,     # m/s²
    "pos_xy": 50.0,    # m
}
STATE_OBS_DIM = 16  # 3+3+3+3+2+2

_DEFAULT_SIM_FPS = 20.0  # sdsim 家族遥测节拍(见 dgym.py 分辨率解耦注释)


class DonkeyDriftEnv(gym.Env):
    """DonkeyDrift 模拟器的 gymnasium 封装(state / pixel 双 obs 模式)。"""

    metadata = {"render_modes": []}

    def __init__(
        self,
        sim_host: str = "127.0.0.1",
        sim_port: int = 9091,
        env_name: str = "donkey-generated-track-v0",
        sim_path: str = "remote",
        conf: Optional[Dict[str, Any]] = None,
        obs_mode: str = "state",
        img_enc: Optional[str] = None,
        frame_skip: int = 1,
        cte_limit: float = 2.0,
        max_episode_steps: Optional[int] = None,
        connect_timeout_s: float = 30.0,
        frame_wait_timeout_s: float = 1.0,
        name: str = "rl-car-0",
    ):
        if obs_mode not in ("state", "pixel"):
            raise ValueError(f"obs_mode 须为 state|pixel,得到 {obs_mode!r}")
        self.obs_mode = obs_mode
        self.frame_skip = max(1, int(frame_skip))
        self.cte_limit = float(cte_limit)
        self.max_episode_steps = max_episode_steps
        self.connect_timeout_s = float(connect_timeout_s)
        self.frame_wait_timeout_s = float(frame_wait_timeout_s)
        self.sim_host = sim_host
        self.sim_port = int(sim_port)

        sim_conf = dict(conf or {})
        sim_conf.setdefault("img_w", 160)
        sim_conf.setdefault("img_h", 120)
        # state 模式默认申请零图像遥测(img_enc=none):sim 支持时省掉
        # JPEG 编码+解码的全部开销(≥3 倍遥测吞吐,见 sdsim 无图模式);
        # 不支持时 sim 仍发图,客户端照常解码,只是无收益、无副作用。
        if obs_mode == "state":
            effective_enc = img_enc or "none"
        else:
            effective_enc = img_enc
        if effective_enc:
            cam_conf = dict(sim_conf.get("cam_config") or {})
            cam_conf["img_enc"] = effective_enc
            sim_conf["cam_config"] = cam_conf
        sim_conf.setdefault("watchdog_sec", 5.0)

        self._cam = DonkeyGymEnv(
            sim_path,
            host=sim_host,
            port=self.sim_port,
            env_name=env_name,
            conf=sim_conf,
            record_location=True,
            record_gyroaccel=True,
            record_velocity=True,
            record_lidar=False,
            output_preview=False,
        )
        # car_name/racer 身份:多开时用 name 区分(conf 透传)
        self._cam_name = name

        # 模板里 Vehicle 承担的步进线程:update() 内部循环 step sim、推帧、
        # 跑健康检查;断线时自动按 1s 周期重连(dgym 既有逻辑,零重写)
        self._update_thread = threading.Thread(
            target=self._cam.update, name="ddrl-sim-update", daemon=True)
        self._update_thread.start()

        self._step_count = 0
        self._prev_action = (0.0, 0.0)
        self._closed = False

        img_h = int(sim_conf["img_h"])
        img_w = int(sim_conf["img_w"])
        if obs_mode == "state":
            self.observation_space = gym.spaces.Box(
                low=np.float32(-np.inf), high=np.float32(np.inf),
                shape=(STATE_OBS_DIM,), dtype=np.float32)
        else:
            self.observation_space = gym.spaces.Box(
                0, 255, shape=(img_h, img_w, 3), dtype=np.uint8)
        self.action_space = gym.spaces.Box(
            low=np.array([-1.0, -1.0], dtype=np.float32),
            high=np.array([1.0, 1.0], dtype=np.float32),
            dtype=np.float32)

    # ------------------------------------------------------------------
    # 底层通道
    # ------------------------------------------------------------------

    def _sim_client(self):
        """底层 SimClient(穿透 gymnasium wrapper;dgym 同款访问器)。"""
        return getattr(self._cam, "_env_client", lambda: None)()

    def _sim_viewer(self):
        """底层 DonkeyUnitySimContoller(done/raw_reward 的权威来源)。"""
        env = getattr(self._cam, "env", None)
        if env is None:
            return None
        try:
            raw = env.unwrapped if isinstance(env, gym.Wrapper) else env
            return getattr(raw, "viewer", None)
        except Exception:
            return None

    def _send_sim_message(self, msg: Dict[str, Any]) -> bool:
        """直发一条消息给 sim(SimClient.send_now 收 dict,json.dumps)。

        与 dgym.request_reset_to_nearest 发的是同一条通道(SimClient);
        绕开 part 方法只为合并「就近复位/随机出生」两条路径并压日志。
        """
        client = self._sim_client()
        if client is None:
            return False
        try:
            client.send_now(msg)
            return True
        except Exception as e:  # socket 已死等:交给看门狗重建
            logger.warning("sim 消息发送失败(%s): %s", msg.get("msg_type"), e)
            return False

    @property
    def sim_connected(self) -> bool:
        """当前 TCP 健康状态(与 dgym 看门狗口径一致)。"""
        return bool(getattr(self._cam, "connected", False))

    # ------------------------------------------------------------------
    # 帧同步
    # ------------------------------------------------------------------

    def _frame_token(self) -> Any:
        """当前遥测帧令牌:优先 sim 侧 frame_id,缺省退 cam.frame 身份。"""
        info = getattr(self._cam, "info", {}) or {}
        fid = info.get("frame_id")
        if fid is not None:
            return ("fid", fid)
        return ("obj", id(getattr(self._cam, "frame", None)))

    def _wait_new_frame(self, token: Any, timeout_s: float) -> bool:
        """阻塞直到遥测帧令牌变化;超时 False(调步进方标记 stale)。

        sim 20fps 节拍下正常等待 ~50ms;超时意味着遥测断流,连接级
        恢复是 dgym 看门狗的职责,这里只如实上报。
        """
        kind = token[0]
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            cur = self._frame_token()
            if cur[0] == kind and cur[1] != token[1]:
                return True
            if cur[0] != kind:
                # frame_id 从有到无(重建中):等身份通道恢复再判
                if cur[0] == "obj" and cur[1] != id(getattr(self._cam, "frame", None)):
                    return True
            time.sleep(0.002)
        return False

    # ------------------------------------------------------------------
    # 观测
    # ------------------------------------------------------------------

    def _build_obs(self) -> Tuple[np.ndarray, list]:
        """按 obs_mode 组观测;返回 (obs, defects)。坏字段记 defects 补零。"""
        info = getattr(self._cam, "info", {}) or {}
        defects: list = []
        if self.obs_mode == "pixel":
            return np.asarray(self._cam.frame, dtype=np.uint8), defects

        def num(key, idx=None):
            v = info.get(key)
            if idx is not None:
                try:
                    v = v[idx]
                except (TypeError, IndexError, KeyError):
                    return None
            try:
                x = float(v)
            except (TypeError, ValueError):
                return None
            if math.isnan(x) or math.isinf(x):
                return None
            return x

        vel = [num("vel", i) for i in range(3)]
        gyro = [num("gyro", i) for i in range(3)]
        accel = [num("accel", i) for i in range(3)]
        vec = [
            num("cte"), num("speed"), num("forward_vel"),
            *vel, *gyro, *accel,
            num("pos", 0), num("pos", 1),
            self._prev_action[0], self._prev_action[1],
        ]
        out = np.zeros(STATE_OBS_DIM, dtype=np.float32)
        for i, x in enumerate(vec):
            if x is None:
                defects.append(f"idx{i}")
            else:
                out[i] = x
        # 缩放(下标对齐 vec;动作两项不缩放)
        out[0] /= _STATE_SCALES["cte"]
        out[1] /= _STATE_SCALES["speed"]
        out[2] /= _STATE_SCALES["forward_vel"]
        out[3:6] /= _STATE_SCALES["vel"]
        out[6:9] /= _STATE_SCALES["gyro"]
        out[9:12] /= _STATE_SCALES["accel"]
        out[12:14] /= _STATE_SCALES["pos_xy"]
        return out, defects

    # ------------------------------------------------------------------
    # gymnasium API
    # ------------------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        """重置 episode。

        - 默认(无 options):订单指定通道 ``reset_to_nearest``——就近复位,
          无随机出生(M1 口径);
        - 可选随机出生:``options={'spawn_cfg': {...}}``(或 {'spawn': True})
          时直发 ``reset_car``+可选字段(seed/node_index/lateral_offset/
          heading_noise),与 gym_donkeycar fork 的 send_reset_car 同款消息;
          sim 支持性由 smoke 探针实测,不支持时 sim 按普通复位处理;
        - ``seed``:本环境无内部 RNG;仅当走随机出生路径时透传给 sim 作
          复现种子(gymnasium seed 语义的超集用法,已在报告声明)。
        """
        super().reset(seed=seed)
        if self._closed:
            raise RuntimeError("env 已关闭,不能 reset")
        self._wait_connected(self.connect_timeout_s)

        options = dict(options or {})
        spawn_cfg = options.get("spawn_cfg")
        want_spawn = bool(spawn_cfg) or bool(options.get("spawn"))
        t0 = time.perf_counter()

        pre_pos = tuple(getattr(self._cam, "info", {}).get("pos", (0.0, 0.0, 0.0))[:2])
        token = self._frame_token()

        if want_spawn:
            msg: Dict[str, Any] = {"msg_type": "reset_car"}
            if isinstance(spawn_cfg, dict):
                msg.update(spawn_cfg)
            if seed is not None:
                msg["seed"] = int(seed)
            sent = self._send_sim_message(msg)
            mode = "reset_car+spawn" if sent else "send_failed"
        else:
            sent = self._send_sim_message({"msg_type": "reset_to_nearest"})
            mode = "reset_to_nearest" if sent else "send_failed"

        # 等命令被 sim 消费(≥1 新遥测帧),再等位姿跳变(就近复位是瞬移;
        # 车本来就在赛道中央时无跳变,按 2s 上限收口并如实标记)
        self._wait_new_frame(token, min(2.0, self.connect_timeout_s))
        detected = self._wait_pose_jump(pre_pos, timeout_s=2.0)
        elapsed = time.perf_counter() - t0

        self._step_count = 0
        self._prev_action = (0.0, 0.0)
        obs, defects = self._build_obs()
        info = self._build_info()
        info["rl/reset_elapsed_s"] = elapsed
        info["rl/reset_mode"] = mode
        info["rl/reset_detected_move"] = bool(detected)
        if defects:
            info["rl/obs_defects"] = defects
        return obs, info

    def _wait_pose_jump(self, pre_xy: Tuple[float, float], timeout_s: float) -> bool:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            pos = getattr(self._cam, "info", {}).get("pos", (0.0, 0.0, 0.0))
            try:
                if math.dist((float(pos[0]), float(pos[1])), pre_xy) > 0.05:
                    return True
            except (TypeError, ValueError):
                pass
            time.sleep(0.01)
        return False

    def _wait_connected(self, timeout_s: float) -> None:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            if self.sim_connected and self._frame_token()[0] == "fid":
                return
            time.sleep(0.1)
        raise ConnectionError(
            f"sim {self.sim_host}:{self.sim_port} 在 {timeout_s:.0f}s 内未建立"
            "健康连接(遥测无 frame_id);请确认模拟器已启动")

    def step(self, action) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        if self._closed:
            raise RuntimeError("env 已关闭,不能 step")
        a = np.clip(np.asarray(action, dtype=np.float64).ravel()[:2], -1.0, 1.0)
        steer, throttle = float(a[0]), float(a[1])
        self._prev_action = (steer, throttle)

        stale = False
        t0 = time.perf_counter()
        for _ in range(self.frame_skip):
            token = self._frame_token()
            # run_threaded:喂动作 + 触发看门狗/重连 + 返回最新帧(dgym 既有)
            self._cam.run_threaded(steer, throttle, 0.0)
            if not self._wait_new_frame(token, self.frame_wait_timeout_s):
                stale = True
        step_elapsed = time.perf_counter() - t0
        self._step_count += 1

        viewer = self._sim_viewer()
        terminated = bool(viewer.is_game_over()) if viewer is not None else False
        raw_reward = float(viewer.calc_reward(terminated)) if viewer is not None else 0.0

        obs, defects = self._build_obs()
        info = self._build_info()
        info["raw_reward"] = raw_reward
        info["rl/stale"] = stale
        info["dt_s"] = step_elapsed
        info["rl/step_elapsed_s"] = step_elapsed
        if defects:
            info["rl/obs_defects"] = defects

        # 客户端侧终止(与 sim terminated 分开的第二个 flag)
        truncated = False
        reason = None
        cte = getattr(self._cam, "info", {}).get("cte")
        try:
            if cte is not None and abs(float(cte)) > self.cte_limit:
                truncated, reason = True, "cte_limit"
        except (TypeError, ValueError):
            pass
        if (not truncated and self.max_episode_steps is not None
                and self._step_count >= self.max_episode_steps):
            truncated, reason = True, "step_budget"
        if reason:
            info["rl/trunc_reason"] = reason
        return obs, raw_reward, terminated, truncated, info

    def _build_info(self) -> Dict[str, Any]:
        """sim 遥测原样透传 + rl/ 前缀扩展键(键名不与 sim 字段冲突)。"""
        info = dict(getattr(self._cam, "info", {}) or {})
        info["rl/sim_connected"] = self.sim_connected
        info["rl/step_index"] = self._step_count
        info["rl/obs_mode"] = self.obs_mode
        info["rl/frame_skip"] = self.frame_skip
        return info

    def close(self):
        """关闭顺序(写死):停步进线程 → 优雅 shutdown → 兜底日志。

        1) cam.running=False 让 dgym update 循环在当前步进后退出;
        2) join 3s——卡死在 observe 自旋内时放弃(daemon 线程,进程退出兜底);
        3) cam.shutdown():join 重建线程 → env.close()(viewer.quit 关 socket)。
        模拟器进程生命周期归脚本管(见 scripts/_sim_proc.py,只按端口/子进程杀)。
        """
        if self._closed:
            return
        self._closed = True
        self._cam.running = False
        if self._update_thread.is_alive():
            self._update_thread.join(timeout=3.0)
            if self._update_thread.is_alive():
                logger.warning("sim 步进线程 3s 未退出(疑似 observe 自旋),"
                               "放弃 join,socket 由 shutdown 关闭")
        try:
            self._cam.shutdown()
        except Exception as e:
            logger.warning("cam.shutdown 异常(忽略): %s", e)
