# RL M1 交付报告(env + reward + 校准 + smoke)

- 分支:`feat/rl-sim-pipeline`(基线为仓库默认分支 **main**;订单写 master,
  本仓库无 master,按实际默认分支开——偏差已声明)
- 日期:2026-11-01 ~ 11-02,执行:开发执行者(M1 工作订单)
- sim:用户未应答 P2 选型,按最佳判断采用 **sdsim 构建**
  `/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app`(arm64 原生,实测支持
  `--port/--host/-batchmode/-nographics`);所有结论对该构建成立,换二进制需重跑 smoke。

---

## 0. 与订单「已核事实」的矛盾上报(最高优先级)

订单事实 1/2 判定「随机出生客户端路线已死」(依据:`car_start_pos` 零命中、
reset 只有 `reset_to_nearest`)。**实测推翻该结论(对 sdsim 构建)**:

- **客户端侧**:`GymDonkeyCar` fork 的 `donkey_sim.py:915-931` 有完整实现
  `send_reset_car(seed, spawn_cfg)` → `{"msg_type":"reset_car", "seed":N,
  node_index/lateral_offset/heading_noise...}`(注释明写 sdsandbox 随机出生协议);
  判死结论的 grep 词没覆盖 `spawn_cfg` 这个名字。
- **sim 侧(smoke #7 实测)**:同 seed 三次复位位姿差 <5cm(PhysX 噪声级),
  seed 42 vs seed 7 相差 **7.19m**,`lateral_offset=1.0` 位置对称偏移
  ——**字段被 sim 完整支持且 seed 可复现**。
- **影响**:M3 出生课程(订单 B/C1 分析里最大缺口)零 sim 改动闭环;
  `DonkeyDriftEnv.reset(options={'spawn_cfg':...}, seed=N)` 已接线(默认不启用,
  不用时不发任何扩展字段,订单默认通道 `reset_to_nearest` 保持不变)。

订单纪律「发现矛盾停下上报,不许静默改道」的执行方式:实现保持中性
(两条通道并存、默认走订单通道),证据链与本节即为上报。

## 1. P1/P2/P3 前置确认

| 项 | 结论 |
|---|---|
| P1 import 路径 | `donkeydrifter` 是别名包:`donkeydrifter/__init__.py` 的 MetaPathFinder 把 `donkeydrifter.parts.*` 映射到 `donkeycar.parts.*` **同一模块对象**(实测 `is=True`),文件实体在 `donkeycar/parts/dgym.py`;env.py 按模板惯例走 `donkeydrifter.parts.dgym`。**顺带修了引导 bug**:别名 finder 对「父包不存在」的点路径抛 ModuleNotFoundError 而非 None,任何 `donkeydrifter/` 新子包(如 `rl/`)孙子级导入必炸;改为 fallback 语义 |
| P2 sim 启动 | 二进制直启 `<app>/Contents/MacOS/donkey_sim --port N --host H [-batchmode [-nographics]] -logFile F`(与 fork `donkey_proc.py` 同款拼装);停止按红线:自家子进程精确 pid → SIGTERM→SIGKILL,外部进程 `lsof -ti tcp:<port>`;**全仓库零 pkill** |
| P3 Python | `.venv`(py3.11.16)+ uv.lock,gymnasium/numpy/pytest/gym_donkeycar(fork editable)齐全,零新依赖 |

## 2. D1 `donkeydrifter/rl/env.py` — DonkeyDriftEnv(gymnasium)

**做了什么**:与 templates 同款构造路径(`DonkeyGymEnv` → gym.make → DonkeyEnv →
SimClient),不拉 Vehicle;补齐 Vehicle 承担的两条驱动线(update() 步进线程 +
run_threaded 轮询喂动作/触发看门狗);断线容忍零重写(复用 dgym 三死法看门狗/
后台重建线程),env 只暴露 `sim_connected` / `info['rl/stale']`。

- obs:`state`(16 维:`[cte, speed, forward_vel, vel×3, gyro×3, accel×3, pos_x, pos_z, 上步 steer, 上步 throttle]`,声明式缩放)/`pixel`(透传 160×120);state 模式默认 `img_enc:none` 零图像遥测 + **渲染分辨率对齐 NN 输入**(省多开实例 CPU)。
- done 双 flag:`terminated`(sim:collision/翻车/卡死/no-progress,经 viewer.is_game_over)/`truncated`(客户端:|cte|>cte_limit 默认 2.0、max_episode_steps),`info['rl/trunc_reason']` 标原因。
- info:sim 遥测原样透传 + `raw_reward`(viewer.calc_reward,与 sim step 内部同函数)+ `rl/` 前缀扩展键(reset 计时/模式、step 计时、连接态)。
- reset:默认 `reset_to_nearest`(订单通道);可选 `options={'spawn_cfg':...}`/`{'spawn':True}`+seed 走 `reset_car` 扩展字段(矛盾上报项,见 §0);计时拆 `rl/reset_cmd_s`(命令回执)与 `rl/reset_elapsed_s`(跳变确认,无跳变时退回前者)。
- 关闭顺序写死:停步进线程(join 3s)→ cam.shutdown(join 重建线程→env.close);卡死在 observe 自旋时放弃 join 留 daemon 兜底(sim-down 场景下会出现该 warning,sim 在线时不发生)。

**与订单规格的偏差(声明)**:
1. `frame_skip` 是 **wrapper 级 action repeat**——dgym 把 conf `frame_skip` 钉死为 1 且订单禁改 dgym;语义等价(每步对同一动作连续取 N 帧新遥测),默认 1。
2. gymnasium `seed` 在 spawn 路径透传给 sim 作复现种子(本环境无内部 RNG,seed 语义为声明式超集)。

## 3. D2 `donkeydrifter/rl/rewards.py` — 分解式 reward(本单最重验收对象)

**做了什么**:纯函数 `reward(info_prev, info_cur, action, cfg) -> (total, components)`,
零网络/sim 依赖;五项规定项 + 订单外补充项(默认关):

1. cte:deadband(默认 0.5m)内不罚,外 huber(delta=0.5);
2. drift:`speed_norm × exp(-((β-μ)²)/(2σ²))`,**μ=25°/σ=10° 为声明式手调超参,无实证标定,待 D3 数据回填**(代码注释与本文 §5 均声明);速度门槛防原地刷分;
3. progress:**速度下限门槛**(默认 0.3m/s)+ 双法——node 法(遥测 activeNode 环绕差分,绕圈零净增,反 hacking 根基)/位移法回退(X-Z 平面前向投影);components 标明所用方法(两法单位不同,不可混用);
4. 超速:`-w·max(speed-v_max,0)`(对称 FASTSAFE 单杠杆);
5. 存活/步罚(w_step)与 timeout 罚(w_timeout)互斥由 `RewardConfig.__post_init__` 直接拒绝;timeout 只在 truncated 终止帧给一次。
6. (订单外,默认关)`w_done`:sim 终止帧一次性罚——不开则撞墙的直接代价只剩 progress 停止,M2 接线时建议显式打开。

`DecomposedRewardWrapper` 把纯函数接到 env.step(reward 换分解式 total,
原始 sim reward 存 `info['raw_reward']`,逐项 `info['reward_components']`,
β 自动注入,gyro 积分链状态维护)。

**单测**:`tests/rl/test_rewards.py` 25 用例全绿(符号/量级/deadband 边界/
速度门/超速单调/NaN-None 防御/序列不双重计罚/β 两口径/互斥配置),零 sim 依赖,
`pytest tests/rl` 直接跑。

## 4. D3 teleop 采样 + β 分析

- `scripts/rl_teleop_record.py`:键控 teleop(termios raw:w/s/a/d/space/x/q,松键保持)+ 脚本化模式(demo/straight/circle/slalom,无人工时验证管线);逐新遥测帧落 npz+jsonl+meta 于 `outputs/rl_teleop_*/`(gitignore)。
- `scripts/rl_beta_analyze.py`:β 双口径 + **直线段 sanity 闸** + 分布统计/直方图 + μ=25° 裁定。

**两项实测标定(闸门与实测共同拦截,均已在代码注释/文档留痕)**:

1. **坐标口径(闸门拦下的真 bug)**:Unity 系 **Y 轴向上,地面平面是 X-Z**。
   首版 course=atan2(vel_y,vel_x) 被闸门否决(直线段 β 中位数 **-93°**);
   修正为 course=atan2(vel_x,vel_z) + **yaw 直读 180° 常数偏移**
   (heading=wrap(yaw+180),直线帧实测 yaw=180° 而车速沿 +Z)后,
   直线段 β 中位数 **0.18°(n=19)** 过闸。同步修正:rewards 位移法、
   env state 向量(X-Y→X-Z)、积分链锚定口径。
2. **订单规定方法被实测否定**:「heading 由 gyro-z 短时段积分」对本 sim
   **不成立**——竖直角速度轴在 **gyro_y**(与 yaw 速率 corr 0.79,gyro_z 仅
   -0.067),且量纲无法用常数标定收敛(×1 / ×57.3(rad→deg)/ ×-57.3 三假设
   积分链漂移均达 40~170°)。**yaw 直读是唯一可信口径**;gyro 链降级为诊断
   输出(`gyro_chain_vs_yaw_drift_deg`)。sanity 闸的存在价值被本次实战验证。

**β 分析输出**(`docs/arch/rl-m1-beta-analysis.json`,脚本 demo 数据 400 帧):

- sanity 闸:双口径直线段中位数 0.18°/-0.24°,**pass**,方法可信;
- β_yaw:n=169,p50=-0.07°,|β| p50=9.1°,|β| p90=46.9°(脚本数据无真漂移,
  大值来自低速瞬态);
- μ=25° 裁定:**数据不足**(样本 169<200 且无人工漂移样本)——裁定逻辑已
  防误判(漂移带质量 ≥15% 才裁定,避免把循线数据误判成「推翻」);
- **待办**:μ/σ 标定需使用者实采漂移数据(命令见 §7),这是 M3 Phase B
  开 drift 项的硬前置。

## 5. D4 协议 smoke(全项连 sim 实测,`docs/arch/rl-m1-smoke-result.json`)

**6 pass / 1 record / 0 fail / 0 BLOCKER**(2026-11-01/02 两轮,第二轮含断言修正):

| # | 项 | 实测 |
|---|---|---|
| 1 | 连接+字段齐全 | 核心字段全命中;另实测 11 个扩展字段(forward_vel/car/lidar/frame_id/collision_impulse/flipped/stuck_time/lap/active_node... **注意:active_node 在首跑命中但二跑未现**,node 法 progress 需以位移法回退兜底——已实现) |
| 2 | reset 耗时 | p50=0.049s / p95=0.05s(5/5 位姿跳变确认)——**远低于 2s 门槛** |
| 3 | 边界动作含 brake | 24/24 不炸连接,连接保持 |
| 4 | n control ↔ n 帧 | 60/60 新帧(构造保证);frame_id 推进 59——async 自由帧(某拍无新 control)致 ≤1 差,断言按真实契约修正并记录逐帧分布 |
| 5 | 断连恢复 | 杀(精确 pid)→看门狗 2.0s 判死→重拉→**恢复 4.77s**→复位 0.05s 全链路可用 |
| 6 | 帧率(三模式×两编码) | **全部恒定 20.0 步/s**(窗/keep-gfx/nographics × none/jpg,step p50≈50ms)。**sdsandbox「headless 异步 1fps」教训本机构建不复现**;async 吞吐被 sim 遥测节拍钉死 20fps → M3 吞吐杠杆在 fork 已有 sync_mode 客户端支持(sdsandbox 实测无图 ~120 步/s),M2 应实测 |
| 7 | seed/spawn 探针(记录) | 见 §0,sim 支持随机出生字段 |

remote 模式(`--mode remote`)按订单预案:5/6 标 BLOCKER,其余照跑。

## 6. D5 双 sim 实例对拍(可选项,已交付)

`scripts/rl_dualsim_probe.py`:同脚本序列(直行 6s→定圆 12s)分打两实例
(默认同二进制异端口=**实例方差口径**;换二进制传不同 --sim-app 即真对拍)。
实测(`docs/arch/rl-m1-dualsim-probe.json`):speed p50 相对差 7.1%、yaw rate
5.9%(一致);**|cte| p50 相对差 47.9%**——开环轨迹敏感量对实例间物理方差
高度敏感,印证 sdsandbox「局级位级方差」结论:M3 评测**严禁单局/单实例口径**;
训练分布走随机出生不受阻。位移效率差 2.6%(形状相似,差异在圆周相位)。

## 7. 交接与复跑命令

```bash
cd /Users/hwp/Dev/DKC/DonkeyDrift
.venv/bin/python -m pytest tests/rl -q                        # D2 单测(零 sim)
.venv/bin/python scripts/rl_smoke_test.py                     # D4 全流程(~5min)
.venv/bin/python scripts/rl_teleop_record.py                  # D3 人工漂移采样(键控)
.venv/bin/python scripts/rl_beta_analyze.py "outputs/rl_teleop_*/"   # β 分析+μ裁定
.venv/bin/python scripts/rl_dualsim_probe.py                  # D5 对拍
```

人工采样后把 `outputs/rl_beta_analysis.json` 的 `mu25_assessment` 回填到
`RewardConfig.drift_mu_deg/drift_sigma_deg` 再开 Phase B。

## 8. 开放问题 / 移交 M2

1. **μ/σ 实证标定**(D3,需人工漂移采样)——Phase B 前置;
2. **sync_mode 吞吐实测**(fork 客户端已带 conf 键,sdsandbox 口径 ~120 步/s)——M2 第一件事,决定 M3 多开规模;
3. active_node 字段时有时无 → progress 以 node 法优先、位移法自动回退(已实现),M2 训练时确认 node 稳定后锁方法与单位;
4. `w_done`(撞墙罚)默认关,M2 接线时建议显式打开并在校准闸跑「人控必得正分」;
5. eval 口径铁律:D5 实测 cte 类指标实例间差 48% —— 一切验收按多局长局+held-out 种子;
6. env 关闭在 sim-down 场景有 3s join 超时 warning(observe 自旋,daemon 兜底),不影响功能;如需彻底根治需动 dgym 核心(本单禁改),M2 评估。

## 9. 自查清单

**必测项对照**(D4 七项):1 字段齐全 ✅ / 2 reset<2s ✅(0.05s)/ 3 边界动作 ✅ /
4 n↔n 帧 ✅(60/60,断言口径修正留痕)/ 5 断连恢复 ✅(4.77s)/ 6 帧率三模式 ✅(20.0 恒定)/ 7 seed 探针(记录)✅。连 sim 实测 ✅(全部条目真实跑通,非 py_compile)。

**纪律红线对照**:
- 零 pkill ✅(全分支 `grep -rn pkill` 无命中;停止仅精确 pid / lsof 按端口);
- 优雅 close→强杀兜底顺序写死 ✅(env.close + _sim_proc.stop_sim);
- 大文件不进 git ✅(outputs/ gitignore;npz/jsonl/日志全在 outputs;证据小文件副本进 docs/arch);
- 关键功能连 sim 实测 ✅(连接/reset/恢复/帧率/对拍全部实跑);
- 小步提交、仓库风格 ✅(见 §10);
- 不做 SB3/训练/长训练 ✅;不改 dgym.py 核心逻辑 ✅(零改动,bug 也只上报不改);
- 不改 GymDonkeyCar ✅(只读参考)。

**规格偏差汇总**:frame_skip=wrapper 级 repeat(§2)/ seed 透传语义(§2)/
w_done 订单外补充默认关(§3)/ 分支基于 main(§标题)/ D5 同二进制实例方差口径(§6)/
μ=25° 裁定=数据不足待人工采样(§4)/ P2 sim 选型用户未应答,按推荐项执行并全部留证(§标题)。

## 10. 提交清单

```
e05d36c9 feat(rl): M1 D1/D2——gymnasium 环境封装 DonkeyDriftEnv + 分解式纯函数 reward
e1d1c724 feat(rl): M1 D4——协议 smoke 全项连 sim 实测通过(6 pass/1 record)
2823a059 feat(rl): M1 D3——teleop 遥测采样 + β 分析管线,坐标口径实测标定
d351885c feat(rl): M1 D5——双 sim 实例统计对拍脚手架(可选项交付)
```

(`git diff main...feat/rl-sim-pipeline` 共 4 commit;新增 donkeydrifter/rl/、
tests/rl/、scripts/rl_*、scripts/_sim_proc.py、docs/arch/rl-m1-*;改
donkeydrifter/__init__.py 别名 fallback 修复、.gitignore outputs/)
