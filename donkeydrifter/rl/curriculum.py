"""M2 D3:出生课程(纯类,零 sim 依赖)。

订单已核事实 4:env 通道对 spawn 字段是**字面透传**,fork send_reset_car 的
「seed 决定 lateral 带符号 ± 随机」没有继承——**带符号随机必须在训练侧自己
生成**。本类即训练侧的随机源:同一课程 seed → 完全相同的 spawn_cfg 序列
(可复现性由单测断言);sim 侧姿态复现另由 reset 消息里的 seed 保证
(sdsim 的 System.Random(seed),M1 smoke #7 与 M2 确定性验证均实测)。

默认 lateral ±1.0m / heading ±8° 为**占位超参,非标定**(M1 对账结论:
出生课程是真正杠杆,但量级须在 M3 用 held-out 评测校准)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, Optional

__all__ = ["CurriculumConfig", "SpawnCurriculum"]


@dataclass(frozen=True)
class CurriculumConfig:
    """出生课程参数(占位超参,非标定,见模块 docstring)。"""

    lateral: float = 1.0        # ±米,带符号均匀随机(防单侧偏科,sdsandbox 2026-10-18 教训)
    heading: float = 8.0        # ±度,sim 侧在其附近随机(经 seed 复现)
    node_min: int = 0           # 出生节点范围;0/0 = 不限(sim 全赛道)
    node_max: int = 0
    seed: Optional[int] = None  # 课程种子:决定 spawn_cfg 序列(训练侧)与 sim 姿态


class SpawnCurriculum:
    """按课程种子逐 episode 生成 spawn_cfg 消息字段(字面透传给 reset)。"""

    def __init__(self, cfg: Optional[CurriculumConfig] = None):
        self.cfg = cfg or CurriculumConfig()
        self._rng = random.Random(self.cfg.seed)
        self.episode_index = 0

    def sample(self) -> Dict[str, Any]:
        """采样一次出生配置;序列由课程种子唯一确定。"""
        c = self.cfg
        fields: Dict[str, Any] = {}
        if c.lateral > 0.0:
            # 带符号 ±均匀:固定单侧会训出「只会向右回正」的偏科策略
            # (sdsandbox 2026-10-18 基线:5 局 crash_rate 1.0 全 |cte|≈2.6 越界)
            fields["lateral_offset"] = round(self._rng.uniform(-c.lateral, c.lateral), 3)
        if c.heading > 0.0:
            fields["heading_noise"] = round(self._rng.uniform(0.0, c.heading), 3)
        if c.node_min > 0 or c.node_max > 0:
            fields["node_min"] = int(c.node_min)
            fields["node_max"] = int(c.node_max)
        # episode 级 seed:同时是课程序列的一部分(可复现)与 sim 姿态随机的
        # 种子(sdsim System.Random;heading 的 ± 抽签在 sim 侧)
        fields["seed"] = self._rng.randrange(1, 2**31)
        self.episode_index += 1
        return fields

    def reset_sequence(self) -> None:
        """重置 RNG 到课程种子(复现性断言/复跑用)。"""
        self._rng = random.Random(self.cfg.seed)
        self.episode_index = 0
