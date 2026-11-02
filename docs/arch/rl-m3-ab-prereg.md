# A/B 预注册:M3 BC 走线热启动(锁定于任何实验 run 之前)

- 锁定时间:2026-11-02(本文件 git 提交时间戳即锁定凭证)
- 预注册纪律:实验开始后本文件不得修改;确需变更 = 作废全部已完成 run 重来。
- 关联:docs/arch/rl-m3-report.md(D3 节按本文件口径判定)

## 假设(三态)

- H0(不确定):两臂 held-out 无实质差异。
- H1(支持):state-BC 热启动臂显著优于纯 PPO 对照臂。
- H2(推翻):对照臂优或持平——在 DonkeyDrift sim 域复现 sdsandbox 证伪口径
  (sdsandbox rl_review.md:纯 BC 蠕行 191/286 步;PPOBC λ 先验 57 vs 175 /
  长训 404.8 vs 773.6;HBC 跨域 crash 10/10)。无论 H2 与否,如实入档。

## 实验设置(全部锁定)

| 项 | 值 |
|---|---|
| 对照臂 C | M2 配方纯 PPO 从头(lr 1e-4,MlpPolicy state 16 维) |
| 实验臂 T | state-BC 热启动:bc_train.py 导出 zip → `rl_train --resume`(SB3 灌权,num_timesteps=0,lr 1e-4) |
| 预算 | 300,000 步/臂/种子(`--steps` 新增口径),两臂同值 |
| 种子组 | {7, 8, 9}(PPO seed = 课程 seed 同号);3 对配对比较 |
| 课程 | ±1.0m lateral(带符号 ±,SpawnCurriculum)/ ±8° heading——M2 占位档,**不因 D4 扫档结果调整**(扫档独立成章) |
| 执行语义 | sync 0.05 × state obs(16 维,env.state_vector 同口径)× Phase A reward(w_drift=0, w_done=1.0) |
| 环境版本 | sdsim 构建(2026-11-02)、SB3 2.9.2、torch 2.15.0 |
| BC 数据 | 用户走线采样(data card 硬门达标才开跑:img std>20 / hard≥15% / thr>0.2≥30% / steer 双侧) |

## KL-to-BC 监控

- 实验臂开 `--kl-monitor`:每 rollout 记录 policy‖BC 的 KL 均值到 jsonl;
- 仅监控,**不进任何损失**(对照臂无 BC 参照,不开);KL 不参与判定,
  只用于事后解读(崩溃/漂移诊断)。

## 评测口径(held-out,锁定)

- **≥2 个 sim 实例**(重拉实例确定性口径,端口隔 ≥2);每实例 ≥5 局,合计 ≥10 局/臂/种子;
- 长局 max 2000 步;**held-out 课程种子:spawn seed 基数 50000+**(训练用 1000+ 系,不重叠);
- 指标:mean ep_rew(分解 reward 总量)、出界率(truncated 占比)、mean ep_len、
  progress 分量总量;按种子配对,报 mean±std;
- 评测执行器:`scripts/rl_eval.py`(确定性动作无关;model zip × 环境参数全记录进 json)。

## 三态判定规则(锁定)

设 Δ_s = held-out mean_rew(T, seed_s) − held-out mean_rew(C, seed_s),s ∈ {7,8,9}:

- **H1 支持**:≥2/3 种子 Δ_s ≥ +10%·|mean_rew(C)_s|,且两臂绝对门(下)均达标者至少 BC 臂达标;
- **H2 推翻**:≥2/3 种子 Δ_s ≤ −10%·|mean_rew(C)_s|,或 BC 臂 held-out 绝对水平劣于
  对照臂且 BC 臂未达绝对门;——即复现 sdsandbox 证伪口径;
- **H0 不确定**:其余情形(含方差覆盖判别差异);如实报每种子数值与样本量。

## 绝对门(补充锁定,D4 定标后填写;同样先于评测提交)

- 定标数据源:M2 `snap_100000` + 对照臂 C 最优种子在 held-out 口径的实测分布;
- 门值(填入后锁定):
  - `ABS_MEW_REW_MIN = <待 D4 填写>`
  - `ABS_OFFTRACK_MAX = <待 D4 填写>`
- A/B 评测时两臂分别过门;「BC 臂未达绝对门而对照达标」按 H2 处理。

## 公平性声明

- 两臂代码路径仅差异:`--resume <bc.zip>`(T)与无(README:除 resume 外,
  rl_train 参数逐项相同,由启动命令记录佐证);
- 评测对两臂盲执行(同一脚本、同一实例池、同一种子序列);
- KL 监控仅 T 臂携带且不回传梯度。
