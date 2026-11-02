# RL M2 交付报告(sync 接线 + 修复 + PPO 冒烟)

- 分支:`feat/rl-sim-pipeline`(M1 未合 main,按订单直接续)
- 日期:2026-11-02
- sim:sdsim 最新构建 `/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app`(用户已拍板)
- SB3 pin:`stable-baselines3>=2.9,<3`(setup.cfg 新 `rl` extra);实测 **SB3 2.9.2 / torch 2.15.0**(macOS MPS 可用)——本单唯一新依赖

---

## 用户待办(显眼处,订单要求)

1. **人工漂移采样回填 μ/σ**:命令沿用 M1 报告 §7
   (`.venv/bin/python scripts/rl_teleop_record.py` 键控驾驶漂移 →
   `.venv/bin/python scripts/rl_beta_analyze.py "outputs/rl_teleop_*/"`)。
   Phase B 开 drift 项的硬前置。
2. **真车目标控制频率确认(0.05s vs 0.02s)**:D2 实测两者吞吐相同(384/389 步/s,
   步耗时 = 协议开销主导),**决策依据只剩真车控制频率与 sim-to-real 口径**——
   50Hz(0.05)已是 sdsandbox 实战推荐下限,20ms 档留作真车 ≥50Hz 控制时的对齐选项。
   M3 开训前定档。

## 交付总览

| 项 | 状态 | 关键结果 |
|---|---|---|
| D0 active_node 提升 | ✅ bc0eef0f | info 含 `active_node/total_nodes`;smoke 实测 **sim 真发 totalNodes=250**,node 法 progress 正式激活;None 兜底不伪造;单测 6 例 |
| D1 sync_mode 接线 | ✅ a21c0bd4 + fix | 一控制一帧直连步进;sync_time_step 0.01 整数倍校验(1/60 拒);字面透传 spawn;wire 实测 frame_id 增量全 1 / idle 1s 冻结 |
| D2 吞吐 + 确定性 | ✅ 67e20efa + 复测 | **sync 0.05 state 383.9 步/s**(async 20 的 19×);0.02 389;pixel 189;**2env 双进程 772.4**(隔离,线性 2×);确定性跨实例 **逐位一致 0.0** |
| D3 PPO 冒烟 | ✅ 56a3e2af + 8803fe6d | **100k 步 315s(318.8 步/s 含更新)**;1721 局;ep_rew -30→+26 单调爬升;eval gate 107→196;校准闸 pass |
| D4 smoke sync 重跑 | ✅ 21b52033 | **7 pass / 1 record / 0 fail**;item8 语义自检;telemetry_fps=60 探针 59.99 步/s |

## M2 期间发现并修复的事故(全部有单测/证据留档)

1. **stop_sim 误杀训练 sim(红线级,必看)**:旧 `stop_sim` 的 `port` 默认 9091 且
   子进程路径结束后仍跑「端口确认释放」兜底——eval-gate 停自己的 9095 sim 时
   未传 port 走默认,兜底把 9091 上的**训练 sim** 杀了(命令名校验也通过)。
   修复:子进程路径与端口彻底解耦;外部路径强制显式 port;`lsof` 加
   `-sTCP:LISTEN`;`tests/rl/test_sim_proc_safety.py` 5 用例守住。这是
   sdsandbox「两次误杀训练」教训的原型复现,已按纪律入档。
2. **sdsim 实例监听 `port` 与 `port+1` 两个端口**(lsof LISTEN 实测 9091+9092):
   多实例部署必须隔 ≥2 端口;D2 首跑的 9091/9092 双实例是 specific-vs-wildcard
   绑定侥幸共存,复测已改 9091/9094。smoke 辅助 sim 全迁 +10 段。
3. **孤儿 sim 污染期数据**:多次异常退出留下的孤儿 sim 曾占端口并吃 CPU,
   首轮 bench(335 步/s)被压低;孤儿按「lsof→校验命令名→逐 pid SIGTERM」
   精确清理后复测 383.9。`launch_sim` 现在端口被占即拒启(防再污染)。
4. **sync 下裸 `reset_car`(无字段)不把车放回出生点**(车留原位、cte 残留旧值、
   出生即 trunc)——带字段 spawn 正常;校准闸改固定起点 spawn。训练路径每局
   走课程带字段,未受影响。
5. **别名 finder bug(M1 引入新子包时暴露)**:`donkeydrifter/__init__.py` 的
   MetaPathFinder 对「父包不存在」的点路径抛 ModuleNotFoundError 而非 None,
   `donkeydrifter/rl/` 孙子级导入必炸;修为 fallback 语义。
6. **`scripts/profile.py`(上游 TF 遗留)遮蔽 stdlib profile**,炸 torch→cProfile
   导入链;rl_train.py 在取到 _sim_proc 后移除 scripts 目录再 import torch。

## D2 吞吐表(干净端口复测,`docs/arch/rl-m2-sync-bench.json`)

