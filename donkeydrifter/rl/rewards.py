"""分解式 reward:纯函数 + 可选 gymnasium 包装层。

工作订单 D2(2026-11-01)约定:
- reward 数学一律放 wrapper 层,``dgym.py``/``gym_donkeycar`` 零改动;
- 核心是纯函数 ``reward(info_prev, info_cur, action, cfg) -> (total, components)``:
  不碰网络、不碰 sim,只吃 info dict,奖励数学可完全离线单测。

项(权重全部在 :class:`RewardConfig`,除注明外均为订单规定项):

1. cte 惩罚:deadband 内不罚,deadband 外 huber(不用裸 cte²——漂移工况横向
   偏移大且车头≠速度方向是特性,硬平方会系统性压制漂移探索)。
2. drift_score:``exp(-((β-μ)²)/(2σ²))``,β 由调用方传入(info['beta_deg'],
   可用本模块 :func:`compute_beta_deg` 计算)。**μ/σ 是声明式手调超参,无实证
   标定,待 D3 人控遥测数据回填**(订单原文要求在注释中声明)。默认 w_drift=0,
   课程后期(Phase B)才开。
3. progress:沿赛道进度差分,**必须带速度下限门槛**(低速不加分)。两种实现:
   - node 法(首选):sim 遥测 activeNode 差分(带环绕修正)。绕圈刷分在
     节点序数上不产生净增量,是反 reward-hacking 的根基;
   - 位移法(回退):无 activeNode 时用位移在速度方向上的前向投影。
     ⚠ 两法自然单位不同(节点数 vs 米),同一训练运行内不要混用——
     components['progress_method'] 会标明本次用哪种。
4. 速度上限项:``-w * max(speed - v_max, 0)``,对称于 sdsandbox FASTSAFE 的
   ``k*max(forward_vel,0)`` 单杠杆思路(漂移任务速度过快直接甩出界)。
5. 存活/步惩罚(w_step)与 timeout 终止罚(w_timeout)**二选一,不允许双重
   计罚**:__post_init__ 直接拒绝两者同时 >0;timeout 罚只在终止帧给一次
   (info['truncated']=True 的那一帧)。

订单外补充(默认全关,验收口径以订单五项为准):
- w_done: sim 终止帧(collision/出界/翻车)一次性罚。默认 0——订单未列此项;
  若不开,撞墙的直接代价只剩「progress 停止」,M2 接线时建议显式打开。
- w_reverse_cte: 反向(vel 与车头反向)时 cte 中心化项关停的镜像思路本模块
  不实现——progress 的 node 法对倒车天然为负,已覆盖。

β 口径(:func:`compute_beta_deg`):heading 与速度方向航向角的差,wrap 到
(-180,180]。heading 来源优先级:
  1) sim 直读:info['car'][2](roll, pitch, yaw 中的 yaw,度)——fork 客户端
     遥测已带,精度远高于积分;
  2) gyro-z 积分(订单规定方法):heading += gyro_z*dt,单段内漂移可接受;
     缺 yaw 或调用方显式指定 method='gyro' 时使用。
两种都实现的原因:D3 校准需要互验(yaw 直读为真值口径,积分法交叉核对,
偏差本身就是诊断信号)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

__all__ = [
    "RewardConfig",
    "compute_beta_deg",
    "gyro_step_heading",
    "reward",
    "DecomposedRewardWrapper",
]


# ---------------------------------------------------------------------------
# 数值防御
# ---------------------------------------------------------------------------

def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    """把遥测字段安全转成 float:None/缺失/NaN/inf 一律落 default。

    sim 遥测经 JSON 往返,坏帧可能出现 None/NaN;reward 对单个坏字段只能
    丢该项(计 defect),绝不能把 NaN 乘进 total 污染整条曲线。
    """
    if value is None:
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(x) or math.isinf(x):
        return default
    return x


def wrap_deg(angle_deg: float) -> float:
    """wrap 到 (-180, 180]。"""
    return (float(angle_deg) + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# β(滑移角)
# ---------------------------------------------------------------------------

def gyro_step_heading(heading_deg: float, gyro_z: float, dt_s: float) -> float:
    """gyro-z 积分一步:heading += gyro_z * dt(gyro 单位 deg/s),wrap 后返回。"""
    return wrap_deg(heading_deg + float(gyro_z) * float(dt_s))


def compute_beta_deg(
    info_prev: Optional[Dict[str, Any]],
    info_cur: Dict[str, Any],
    method: str = "auto",
) -> Optional[float]:
    """计算滑移角 β = wrap(heading - course),单位度;无法计算返回 None。

    - course:速度向量方向(info['vel'],车体系?世界系?)——⚠ 遥测 vel 的坐标系
      由 sim 决定,sdsim 家族遥测为世界系(与 pos 同系),course=atan2(vel_y, vel_x)。
      speed 低于 ``0.2 m/s`` 时航向无定义,返回 None(调用方按无 β 处理)。
    - heading:
      * method='yaw':info['car'][2] 直读(度)。
      * method='gyro':需要 info_prev['rl/heading_deg'](积分链状态)+ info_cur
        的 gyro_z/dt_s;调用方(teleop 录制端)负责沿帧维护积分链。
      * method='auto':有 yaw 用 yaw,否则退 gyro 链,再不行返回 None。
    """
    speed = _num(info_cur.get("speed"), 0.0) or 0.0
    vel = info_cur.get("vel") or (None, None, None)
    vx, vy = _num(vel[0]), _num(vel[1])
    if vx is None or vy is None or speed < 0.2:
        return None
    course = math.degrees(math.atan2(vy, vx))

    heading: Optional[float] = None
    if method in ("yaw", "auto"):
        car = info_cur.get("car")
        if car is not None and len(car) >= 3:
            yaw = _num(car[2])
            if yaw is not None:
                heading = yaw
    if heading is None and method in ("gyro", "auto"):
        if info_prev is not None:
            prev_h = info_prev.get("rl/heading_deg")
            gz = _num(info_cur.get("gyro", (None, None, None))[2])
            dt = _num(info_cur.get("dt_s"))
            if prev_h is not None and gz is not None and dt:
                heading = gyro_step_heading(prev_h, gz, dt)
    if heading is None:
        return None
    return wrap_deg(heading - course)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RewardConfig:
    """分解式 reward 全部权重与形状参数(见模块 docstring 逐项说明)。"""

    # 1) cte 惩罚:deadband 内不罚;外 huber(delta 内二次、外一次)
    w_cte: float = 1.0
    cte_deadband_m: float = 0.5
    cte_huber_delta_m: float = 0.5

    # 2) drift_score。⚠ μ/σ 为声明式手调超参,无实证标定,待 D3 人控遥测
    #    (β 分布)回填后才允许转正启用。
    w_drift: float = 0.0
    drift_mu_deg: float = 25.0
    drift_sigma_deg: float = 10.0
    drift_speed_floor_mps: float = 2.0   # 低于此速度不给漂移分(原地打转不刷分)
    drift_speed_ref_mps: float = 6.0     # speed_norm = min(speed/ref, 1)

    # 3) progress(速度门槛:低于 floor 的帧 progress=0)
    w_progress: float = 1.0
    progress_speed_floor_mps: float = 0.3

    # 4) 速度上限惩罚(每步,超速部分线性)
    w_overspeed: float = 0.5
    speed_max_mps: float = 8.0

    # 5) 存活/步惩罚 与 timeout 终止罚:二选一,不允许双重计罚
    w_step: float = 0.0        # 每步固定罚(鼓励跑快)
    w_timeout: float = 0.0     # 仅 truncated 终止帧给一次

    # 订单外补充,默认关
    w_done: float = 0.0        # 仅 sim terminated 帧给一次(collision/出界/翻车)

    # node 法 progress 的单位换算:节点间距未知时保持 1.0(单位=节点数);
    # 已知间距(米/节点)时填入即可换算成米,两法单位才可比。
    node_spacing_m: float = 1.0

    def __post_init__(self):
        if self.w_step > 0.0 and self.w_timeout > 0.0:
            raise ValueError(
                "w_step 与 w_timeout 不允许同时 >0(存活/步惩罚与 timeout 罚"
                "二选一,禁止双重计罚——订单 D2 第 5 项)"
            )


def _huber(x: float, delta: float) -> float:
    """标准 huber:x<=delta 二次段,超出线性段。x>=0。"""
    if x <= delta:
        return 0.5 * x * x
    return delta * (x - 0.5 * delta)


# ---------------------------------------------------------------------------
# 纯函数 reward
# ---------------------------------------------------------------------------

def reward(
    info_prev: Optional[Dict[str, Any]],
    info_cur: Dict[str, Any],
    action: Optional[Any] = None,
    cfg: Optional[RewardConfig] = None,
) -> Tuple[float, Dict[str, Any]]:
    """分解式 reward 主入口(纯函数)。

    参数
    ----
    info_prev/info_cur:
        env step 透传的遥测 dict(可含调用方注入的 'beta_deg'、'truncated'、
        'terminated'、'dt_s'、'rl/heading_deg' 等扩展键)。
    action:
        本步动作 [steer, throttle(, brake)],当前各项都不直接依赖它,
        收进 components['action'] 纯为记账/排查用。
    cfg:
        权重配置,None 时用默认(= Phase A:循线向,drift/步罚/timeout 全关)。

    返回
    ----
    (total, components):components 含每一项的**净贡献**(权重已乘)、
    'progress_method'、'defects'(坏字段清单)与 'action'。
    """
    cfg = cfg or RewardConfig()
    comps: Dict[str, Any] = {}
    defects: list = []

    # ---- 1) cte 惩罚 -------------------------------------------------------
    cte = _num(info_cur.get("cte"))
    if cte is None:
        defects.append("cte")
        comps["cte"] = 0.0
    else:
        over = max(abs(cte) - cfg.cte_deadband_m, 0.0)
        comps["cte"] = -cfg.w_cte * _huber(over, cfg.cte_huber_delta_m)

    # ---- 3) progress(先于 drift 算,speed 在这里取) ------------------------
    speed = _num(info_cur.get("speed"))
    if speed is None:
        defects.append("speed")
        speed = None
    progress = 0.0
    progress_method = "none"
    if speed is not None and speed >= cfg.progress_speed_floor_mps and info_prev is not None:
        node_prev = _num(info_prev.get("active_node"))
        node_cur = _num(info_cur.get("active_node"))
        total_nodes = _num(info_cur.get("total_nodes"))
        if node_prev is not None and node_cur is not None and total_nodes and total_nodes >= 2:
            # node 法:带环绕的最短有符号差分。节点沿赛道顺序编号(sdsim 的
            # CarPath 序),倒车/绕圈在该序数上不产生净增量。
            d = (node_cur - node_prev) % total_nodes
            if d > total_nodes / 2.0:
                d -= total_nodes
            progress = d * cfg.node_spacing_m
            progress_method = "node"
        else:
            # 位移法回退:位移在速度方向上的前向投影(米)。弱于 node 法
            # (绕圈也产生投影),仅当 sim 不发 activeNode 时使用。
            pos_prev, pos_cur = info_prev.get("pos"), info_cur.get("pos")
            vel = info_cur.get("vel") or (None, None, None)
            if pos_prev is not None and pos_cur is not None and vel[0] is not None:
                try:
                    dx = float(pos_cur[0]) - float(pos_prev[0])
                    dy = float(pos_cur[1]) - float(pos_prev[1])
                    vnorm = math.hypot(*[_num(v, 0.0) or 0.0 for v in vel[:2]])
                    if vnorm > 1e-6:
                        progress = (dx * float(vel[0]) + dy * float(vel[1])) / vnorm
                        progress_method = "displacement"
                except (TypeError, ValueError, IndexError):
                    defects.append("pos/vel")
    comps["progress"] = cfg.w_progress * progress
    comps["progress_method"] = progress_method

    # ---- 2) drift_score -----------------------------------------------------
    beta = _num(info_cur.get("beta_deg"))
    if beta is None:
        if cfg.w_drift > 0.0:
            defects.append("beta_deg")
        comps["drift"] = 0.0
    else:
        speed_norm = 0.0 if speed is None else min(max(speed, 0.0) / cfg.drift_speed_ref_mps, 1.0)
        if speed is not None and speed < cfg.drift_speed_floor_mps:
            speed_norm = 0.0
        comps["drift"] = (
            cfg.w_drift
            * speed_norm
            * math.exp(-((beta - cfg.drift_mu_deg) ** 2) / (2.0 * cfg.drift_sigma_deg**2))
        )

    # ---- 4) 速度上限惩罚 -----------------------------------------------------
    if speed is None:
        comps["overspeed"] = 0.0
    else:
        comps["overspeed"] = -cfg.w_overspeed * max(speed - cfg.speed_max_mps, 0.0)

    # ---- 5) 存活/步惩罚 vs timeout 罚(互斥由 cfg 校验保证) -------------------
    comps["step"] = -cfg.w_step
    comps["timeout"] = 0.0
    if cfg.w_timeout > 0.0 and bool(info_cur.get("truncated", False)):
        # 只有调用方在终止帧标 truncated 才触发一次;序列中途不该出现该键为 True
        comps["timeout"] = -cfg.w_timeout

    # ---- 订单外补充(默认关) --------------------------------------------------
    comps["done"] = 0.0
    if cfg.w_done > 0.0 and bool(info_cur.get("terminated", False)):
        comps["done"] = -cfg.w_done

    total = (
        comps["cte"]
        + comps["progress"]
        + comps["drift"]
        + comps["overspeed"]
        + comps["step"]
        + comps["timeout"]
        + comps["done"]
    )
    comps["total"] = total
    comps["action"] = None if action is None else list(np.asarray(action, dtype=float).ravel())
    comps["defects"] = defects
    return total, comps


# ---------------------------------------------------------------------------
# 可选包装层
# ---------------------------------------------------------------------------

try:  # gymnasium 在纯离线单测环境可用;缺它时纯函数部分照常工作
    import gymnasium as gym

    class DecomposedRewardWrapper(gym.Wrapper):
        """把 :func:`reward` 接到 env.step 输出上(订单「reward 一律放 wrapper 层」)。

        - step 返回的 reward 换成分解式 total;原始 sim reward 写入
          info['raw_reward'](与 DonkeyDriftEnv 自身的透传键同键,幂等);
        - info['reward_components'] = components(逐项记账);
        - info 缺 β 时自动注入 compute_beta_deg(auto 口径)结果;
        - 维护 gyro 积分链 info['rl/heading_deg'](yaw 缺失时 D3/回放可用)。
        """

        def __init__(self, env, cfg: Optional[RewardConfig] = None):
            super().__init__(env)
            self.reward_cfg = cfg or RewardConfig()
            self._prev_info: Optional[Dict[str, Any]] = None

        def reset(self, **kwargs):
            self._prev_info = None
            obs, info = self.env.reset(**kwargs)
            self._stash(info)
            return obs, info

        def step(self, action):
            obs, raw, terminated, truncated, info = self.env.step(action)
            info["raw_reward"] = raw
            info["terminated"] = bool(terminated)
            info["truncated"] = bool(truncated)
            if info.get("beta_deg") is None:
                info["beta_deg"] = compute_beta_deg(self._prev_info, info, method="auto")
            total, comps = reward(self._prev_info, info, action, self.reward_cfg)
            info["reward_components"] = comps
            self._stash(info)
            return obs, total, terminated, truncated, info

        def _stash(self, info: Dict[str, Any]) -> None:
            """维护 gyro 积分链(下一帧的 method='gyro' 起点)。

            info 为浅拷贝语义:reward() 只读,这里写入前先浅拷贝,避免
            env 侧下一轮整体替换 info 时把扩展键带进 sim 透传流。
            """
            carried = {k: v for k, v in info.items() if k.startswith("rl/")}
            yaw = None
            car = info.get("car")
            if car is not None and len(car) >= 3:
                yaw = _num(car[2])
            if yaw is not None:
                carried["rl/heading_deg"] = yaw  # yaw 可用时链重置为直读值
            elif self._prev_info is not None:
                prev_h = self._prev_info.get("rl/heading_deg")
                gz = _num(info.get("gyro", (None, None, None))[2])
                dt = _num(info.get("dt_s"))
                if prev_h is not None and gz is not None and dt:
                    carried["rl/heading_deg"] = gyro_step_heading(prev_h, gz, dt)
            self._prev_info = dict(info)
            self._prev_info.update(carried)

except ImportError:  # pragma: no cover - gymnasium 缺失时的降级
    DecomposedRewardWrapper = None  # type: ignore[assignment]
