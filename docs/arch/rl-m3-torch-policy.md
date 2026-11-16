# torch 版本策略(M3 D1,2026-11-02 决策)

## 结论

仓库内存在两条 torch 链,**互斥、不合并**:

| 链 | extra | torch 版本 | 用途 | 状态 |
|---|---|---|---|---|
| 车端/legacy | `torch` | 2.1.* + pytorch-lightning | `donkeycar/parts/pytorch/`(ResNet18 Lightning 训练、车端推理)、`donkeycar/parts/torch_linear.py`、`management/base.py` 的 `donkey train` 入口 | 保持不动(车端资产) |
| 研究/RL-BC | `rl` | 2.15.0(SB3 2.9.2 带入,MPS 可用) | `scripts/rl_train.py`、`scripts/bc_train.py`(M3)、`donkeydrifter/rl/` | **唯一研究链** |

- 同一 venv **只装其一**;本仓库研究 venv(`.venv`)按 `rl` extra 配置。
- BC 训练(M3 D2)与 RL 统一走**纯 torch**,零 Lightning 依赖(grep 校验进单测/CI 清单)。
- 不升级 `torch` extra(2.1.* 受 `fastai<2.8` 与车端 Jetson 轮子约束,升级是车端工作单,不在 M3)。

## 为什么不合并

- M2 实测 SB3 2.9.2 需要 torch ≥2.3;车端链锁 2.1.*——硬冲突。
- Lightning 带来的训练循环抽象对 BC→SB3 灌权没有价值(灌权要的是裸 `nn.Module` 的
  state_dict 可控映射),反而让 features_extractor/action_net 的权重对位更难审计。
- 车端 ResNet18 资产(ImageNet-224 口径)与 RL 口径(NatureCNN /255-CHW)本就不同源,
  强行同栈会制造"看似可共享实则口径不同"的隐患。

## 口径表(M3 统一)

| 项 | 研究链(RL/BC) | 车端 legacy |
|---|---|---|
| 图像预处理 | uint8 HWC → CHW,`/255`(SB3 `normalize_images=True`) | /255 HWC(torch_linear)或 ImageNet Normalize 224(ResNet18) |
| 像素骨干 | NatureCNN(SB3 CnnPolicy 镜像,features 512) | ResNet18 / KerasLinear 镜像 |
| 状态骨干 | MlpPolicy pi 64-64 Tanh + action_net | — |
| 动作 | [steer, throttle] ∈ [-1,1]² | [angle, throttle] |

## 验证记录(D1)

- `.venv` import 链:`torch 2.15.0` / `stable_baselines3 2.9.2` / `lightning`:缺失(预期);
- `pytest tests/rl` 全绿;
- `donkeycar/parts/pytorch/*`、`donkeycar/tests/test_torch.py` 零改动(git diff 为空)。