| 配置 | steps/s | step p50 | stale |
|---|---|---|---|
| sync 0.05 × state | **383.9** | 2.55ms | 0 |
| sync 0.02 × state | 389.0 | 2.54ms | 0 |
| sync 0.05 × pixel(参考) | 189.0 | 5.12ms | 0 |
| async × state(参照) | 20.0 | 49.98ms | 0 |
| 2env × 0.05 × state 单进程轮转 | 375.0(GIL 顶死 ≈ 单 env) | — | — |
| 2env × 0.05 × state 双进程隔离 | **772.4**(线性 2×) | — | — |

- 0.02 与 0.05 吞吐相同 → 步耗时由协议开销主导,物理更细无吞吐代价;
  0.05/0.02 决策依据只剩真车控制频率(见用户待办 2)。
- sim CPU ~28-66% 单实例;双实例各 ~46%。
- **确定性**:同 seed+同动作序列,重拉 sim 实例后逐帧遥测(pos/cte/speed/yaw)
  **max delta = 0.0(逐位一致)**;同实例连跑两次有微小状态残留
  (pos ≤0.27m / yaw ≤5.2°,M1 seed 探针同量级)——确定性结论以「重拉实例」
  口径成立,校准闸两次运行 +11.682 逐位相同是直接佐证。
- 2env 探针:**零死锁**——sdsandbox 的 SubprocVecEnv 死锁在「进程隔离 +
  不用 SB3 VecEnv」形态下不复现;单进程轮转被 GIL 顶死(375≈单 env),
  M3 多开必须进程隔离。订单范围:报数即止,不解、不深入。

## D3 训练曲线判读(`docs/arch/rl-m2-train/`)

100k 冒烟(`rl_m2_smoke`,lr 1e-4,seed 7,course lateral±1.0/heading±8° 占位):

- **ep_rew**:窗口(10 局)均值 -30.4 → +25.9,1721 局单调爬升,max 89.4;
  无发散(3e-4 铁律规避生效)、无冻结(活性监控全程绿灯,fps 318-365)。
- **ep_len**:首 10 局 227(乱撞耗满 trunc 预算)→ 后期 ~67——「提速学习期」
  形态:跑得更快更远才触界,与 ep_rew 上升一致。
- **reward 分量**(前 20% vs 后 20%):
  - progress **0.051 → 0.438(8.6×)**,node 法 88870 帧(88%);无 node 帧
    (起步 speed<0.3)11210 帧自动退 none(不计分)——D0 修复生效;
  - cte 罚 -0.135 → -0.071(**减半**,循线改善);
  - drift / overspeed / step / timeout **全程恒 0**——Phase A 配置正确生效;
  - done -5e-5 → 0;1720/1721 局 truncated(cte_limit 出界)、1 局
    terminated(撞/翻)——100k 冒烟预期水平,非成品策略。
- **对账**:raw(sim)vs 分解 reward 相关性 0.446——同向不镜像,口径独立,
  分解 reward 在用自己的定义而非复刻 sim。
- **过门快照**:50k mean 107.5 / 100k **195.6**(各 3 局全正)→ 独立快照
  `snap_50000` / `snap_100000`(同路径覆盖禁令生效,无覆盖丢档风险)。
- **课程复现性(端到端)**:两个**重拉的** sim 实例 + 同课程 seed=7 → 5 局
  出生 pos+yaw **逐位一致**;seed=8 全部 5 局不同
  (`curriculum_reproducibility.json`)。带符号 lateral 单测(± 均双侧出现)
  + 序列可复现单测 7 例。
- **校准闸(收尾,自动)**:straight demo 累计 **+11.682**,progress +17.0 /
  cte -5.3 / drift 0 / overspeed 0,符号全符合预期——pass。两次运行逐位相同。

## D4 smoke sync 增量(`docs/arch/rl-m2-smoke-sync.json`)

7 pass / 1 record / 0 fail(窗口 sim + headless 辅助实例):

- item8 语义自检(专用 headless sim = 训练形态):20 步 frame_id 增量全 1、
  idle 1s 冻结(0 增量)、reset 应答 true、步 p50 2.5ms;
- item1 实测 `total_nodes=250`(sim 真发)——node 法激活闭环;
- item6 sync 吞吐量级检查 390 步/s、跨度 300/300 精确;
- item5 断连恢复 7.7s(step 内连接保障自愈——sync 无自由跑线程后的
  唯一自愈入口,由 item5 FAIL 定位补上);
- `--telemetry_fps 60` 异步探针:**59.99 步/s**(CLI 优先级证实,记录性,
  M4 前评测语义项的数据点)。
- 教训入档:窗口 sim 的 sync 步耗时 75ms vs headless 2.5ms(每步渲染相机)
  ——**sync 训练必须 -nographics/keep-gfx**;窗口 sim 渲染循环偶发背景帧。

## 与订单的偏差(诚实清单)

1. item8 语义自检的「停发控制挂 1s frame_id 不动」在**窗口 sim** 上不成立
   (渲染循环偶发 +1 背景帧)——按训练形态(headless)口径执行,窗口现象
   如实记录;订单语义本身在训练形态下严格成立。
2. D2 首跑 bench(335 步/s)在孤儿污染期产生,数字偏低但结论一致;最终
   口径以干净复测为准(383.9),两组数据均留档。
