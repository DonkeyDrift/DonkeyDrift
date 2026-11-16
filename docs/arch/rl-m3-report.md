# RL M3 交付报告(BC 走线热启动 A/B + 采样增强 + torch 统一)

- 分支:`feat/rl-sim-pipeline`(M2 已验收,续);日期:2026-11-02 ~ 11-03
- sim:sdsim 构建;SB3 2.9.2 / torch 2.15.0;数据 = 用户走线采样(清洗后 12583 帧/35 局,五门全过)
- **三态结论:【H1 支持】——3/3 种子 held-out Δ 全过 prereg 门,BC 热启动 10~23× 领先**

---

## 一、结论与判定(prereg 口径,`docs/arch/rl-m3-ab-prereg.md`)

### 三态判定(**H1 支持**)

held-out 评测 = ≥2 重拉 sim 实例 × 12 局/实例/臂/种子 × held-out spawn 种子
(50000+,训练未见)× sync 0.05 × state × 分解 reward;按 prereg 的
Δ_s = T_s − C_s ≥ +10%·|C_s| 配对规则:

| 种子 | C(纯 PPO) | T(BC 热启动) | Δ | 过 prereg 门 |
|---|---|---|---|---|
| s7 | 47.96 | **890.48** | +842.52 | ✓(门阈 +4.80) |
| s8 | 42.81 | **551.27** | +508.46 | ✓(门阈 +4.28) |
| s9 | 59.85 | **1102.89** | +1043.04 | ✓(门阈 +5.99) |

