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
    "pos_xz": 50.0,    # m(X-Z 地面平面;Unity 系 y 轴向上为高度,不入平面分量)
}
STATE_OBS_DIM = 16  # 3+3+3+3+2+2

_DEFAULT_SIM_FPS = 20.0  # sdsim 家族遥测节拍(见 dgym.py 分辨率解耦注释)


def build_state_vector(info: Dict[str, Any],
                       prev_action: Tuple[float, float]) -> Tuple[np.ndarray, list]:
    """16 维 state 向量(声明式缩放,下标见 vec 列表);坏字段记 defects 补零。

    模块级纯函数(M3 D0 补丁,2026-11-03):训练 obs(``_build_state_vec``)、
    终端采样器(``state_vector()``)与**网页驾驶录制器**(bc_drive_recorder)
    三方共用的唯一实现——数据集口径与策略观测口径由此强制一致。
    """
    info = dict(info or {})
    defects: list = []

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
        num("pos", 0), num("pos", 2),  # X-Z 地面平面(y=高度不入)
        prev_action[0], prev_action[1],
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
    out[12:14] /= _STATE_SCALES["pos_xz"]
    return out, defects


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
        sync_mode: bool = False,
        sync_time_step: float = 0.05,
        spawn_curriculum=None,
        cte_anchor: Optional[Dict[str, Any]] = None,
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
        # M2 D1:同步步进。sync_time_step 必须是物理 tick 0.01 的整数倍
        # (sdsim 协议约束;0.05/0.02 合法,1/60 不合法)
        self.sync_mode = bool(sync_mode)
        self.sync_time_step = float(sync_time_step)
        # M4 D1.4:cte 锚定(口径红线:三处统一 = reward cte 项 / cte_limit 截断 /
        # state obs cte 分量;实现为单点 in-place 替换 cam.info["cte"],下游全部
        # 自动统一)。格式:{"mode":"line","offsets":[米], "cte_unit_gain":g}
        # (rl-m4-driveline.json);None = "center"(M3 语义,cte 原样)。
        # sim cte 为增益单位(实测 gain≈-8.114,见 rl-m4-driveline.json),line 锚
        # 下所有 cte 量先换算米制:cte_m = cte_raw / gain,再减行车线 offset。
        self._cte_offsets: Optional[np.ndarray] = None
        self._cte_gain: float = 1.0
        self._anchor_defects = 0
        if cte_anchor is not None and cte_anchor.get("mode") == "line":
            self._cte_offsets = np.asarray(cte_anchor["offsets"], dtype=float)
            self._cte_gain = float(cte_anchor.get("cte_unit_gain", 1.0))
            if self._cte_gain == 0:
                raise ValueError("cte_anchor.cte_unit_gain 为 0(除法无意义)")
        # M2 D3:出生课程(SpawnCurriculum)。SB3 裸调 reset() 时不带 options,
        # 有课程则每 episode 内部采样 spawn_cfg(带符号 lateral 在训练侧生成)
        self._curriculum = spawn_curriculum
        if self.sync_mode:
            ticks = self.sync_time_step / 0.01
            if abs(round(ticks) - ticks) > 1e-6 or ticks < 1:
                raise ValueError(
                    f"sync_time_step {self.sync_time_step} 必须是物理 tick 0.01 "
                    f"的整数倍(0.05/0.02 合法,1/60 不合法)")

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
            # 零图像/低分辨率用途下渲染分辨率对齐 NN 输入:dgym 默认渲染
            # 640×480,纯状态量训练用不到,多开实例时白烧 sim CPU
            sim_conf.setdefault("render_img_w", sim_conf["img_w"])
            sim_conf.setdefault("render_img_h", sim_conf["img_h"])
        sim_conf.setdefault("watchdog_sec", 5.0)
        if self.sync_mode:
            # fork supply_defaults 已登记的 sync 键:init 时向 sim 发
            # step_mode synchronous,此后每条 control 推进 sync_time_step
            # 物理时长并回一帧(一控制一帧,sim 不再自由前进)
            sim_conf["sync_mode"] = True
            sim_conf["sync_time_step"] = self.sync_time_step

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
        # 跑健康检查;断线时自动按 1s 周期重连(dgym 既有逻辑,零重写)。
        # **仅异步模式启动**:sync 模式下自由跑线程会把 held action 反复
        # 步进,sim 在策略决策之间继续前进——sync 的正确形态是「一策略步 =
        # 一条 control = 一帧步进遥测」,step() 直连 DonkeyEnv.step(M2 D1)。
        self._update_thread = None
        if not self.sync_mode:
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

    # ------------------------------------------------------------------
    # sync 直连步进(M2 D1)
    # ------------------------------------------------------------------

    def _sync_ensure_connected(self, timeout_s: float) -> None:
        """sync 模式连接保障:无自由跑 update 线程,重连由本路径驱动。

        复用 dgym part 的重建设施:env 为 None 时按 update 线程同款
        (锁内 _check_config_reload + _try_connect)重试;连接存在但 TCP
        不健康时投递看门狗重建(only_if_stale 双检)并等待重建产物。
        """
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            if self._cam.env is None:
                with self._cam._reconnect_lock:
                    if self._cam.env is None:
                        self._cam._check_config_reload()
                        self._cam._try_connect()
                if self._cam.env is None:
                    time.sleep(1.0)
                    continue
            if self._cam._is_env_connected():
                return
            before = id(self._cam.env)
            self._cam._post_rebuild("watchdog")
            while time.perf_counter() < deadline:
                if (self._cam.env is not None and id(self._cam.env) != before
                        and self._cam._is_env_connected()):
                    break
                time.sleep(0.2)
            if self._cam._is_env_connected():
                return
        raise ConnectionError(
            f"sim {self.sim_host}:{self.sim_port} 在 {timeout_s:.0f}s 内未建立"
            "健康连接(同步模式)")

    def _wait_sync_answer(self, viewer, ts0: float, timeout_s: float) -> bool:
        """等 sync reset 应答帧(viewer.time_received 前进);超时 False。"""
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            if viewer.time_received != ts0:
                return True
            time.sleep(0.002)
        return False

    def _step_sync_once(self, steer: float, throttle: float):
        """一控制一帧:直连 fork DonkeyEnv.step(take_action+observe)。

        observe() 自旋等新步进帧(fork 15s 陈旧守卫),返回即为本控制
        推进 sync_time_step 后的遥测;terminated/raw_reward 用 sim 直出值
        (不再经 viewer.is_game_over/calc_reward 间接读)。
        ⚠ 每控制前必须过连接保障:断连后 observe 的陈旧守卫会瞬间返回
        旧帧,连接级恢复(重建/重连)只能由 _sync_ensure_connected 驱动
        ——sync 无自由跑线程,这里是唯一的自愈入口(M2 item5 实测教训)。
        """
        self._sync_ensure_connected(self.connect_timeout_s)
        raw = self._cam._raw_env()
        out = raw.step(np.array([steer, throttle], dtype=np.float32))
        obs_raw, raw_reward, terminated, _trunc, info = out
        if self.obs_mode == "pixel":
            # part 的帧缓存由 update 线程维护,sync 下无线程——用 part 自带
            # 的拆帧变换(_set_frame:翻转/下采样/到达时间戳)落缓存
            self._cam._set_frame(obs_raw)
        self._cam.info = info  # 保持 part 缓存一致(_frame_token/_build_obs 读它)
        return float(raw_reward), bool(terminated), info

    @property
    def sim_connected(self) -> bool:
        """当前 TCP 健康状态(与 dgym 看门狗口径一致)。

        sync 模式无缓存 flag(connected 只由 run_threaded/update 线程刷新,
        sync 下都不跑)——直接查底层连接健康,保证断连检测不依赖步进。
        """
        if self.sync_mode:
            return bool(self._cam.env is not None and self._cam._is_env_connected())
        return bool(getattr(self._cam, "connected", False))

    # ------------------------------------------------------------------
    # cte 锚定(M4 D1.4,单点)
    # ------------------------------------------------------------------

    def _apply_cte_anchor(self, info: Dict[str, Any]) -> None:
        """in-place 锚定 info["cte"](cam.info 当前帧 dict;dgym 每轮整体替换,
        无跨帧累积)。line 锚:cte_m = cte_raw/gain − offsets[active_node];
        缺 active_node 时保持原值并计缺陷(训练链路 active_node 恒在,
        出现即口径事故,计数供 Liveness/报告显式暴露)。center 模式 no-op。"""
        if self._cte_offsets is None:
            return
        raw = info.get("cte")
        # node 来源与 _build_info 提升同源:handler.active_node(sim 组装的 info
        # dict 无此键——M2 D0 教训的时序版;直接从 info 取会全程 None → 锚定
        # 失效回退 raw sim 单位,M4 首轮 held-out 全挂的直接原因,已修)
        node = info.get("active_node")
        if node is None:
            viewer = getattr(getattr(self._cam, "env", None), "unwrapped", None) \
                if self._cam.env is not None else None
            handler = getattr(getattr(viewer, "viewer", None), "handler", None)
            node = getattr(handler, "active_node", None)
        info["active_node"] = node  # 回写:让 _build_info 的提升与本处一致
        info["cte_raw"] = raw
        if raw is None or node is None:
            self._anchor_defects += 1
            return
        try:
            cte_m = float(raw) / self._cte_gain
            anchored = cte_m - float(self._cte_offsets[int(node) % len(self._cte_offsets)])
        except (TypeError, ValueError, IndexError):
            self._anchor_defects += 1
            return
        info["cte"] = anchored
        info["cte_anchor_node"] = int(node)

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
        if self.obs_mode == "pixel":
            return np.asarray(self._cam.frame, dtype=np.uint8), []
        return self._build_state_vec(self._prev_action)

    def state_vector(self, prev_action: Optional[Tuple[float, float]] = None) -> np.ndarray:
        """公开访问器(M3 D0):训练 state obs 的**同一函数**产出,供采样器落
        state_vec——数据集口径与策略观测口径由此强制一致(两处各写一份是
        数据集级 bug 的温床)。pixel 模式的 env 也可调用。

        prev_action:观测里「产生该观测的那条动作」[steer, throttle](训练时
        = step() 的 clip 后动作;采样时 = 上一帧人驾动作,brake 不入)。
        None → 用 env 内部 _prev_action(step 路径语义)。
        """
        pa = self._prev_action if prev_action is None else (float(prev_action[0]), float(prev_action[1]))
        return self._build_state_vec(pa)[0]

    def _build_state_vec(self, prev_action: Tuple[float, float]) -> Tuple[np.ndarray, list]:
        """16 维 state 向量(委托模块级纯函数 :func:`build_state_vector`)。"""
        info = getattr(self._cam, "info", {}) or {}
        return build_state_vector(info, prev_action)

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

        options = dict(options or {})
        spawn_cfg = options.get("spawn_cfg")
        want_spawn = bool(spawn_cfg) or bool(options.get("spawn"))
        if not want_spawn and not options and self._curriculum is not None:
            spawn_cfg = self._curriculum.sample()  # 课程驱动(每 episode 一次)
            want_spawn = True
        t0 = time.perf_counter()

        if self.sync_mode:
            # sync 应答路径:复刻 fork viewer.reset 的序列(清 episode 状态 →
            # 发 reset_car → 等应答帧 → 手刹步进一帧取复位后遥测),但消息
            # **自建字面透传**——不经 send_reset_car,它会在 seed 存在时对
            # lateral_offset 再做一次隐藏 ±随机(违反「带符号随机在训练侧」
            # 且使 spawn 语义随模式漂移,订单已核事实 4)。⚠ 语义声明:sync
            # 裸 reset = reset_car(回出生点),与异步的 reset_to_nearest 是
            # 两条互斥通道(双发会互相覆盖);训练 reset 一律走出生课程。
            self._sync_ensure_connected(self.connect_timeout_s)
            raw = self._cam._raw_env()
            viewer = getattr(raw, "viewer", None)
            # fork 结构:壳类 DonkeyUnitySimContoller 全部委托给
            # self.handler(DonkeyUnitySimHandler,状态承载者:
            # _clear_episode_state/time_received/send_control/observe 都在它上)
            handler = getattr(viewer, "handler", None) or viewer
            if handler is None or not hasattr(handler, "_clear_episode_state"):
                raise ConnectionError("sync reset:底层 viewer.handler 不可达")
            msg: Dict[str, Any] = {"msg_type": "reset_car"}
            if want_spawn and isinstance(spawn_cfg, dict):
                msg.update(spawn_cfg)  # 字面透传(含已带符号的 lateral_offset)
            if seed is not None:
                msg["seed"] = int(seed)
            handler._clear_episode_state()
            ts0 = handler.time_received
            sent = self._send_sim_message(msg)
            answered = self._wait_sync_answer(handler, ts0, 10.0)
            # 手刹步进一帧:取复位后遥测(sim 静止,不引入位移)
            handler.send_control(0.0, 0.0, 1.0)
            _o, _r, _d, info_raw = handler.observe()
            if self.obs_mode == "pixel":
                self._cam._set_frame(_o)
            self._cam.info = info_raw
            elapsed = time.perf_counter() - t0
            self._apply_cte_anchor(getattr(self._cam, "info", {}) or {})
            self._step_count = 0
            self._prev_action = (0.0, 0.0)
            obs, defects = self._build_obs()
            info = self._build_info()
            info["rl/reset_elapsed_s"] = elapsed
            info["rl/reset_mode"] = ("reset_car+spawn" if want_spawn else "reset_car")
            info["rl/reset_answered"] = bool(answered and sent)
            info["rl/reset_detected_move"] = None  # 应答路径无位姿跳变检测语义
            if defects:
                info["rl/obs_defects"] = defects
            return obs, info

        self._wait_connected(self.connect_timeout_s)

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
        # 车本来就在赛道中央时无跳变,按上限收口并如实标记,此时耗时口径
        # 退回「命令回执」时间,不把无跳变罚成满超时)
        self._wait_new_frame(token, min(2.0, self.connect_timeout_s))
        t_cmd = time.perf_counter() - t0
        detected = self._wait_pose_jump(pre_pos, timeout_s=1.5)
        elapsed = time.perf_counter() - t0

        self._apply_cte_anchor(getattr(self._cam, "info", {}) or {})
        self._step_count = 0
        self._prev_action = (0.0, 0.0)
        obs, defects = self._build_obs()
        info = self._build_info()
        info["rl/reset_cmd_s"] = t_cmd
        info["rl/reset_elapsed_s"] = elapsed if detected else t_cmd
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

        t0 = time.perf_counter()
        stale = False
        if self.sync_mode:
            # 一控制一帧;frame_skip=N = 同一动作连续 N 个步进帧(wrapper 级
            # repeat,与异步口径一致)
            raw_reward = 0.0
            terminated = False
            for _ in range(self.frame_skip):
                raw_reward, terminated, _info = self._step_sync_once(steer, throttle)
        else:
            for _ in range(self.frame_skip):
                token = self._frame_token()
                # run_threaded:喂动作 + 触发看门狗/重连 + 返回最新帧(dgym 既有)
                self._cam.run_threaded(steer, throttle, 0.0)
                if not self._wait_new_frame(token, self.frame_wait_timeout_s):
                    stale = True
            viewer = self._sim_viewer()
            terminated = bool(viewer.is_game_over()) if viewer is not None else False
            raw_reward = float(viewer.calc_reward(terminated)) if viewer is not None else 0.0
        step_elapsed = time.perf_counter() - t0
        self._step_count += 1

        # M4 D1.4:锚定单点——先 in-place 替换 cam.info["cte"],此后截断判定、
        # _build_obs/_build_info、DecomposedRewardWrapper 读到的全是锚定米制 cte'
        self._apply_cte_anchor(getattr(self._cam, "info", {}) or {})

        obs, defects = self._build_obs()
        info = self._build_info()
        info["raw_reward"] = raw_reward
        info["rl/stale"] = stale
        info["dt_s"] = step_elapsed
        info["rl/step_elapsed_s"] = step_elapsed
        if self._cte_offsets is not None:
            info["rl/anchor_defects"] = self._anchor_defects
        if defects:
            info["rl/obs_defects"] = defects

        # 客户端侧终止(与 sim terminated 分开的第二个 flag);读锚定后 cte'
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
        """sim 遥测原样透传 + rl/ 前缀扩展键(键名不与 sim 字段冲突)。

        active_node/total_nodes 从底层 viewer 属性**提升**进 info(M2 D0):
        fork 在 on_telemetry 里解析(donkey_sim.py:797-799)但 observe() 组装
        info 时不含这两个键——M1 期间 node 法 progress 因此是死代码。提升时
        None 兜底、不伪造:viewer 初始值 active_node=0/total_nodes=1,若 sim
        根本不发 activeNode/totalNodes,提升出来就是初始值,reward 侧以
        total_nodes>=2 守卫退回位移法(smoke item1 记录提升值以判别 sim 是否真发)。
        """
        info = dict(getattr(self._cam, "info", {}) or {})
        viewer = self._sim_viewer()
        # fork 结构:壳类 DonkeyUnitySimContoller 无状态,active_node/total_nodes
        # 在 handler(DonkeyUnitySimHandler)上——提升必须落到 handler
        handler = getattr(viewer, "handler", None) or viewer
        info["active_node"] = getattr(handler, "active_node", None)
        info["total_nodes"] = getattr(handler, "total_nodes", None)
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
        if self._update_thread is not None and self._update_thread.is_alive():
            self._update_thread.join(timeout=3.0)
            if self._update_thread.is_alive():
                logger.warning("sim 步进线程 3s 未退出(疑似 observe 自旋),"
                               "放弃 join,socket 由 shutdown 关闭")
        try:
            self._cam.shutdown()
        except Exception as e:
            logger.warning("cam.shutdown 异常(忽略): %s", e)