3. 100k 训练实际终身计数 100352(SB3 rollout 边界取整);`--steps` 语义 =
   新增步数,resume 时换算为终身目标(代码注释+运行日志双声明)。
4. eval gate 每次过门即**独立快照**,且评测用独立 sim 实例(+4 端口)——
   订单未指定,为实现层决策(避免与训练 sim 双车共用连接)。
5. SB3 安装经 `uv pip install`(未重算 uv.lock);pin 落在 setup.cfg `rl`
   extra,`uv lock` 重算留给仓库主人(避免本单大面积改动 lockfile)。

## 开放问题(移交 M3)

1. **torch 版本统一**:`torch` extra(2.1.*,Lightning/ResNet18 栈)与 RL 栈
   (2.15.0)不共存——M3 BC 热启动同时用两者时必须统一(torch extra 升级
   会牵动 fastai<2.8 约束,需仓库主人拍板)。
2. **sync 下裸 reset_car 语义**(不带字段不复位)是否要向 sim 侧报修——
   当前训练路径全走带字段课程,无实际影响。
3. eval gate 的过门阈值目前是「比上次好就快照」,无绝对门(如 mean_rew>X)——
   M3 定课程时一并定绝对门。
4. 出生课程量级(±1.0m/±8°)为占位超参,按 M1 对账结论在 M3 用 held-out
   评测校准。

## 自查清单(逐条对照订单)

**必测项**:
- D0 提升逻辑+激活回归单测 ✅(6 例)/ smoke item1 存在性断言 ✅(实测 250)/
  progress_method 全程记录 ✅(components.jsonl 含 progress_method 字段)
- D1 conf 透传 ✅ / 驱动形态切换(无自由跑线程,直连步进)✅ / reset 应答路径 ✅ /
  语义自检进 smoke(item8)✅:frame_id 增量=1/步、停发 1s 冻结、reset answered
- D2 {0.05,0.02}×state ✅ / 0.05×pixel 有超时守卫 ✅ / 2env 双端口进程隔离
  不用 SB3 ✅(死锁零,如实报)/ steps-s、p50/p95、stale、sim CPU 全记录 ✅ /
  **确定性:同 seed+同动作两次 rollout 逐帧比对,max delta 如实报(跨实例 0.0)** ✅
- D3 lr 默认 1e-4 ✅ / --steps 语义注释 ✅ / checkpoint 档位+过门独立快照 ✅ /
  crash 保命档 ✅ / --run-name 隔离 ✅ / 优雅 close→按端口清 sim ✅ /
  活性监控(fps 带宽/sim 失联/ep_rew 冻结/无收束→loud 退出)✅ /
  Phase A+w_done 显式开 ✅ / 分量逐项落盘 ✅ / 出生课程(带符号±+seed 复现)✅ /
  ~100k 冒烟 ✅(100352 步)/ 收尾校准闸 pass ✅
- D4 sync 全套重跑 1-7 ✅ / active_node 断言 ✅ / telemetry_fps 探针(记录)✅

**纪律红线**:
- 零 pkill ✅(分支交付物 grep 无命中;清理仅「lsof→校验命令名→逐 pid」)
- 优雅 close→强杀兜底顺序写死 ✅(env.close / stop_sim / rl_train finally)
- 大文件不进 git ✅(components.jsonl 27MB、模型 zip 留 outputs;证据小文件进 docs/arch)
- 关键功能连 sim 实测 ✅(训练/gate/bench/smoke 全部真实跑通)
- 小步提交、仓库风格 ✅(bc0eef0f → f919817f 共 9 commit)
- 范围外未做 ✅(无 BC 热启动/无视觉训练/未调 reward 超参追策略质量/
  未动 SubprocVecEnv 死锁/未动人驾数据)

## 提交清单(M2 段)

```
bc0eef0f fix(rl): M2 D0——active_node/total_nodes 从 viewer 提升进 info,锁死 node 法 progress
a21c0bd4 feat(rl): M2 D1——DonkeyDriftEnv sync_mode 接线(一控制一帧直连步进)
(同批)  fix(rl): D1 修正——sync reset 自建字面消息路径 + viewer.handler 调用链
67e20efa feat(rl): M2 D2——sync 吞吐表+确定性验证
21b52033 feat(rl): M2 D4——smoke sync 全套重跑全绿(7 pass/1 record)+ stop_sim 自杀修复
56a3e2af feat(rl): M2 D3——SB3 PPO 冒烟训练脚本 + 出生课程 + 两处红线级事故修复
8803fe6d feat(rl): M2 D3——100k PPO 冒烟完成 + 曲线分析器 + 干净端口 bench 复测
f919817f chore(rl): M2——SB3 pin 进 setup.cfg rl extra + 课程复现性端到端证据
```

(`git diff main...feat/rl-sim-pipeline` 现共 14 commit;M2 新增
donkeydrifter/rl/curriculum.py、scripts/{rl_train,rl_train_analyze,rl_sync_bench}.py、
tests/rl/{test_env_info_lift,test_curriculum,test_sim_proc_safety}.py、
docs/arch/rl-m2-*)
