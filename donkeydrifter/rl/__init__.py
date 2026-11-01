"""RL 管线 M1:环境封装 + 分解式 reward。

- env.DonkeyDriftEnv: gymnasium 封装,构造路径与 templates 同款
  (donkeydrifter.parts.dgym.DonkeyGymEnv → gym_donkeycar),不拉起 Vehicle。
- rewards: 纯函数分解式 reward(离线可测)+ 可选 DecomposedRewardWrapper。

M1 范围(工作订单 2026-11-01):不含 SB3/训练循环;reward 一律在 wrapper 层,
dgym/gym_donkeycar 零改动。
"""

from .rewards import (
    RewardConfig,
    compute_beta_deg,
    reward,
)
from .env import DonkeyDriftEnv

__all__ = [
    "DonkeyDriftEnv",
    "RewardConfig",
    "compute_beta_deg",
    "reward",
]