- **Δ 过种子数 3/3(prereg 要求 ≥2/3);绝对门(mean_rew≥40)双臂全过 → 无 H2 触发路径**;
- offtrack(C 全 1.0 → T 0.584/0.709/**0.25**)与 ep_len(93/84/100 → 1258/1096/**1821**)同向改善;
- **定性结论:「人驾正向输入 + RL 超越」方法论在 DonkeyDrift sim 域内成立**;
  sdsandbox 证伪史(HBC crash 10/10、PPOBC λ 净负)的口径被精确定位为
  **「跨域(真车→sim)+ 特定数据配方」问题**——in-domain 人驾热启动不仅无害,
  且量级性受益。证据:`rl-m3-ab-verdict.json` + `rl-m3-train/eval_*_i[12].json` 12 份。
- 训练期 gate 曲线同向:T 150k gate 1056.7/199.0/1608.0、300k gate
  **2087.6/3680.9/6509.0** vs C 150k 141.8/185.3/—、300k 172.1/192.6/233.9。

### KL(policy‖BC)监控(仅记录,不进损失;`kl_monitor_console.log`)

- 起步 0.004(resume 瞬间 policy==BC,语义自洽)→ 200k 峰值 ~0.89;
  策略大幅超越 BC 先验 =「RL 超越」的直接信号;判定全程未使用 KL(prereg 约定)。

## 二、数据:采样、清洗、宽线事实(必录)

- **采样**:用户网页键控走线驾驶,原始 `bc_data_web1` 19215 帧/49 局;
  D0 采样器(观测→动作配对 + state_vec 与训练 obs 同函数)全程无口径漂移。
- **清洗(`scripts/bc_filter_idle.py`,数据准备步骤,prereg 判据不变)**:
  原始 42.5% 为静止帧(等待期/圈间停顿被录),14 局几乎纯静止——静止帧会教
  BC「停车」,加剧 sdsandbox 证伪史中的「MSE 多峰→油门蠕行」。规则:整局静止
  占比 >0.6 剔除;局内 throttle<0.05 且 speed 低(真站立)剔除(松油门滑行保留);
  过滤后 <50 帧碎局剔除。**产出 `bc_data_web1_clean` 12583 帧/35 局**,
  hard_frac 0.260→0.352(清洗顺带浓缩了纠偏帧)。
- **|cte|>2 占 57% 的宽线事实(必录)**:清洗集实测 |cte|>2 占 **57.4%**
  (n=12583;|cte|>1 占 76.5%,mean|cte|=3.09)——**人驾走线与 sim 中央线口径
  存在系统性偏移**(赛道宽/中央线≠行车线),而训练 reward 的 cte 罚与
  cte_limit=2.0 截断以中央线为锚。后果:RL 学到贴中央线(评测 mean|cte|≈0.5),
  与教师分布不同仍全面胜出 = progress 主导项的正确性佐证;同时构成开放问题:
  **若 M4 要真车对齐,cte 锚点口径需与行车线定义对齐**(或 reward 换锚)。
- BC 探针门在清洁集重过(img_std 49.5 / hard 35.2% / thr 85.0% / 双侧 / 帧数 12583);
  state-BC val_mse 0.0054(steer 0.0086/thr 0.0022),25 epochs;
  **自检 max|SB3−BC| = 0.00e+00(逐位一致)**——热启动权重正确性的机器证明。

## 三、value head 冷启动混杂(必录)

BC 只灌 pi trunk + action_net(SB3 action_net 是策略 μ 头),**value head(vf)保持
SB3 随机初始化**——T 臂训练初期 value 估计差 → GAE 优势归一化噪声大。表现为
种子间爆发点位不同:s7 在 150k gate 已 1056.7,s8/s9 到 300k 才 3680.9/6509.0
(150k 时 199/1608)。该混杂**不改变 A/B 结论**(对照臂同样 value 冷启动,
T 的 BC 先验只可能帮策略不可能帮 value,领先被低估而非高估),但 M4 做法上
可选择「BC 拟合 value 初值」或「训练初期加大 GAE λ」对冲。KL 监控不受影响。

## 四、交付物明细

| 项 | 提交 | 内容 |
|---|---|---|
| D1 torch 统一 | 3421e6d3 | `torch` extra 标 legacy(车端/Jetson/Lightning 链),与 `rl` extra 互斥;`docs/arch/rl-m3-torch-policy.md` 两链对照表;车端资产零改动;BC/RL 统一纯 torch 2.15 |
| D0 采样器 | 58f8b95b | `env.state_vector()` 公开访问器(与训练 obs **同一函数**);`bc_data.py`(bc_%05d.npz 格式/data card 门/蒙太奇);teleop 重写(观测→动作配对、spawn 起点、r 键新局、auto 切段);13 单测 |
| D3 前置 prereg | 1d62acc9 | 假设/预算/种子/课程/判据/口径先于一切 run 锁定;held-out 执行器 `rl_eval.py` |
| D2 BC 管线 | 63007ede | `bc_train.py`:state-BC(MlpPolicy 镜像)/pixel-BC(NatureCNN 镜像);整局分层 val;过采样;探针门拒训;SB3 zip 导出;**一致性自检 max=0**;7 单测 |
| 绝对门+扫档 | 315b91e1 / 2395a1b6 | 门=mean_rew≥40(定标:四组 held-out12);课程 ±1.8 档 held-out 55.98 落 ±1.0 档带内(48.3/43.0/59.0)→ **M4 默认维持 ±1.0** |
| D5 4-env 探针 | 2395a1b6 | 9101/9104/9107/9110:**1418 步/s 线性**,stale 0,零死锁 |
| KL 监控 | 81c23d9e + d4607ce6 | `--kl-monitor` 只记录不进损失;SB3 2.9 Distribution 无 kl 方法 → torch 泛型 kl_divergence |
| 事故修复 | (M3 段) | `scripts/profile.py → tf_profile_demo.py`(git mv 治本:与 stdlib 撞名遮蔽 torch 导入链,零代码引用);stop_sim 默认端口移除(M2 复盘延续) |

## 五、与订单的偏差(诚实清单)

1. **评测补充了第 2 实例**:prereg 要求 ≥2 实例,M2 的 rl_eval 单实例口径 →
   通过 `--port 9301/9304` 双实例各 12 局(超配到 24 局/臂/种子);
2. 课程扫档只跑了 ±1.8 档 seed7(订单允许 1-2 种子),held-out 单种子落带内
   不定论,M4 默认维持 ±1.0(与 A/B 同课程,公平性优先);
3. D5 的 SB3 SubprocVecEnv 对照子项未执行(时间盒:4-env 进程隔离探针已回答
   「多开可行」,死锁对照留 M4);
4. bc_filter_idle.py 由用户侧交付验收后并入(非本会话编写),本报告按数据
   准备步骤如实收录;原始 `bc_data_web1` 留档未动。

## 六、用户待办(移交 M4)

1. **cte 锚点口径决策**(宽线 57% 事实):真车对齐需定 cte 锚(中央线 vs 行车线);
2. M4 预算:本预算(300k)下 offtrack 仍 >0(T 最优 0.25)——**完赛不是 300k 的
   现实目标**,M4 若要完赛率指标,预算需 1M+ 或先做课程强化;
3. 真车频率决策仍挂起(默认 0.05)。

## 七、自查清单(逐条对照订单验收方式)

- **diff 全读重点**:D2 灌权正确性 = self_check max|SB3−BC|=0.00e+00(机器证明
  + CLI 复现)+ 7 单测;D3 双臂公平性 = 同 rl_train 入口、参数仅差 --resume
  (runner 脚本 `/tmp/m3_treat_runner.sh` 与对照臂 runner 逐项同构)、同课程
  同种子同预算(启动日志三臂 lr/seed/steps 逐项一致)✅
- **pytest 独立重跑**:63 全绿(含 D0 13 例/D2 7 例/安全 5 例)✅
- **BC 探针门/data card 与报告互证**:clean 集五门全过(帧 12583≥3000、
  img_std 49.5>20、hard 35.2%≥15%、thr 85%≥30%、双侧)✅
- **A/B held-out 独立复跑抽样**:12 份 eval json 全留档(可任意抽 instance 重跑,
  重拉实例确定性口径下逐位一致)✅
- **KL 只在记录不在损失**:代码路径 = KLMonitor.feed 仅写 jsonl/打印,
  learn() 无 KL 项;prereg 注明判定不用 KL ✅
- **采样数据质量(data card)达标后才开 A/B**:时间序满足(prereg 1d62acc9 锁定
  于 T 臂启动之前;A/B 实际开跑在采样验收之后)✅
- 红线:零 pkill(清理全走精确 pid/显式端口)/端口隔 ≥2(9091-训练段、9201 对照、
  9221 实验、9301/9304 评测、9101+ 探针)/快照独立命名/crash 档/活性监控
  (全程绿灯)/大文件留 outputs ✅

## 八、提交清单(M3 段,main...feat 共 15 → 24)

```
3421e6d3 chore(rl): M3 D1——torch 链策略定稿
58f8b95b feat(rl): M3 D0——BC 级采样器
1d62acc9 feat(rl): M3 D3 前置——A/B 预注册锁定 + held-out 评测执行器
63007ede feat(rl): M3 D2——BC 训练管线 + 灌权一致性逐位证明
2395a1b6 feat(rl): M3 D5——4-env 双进程探针 + D4 课程扫档
81c23d9e feat(rl): M3 D3 前置——KL 监控接线
d4607ce6 fix(rl): KL 监控改走 torch 泛型 kl_divergence
315b91e1 docs(rl): M3 D4——绝对门定标回填
8803fe6d…17c0aa64(M2 段此前已列)
(本报告) docs(rl): M3 交付报告
```
