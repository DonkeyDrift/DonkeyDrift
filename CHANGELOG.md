# 变更日志

## 2026-09-04 (175)

- perf(frontend, backend) + feat(web-ui): Pilot Arena 推理链路优化（config 按 mtime 缓存 + 评估节流 250ms→逐帧）+ 批量预测新增「模型贴合摘要」
  - **背景（实测分解）**：DKG-1.tflite(120×160 float32) 裸 TFLite 推理 1.24ms(≈807FPS)、`pilot.run` 1.33ms(≈750FPS)，模型本身非瓶颈；真瓶颈是 ① `web_ui/backend/routers/arena.py` 每次 predict 重新 `load_config()` 编译执行 config.py+myconfig.py ≈**75~80ms/帧**（占 97%，且每帧刷两行 `INFO:donkeycar.config` 日志）② 前端 `PilotArenaPage.tsx` 评估节流硬下限 250ms → 观察到的"4~5FPS"。
  - **后端**：`arena.load_car_config` 按 (config.py, myconfig.py) mtime 缓存（线程锁 + 变化即重载；`arena.py` 模块级 `_car_config_cache`）。效果：单帧预测（缓存 config+磁盘读图+解码+TFLite）**79ms → 1.72ms（≈580FPS）**；config INFO 日志仅在首次/配置保存后出现一次。全部调用点（predict/preview/批量/load）共享缓存，无行为回归（mtime 变化即失效）。
  - **前端**：推理评估节流下限 250→**16ms**（与图像加载一致，评估节奏=逐帧播放 `DRIVE_LOOP_HZ`，60Hz 时每播放帧一次推理）；新增 config 旋钮 `ARENA_PREDICTION_INTERVAL_MS`（可调大限流）；`ARENA_INFERENCE_CONCURRENCY` 上限 2→4。inference 徽标预期从 ~4 提升到接近播放帧率（受 DRIVE_LOOP_HZ=60 约束 ≈60）。
  - **新功能（规划 §3.3「模型性能指标摘要」）**：`POST /api/arena/pilots/{id}/predictions` 响应新增 `summary`——角度/油门两序列各自的 MAE/RMSE/平均偏差(bias=pilot−user)/max|err|/count，非有限值所在帧自动剔除；纯函数 `compute_prediction_metrics`（arena.py）+ 前端 Tub Plot 图下「贴合摘要」展示区（i18n zh/en 各 10 词条）。批量 200 帧含摘要 330ms（≈606FPS 当量）；摘要计算 ~0.27µs/点（20 万点 53ms），开销可忽略；全缓存命中重跑 1.1ms。
  - **测试**：`test_arena.py` +4 例（config 缓存语义 1 + 摘要 3，TDD 先红后绿）。后端 `pytest tests/` **340 passed + 2 skipped**；其中 `test_drift_vision.py::TestAdaptiveDetection` 4 例失败为**本机(Linux)既有环境问题**——`drift_vision.py:30` try 导入 `pupil_apriltags` 不在此环境（无 `_PupilDetector` 属性），与本次改动无关（未触碰 drift 链路文件）；Windows 基线 345 全绿无此问题。前端 vitest **158 passed**（27 文件）+ `tsc -b` + `npm run build` 全绿。
  - 注：仅 DD 改动（arena 后端/前端 6 文件 + 测试 + 本日志），未 git 提交（工作区待用户 review）；浏览器端 FPS 徽标提升与真机多 viewer 并发负载待明早人工确认。

## 2026-09-03 (174)

- chore(security): 隐私防漏加固与泄露清理——`.gitignore` 补全密钥/证书/agent 目录屏蔽规则；移除被旧分支合并复活的 `AGENTS.md`/`CLAUDE.md` 跟踪
  - 背景：两仓库安全审计（GitHub 均为公开）确认本仓库文件内容（含全历史）无密钥/邮箱实质泄露；但发现 main 尖端被旧分支（eed2e4d4 "init"/27dbd9e1 "Rename to DonkeyDrift" 经今日合并）复活了 `AGENTS.md`/`CLAUDE.md` 的跟踪——内容为旧版开发指南、无凭据，但按约定 agent 说明文件不入库，本次重新解除跟踪（本地文件保留，`.gitignore` 的 `/AGENTS.md`、`/CLAUDE.md` 规则本已存在、此前被跟踪导致无效）。**注意：旧基点分支合并进 main 会复活早已移除的文件，合并前务必检查 diff。**
  - `.gitignore` 新增：`.env`/`.env.*`、`*.pem`/`*.key`/`id_rsa*`/`known_hosts`/`*.ovpn`/`*.p12`/`*.keystore`/`credentials*`/`secrets*`、`*.log`、`.claude/`/`.agents/`。经 `git ls-files` 确认无被这些规则命中的其余已跟踪文件。
  - 无代码行为变化、无需本机部署（纯仓库卫生）；Tony 分支同等改动见 2026-09-03 (165)；Firmware 侧配套清理见 `Firmware/MUS4_FW/CHANGELOG.md` v1.8.66。

## 2026-09-01 (173)

- fix(drift): 俯拍系统全量夜间审计与加固——5 领域并行审计 40+ 发现，安全链路/线程安全/NaN 防线/WebRTC 协议/脚本可靠性全面修复，后端测试 257→345 全绿
  - **安全链路（最高优先）**：
    - 相机循环异常护栏（`drift_engine.py`）：核心链路（检测/解算/估计/控制/落盘）整体 try/except——异常即计数+日志+看门狗+干净退出（finally 停泵），此前任一异常杀线程且句柄泄漏、看门狗不触发。
    - 看门狗三链路补齐（RFC 第 9 节）：ENGAGED 期 检测丢失>0.2s（按相机时戳）/遥测停滞>0.5s/控制下发连续失败≥3 均触发交还人工；此前仅泵线程死亡一项落地，`Watchdog.expired()` 是无人调用的结构僵尸。`trigger_watchdog` 修正为仅 AUTO 期间才下发车控（非 AUTO 只记事件——预览毛刺不再误动车辆）。
    - NaN 全链路防线：估计器非有限输入按丢帧处理（`nan_dropped` 计数）；控制器非有限输入抛 ValueError 走护栏；`PoseSolver.push` 拒收非有限位姿（可返回 None，引擎按丢帧兜底）；单应 `from_file` 校验 shape/有限性/行列式，`_map` 除零显式报错。此前 `min/max` 顺序使单帧 NaN 退化为满舵+积分永久钉满幅、估计器不可恢复。
    - 引擎 stop 竞态：泵线程卡死（DSHOW 僵尸句柄）时跳过 `camera.close()`（并发 release 是 UB，泄漏给 OS 更安全）；`main.py` 加 shutdown 钩子+atexit 兜底释放相机；`/camera/start` 重入守卫（幂等停旧启新）+ 检测器构造失败关闭相机句柄。
  - **线程安全**：`TelemetryBuffer`/`ThrottlePulseAnalyzer` 加锁（push 在事件循环线程、interpolate/features 在相机线程，两段 insert 非原子可致 IndexError/错配）；遥测缓冲 30s 前缀裁剪（原 maxlen 是死代码，小时级会话可涨 150MB+）；`DriftSession` 状态迁移加锁 + `events` 有界（500）；`install_drive_hooks` 幂等。
  - **控制器**：delta 限幅 dt 化（新键 `max_steering_rate_per_s`，旧 per-tick 键 ×60 兼容映射，`effective_max_steering_rate_per_s` 统一口径）；脉冲 duty/amp/base 热更新生效（原仅频率每拍回写，面板改其余三参数无效）；半径环符号配置化 `radius_freq_sign`（默认 −1 按 RFC §7.3 机理负反馈：偏内→降频——原实现偏内增频按 RFC 机理是正反馈，M2 实证相反则置 +1）。
  - **估计器**：割线基线取点修正（取**最新**满足跨度的点，稳态跨度回到设计值 0.2s，此前取窗内最旧点使 0.5s 窗长成为实际基线）；dt=0 静止衰减冻结而非清零笔误修复；`anchor()` 补清 `_last_t`。
  - **WebRTC 两端**：前端 `DriftCard.tsx` 等 ICE gathering 完成再 POST 且用 `pc.localDescription`（原实现 POST 零候选的旧 offer.sdp，aiortc 无 trickle → 60fps 路径必败永远回退 MJPEG）；连接态监控+首轨 5s 超时回退。后端 `handle_offer` 协商失败清理 pc（原垃圾 SDP 每次泄漏一个 RTCPeerConnection）；节拍换 monotonic；黑帧缓存复用；disconnected 态清理。
  - **前端 DriftCard 重写**：cameraOn 以后端快照 `camera_running` 为权威（刷新/多标签不再脱钩）；i18n 全量（`drive.drift*` 38 词条 zh/en）；轮询改串行+3s 超时+连续失败离线徽标；「标定」按钮补齐、按钮 gating 对齐后端 `calibration_ready` 守卫；输入 Number.isFinite 校验+物理域 clamp；saveParams 竞态/lazy localStorage/MJPEG 走 API_URL。新增 `DriftCard.test.tsx` 16 例。
  - **脚本（明早验收链路）**：三脚本 `sys.stdout.reconfigure(utf-8)` 根治 GBK 控制台 ✅ 打印崩溃（原崩在写报告文件**之前**）；`measure_loop_latency.py` 排空 ws 初始推送（原首两个 RTT 样本是假的）+视觉段复用生产检测器配置（downscale=2/锐化 0.6/`--exposure`）+无有效样本不误报超预算+超预算退出码 1+报告先落盘后打印；`analyze_throttle_pulses.py` 参数/tub 路径中文错误提示；`calibrate_field_homography.py` ESC 随时可退+try/finally 释放相机+屏幕提示改英文（putText 不支持中文）；`build_drift_clip.py` 多 tub 独立段拼接（原单段早退致时戳可回退为负）+Windows 反斜杠路径文件名修复+speed 校验。
  - **测试**：新增 `test_drift_engine_watchdog.py`（6 例）/`test_drift_engine_integration.py`（8 例）/`test_measure_loop_latency.py`（12 例）/`test_analyze_throttle_pulses.py`（3 例）/`test_simulate_drift_controller.py`/`DriftCard.test.tsx`（16 例）；修复两处空洞断言（观察期零下发语义化、smoke EMA 恒真改 >0）。全部 TDD 先红后绿。
  - 验证：后端 pytest **345 全绿**；前端 vitest 156 全绿 + `tsc -b` + `npm run build` 通过；离线仿真 β=24.72°/极差 0.47° 收敛；脚本实跑退出码正确。仓库根 tests/ 的 4 收集错误（fcntl）+3 失败（SIGKILL/前端构建判定）为本机 Windows 平台既有问题，与本次无关。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA；未做 git 提交（工作区待用户 review）；全程纯本地。审计全量发现与遗留实车核对项见交接文档 §9。

## 2026-09-01 (172)

- fix(drift): 控制链路航迹角换 0.2s 割线基线（M4 前最后软件遗留项清零）+ FakeCamera 节拍根治测试抖动 + 交接文档状态核实
  - `web_ui/backend/state_estimator.py`：`BetaEstimator` 航迹角由逐帧差分+半步外推改为 **0.2s 割线基线 + 陀螺横摆率半程外推**（割线代表基线中点时刻方向，β̇≈0 假设下外推 span/2 消滞后）——低速段逐帧位移贴近 2cm 阈值被位姿噪声主导、方向随机（§4.4 实车 β 箭头乱指同款根因，显示链路此前已换 `trail_course_deg`，本次控制链路对齐）。新增构造参数 `course_baseline_s=0.2`/`pose_window_s=0.5`；位姿滑窗 deque 取代单点 `_prev`；`anchor()` 清窗。对外接口不变（`drift_engine.py` 调用点零改动）。
  - 测试（TDD 先红后绿）：`test_state_estimator.py` 新增 `TestSecantBaselineCourse` 2 例——低速噪声直行（0.5m/s@60fps + σ8mm 位姿噪声）β 均值收敛 25°±4° 且 std<8°（旧实现实测红：std 60°）；爬行 0.15m/s 航迹角正常解算（旧实现 course 恒 None、β 卡 0）。
  - `web_ui/backend/drift_vision.py`：`FakeCamera.read` 加 60fps 节拍 sleep，根治泵线程自由空转吃满单核致 `TestCameraLoopSmoke` 重载抖动（交接文档 §8.3 教训 3）；`test_drift_vision.py` 新增 `test_fake_camera_read_is_paced` 固化。
  - 交接文档 `docs/guide/overhead-drift-handoff.md`：§6「分支未合并 main」核实为**已合并**（tip 3bbc3d03 同为 `feat/overhead-drift-control` 与 `main` 分支头）并勾销；§6 course_deg 遗留项勾销（M4 前软件遗留清零，剩余全是实车核对项）；§7 代码地图与 §8.3 同步。
  - 验证：后端 pytest **257 项全绿**（254→257）；离线仿真 `simulate_drift_controller.py` 复跑 β=24.72°/极差 0.47° 仍收敛（β\*=25°）。仓库根 `tests/` 的 4 个收集错误（launcher 依赖 Unix `fcntl`）与 3 个失败（`signal.SIGKILL` Windows 不存在、前端构建新旧判定）为本机 Windows 平台既有问题，与本次改动无关（改动仅 5 文件：docs 1 + backend 4）。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA；全程纯本地，未碰 GitHub。

## 2026-08-30 (171)

- feat(drift): 俯拍漂移监控系统全量落地——方案 C 状态估计+反馈控制整链实现，M0 相机链路收官（60fps），分支 `feat/overhead-drift-control` 合并入 main
  - 背景与架构：笔记本（FastAPI :8000 + React 前端 + USB 俯拍相机）检测车顶 AprilTag（tag36h11 ID 0）→ 场地坐标位姿 → β 估计 → 级联 PID + 油门脉冲发生器 → ws 下发控制；车端 SBC 主动回连上报 rc/IMU 遥测；**人工控制始终走 RC 遥控器（ESP32 本地），笔记本只接管、随时可夺回**。里程碑 M0（相机链路）✅ 收官，M1（人工漂移录制）/M2（点动机理验证）待实车实操。
  - 设计与文档：`docs/Rfc/overhead-drift-control.md`（总设计 13 节）、`docs/plan/overhead-drift-control-implementation.md`（M0~M5 里程碑与验收门禁）、`docs/guide/overhead-drift-first-run.md`（实操手册）、`docs/guide/overhead-drift-handoff.md`（状态交接+踩坑记录）。
  - 后端模块（`web_ui/backend/`，全部 TDD 先红后绿）：
    - `drift_vision.py`：场地单应性/位姿解算（heading_offset_deg 贴标朝向补偿）；PoseSolver 跳变拒绝+持续离群（5 帧一致）恢复；USBCamera 手动曝光（DSHOW log2 秒语义，重构废弃错误的 exposure_us）；检测=半分辨率快速路径+decode 锐化 0.6+全分辨率自适应重试；叠加绘制=加粗绿框/车头红箭/2s 速度着色轨迹（绿→黄→红）/深蓝 β 航迹箭（0.2s 割线基线抗噪）。
    - `state_estimator.py`：β 估计 heading 域互补滤波（视觉割线+陀螺 gz 积分），静止 0.3s 时间常数衰减归零（消除残影与 AUTO 误触发）。
    - `drift_controller.py`：级联 PID + 油门脉冲发生器（频率/占空比/幅值）+ delta 限幅 + 看门狗（丢帧/断线零油门）。
    - `drift_session.py`：会话状态机（观察 → β 稳定 → 接管）。
    - `sync_recorder.py`：以相机帧时戳为基准对齐 ws 遥测流（rc 60Hz/imu 100Hz）线性插值，在线提取点动特征，tub v2 写入。
    - `throttle_analysis.py`：点动机理离线分析（相关性+低/中/高分档参数表）。
    - `drift_engine.py`：相机循环编排，分段计时诊断（read_ms/detect_ms/camera_fps），display_frame 逐帧透传+检测成功叠加，frames_total/tag_hits 命中率计数。
    - `routers/drive.py`：AUTO（观察/接管）期间浏览器控制字段服务端仲裁——一律丢弃并回发 `control_rejected`。
    - `drift_webrtc.py`：aiortc 60fps 推流（运动画面降 360p 编码），MJPEG 自动兜底。
  - 前端：`DriftCard.tsx`「第三视角漂移」卡片——WebRTC 预览/MJPEG 兜底/相机接入表单/模式控制/参数面板，启动参数 localStorage 持久化回填；朝向/β/速度实时数值格。
  - 脚本：`generate_apriltag.py`（tag36h11 打印件，螺旋位序，官方检测器 hamming=0 闭环验证）、`calibrate_field_homography.py`、`calibrate_overhead_camera.py`、`measure_loop_latency.py`、`analyze_throttle_pulses.py`、`simulate_drift_controller.py`（离线闭环仿真 β 收敛 25.00°/极差 0.01°）。
  - 实操验收（M0）：1.0×1.0m 场地四点单应性标定完成（仓库根 `field_homography.npz`）；处理循环 60fps 稳定（read≈16.7ms、detect≈8ms@360p）；运动丢检测四层排障闭环——显示帧逐帧透传/PoseSolver 跳变恢复/锐化+全分辨率重试/**相机曝光 1/400s 根治运动拖影**（物理层根因）。
  - README：新增「俯拍漂移监控系统 (Overhead Drift Control)」章节（架构链路/核心能力/模块地图/文档链接），Features 与 Documentation 列表同步补充。
  - 测试：`web_ui/backend` pytest **254 项全绿**（基线 199→254，+55）；前端 build 验证通过。
  - 注：仅 DD 改动；M0~M5 详细状态与运维纪律（Windows 僵尸进程清场、热重载不可信、五链路帧率定位法）见交接文档 §4。

## 2026-08-23 (164)

- feat(drive): Drive 页新增「模拟器采集」卡片——浏览器一键经后端 SSH 控制 Mac 上的 donkey_sim 跑采集，实时进度/cte/速度，完成后展示结果摘要
  - 背景：8-23 已把"Linux 经 SSH 控制 Mac 上的 DonkeySim 采集数据"跑通为命令行管线（`mycar/collect_sim_mac.sh` + `mycar/collect_sim_data.py` 远程模式，1500 帧实锤）。本次将其包成 DD Web UI 功能，用户在浏览器 Drive 页点「开始采集」即自动完成 SSH 启停 Mac sim + 采集 + 数据落盘，无需命令行。
  - 后端：
    - `web_ui/backend/simcollect_engine.py`（新增）：`SimCollectJob` + 单例 `SimCollectJobManager`，仿 `connector_engine`；以 `asyncio.create_subprocess_exec("bash", collect_sim_mac.sh, env, start_new_session=True)` 启动编排脚本，逐行解析 `[collect] step i: ... cte=.. speed=..` → progress、`RESULT steps=.. mean_cte=.. max_cte=.. crashed=.. out=..` → done 结果、`[mac-collect] 错误: ..`/非零退出 → error；stop 用 `os.killpg(SIGTERM→SIGKILL)` 终止整组（让脚本 EXIT trap 完成 Mac 侧 sim/隧道清理）；同时只允许一个 running job。解析函数抽为模块级纯函数（parse_step_line/parse_result_line/parse_error_line）便于单测。
    - `web_ui/backend/routers/simcollect.py`（新增）：`POST /api/simcollect/start`（steps/kp/kd/throttle/min_throttle/keep_sim，已有任务在跑 409）、`GET /api/simcollect/{job_id}/status`、`POST /api/simcollect/{job_id}/stop`、`GET /api/simcollect/{job_id}/events`（SSE，含 15s keep-alive 心跳）。
    - `web_ui/backend/main.py`：挂载 simcollect router（`/api/simcollect`）。
  - 前端：
    - `web_ui/frontend/src/services/api.ts`：新增 `SimCollectStartParams`/`SimCollectJobState`/`SimCollectResult`/`SimCollectStatus` 类型与 `startSimCollect`/`getSimCollectStatus`/`stopSimCollect`/`createSimCollectEventStream` 四函数。
    - `web_ui/frontend/src/hooks/useSimCollectJob.ts`（新增）：自包含 local state，SSE 优先推送 progress/log/status，SSE 断开且未到终态自动降级 2s 轮询 status 兜底；409 → 已有任务在跑提示。
    - `web_ui/frontend/src/components/drive/SimCollectCard.tsx`（新增）：卡片 UI——标题/说明、步数输入、可折叠高级参数（KP/KD/油门/最低油门）、开始/停止按钮、运行中进度条+实时 cte/速度、完成结果摘要（步数/mean|cte|/max|cte|/是否冲出/输出目录）、出错信息+可展开日志；全文案走 i18n。
    - `web_ui/frontend/src/pages/DrivePage.tsx`：根容器主 flex 行后插入 `<SimCollectCard />` 全宽卡片（最小侵入，未重排其它结构）。
    - `web_ui/frontend/src/i18n/messages/drive.ts`：新增 `drive.simCollect*` 词条 25 条（zh/en 双份）。
  - 测试同步：`web_ui/backend/tests/test_simcollect.py` 12 项（行解析纯函数 + start/status/stop/conflict 404/错误退出，子进程级 FakeProcess mock）；后端 `pytest tests/` 118 项全绿。前端 `SimCollectCard.test.tsx` 5 项（mock `useSimCollectJob` 控制 idle/running/done/error 状态断言文案与参数）；前端 `vitest run` 25 文件 138 项、`tsc -b`、`npm run build` 全绿。端到端实测：worktree 后端（8123）跑 `POST /simcollect/start {steps:20}` → SSH 启 Mac sim → 采 20 步 → status=done、result 正确解析、数据落 `mycar/sim_collect_20260823_141731`。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA。采集编排脚本与采集脚本（`mycar/collect_sim_mac.sh`、`mycar/collect_sim_data.py`）为本机工作目录文件、非 git 仓库，不在本次 commit 范围（已在前序 mycar 工作中就绪）。全程纯本地，未碰 GitHub。

## 2026-08-23 (163)

- fix(trainer): 修复 macOS 远端训练 loss 发散——createcar 模板 mixed_float16 加 macOS 门控 + createcar 成功后远程 sed 补丁立即生效；顺带修 train() comment 位置参数错落 bug
  - 背景（问题 8「训练 loss 上升」排查实锤）：同一批 12531 条数据、同一代码，本机（NVIDIA CUDA）训练收敛（val_loss→0.017），Mac（Apple Metal）3/3 发散（train loss 0.47→2.60、val 降）。createcar 生成的 `train.py` 无条件 `mixed_precision.set_global_policy('mixed_float16')`——CUDA 上正常，Metal/CPU 上数值不稳定导致发散。
  - `donkeycar/templates/train.py`：mixed_float16 由无条件启用改为「非 macOS 且有 GPU」才启用（`if gpus and sys.platform != 'darwin':`，否则打印跳过原因）；`/home/dkc/projects/mycar/train.py`（本机工作目录副本，非 git 文件）同步补 macOS 门控——原仅有 GPU 门控，而 Metal 会被 `list_physical_devices('GPU')` 识别为 GPU 从而误开 fp16。
  - `donkeycar/management/train_online.py`：`setup_remote_workspace()` 在 createcar 成功后调用新增 `_patch_remote_train_py_if_macos()`——远程 `uname -s` 检测为 Darwin 则对生成的 `train.py` 执行 `sed -i.bak 's/mixed_precision\.set_global_policy(policy)/pass …/'` 禁用混合精度（`-i.bak` 粘连形式 GNU/BSD sed 均兼容，已对旧/新两版模板干跑验证产出合法 Python；失败只记日志不阻断训练）。远程训练用的是远端 env 自带模板，模板修复要等远端更新 env 才生效，此补丁让修复立即到达 Mac；`WebOnlineTrainer` 经父类 `setup_remote_workspace` 覆盖，web 与 CLI 两路径全覆盖。
  - 顺带修（8.21 已发现的潜伏 bug，与 loss 发散无关）：模板与 mycar/train.py 的 `train(cfg, tubs, model, model_type, comment)` 位置传参会错落到 `train(cfg, tub_paths, model, model_type, transfer, comment)` 的 `transfer`（仅传 `--comment` 时触发），均改为 `comment=comment` 关键字传参。
  - 测试同步：`tests/test_online_trainer_workspace.py` 两个既有用例适配新增 uname 调用（createcar 断言改用 call_args_list），新增 2 用例（Darwin 远端收到指向 createcar 路径的 sed 补丁命令并记日志；sed 失败不阻断、仍返回工作目录）；新增 `tests/test_train_template_fp16.py` 3 项（darwin 门控存在、`set_global_policy(policy)` 仍保留、`comment=comment` 关键字传参）。另修复两个 Tony 上本就在失败的 stale 测试：`test_tub_image_cache.py`（(162) 把 `/tub/image` 改同步后遗留的 `asyncio.run` 调用）与 `test_tub_manager_auto_refresh.py`（#178 把自动刷新逻辑从 App.tsx 迁到 TubManagerPage.tsx 后未同步的断言目标）。`pytest tests/ web_ui/backend/tests` 374 项全绿。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA；改动作用于远程训练链路，不影响本机 8000/8001 可见页面，无需重建 dist。远程补丁覆盖此后每次新建工作区的训练（含续训 import 的同一 train.py）；存量旧工作区的续训（断点续训功能仍在 dd-deploy 在制、未入 Tony）不在本次范围。Mac 远端 env 仍建议日后用本地 Tony 源码重装以彻底对齐。全程纯本地，未碰 GitHub。

## 2026-08-23 (162)

- perf(tub-library): 录制视频库回放改墙钟调度冲刺 60 FPS——帧未加载完跳过不停摆、抖动后自动追帧、长停顿原地续播；后端 /tub/image 改线程池执行消除事件循环阻塞
  - 背景：回放帧率两轮优化（(121) 播放绕过 React 直画 canvas、(125) 去热路径多余 setState/去 backdrop-blur）后仍达不到 60 FPS。剩余瓶颈不在主线程开销，而在调度策略与逐帧取图：旧播放循环每 tick 最多推进 1 帧、下一帧图片未 ready 就整段停摆等它（且已消耗的墙钟时间永久丢失、不追帧），rAF 频率又恰好是 60Hz 零余量——任何网络/调度抖动都直接变成可见卡顿，FPS 角标（按实际换帧统计）随之跌落。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - 播放循环改为墙钟调度：目标帧 = 播放起点帧 + 经过时间 / 帧间隔（`playStartTimeRef`/`playStartFrameRef` 替代表述相位递增的 `lastFrameTimeRef`）；每个 rAF tick 在 `(当前帧, min(当前帧+MAX_CATCHUP_FRAMES=10, 目标帧)]` 窗口内画最后一个图片已 ready 的帧——中间未 ready/损坏的帧直接跳过（`img.complete && img.naturalWidth > 0` 判定，顺带消除旧逻辑对 404 破图 `drawImage` 抛异常中断播放的隐患），不再一帧未 ready 就停摆；网络恢复后按每 tick 最多 10 帧自动追平墙钟进度。
    - 落后墙钟超过 `MAX_RESUME_LAG_FRAMES=60` 帧（~1s，切后台/网络卡死）时从当前帧重新对表继续 1x 播放，不快进不追帧爆冲。
    - 预取与节流 UI 更新由「帧号取模」改为「越过 6 帧边界」判定（追帧跳号时不错过）；FPS 角标语义不变（每秒实际换帧数）。
  - `web_ui/backend/routers/tub.py`：`GET /tub/image` 由 `async def` 改为同步 `def`（Starlette 线程池执行）——此前缓存未命中时在事件循环里同步 `open().read()` 整文件，一次冷读卡住全部并发帧请求与遥测；图像 LRU 缓存 `_cache_get`/`_cache_put` 加 `_image_cache_lock`（threading.Lock）保证线程池并发安全。
  - 测试同步：`TubLibrary.test.tsx` 新增 2 项（手工泵 rAF + Mock Image 控制按 URL 就绪——缺帧跳过不停摆继续按墙钟推进；5s 突跳后原地续播不快进）；前端 `vitest run` 24 文件 133 项、`tsc -b`、`npm run build` 全绿；后端 `pytest` 106 项全绿。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA；收尾后部署本机 8000。全程纯本地，未碰 GitHub。

## 2026-08-23 (161)

- fix(trainer): 训练主机配置表单（本机/IP/密码）抑制苹果「存储密码？」与「强密码」建议——密码框声明 new-password + 密码管理器忽略属性，主机/用户名框 autocomplete=off
  - 背景：Trainer 页训练主机配置（`RemoteConfigForm`，本机/车载电脑/云端三档共用）里主机 IP、用户名、密码三个输入框全无 autocomplete 属性；Safari/iOS 把「用户名 + type=password」组合识别为登录表单，输入密码后弹系统级「是否存储此密码」，并可能给出「强密码」建议——这里是 SSH 训练主机凭据，不是网站账号，提示无意义且打扰。ESP32 侧 STA 配网同款问题已在固件 v1.8.59 修复，本次对齐 DD 侧。
  - `web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx`：密码框加 `autoComplete="new-password"`（声明为设置新密码而非登录凭据，Safari/Chrome 不弹保存提示）+ `data-1p-ignore` / `data-lpignore` / `data-form-type="other"`（1Password/LastPass/Dashlane 等忽略）；主机 IP 与用户名框加 `autoComplete="off" autoCapitalize="none" spellCheck={false}`（破除登录表单启发式，顺带关闭 iOS 首字母大写与拼写检查）。纯属性改动，无逻辑变化。
  - 测试同步：新增 `web_ui/frontend/src/components/trainer/RemoteConfigForm.test.tsx`（2 项——密码框 new-password + 三个忽略属性；主机/用户名框 autocomplete=off/autocapitalize/spellcheck）。

## 2026-08-23 (160)

- fix(console): DD 顶栏 DEV 开关显示与车端实际状态不一致——缓存 IP 失效不自愈 + 未知态误显示为「关」
  - 背景：车端 Drifter Console 的 DEV 开关为开，但 DD 顶栏的 DEV 开关显示为关。实测车端 `/api/devmode` 直连、DD 后端 `/api/console/proxy` 代理、`/api/status` 的 `dev_mode=1` 三处均返回开——固件与后端代理链路无问题，根因在 DD 前端。
  - 根因一（IP 缓存失效）：`web_ui/frontend/src/hooks/useConsoleDevice.ts` 把车端 IP 缓存进 `sessionStorage`（`donkeydrifter.console.ip`），整个 tab 会话内不再重扫；车端换 IP（车 AP 192.168.4.1 ↔ 家里 Wi-Fi 192.168.3.x、DHCP 重租）后轮询经代理 10s 超时失败。
  - 根因二（未知态误显示）：`web_ui/frontend/src/components/ConsoleControls.tsx` 的 `ConsoleDevToggle` fetch 失败时 `setEnabled(null)`，而 `null` 与 `false` 走同一灰底「关」样式，且按钮可点但点击直接 return——用户无法区分「DEV 关」与「读不到状态」。
  - 修复：
    - `useConsoleDevice.ts`：新增导出 `invalidateConsoleDeviceCache()`（清 sessionStorage 与模块级缓存）与 hook 返回值 `refresh()`（失效缓存并重扫，`attempt` state 驱动 effect 重跑）；扫描不到车端时以 10s 慢速重试（`RETRY_SCAN_MS`），车重新上线自动恢复。顺带修掉一个随 refresh 暴露的潜伏 bug——`resolveConsoleIp` 里 `inFlight` 的清理原放在 IIFE 的 `finally` 中，同步完成路径（sessionStorage 命中、全程无 await）下 finally 先于 `inFlight = ...` 赋值执行，导致 inFlight 永久卡住为旧 promise、之后所有 resolve 都吃旧值；改为把清理回调挂在 promise 的 `.finally()` 上（微任务，时序安全）。
    - `ConsoleControls.tsx`（仅 `ConsoleDevToggle`）：`fetchDevMode` 的 catch 分支除 `setEnabled(null)` 外调用 `refresh()`——ip 更新后 `fetchDevMode` 随依赖重建，既有 effect 自动用新 IP 重取，一个轮询周期内自愈；渲染上 `enabled === null`（含初次加载中）按「未知/不可达」处理——按钮 disabled、去 hover 高亮、title 复用既有 `console.unreachable` 词条，不再伪装成「关」。`ConsoleMuteButton`/`ConsoleOtaButton` 本次不动。
  - 测试同步：`ConsoleControls.test.tsx` 三处 `useConsoleDevice` mock 补 `refresh` 字段，新增 2 用例（fetch 失败触发 refresh 重扫；未知态 disabled + unreachable title 而非「关」样式）；新增 `useConsoleDevice.test.ts` 4 用例（扫描缓存、sessionStorage 复用不重扫、refresh 失效旧 IP 重扫新 IP——覆盖 inFlight 修复、扫不到时慢速重试并自动恢复）。`npx tsc -b` 与 `vitest run`（23 文件 129 项）全绿。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；全程纯本地，未碰 GitHub。

## 2026-08-22 (159)

- fix(launcher): 启动中转页标签标题由 "Donkey" 改为 "Donkey Drifter"——新标签页一开即显示最终名称
  - 背景：Launcher 菜单 6 号「Donkey Drifter」点击后，新标签页先打开启动中转页 `LAUNCH_DRIVE_HTML`（转圈 + 轮询 + 跳转 DD），其 `<title>` 为 "Donkey"，跳转后才由 DD 前端 `DonkeyDrifter` 标题接管——标签页先显示 "Donkey" 过一会才变。
  - 修复（`donkeycar/launcher/server.py`，1 行）：`LAUNCH_DRIVE_HTML` 的 `<title>Donkey</title>` 改为 `<title>Donkey Drifter</title>`，与菜单项名称一致；`MENU_HTML`（Launcher 菜单页自身标题）不在诉求范围，未动。
  - 测试同步：`pytest tests/test_launcher_language_autodetect.py tests/test_launcher_menu_actions.py` 38 项全绿；无测试断言该 `<title>`，无需改测试。
  - 注：仅 Launcher 后端页面改动，Firmware 无改动、无需 OTA；全程纯本地，未碰 GitHub。

## 2026-08-22 (158)

- fix(tub-editor): 两次点击选择——锚点改模块级变量并在 mousedown 处理，修复选区恒为最左最右
  - 背景：两次点击选择功能在连续多轮反馈中始终表现为「不管怎么点，选中的永远是最左和最右两个点」（如点 A→B→C→D 选 [A,D] 而非 [C,D]）。
  - 根因：锚点存于组件内 `useRef`，且选择逻辑挂在 `onClick`——组件重挂载/事件时序问题导致锚点丢失或滞后，第二次以后的点击未按「上次点击点」为锚更新。
  - 修复（`web_ui/frontend/src/components/TubEditor.tsx`，9 增 31 删）：
    - 锚点从 `selectionAnchorIndexRef`（useRef）改为模块级变量 `globalSelectionAnchorIndex`，避免组件重新挂载时锚点被重置为 null；
    - 选择逻辑从 `handleClick`（onClick）移入 `handleMouseDown`（mousedown 立即处理，不依赖 click 事件合成时序），删除 `handleClick` 与其 JSX 绑定；
    - Escape 清锚点同步改用模块级变量。
  - 验证：`tsc --noEmit`、`vitest run`（22 文件 123 项）、`npm run build` 全部通过；并用 geckodriver + 无头 Firefox 对 8000 在线实例做真实鼠标点击测试：单击（20%）无选区 → 50% 得 [2336,6212] → 65% 得 [6212,8143] → 80% 得 [8143,10081] → 回跳 30% 得 [3623,10081]——每一步都是「最近两次点击」的区间，含向前回跳场景。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾合入本地 Tony（efe0e943）后重建 dist 部署 8000 并复测通过。全程纯本地，未碰 GitHub。
# 2026-08-22 (170)

- feat(connector): CC 页顶栏「重新扫描」右侧新增「手柄校准」按钮——点击经 postMessage 让内嵌车端视图打开校准弹窗
  - 背景：车端 v1.8.47 起漂移/Judge 设置在 CC 内嵌视图默认展开后，「调校」行只剩手柄校准一个按钮；用户要求把该按钮移到 CC 页顶部「重新扫描」右边，并删掉内嵌视图里的「车辆设置」标题与「调校」行框（车端 v1.8.49 已整行隐藏）。
  - 改动（`web_ui/frontend/src/components/CarSettingsPanel.tsx`）：工具行新增「手柄校准」Button（Gamepad2 图标，未选设备时禁用）；点击 `iframeRef.current?.contentWindow?.postMessage({type:'dd-open-joystick-cal'}, 'http://<selectedIp>')`——沿用 DrifterConsolePage 静音同步的同款 postMessage 通道，车端页面监听后调用 `openJoystickCalModal()`，弹窗在内嵌 iframe 可视区内居中打开。iframe 加 `ref`。
  - i18n：`web_ui/frontend/src/i18n/messages/connector.ts` 新增 `connector.joystickCal`（手柄校准 / Joystick Cal）与 `connector.joystickCalHint`（悬停提示，中英）两键。
  - 测试同步：新增 `CarSettingsPanel.test.tsx`——按钮位于重新扫描右侧、点击后对 iframe contentWindow postMessage `{type:'dd-open-joystick-cal'}` 与正确 targetOrigin、无设备时禁用；`vitest run` 23 文件 125 项全部通过。
  - 注：仅 DD 前端改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；cp 到 dd-deploy 重建 dist 部署 8000/8001。需配合车端固件 v1.8.49+（含 `dd-open-joystick-cal` 监听分支与 setTitle/setRow 隐藏）。

## 2026-08-22 (169)

- refactor(connector): CC 页删除「车辆设置」外层卡片框与标题——内容直接平铺，避免与内嵌车端视图的「车辆设置」标题重复
  - 背景：CC 页面精简后整页只剩车辆设置，外层 Card + 标题（扳手图标 +「车辆设置」+ 副标题）与内嵌 iframe 里车端的「车辆设置」标题重复，用户要求删掉外层标题和大框。
  - 改动（`web_ui/frontend/src/components/CarSettingsPanel.tsx`）：移除 `Card`/`CardHeader`/`CardContent`/`SectionCardTitle`/`Wrench` 包装，根节点改为普通 `div.space-y-3`；内容（车辆选择下拉 + 重新扫描按钮 + `?embedded=1&settings=1&wifi=1` 内嵌视图）不变。
  - 依赖说明：本次改动基于本会话早先的 wifi 配网板块版本（`Tony-issue234-wifi-panel` 分支 commit `ed8d77bb` 的 CarSettingsPanel.tsx 文件版本，经 `git checkout ed8d77bb -- <file>` 取入本分支），与线上 dd-deploy 部署的未提交版本对齐。
  - 测试同步：`npm run build`（tsc + vite）、`vitest run`（22 文件 123 项）全部通过。
  - 注：仅 DD 前端改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；cp 到 dd-deploy 重建 dist 部署 8000/8001。

## 2026-08-22 (168)

- refactor(connector): CC 页删除「连接配置」「推送 Pilots」板块——页面精简为纯车辆设置中心
  - 背景：与拉取 Tub 同批查证——连接器配置 `~/.donkeycar_web_connector.json` 从未创建（SSH 车端从未配置）；推送 Pilots 的源目录 `<backend cwd>/models` 在部署实例中不存在（真实模型在 `mycar/models`，均为模拟器产物）；整套 SSH 管线面向"车上跑 donkeycar 主机"架构，与当前 ESP32 真车 + 模拟器训练的实际工作流不符。用户决策：两个板块都删。
  - 改动（`web_ui/frontend/src/pages/CarConnectorPage.tsx`）：页面精简为仅渲染 `CarSettingsPanel`（车辆设置）；删除全部 SSH 管线代码——连接配置卡、推送 Pilots 卡、`getConnectorConfig`/`setConnectorConfig`/`checkConnectorStatus`/`pushConnectorPilots` 引用、`useConnectorJob` 调用、相关 state 与图标。后端 `/connector/*` 接口与 `useConnectorJob` hook 文件保留不动，仅前端入口移除。
  - 测试同步：`npm run build`（tsc + vite）、`vitest run`（22 文件 123 项）全部通过。
  - 注：仅 DD 前端改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；cp 到 dd-deploy 重建 dist 部署 8000/8001。

## 2026-08-22 (167)

- refactor(connector): CC 页删除「拉取 Tub」板块——实证从未使用（数据流全走模拟器）
  - 背景：用户要求评估拉取 Tub 是否用得上。查证：连接器配置 `~/.donkeycar_web_connector.json` 从未创建（SSH 车端从未配置，功能无从执行）；各部署 checkout 的后端 `./data` 落地目录全空（零拉取记录）；近期数据目录全为模拟器产物（`data_sim*`、`sim_collect_*`）。用户决策：只删拉取 Tub，保留连接配置与推送 Pilots。
  - 改动（`web_ui/frontend/src/pages/CarConnectorPage.tsx`）：删除拉取 Tub 整卡及连带代码——`tubs`/`selectedTub`/`createNewDir` state、`loadRemoteLists`（远端 tub 列表只服务于该板块）、`refreshLocalTub`/`handlePullTub`、`pullConnectorTub`/`listConnectorTubs`/`loadTub`/`useStore`/`Download` 图标引用。后端 `/connector/tubs/*` 接口保留不动，仅 CC 前端移除入口。
  - 测试同步：`npm run build`（tsc + vite）、`vitest run`（22 文件 123 项）全部通过。
  - 注：仅 DD 前端改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；cp 到 dd-deploy 重建 dist 部署 8000/8001。

## 2026-08-22 (166)

- refactor(connector): CC 页删除整个「远程驾驶」板块——DriveApiBridge 回连地址全自动配置，无需手动项
  - 背景：用户确认回连地址应自动配置（前端默认值本就取自浏览器访问地址、localhost 自动换本机网卡 IP），输入框无存在必要；删掉输入框后整个远程驾驶板块也随之删除。
  - 改动（`web_ui/frontend/src/pages/CarConnectorPage.tsx`）：删除远程驾驶整卡（bridge URL 输入框、车辆在线状态、PID 显示、启动/停止驾驶、打开驾驶控制台按钮）及连带代码——`startConnectorDrive`/`stopConnectorDrive`/`getConnectorDriveStatus`/`getDriveCarWebSocketUrl`/`getConnectorLocalIps` 引用、`useDriveWebsocket`、`useNavigate`、`bridgeServerUrl`/`drivePid` state、bridge URL 自动修正 effect、`refreshDriveStatus`；`useConnectorJob` 改为无参调用（拉取/推送任务仍在用）。后端 `/connector/drive/*` 接口与 donkeycar 侧 `DRIVE_API_SERVER_URL` 自动注入逻辑保留不动，仅 CC 前端不再提供入口。
  - 布局：右栏清空后移除两列 grid，剩余三卡（连接配置、拉取 Tub、推送 Pilots）整栏纵向堆叠，`CarSettingsPanel` 位置不变。
  - 测试同步：`npm run build`（tsc + vite）、`vitest run`（22 文件 123 项）全部通过。
  - 注：仅 DD 前端改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；cp 到 dd-deploy 重建 dist 部署 8000/8001。

## 2026-08-22 (165)

- refactor(connector): CC 页删除「任务进度与日志」板块与远程驾驶「模型类型/Pilot」下拉（与 Drive 页重复）
  - 背景：用户精简 Car Connector 页面——任务日志板块从来用不上；远程驾驶卡里的模型类型与 Pilot 两个下拉在 Drive 页面已有同等功能（`ModelSelector` 组件 + `loadModelToCar`），属重复入口。
  - 改动（`web_ui/frontend/src/pages/CarConnectorPage.tsx`）：
    - 删除「任务进度与日志」整卡（进度条、完成/失败提示、日志滚动区、取消按钮）；`useConnectorJob` hook 保留（拉取/推送/启停任务仍靠它执行），仅解构精简为 `isJobRunning`/`startJob`，删除 `ScrollText` 图标引用。
    - 删除远程驾驶卡「模型类型」「选择 Pilot」双下拉及连带死代码：`MODEL_TYPES` 常量、`modelType`/`selectedPilot`/`remoteModels` state、`listConnectorModels` 调用（`loadRemoteLists` 改为只拉 tub 列表）；`handleDriveStart` 简化为只发 `bridge_server_url`（后端 `startConnectorDrive` 的 `model_type`/`pilot` 本为可选参数，无后端改动）。
    - i18n 键（`connector.modelTypeLabel`/`selectPilotLabel`/`jobLog` 等）保留不删，避免影响其它引用与 i18n 测试。
  - 重复功能审查结论（其余板块均保留）：连接配置（车端 SSH host/user/port/car_dir/key，与 Trainer 页训练主机配置是另一用途）、拉取 Tub、推送 Pilots、远程驾驶启停 + bridge URL + 车辆设置（CarSettingsPanel）均为 CC 独有功能，其它页面无重复。
  - 测试同步：`npm run build`（tsc + vite）、`vitest run`（22 文件 123 项）全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动；按用户要求全流程纯本地（本地功能分支 commit，不合 Tony、不碰 GitHub）；改动文件 cp 到 dd-deploy 部署 worktree 重建 dist 部署 8000/8001。
## 2026-08-21 (154)

- feat(tub-editor): 底部滑块改为帧位置滑块——始终激活、与录制库进度条同步、thumb 改椭圆白色
  - 背景：TubEditor 底部滑块此前是缩放滚动条（`scrollProgress` 0~1），仅在图表放大时可用，用户无法用它快速定位帧；且 thumb 是圆形青色，与 Drive 页的椭圆白色不一致。
  - 修复：
    - `web_ui/frontend/src/components/TubEditor.tsx`：底部滑块从 `scrollProgress`（缩放滚动）改为 `currentIndex`（全局帧位置），`min=0 max=records.length-1 value=currentIndex onChange=setCurrentIndex`，`disabled` 条件从「未缩放时禁用」改为「无记录时禁用」——始终激活，拖动即定位帧；自动滚动 effect 从 `!isPlaying` 条件移除——非播放时拖滑块也自动滚动图表保持当前帧可见。删除不再使用的 `handleScrollSliderChange`。
    - 同步：滑块拖动 → `setCurrentIndex` → TubEditor 竖线移动 + TubLibrary 订阅 store 反向同步 `frame` → 顶部进度条跟随。双向同步已有机制（TubLibrary L302 store→frame、L314 frame→store），无需新代码。
    - `web_ui/frontend/src/index.css`：thumb 从 `width:16px height:16px` 圆形青色改为 `width:24px height:16px` 椭圆白色，与 Drive 页 ParameterPanel 滑块一致。
    - `web_ui/frontend/src/themes/theme-mus4.css`、`theme-light.css`：删除主题级 thumb 覆盖（基础样式已统一为白色椭圆）。
  - 测试同步：`tsc -b --noEmit`、`vitest run`（22 文件 123 项）、`npm run build` 全部通过。TubEditor 无单测（canvas/chart.js 组件），纯交互+样式改动。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (153)

- fix(tub-library): 点击播放不走的根因修复——播放循环启动时加初始预取，解除死锁
  - 背景：用户在录制视频库点击播放按钮后，视频不播放、进度条不走。
  - 根因：播放循环的 `step()` 在推进帧时检查下一帧图片是否已加载（`imageCacheRef.current.get(url)?.complete`），未加载则 `requestAnimationFrame(step); return;` 不推进帧。但预取（`prefetchFromIndex`）只在帧成功推进后才调用（每 6 帧一次），导致帧 1 图片永远不会被加载——预取等帧推进、帧推进等预取，形成死锁。
  - 修复：`web_ui/frontend/src/components/TubLibrary.tsx` 播放循环启动 effect 中，在 RAF 循环开始前调用 `prefetchFromIndex(frameRef.current)` 做初始预取（60 帧窗口），让前 60 帧图片在播放循环需要它们之前就开始加载。
  - 测试同步：`tsc -b --noEmit`、`vitest run`（22 文件 123 项）、`npm run build` 全部通过。TubLibrary 测试不覆盖播放逻辑，本次为时序 bug 修复，无需新增测试。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (152)

- revert(tub-manager): 回退一屏并排布局改动（143/148/149），恢复原始纵向滚动布局
  - 背景：143/148/149 三版尝试把录制视频库与 Tub 编辑器压缩到一屏内，但视频被压得太小、编辑器底部被裁，用户要求回退。
  - 回退（7 处 CSS 恢复，3 个文件）：
    - `TubManagerPage.tsx`：`flex flex-col gap-4 h-[calc(100vh-180px)] min-h-0` → `space-y-6`。
    - `TubLibrary.tsx`：Card `shrink-0` 移除；会话列表 `max-h-[24vh]`→`max-h-[520px]`；视频容器 `max-h-[36vh]` 移除；`RecordStats` 恢复 `h-[60px] w-[88px]` + `text-xs` + `text-lg`。
    - `TubEditor.tsx`：`chartCardClassName` 恢复 `min-h-[clamp(20rem,48vh,34rem)]`；图表容器恢复 `min-h-[12rem]`。
  - 验证：`diff` 对照 0dd0696d（改动前基线）确认 TubManagerPage/TubEditor 完全一致，TubLibrary 仅差异来自并行会话的 PR #353（下载优化，非本次布局改动）。
  - 测试同步：`tsc -b --noEmit`、`vitest run`（22 文件 123 项）、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (151)

- feat(launcher): KCW/DSH 每次点击都开新会话，不再复用旧窗口的旧会话
  - 背景：用户要求"不管是 KCW 还是 DSH，点击之后，不是搜索现在已经有的窗口，而是直接重新开一个新的 Session"。此前复用路径返回裸入口 URL（不带会话 ID），浏览器会显示上次的旧会话；冷启动路径的 `Session:` banner 虽带新会话但仅首次可用。
  - KCW（`donkeycar/launcher/kimi_web.py`）：新增 `_create_session(port, token, cwd_str)`——通过 `POST /api/v1/sessions` REST API 在已运行的 kimi web 实例上创建新会话，返回 session ID；新增 `_ensure_session_url(url, cwd_str, create_session_fn)`——URL 路径已是 `/sessions/<id>` 的（冷启动 banner）直接返回，裸入口（`/`）的创建新会话并插入路径。`launch_kimi_code_web()` 在三条返回路径（复用/冷启动/兜底复用）上统一调用 `_ensure_session_url`，每次点击都返回新会话专属 URL。
  - DSH（`donkeycar/launcher/dsh_web.py`）：DSH 没有 REST API 创建会话，改在前端侧清除当前会话指针。新增 `_mark_new_session(url)`——给入口 URL 追加 `?dsh_new_session=1`；扩展 `_PATCH_UUID_NEW` 补丁（client.js）注入检测逻辑：URL 带 `?dsh_new_session=1` 时清除 `localStorage["dsh.sessions.current"]`，使 DSH 前端进入"New Session"空白视图。保留 `_PATCH_UUID_NEW_LEGACY`（旧版仅 UUID 补丁）做迁移检测，已打过旧版的文件自动升级。
  - `launch_dsh_web()` 在三条返回路径上统一调用 `_mark_new_session`。
  - 测试同步：`tests/test_launcher_kimi_web.py` 更新 5 项现有测试（增加 `create_session_fn` mock、预期 URL 含 `/sessions/<id>`），新增 4 项（`_ensure_session_url` 3 项 + `_create_session` API 调用验证 1 项）；`tests/test_launcher_dsh_web.py` 更新 7 项现有测试（预期 URL 含 `?dsh_new_session=1`），新增 2 项（`_mark_new_session` 幂等性 + `_PATCH_UUID_NEW` 含新会话标记验证）。全 launcher 169 项测试通过。
  - 注：仅 launcher Python 改动，Firmware 无改动、无需 OTA；收尾后部署 8000 + 重启 launcher 生效。

## 2026-08-21 (150)

- fix(drive): 摄像头未连接时去掉四角取景框，仅保留容器圆角
  - 背景：摄像头离线时 VideoStream 组件渲染 4 个 `span`（左上/右上/左下/右下角）拼出 L 形取景框，每角有一横一竖的 border 弧线，四个角出现黑色直角块，用户希望只保留容器本身的圆角。
  - 修复：删除 `VideoStream.tsx` 中 `{!webRtcVisible && status !== 'connected' && (<>…4 个 span…</>)}` 整块，替换为一行注释。容器圆角由 `DrivePage.tsx` 视频容器 `rounded-lg overflow-hidden` 提供，删后四角仅呈现干净的圆角。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：删除四角取景框 span 块。
  - 测试同步：`npx vitest run`（22 文件 123 项全通过）、`npm run build` 通过。纯删除改动，无新增单测。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (149) bf88f76f (feat(launcher): KCW/DSH 每次点击开新会话)

## 2026-08-21 (148)

- fix(tub-manager): 修正一屏布局——视频画面放大、Tub 编辑器底部滑块不再被裁
  - 背景：上一版（143）把录制视频库与 Tub 编辑器改为一屏并排，但视频 `max-h-[22vh]` 压得太小看不清，图表容器 `min-h-[12rem]`（192px）占满空间把底部滚滑块+选区/删除指示条挤出 `overflow-hidden` 可见区域。
  - 修复：视频容器 `max-h-[22vh]`→`max-h-[30vh]`（1080p 下 237px→324px，画面明显更大）；图表容器 `min-h-[12rem]`→`min-h-[8rem]`（192px→128px，给底部滑块留足空间）。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：视频容器 max-h 调大。
  - `web_ui/frontend/src/components/TubEditor.tsx`：图表容器 min-h 调小。
  - 测试同步：`tsc -b --noEmit`、`vitest run`（22 文件 123 项）、`npm run build` 全部通过。纯 CSS 改动。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

- fix(tub-library): 下载 tar.gz 改为 pipe+线程流式响应，Safari 立即弹出下载通知
  - 背景：此前 `download_session` 端点先把整个 tar.gz 构建到 `BytesIO` 内存缓冲（遍历所有 record、读所有 JPEG、gzip 压缩），完成后才 `StreamingResponse` 开始发送。浏览器要等好几秒才收到第一个字节，Safari 不会在等待期间弹出下载通知。
  - `web_ui/backend/routers/tub.py`：改用 `os.pipe()` + `threading.Thread`——后台线程把 tar.gz 写入管道写端，`StreamingResponse` 的生成器从管道读端 `read(65536)` 逐块 yield。浏览器在第一张图片压缩完成时（毫秒级）就收到数据，立即弹出下载通知并显示进度条。新增 `import threading`。
  - 测试同步：后端 `pytest -q` 106 项通过（无 download_session 专属测试，不涉及）。
  - 注：仅 DD 后端改动，Firmware 无改动、无需 OTA；收尾后重启 8000 后端部署。

## 2026-08-21 (147)

- fix(drive): 遥测图例「全选」框在全选状态下变蓝
  - 背景：上一轮 (142) 加的「全选」勾选框固定用 `accent-slate-400`（灰色），全选时没有「已全选」的视觉反馈；用户希望全选状态下勾选框被勾上且变蓝。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：「全选」`input` 的 `className` 从固定 `accent-slate-400` 改为 `allSelected ? 'accent-blue-500' : 'accent-slate-400'`——全选时蓝色勾、半选/未选时灰色（半选仍显示 indeterminate 横杠）。
  - 验证：`npx vitest run src/components/drive/TelemetryChart.test.tsx` 11 项通过、`npm run build` 通过；临时预览端口实测两个「全选」框在全选态 `checked:true`、`accent-color: rgb(59,130,246)`（blue-500）。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (146)

- fix(frontend): 移除 DD 标签栏「C Code」入口按钮及其全部配套代码（后端路由 / launcher 端点 / 前端组件 / i18n / 测试），恢复为 Kimi Code Web + DeepSeek Harness 两个弱化入口
  - 背景：C Code 入口（条目 (137) / PR #337 引入）经实际使用后用户决定移除；Claude Code 无官方 web UI，复用 launcher 网页终端的方案体验不佳，遂删除。
  - `donkeycar/launcher/server.py`：删除 `POST /api/launch/claude-code` 端点分发与 `_handle_launch_claude_code()` 方法（返回网页终端 URL 的实现）；清理仅 claude-code 使用的 `import shlex`、`from urllib.parse import quote`、`from donkeycar.launcher.kimi_web import _entry_host`（`_KIMI_WEB_CORS_HEADERS` 保留——kimi/dsh 仍在用）。
  - `web_ui/backend/routers/launch.py`：删除 `POST /claude-code` 转发路由与 `launch_claude_code` 函数；docstring 改回只描述 kimi-code-web / dsh 两个端点。
  - `web_ui/frontend/src/services/api.ts`：删除 `launchClaudeCode` 函数。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：删除 `CCodeEntryLink` 组件；lucide import 去掉 `Terminal`；api import 去掉 `launchClaudeCode`。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面导航与移动菜单两处删除 `<CCodeEntryLink />` 及 import；注释去掉「C Code」。
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh + en 各删除 `cCode` 5 键（`cCode` / `cCodeTitle` / `cCodeStarting` / `cCodeFailed` / `cCodeNetworkError`）。
  - `web_ui/frontend/src/components/EnterButtons.test.tsx`：删除 `describe('CCodeEntryLink')` 测试块及相关 mock（`launchClaudeCode` / `mockLaunchCCode`）；import 去掉 `CCodeEntryLink`。
  - 删除文件 `tests/test_launcher_claude_code.py`（claude-code 端点专属测试，端点已移除）。
  - `web_ui/backend/tests/test_launch.py`：保留文件（仍覆盖 kimi / dsh 转发），删除 claude-code 用例、路由注册断言改回两条（kimi-code-web / dsh）。
  - 测试同步：`pytest web_ui/backend/tests/test_launch.py tests/test_launcher_kimi_web.py tests/test_launcher_dsh_web.py -q` → 108 passed；`npx vitest run src/components/EnterButtons.test.tsx` → 8 passed；`npx tsc --noEmit` 通过。
  - 注：配套固件侧 DC 头部 C Code 按钮移除在 Firmware 仓库 v1.8.32；收尾后部署 DD 到 8000 + OTA 刷车验证。


## 2026-08-21 (145)

- fix(layout): DD 左上角 logo 与 Drifter Console 图标同尺寸（box-sizing 改 content-box，总 34px）
  - 背景：上一轮对齐了圆角与边框色，但 DD logo 仍比 DC 小一圈。根因：DC headerLogo 是 `width:32px` + `border:1px`（content-box，边框外凸，总 34px）；而 Tailwind preflight 把 `*` 默认设为 border-box，DD 的 `w-8 h-8`(32px) + 1px border 被算进 32px 内，图片只有 30px、整体 32px，比 DC 小 2px 且边框压在图内。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.header-logo` 规则内新增 `box-sizing: content-box;`（与 DC 一致，32px 内容 + 1px 边框外凸 = 34px）；圆角 8px、边框色随主题不变。
  - `web_ui/frontend/src/components/Layout.tsx`：注释同步更新为「32px 内容 + 1px 边框外凸（content-box，总 34px）」。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过、`npx vitest run` → 22 文件 126 项全绿。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。


## 2026-08-21 (144)

- fix(tub-library): 下载改为浏览器原生 HTTP 下载，Safari 立即弹出下载通知+进度条
  - 背景：此前 `downloadTubSession` 用 axios `responseType:'blob'` 先把整个文件下载到内存，再用 blob URL 触发保存。Safari 不会在"内存下载"阶段显示下载通知，用户只看到图标弹跳却无下载进度条。
  - `web_ui/frontend/src/services/api.ts`：`downloadTubSession` 从 async axios blob 改为同步——直接构造 `<a href="服务器URL">` + `link.click()` 让浏览器原生发起 HTTP 下载。后端已设 `Content-Disposition: attachment`，浏览器立即显示原生下载通知与进度条。函数签名去掉 `start_time_ms`（文件名由后端 Content-Disposition 设置）。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：`handleDownload` 改为同步调用，`downloadingId` 设 1 秒后自动清除作为点击视觉反馈，实际下载进度由浏览器原生 UI 显示。
  - 测试同步：`TubLibrary.test.tsx` 下载测试参数去掉 `start_time_ms`，断言改为同步调用；`npx vitest run --root . src/components/TubLibrary.test.tsx` 6 项通过，`npx tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署到 8000。

## 2026-08-21 (143)

- feat(tub-manager): 录制视频库与 Tub 编辑器一屏并排显示，无需滚动切换
  - 背景：TubManagerPage 用 `space-y-6` 简单纵向堆叠，TubLibrary 的 `aspect-video` 播放器在宽屏上高度达 ~480px+、会话列表 `max-h-[520px]`，TubEditor 图表 `min-h-[clamp(20rem,48vh,34rem)]` 至少 320px，两者合计远超视口高度，用户必须上下滚动才能分别看到录制库和编辑器曲线。
  - 修复：TubManagerPage 容器改为 `flex flex-col gap-6 h-[calc(100vh-200px)] min-h-0`，视口高度约束的 flex 列；TubLibrary 加 `shrink-0` 不抢空间、会话列表 `max-h-[520px]`→`max-h-[30vh]`、播放器加 `max-h-[22vh]` 约束高度；TubEditor 图表卡片 `min-h-[clamp(20rem,48vh,34rem)]`→`min-h-0 flex-1`，撑满剩余空间。CardContent 已有 `flex-1 min-h-0`、图表容器已有 `flex-1 min-h-[12rem]`，无需再改内部。
  - `web_ui/frontend/src/pages/TubManagerPage.tsx`：容器 div 改 flex 列 + 视口高度约束。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：Card 加 `shrink-0`；会话列表 `max-h` 改 `30vh`；播放器容器加 `max-h-[22vh]`。
  - `web_ui/frontend/src/components/TubEditor.tsx`：`chartCardClassName` 从 `min-h-[clamp(20rem,48vh,34rem)]` 改为 `min-h-0 flex-1`。
  - 测试同步：`tsc -b --noEmit`、`vitest run`（22 文件 125 项）、`npm run build` 全部通过。本次为纯 CSS 布局改动，未新增单测。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (142)

- feat(drive): 遥测曲线图例左侧加「全选」、全屏放大键挪到视频画面右下角
  - 背景：两个需求——① 两张遥测曲线底部勾选区各加一个「全选」：半选（部分勾选）时点击→全选，已全选时点击→全不选；② 全屏/放大键从原来避让遥测框的上方位置挪到整个视频画面的右下角。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：`TelemetryLegend` 新增可选 `onToggleAll(select:boolean)`；左侧渲染「全选」勾选框——已全选时 `checked`、半选时用 ref 设 `indeterminate` 横杠、点击调 `onToggleAll(!allSelected)`（全选→全不选、半选/全不选→全选）。`TelemetryChart` 内部（非受控时）提供 `toggleAll` 给自身图例；受控时不渲染（由父组件处理）。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：新增 `setSteeringAll`/`setThrottleAll`（一次性把整组 key 设为显示或隐藏）传给两个 `TelemetryLegend`；全屏按钮位置由 `fullscreen ? 'bottom-60' : 'bottom-44'` 改为固定 `bottom-3`（与遥测浮层同 `right-3/bottom-3` inset，叠在曲线之上 z-30），即整个视频画面右下角。
  - i18n：`driveviz.ts` 新增 `driveViz.selectAll`（zh「全选」/en「Select All」）。
  - 测试同步：`TelemetryChart.test.tsx` group 模式勾选框计数 6→7（含「全选」）；新增回归「半选时点击→全选、已全选时点击→全不选」（覆盖 indeterminate）。`npx vitest run TelemetryChart` 11 项、`npx vitest run` 22 文件 126 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 验证：临时预览端口实测——全屏按钮位于右下角（距视频右边/下边各 12px，与遥测浮层对齐）；两组图例各 1 个「全选」（共 2 个 + 12 条曲线勾选框 = 14 个）。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (141)

- fix(launcher): avahi AAAA 防护改用 0.8 正确键名 publish-aaaa-on-ipv4/use-ipv6（publish-aaaa-on-ipv6 不存在，误写会导致 avahi-daemon 拒绝启动、mDNS 全停）
  - 背景：条目 138 的入口 host IPv6/AAAA 防护（PR #340）在配置里写了 `publish-aaaa-on-ipv6`——avahi 0.8 的 `avahi-daemon.conf(5)` 没有这个键，重启时 avahi-daemon 报 `Invalid configuration key` 直接退出，mDNS 全停，tony007.local 反而彻底不可解析（用户实测报错更严重）。avahi 0.8 控制 AAAA 的正确键：`publish-aaaa-on-ipv4`（IPv4 mDNS 应答是否带 AAAA，默认 yes）、`use-ipv6`（IPv6 传输开关，默认 yes；IPv6 应答恒带 AAAA 无独立开关），两者都 no 才完全无 AAAA。
  - `donkeycar/launcher/kimi_web.py`：`_avahi_publishes_ipv6()` 改为解析 `publish-aaaa-on-ipv4` / `use-ipv6` / `publish-addresses` 三键（`publish-addresses=no` 视为安全；缺失/不可读/注释一律保守视为发布）。
  - 本机配置：`/etc/avahi/avahi-daemon.conf` 删除无效键，`[server] use-ipv6=no` + `[publish] publish-aaaa-on-ipv4=no`；重启后 daemon active，实测 `tony007.local` 只解析出 A（192.168.3.62）、AAAA 全无；launcher 入口恢复 `http://tony007.local:58640/`（A-only，无 IPv6 黑洞，origin 稳定）。
  - 测试同步：TestAvahiIpv6Entry 重写为双键语义（都关→False；只关其一→True；默认→True；注释忽略→True；`publish-addresses=no`→False；文件缺失→True）；kimi 测试文件 66 passed、launcher 回归 170 passed。
  - 注：仅 launcher 后端改动，Firmware 无改动、无需 OTA；已 ff 部署 worktree 并重启 donkeydrifter-launcher 生效。

## 2026-08-21 (140)

- fix(launcher): DeepSeek Harness 改用固定专属端口 58641 + 跨 launcher 重启复用，根治「置顶（手动排序）/当前会话/草稿丢失」
  - 背景：DSH 浏览器端的手动排序（localStorage `dsh.workspace.view.v5` 的 `sessionOrderByAccount`，即用户感知的「置顶」）、当前会话（`dsh.sessions.current`）、草稿（`dsh.conversation.chat`）均按 origin（协议+host+端口）隔离。host 维度此前已随 `_lan_url` mDNS 优先修复，但 DSH 冷启动用 `--port 0` 随机端口、复用登记 `_SPAWNED` 仅是 launcher 进程内存——launcher 一重启必冷启动新端口，origin 必变，localStorage 偏好全丢（launcher 日志实锤：14 天 8 次启动 8 个端口、零次复用）。与 Kimi Code Web 的 origin 漂移是同一个病的端口维度，KCW 已由固定端口 `KIMI_WEB_PORT = 58640` 根治，本次对齐。
  - `donkeycar/launcher/dsh_web.py`：新增 `DSH_WEB_PORT = 58641`，冷启动由 `--port 0` 改为固定端口；新增 `_probe_dsh_fixed_port()`——GET 回环固定端口根路径，200 且响应体含 DSH 特征标记 `__DSH_BOOT__` 才视为存活 dsh（防误复用占用该端口的外部服务）；`_live_spawned_url()` 在 `_SPAWNED` 无存活条目后兜底探测固定端口（launcher 重启后也能复用存活实例，端口不再变）；`_spawn_and_capture` 失败后再探一次固定端口兜底复用（对齐 `kimi_web.py` 冷启动失败语义）；模块与各函数 docstring/注释全量对齐新语义。`_PATCH_YAML` 端口表达式跟随 `--port`、`--trusted-host` 裸 host 匹配任意端口，均无需改动。
  - 测试同步：`tests/test_launcher_dsh_web.py` 既有用例由随机端口/`--port 0` 改为固定 58641；新增回归——冷启动与复用两条路径入口 URL mDNS 优先（`test_spawn_url_prefers_mdns_host`/`test_reuse_url_prefers_mdns_host`，此前 DSH 侧零直接断言）、`TestFixedPortReuse`（登记空+固定端口存活→跨重启直接复用；200 无标记→不复用走冷启动；spawn 失败→兜底探测复用）、`TestProbeDshFixedPort` helper 单测三项；新增 autouse fixture `_no_fixed_port_dsh` 防测试真实探测本机 58641。合并 origin/Tony（含 `_avahi_publishes_ipv6` 防护）后 mDNS 用例同步钉 `_avahi_publishes_ipv6=False`。
  - 验证：`pytest tests/test_launcher_dsh_web.py test_launcher_kimi_web.py test_launcher_claude_code.py test_launcher_menu_actions.py test_launcher_drive_launch.py test_launcher_service_unit.py -q` → 159 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist；收尾后需重启 8090 launcher 部署验证（首次点击 DSH 会在 58641 冷启动新实例，原随机端口实例需清理）。

## 2026-08-21 (139)

- fix(tub-editor): Tub 编辑器会话视图 x 轴改用「会话内数组下标」，与录制库「N 帧」对齐
  - 背景：上一版（122）已实现「只显示录制视频库当前浏览视频的遥测曲线」，但图表 x 轴仍用整个 tub 的全局物理帧号 `_index`（当前会话记录物理位置在 3832~16742），右端显示 ~16742，与录制库的「12531 帧」对不上，用户误以为遥测没按当前视频过滤。
  - 根因：编辑器里范围输入框、悬停提示本就用「会话内数组下标」（0~N-1），唯独图表 x 轴用全局物理 `_index`，两套坐标不一致。
  - 修复：会话视图下把 TubEditor 图表坐标统一为「会话内数组下标」(0..N-1)——数据点、x 轴 min/max、播放头、选区框、指针取帧、底部滑块（选区绿条/删除红条）全部按数组下标定位；删除段在数组里无占位，压缩为连续曲线（红条收敛为细条标记删除位置）。未选中会话的全局视图保持物理 `_index` 与删除空洞不变；删除/恢复后端调用仍用物理 `_index`（数据操作不受影响）。
  - `web_ui/frontend/src/components/TubEditor.tsx`：新增 `isSessionScoped` / `isSessionScopedRef`；图表数据点 x 会话视图用 `originalIndex` 并跳过 null 断点；x 轴 min/max 会话视图用 `visibleRange.startIndex/endIndex`；`getIndexFromPointerX` 会话视图直接取整；播放头/选区框用数组下标；滑块绿条会话视图按数组下标百分比定位、红条经 `physicalToArrayPos` 映射到数组插入位置。
  - 附带修复（顺手，规则 8）：`web_ui/frontend/src/App.test.tsx` 的 `services/api` mock 补上 `launchClaudeCode`——PR #337 引入 `CCodeEntryLink` 后该 mock 缺此导出导致 App.test.tsx 4 项报错。
  - 测试同步：`npx tsc -b --noEmit`、`npx vitest run`（22 文件 125 项）、`npm run build` 全部通过。TubEditor 为 canvas/chart.js 组件、本仓库无其单测，本次坐标改动为纯展示层、不改数据操作，未新增单测。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (138)

- fix(launcher): KCW 入口 host 防 IPv6/AAAA 黑洞——avahi 发布 AAAA 时入口回退局域网 IPv4 IP，浏览器不再因选中 IPv6 连接黑洞报「无法连接到 Kimi 服务器」
  - 背景：DC 点击进入 Kimi Code Web 偶发报「无法连接到 Kimi 服务器」（fetch AbortError，前端 30s 超时）。排查实锤：POST /sessions/*/prompts 超时期间服务器侧零痕迹（无事件/无 llm 日志），请求根本没到达 kimi web；入口 URL host 是 mDNS 主机名 `tony007.local`，而 avahi 默认给 mDNS 名发布 AAAA（IPv6 地址）记录、kimi web 只监听 IPv4（0.0.0.0）——浏览器解析入口选中 IPv6 时（部分浏览器优先 IPv6、或 mDNS 缓存残留已轮换的临时地址）TCP 连接黑洞不立即失败，直到前端 30s 超时；WS 连接状态「connected」是旧连接，新 fetch 走新解析。
  - `donkeycar/launcher/kimi_web.py`：新增 `_avahi_publishes_ipv6()`（读 `/etc/avahi/avahi-daemon.conf` 的 `publish-aaaa-on-ipv6`，默认 yes；缺失/不可读/未显式关闭一律按「发布」保守处理）；`_entry_host()` 改为——avahi 不发布 AAAA 时才用 mDNS 主机名（origin 稳定，置顶/收藏不随 DHCP 换 IP 丢失，issue #168 后续），发布 AAAA 时回退局域网 IPv4 IP（可达性优先）。模块 docstring 补充 IPv6/AAAA 防护说明。
  - 本机配套：avahi `publish-aaaa-on-ipv6=no`（需 sudo 改 /etc/avahi/avahi-daemon.conf 并重启 avahi-daemon），浏览器只拿到 A 记录，mDNS 入口彻底无 IPv6 黑洞。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestAvahiIpv6Entry` 7 项（配置解析 no/yes/缺省/注释/文件缺失 + 两条入口路径：发布 AAAA→局域网 IP、不发布→mDNS 名）+ TestLanUrl 2 项（发布 AAAA 时回环/局域网 host 均改写为 IP）；launcher 回归 `pytest -q -k launcher` 160 passed。
  - 注：仅 launcher（Python 后端）改动，Firmware 无改动、无需 OTA；已 ff 部署 worktree（dd-deploy）并重启 `donkeydrifter-launcher` 服务生效。
## 2026-08-21 (137)

- feat(launcher): 新增「C Code」入口——DD 标签栏与 DC 头部在 Kimi Code Web 与 DeepSeek Harness 之间加入 Claude Code 入口，点击在 launcher 网页终端新标签页里运行 `claude`
  - 背景：DD/DC 已有 Kimi Code Web、DeepSeek Harness 两个弱化入口按钮，用户要求在其间加入 C Code（Claude Code）。Claude Code 无官方 web UI，故复用 launcher 的 `/terminal?cmd=` 网页终端机制（菜单 8/9/10 同款：终端页面连上 WebSocket 后把 cmd 作为首行命令执行），入口即开即得、端点毫秒级返回。
  - `donkeycar/launcher/server.py`：新增 `POST /api/launch/claude-code` 端点（`_handle_launch_claude_code`），镜像 kimi/dsh 处理器的请求体校验（可选 JSON `{"cwd": ...}`，非法 JSON/非对象/cwd 非字符串 → 400，cwd 目录不存在 → 500 且不回退其它目录，缺省 `/home/dkc/projects`）；成功返回 `{"status":"ok","url": "http://<entry-host>:8090/terminal?cmd=<urlencoded 'cd <cwd> && claude'>"}`，entry-host 复用 `kimi_web._entry_host()`（mDNS 主机名优先、局域网 IP 兜底，origin 不随 DHCP 漂移）；所有响应带 `_KIMI_WEB_CORS_HEADERS`（DC 从 ESP32 origin 跨域调用），该常量注释由「仅该端点放行」更新为「仅 launch 类端点放行」。不启动任何子进程——claude 由浏览器终端会话执行。
  - `web_ui/backend/routers/launch.py`：新增 `@router.post("/claude-code")` 转发路由（镜像 dsh 路由），模块 docstring 更新为涵盖三个端点。
  - `web_ui/frontend/src/services/api.ts`：新增 `launchClaudeCode`（POST `/launch/claude-code`，`validateStatus: () => true`，返回复用 `LaunchKimiCodeWebResult`）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`KimiCodeWebEntryLink` 与 `DshEntryLink` 之间新增 `CCodeEntryLink`——lucide-react `Terminal` 图标（`w-3.5 h-3.5`），复用 `useLauncherEntry` 与 `entryLinkCls` 弱化样式，timeoutMs 10000（端点即时返回）。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面 nav 与移动端菜单两处均在 KCW 与 DSH 之间插入 `<CCodeEntryLink />`。
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh/en 各新增 `common.enterButtons.cCode` 组 5 键（标签 "C Code"，title 说明在网页终端启动 Claude Code）。
  - 测试同步：新建 `tests/test_launcher_claude_code.py` 7 项（缺省/显式/含空格/不存在 cwd、非法 JSON、非对象体、CORS 头、URL 形态，`_entry_host` monkeypatch 钉住）；新建 `web_ui/backend/tests/test_launch.py` 6 项（三条 launch 路由注册、转发与 502 兜底）；`web_ui/frontend/src/components/EnterButtons.test.tsx` 新增 `describe('CCodeEntryLink')` 3 项（弱化样式/成功开窗/失败 alert，11 项全过），`tsc --noEmit` 通过。launcher 侧回归 `test_launcher_dsh_web.py`/`test_launcher_kimi_web.py` 84 项全过。
  - 注：Firmware 侧配套改动在同日条目 v1.8.30（DC 头部按钮 + openCCode() + i18n）；收尾后部署 8000（重建 dist）并 OTA 刷车。
## 2026-08-21 (136)

- feat(evaluate): `donkey evaluate` 不传 `--model` 时新增转向数据健康度告警，把「angle corr≈0」的根因固化进诊断输出
  - 背景：用新录制的 12531 条数据验证根因——旧数据（中间幅度 mid_ratio 仅 3.2%、左转 7.9%/右转 91.5%、直行 85%）训练后 angle corr≈0；重新采集均衡数据（mid_ratio 16.4%、左 37.3%/右 61.8%、直行 30.4%）后，纯 linear 基线 angle corr 即达 **0.9895**、throttle corr 0.8779。证明 angle corr≈0 不是训练不足，而是转向标签分布病态。
  - `donkeycar/management/base.py`：新增 `Evaluate._angle_health_warnings()`，对 `mid_ratio<5%`、`left_ratio<10%` 或 `right_ratio<10%`、`abs_lt_0.05_ratio>70%` 三类病态输出中文告警并给「重新采集平滑连续转向数据」建议；`run()` 不传 `--model` 分支打印告警，并在 `--out` JSON 里写 `warnings` 字段（健康时无该字段）。
  - 测试同步：`donkeycar/tests/test_evaluate_command.py` 新增 `test_angle_health_warnings_healthy` / `test_angle_health_warnings_unhealthy`，并给无模型路径加「健康数据无 warnings」断言；`pytest -q` 6 passed。
  - 注：仅 donkeycar CLI 统计字段改动，不影响本机 Web UI，无需部署/OTA。

## 2026-08-21 (135)

- fix(console): DD 内嵌 Drifter Console 扫描期间不再误显示「未发现设备」，改为显示「正在扫描局域网…」
  - 背景：进入 DD 的 Drifter Console 页后局域网扫描约需 2.5–3s，期间设备下拉与主区域一直显示「未发现设备」，扫描结束后才纠正——用户观感为「显示未发现设备、扫描很久、还是未发现设备」。另实测本轮用户侧扫不到设备的根因是 Clash VPN（系统代理/TUN）拦截了到本机后端与车端的局域网请求，关闭 VPN 后 `POST /api/connector/discover_console` 实测 ~2.5s 正常返回 `found:[192.168.3.46]`。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：设备下拉的空占位 option 与主区域占位文案均由固定 `console.noDevice` 改为 `scanning ? console.scanning : console.noDevice`（扫描中与扫描结束无设备两种状态正确区分）。
  - 测试同步：新增 `web_ui/frontend/src/pages/DrifterConsolePage.test.tsx` 两项回归——① 扫描进行中显示 `console.scanning` 且不出现 `console.noDevice`、扫描结束无设备才显示 `console.noDevice`；② 扫描发现设备后自动选中第一台并加载内嵌 DC iframe（src 指向该车 IP）。`npx vitest run` → 22 文件 122 项全绿（App.test.tsx 的 TubManager keep-alive 用例在全量并发下偶发超时，单跑与全量复跑均通过，与本改动无关）；`npm run check`（tsc）、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (134)

- fix(layout): DD 左上角 logo 圆角对齐 Drifter Console headerLogo（8px，修正 12px）
  - 背景：logo 此前用 Tailwind `rounded-lg`，但主题 CSS（`theme-mus4.css` / `theme-light.css`）把 `.rounded-lg` 全局改写为 12px，导致 logo 实际圆角 12px；而 Drifter Console 的 headerLogo 是 `border-radius:8px`。用户反馈两者圆角不一样。
  - `web_ui/frontend/src/components/Layout.tsx`：logo `<img>` className 由 `w-8 h-8 rounded-lg border header-logo` 改为 `w-8 h-8 border header-logo`（去掉被主题改写的 rounded-lg）。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.header-logo` 规则内新增 `border-radius: 8px;`（显式锁定，对齐 DC），边框色随主题（深色 #2b3441 / 浅色 #d5dce4）不变。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过、`npx vitest run` → 21 文件 118 项全绿。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (133)

- fix(drive): 视频画面恢复圆角、遥测曲线去掉横向网格线与左侧刻度数字、面板标题移到曲线下方
  - 背景：Drive 页用户反馈三处——① 摄像头画面四个角变成直角（之前是圆弧）；② 遥测曲线之间的横向网格线（1.0/0.5/-0.5/-1.0）与左侧刻度数字遮挡画面；③ 「转向 / 姿态」「油门 / 加速度」两个面板标题应移到各自曲线下方（左右位置不变、高度贴近原 -1.0 刻度下方）。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：视频容器（`videoContainerRef`）在非全屏时加 `rounded-lg overflow-hidden`，四角恢复圆角并把 object-cover 视频与底部遥测浮层裁进圆角；全屏时不加圆角（铺满屏幕）。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：
    - `chartOptions.scales.y` 改为 `display: false`（删掉原 grid/ticks 配色），整体隐藏 y 轴——横向网格线与左侧刻度数字全去掉；`min: -1, max: 1` 保留仍决定量程，曲线铺满全宽（不再给左侧刻度留 gutter）。
    - 面板标题行从画布上方移到画布下方（`mb-2` 改 `mt-2`），overlay 与分栏两种模式都生效；左右对齐不变。
  - 测试同步：`web_ui/frontend/src/components/drive/TelemetryChart.test.tsx` 新增两项回归——「y 轴整体隐藏（display:false 且 min/max 仍为 -1/1）」「面板标题渲染在曲线画布下方（DOM 顺序 canvas 先于 title）」；`npx vitest run src/components/drive/TelemetryChart.test.tsx` 10 项通过、`npx vitest run` 21 文件 120 项通过、`npx tsc -b --noEmit`、`npm run build` 全部通过。
  - 验证：临时预览端口实测截图——视频四角恢复圆角（computed border-radius 12px）、两张遥测 canvas 非背景像素为 0（无横线无数字）、标题位于曲线下方。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (132)

- fix(tub-library): Safari 点击下载后始终不触发下载——blob URL 过早回收
  - 背景：`downloadTubSession` 在 `link.click()` 后立刻 `revokeObjectURL(url)`，Chrome 同步触发下载不受影响，但 Safari 下载是异步的——等 Safari 真正去取 blob 时 URL 已被回收，导致下载永远不开始（图标弹跳但无下载）。
  - `web_ui/frontend/src/services/api.ts`：`createObjectURL` 改为显式构造 `new Blob([...], { type: 'application/gzip' })` 确保 MIME 类型正确；`removeChild` + `revokeObjectURL` 延迟到 `setTimeout(..., 150)` 执行，给 Safari 足够时间启动异步下载。
  - 测试同步：`npx vitest run --root . src/components/TubLibrary.test.tsx` 6 项通过，`npx tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署到 8000。

## 2026-08-21 (131)

- fix(launcher): DD 内嵌 Donkey 去掉「当前工作目录」上方的多余间距（隐藏空 headerRow + 去 body 上边距）
  - 背景：删掉「Donkey」标题并移走版本号后，内嵌视图里 `.headerRow` 变为空容器但仍保留 `margin:0 0 10px` 的下边距，叠加 `body` 的 `margin:12px` 上边距，导致「当前工作目录」行离 DD 标题栏间隔过大（约 22px）。
  - `donkeycar/launcher/server.py`：`isEmbedded` 清理逻辑中，隐藏选择器由 `.logoLink, .ghLink, .headerRow h1, .sectionTitle` 扩展为 `.logoLink, .ghLink, .headerRow, .sectionTitle`（隐藏整个 headerRow，连带去掉其 10px 下边距）；新增 `document.body.style.marginTop = '0'` 去掉 body 上边距，让「当前工作目录」贴近 DD 标题栏；单独打开 Donkey（:8090）时 headerRow 与 body 边距均保持不变。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_embedded_hides_topbar_chrome` 断言同步更新（隐藏选择器含 `.headerRow`、新增 `document.body.style.marginTop = '0'` 断言）；`python -m pytest tests/test_launcher*.py -q` → 143 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist；收尾后需重启 8090 launcher 部署验证。

## 2026-08-21 (130)

- fix(connector): Car Connector「车辆设置」把连接与配网融合成一个板块——顶部设备发现/选择 + STA/AP 配网按钮合并，iframe 只保留车端 DC 的「调校」视图
  - 背景：上一版「车辆设置」顶部是设备发现/选择（连接），下方 iframe 里车端 DC 的 `?settings=1` 视图还带有「系统（OTA/开发模式）」与「Wi-Fi 配网」两行；用户反馈「系统」行太突兀应整行删除，「配网」与顶部「连接」功能重复，应融合成一个板块。
  - `web_ui/frontend/src/components/CarSettingsPanel.tsx`：
    - 顶部连接行新增「STA Wi-Fi 配置」「AP 名称配置」两个按钮（与设备选择、重新扫描并列，中间用竖线分隔），点按经 `iframeRef.contentWindow.postMessage({type:'dd-open-wifi-sta'|'dd-open-wifi-ap'})` 打开车端 DC 的配网弹窗；未选中设备时禁用配网按钮。
    - iframe 增加 `ref={iframeRef}`；组件头注释同步更新为「连接 + 配网融合、下方只呈现调校」。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：新增 `connector.wifiStaButton` / `connector.wifiApButton`（zh/en），`connector.carSettingsSubtitle` 由「配网 / OTA / 开发模式 / 漂移设置等」改为「连接 / 配网 / 漂移设置 / Judge / 手柄校准」。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过，入口 `index-DYVHxIKZ.js`、CarConnectorPage chunk `CarConnectorPage-BegwM-jT.js`。
  - 注：本改动依赖 Firmware v1.8.30（车端 DC `?settings=1` 删掉系统/配网行并新增 `dd-open-wifi-*` postMessage 处理），Firmware 已同步 OTA。

## 2026-08-21 (137)

- refactor(tub-library): 下载按钮移入会话行 pin/trash 区域，与 Pin/Delete 并列
  - 背景：下载按钮此前在底部播放控制工具栏（Refresh 与 Delete 之间），与会话行内 Pin/Delete 按钮分离，操作入口不统一。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - `isDownloading` state 改为 `downloadingId: string | null`，按会话跟踪下载状态。
    - `handleDownload` 从使用 `selected` 改为接受 `session: TubSession` 参数，每行独立下载。
    - 会话行按钮组（`gap-1`）在 Pin 与 Trash2 之间插入 Download 按钮（span role="button"），逻辑顺序 Pin → Download → Delete（组织 → 导出 → 销毁），下载中图标弹跳动画。
    - 底部工具栏移除原 Download Button。
  - 测试同步：`TubLibrary.test.tsx` 下载测试改用 `findAllByRole` 断言每行一个下载按钮（2 个会话 = 2 个按钮）、点击首行按钮调用 `downloadTubSession` 传入正确参数；`npx vitest run --root . src/components/TubLibrary.test.tsx` 6 项通过，`npx tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署到 8000。

## 2026-08-21 (128)

- fix(launcher): KCW 入口 origin 改用 mDNS 主机名优先，置顶/收藏/自主模式不再随 DHCP 换 IP 丢失
  - 背景：本机在家庭 Wi-Fi 走 DHCP，实测一天内 IP 连续变化（192.168.3.57 → .103 → .62）。KCW 前端的置顶 `kimi-web.pinned-sessions`、权限模式 `kimi-web.permission`、收藏模型 `kimi-web.starred-models` 等偏好都存浏览器 localStorage、按 origin（含 host）隔离。launcher 此前用局域网 IP 做入口 host，IP 每变一次 origin 就变、偏好被"清空"，用户反复表现为「置顶全没了、自主模式变逐条确认、收藏被取消」。
  - `donkeycar/launcher/kimi_web.py`：`_entry_host()` 由 `_lan_ip() or _mdns_hostname()` 改为 `_mdns_hostname() or _lan_ip()`（mDNS 主机名优先，IP 仅作兜底）；同步更新模块 docstring 与 `_mdns_hostname`/`_entry_host`/`_lan_url` 的 docstring。mDNS 名与局域网 IP 都已写进 `--allowed-host`，两种入口都能过 kimi 的 DNS-rebinding 栅栏（40301）。
  - 测试同步：`tests/test_launcher_kimi_web.py` 4 处断言从「IP 优先」改为「mDNS 优先」（`test_lan_ip_preferred_over_mdns_for_loopback`→`test_mdns_preferred_over_lan_ip_for_loopback`、`test_lan_ip_preferred_over_mdns_for_lan_host`→`test_mdns_preferred_over_lan_ip_for_lan_host`、`test_mdns_fallback_when_no_lan_ip`→`test_mdns_used_even_without_lan_ip`、`test_lan_ip_preferred_for_local_instance`→`test_mdns_preferred_for_local_instance`），并更新 fixture 注释；`tests/test_launcher_dsh_web.py` 的 `_fake_lan_ip` fixture 补 patch `kimi_web._mdns_hostname`（`_entry_host` 现 mDNS 优先，需同时钉住 kimi_web 命名空间的 mDNS 探测，避免 `_lan_url` 真去解析 mDNS 导致断言随网络漂移）。两文件 84 项单测全部通过。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；收尾后重启 launcher 服务部署并实测入口 URL 为 `tony007.local`。

## 2026-08-21 (127)

- fix(drive): 遥测曲线勾选框默认全部勾选
  - 背景：用户此前要求「默认每个选项都勾选上」，但 Drive 页遥测曲线图例仍有部分参数默认未勾选（只有 5 条 `defaultOn: true`、其余 7 条 `defaultOn: false`），打开页面时这些曲线不显示。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：`CURVES` 数组里 7 条 `defaultOn: false` 全部改为 `defaultOn: true`，现在 12 条曲线全部默认勾选。`DrivePage.tsx` 与 `TelemetryChart.tsx` 的初始 `visibleKeys` 均用 `filter((c) => c.defaultOn)` 派生，无需改动初始化逻辑，全勾选即自动生效。
  - 测试同步：`web_ui/frontend/src/components/drive/TelemetryChart.test.tsx` 4 处更新——①「收到遥测后显示默认 5 条曲线」改为「收到遥测后默认显示全部曲线」，断言改为 `arrayContaining` 含全部 12 条 + `toHaveLength(12)`；② gyro/accel 缩放用例删除「勾选默认隐藏的 AccX 复选框」段，AccX 现在默认已显示，直接断言 `ax scale=1/9.8` 已写入；③「勾选隐藏的曲线后显示」改为「取消勾选默认显示的曲线后隐藏」，GyroX 默认已显示，点 checkbox 取消后应消失；④ 注释「三条默认曲线」改「全部默认曲线」。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (126)

- feat(tub-library): 录制视频库新增下载视频到浏览器功能，打包为 tar.gz
  - 背景：用户在 TubLibrary 浏览录制会话时，需要把整条录制的图片帧下载到本地浏览器，此前没有对应入口。
  - `web_ui/backend/routers/tub.py`：新增 `GET /tub/download_session` 端点——以 read_only 打开 tub，按 `sessionId` 过滤 records，从 `tub_path/images/` 读取每条 record 的 JPEG，用 `tarfile.open(fileobj=buf, mode='w:gz')` 内存打包，`StreamingResponse` 返回；文件名用 session 的 `start_time_ms` 格式化为 `recording_YYYY-MM-DD_HH_MM_SS.tar.gz`。
  - `web_ui/frontend/src/i18n/messages/tublibrary.ts`：zh/en 各新增 `download`/`downloadAria`/`downloading`/`downloadFailed` 四个键。
  - `web_ui/frontend/src/services/api.ts`：新增 `downloadTubSession` 函数——axios `responseType:'blob'` 请求端点，`createObjectURL` + `<a>` 标签触发浏览器下载，文件名在前端用 `start_time_ms` 格式化。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：import `downloadTubSession` + `Download`（lucide-react）；新增 `isDownloading` state 与 `handleDownload` callback；在 Refresh 与 Delete 按钮之间加 Download 按钮（variant=secondary, size=sm, disabled=`!hasRecords || isDownloading`）。
  - 测试同步：`TubLibrary.test.tsx` mock 加 `downloadTubSession: vi.fn()`，新增 `describe('TubLibrary download button')` 两个测试（按钮存在且 enabled、点击调用 `downloadTubSession`）；`npx vitest run --root . src/components/TubLibrary.test.tsx` 6 项通过。
  - 注：仅 DD 改动（后端 + 前端），Firmware 无改动、无需 OTA；收尾后重建 dist 并部署到 8000。

## 2026-08-21 (125)

- fix(tub-library): 二轮帧率优化——移除播放热路径多余状态调用、节流预取、去掉 FPS 徽章 backdrop-blur
  - 背景：第一轮 (121) 做了直接 canvas 绘制 + 节流 `setFrame` 每 6 帧，但播放循环仍有三个性能瓶颈：① 每帧调 `setImageError(false)` / `setFrameAspect()` 产生无谓的 React 状态入队开销（即使值不变也会创建 update 对象、入队、处理队列）；② `prefetchFromIndex(next)` 每帧调用，遍历 60 个 URL + 对每个 cached entry 做 LRU touch（Map.delete + Map.set）；③ FPS 徽章 `backdrop-blur-md` 在 canvas 每帧更新时强制浏览器重新采样模糊背景，是 backdrop-filter 配合频繁变化背景的已知性能陷阱。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - 播放循环每帧不再调 `setImageError(false)` / `setFrameAspect()`——`setFrameAspect` 在 draw effect（非播放时）已处理，播放期间 aspect ratio 不变；`setImageError` 也无需每帧调，图片能画出说明没出错。
    - `prefetchFromIndex` 从每帧调用改为 `if (next % UI_UPDATE_EVERY_N_FRAMES === 0)` 每 6 帧一次，预取窗口 60 帧仍有 54 帧余量。
    - FPS 徽章去掉 `backdrop-blur-md`，改用不透明背景 `bg-zinc-900/80`，消除 backdrop-filter 每帧重采样开销。
  - 测试同步：`npx vitest run TubLibrary` 4 项通过；`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动，无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (124)

- fix(tub): TM 报错 `len should return >= 0`——`Manifest.__len__()` 在删除全部记录后返回负数
  - 根因：`donkeycar/parts/datastore_v2.py:441` `Manifest.__len__()` 返回 `self.current_index - len(self.deleted_indexes)`，当 `deleted_indexes` 条目数超过 `current_index`（如 tub 中所有记录被删除）时返回负数，Python `len()` 内置函数抛出 `TypeError: 'len()' should return >= 0`。任何对 `Tub`、`Manifest`、`ManifestIterator` 调用 `len()` 的代码路径（makemovie、training pipeline、TM 等）均会触发。
  - 修复：`Manifest.__len__()` 改为 `return max(0, self.current_index - len(self.deleted_indexes))`，用 `max(0, ...)` 钳制为非负。不影响正常场景下的行为。
  - 测试同步：`donkeycar/tests/test_tub_v2.py` 新增 `test_delete_all_records_len`——删除全部记录后 `len(tub)` 应返回 0 而非抛出 `TypeError`；4 项测试全部通过。
  - 注：仅 donkeycar Python 库改动，DD 前端/Firmware 无改动、无需 OTA；无需本机部署。

## 2026-08-21 (123)

- fix(drive): Drive 遥测曲线不显示——移除数据集 `parsing:false` 导致的解析跳过（Issue #135 收尾回归）
  - 背景：上一轮 (118) 把遥测图改为原生 Chart.js 直改 dataset + `update('none')`，并在每个数据集里写了 `parsing:false`/`normalized:true`。Chart.js 的 `DatasetController.parse` 在 `parsing===false` 时把 `meta._parsed` 直接设为原始 number 数组、跳过 `number → {x,y}` 解析；而 `LineController.updateElements` 读 `parsed[vAxis]`（即 `number['y']`）得 `undefined`，于是每个点 `skip=true`，曲线完全不画。Playwright 实测运行实例两张遥测图 canvas `colored:0`（只有灰色网格、零彩色曲线像素），而数据已写入缓冲（`waitingData=false`）——正好吻合。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：数据集配置删除 `parsing:false` 与 `normalized:true`（第 207 行 chartOptions 顶层的 `normalized:true` 属无效配置、无害，保留不动）。默认解析下 in-place 改数组 + `chart.update('none')` 会走 `_resyncElements → parse()` 重新解析，曲线正常重绘。
  - 测试同步：`web_ui/frontend/src/components/drive/TelemetryChart.test.tsx` 新增回归断言「数据集未禁用 parsing」，防止再引入 `parsing:false`；`npx vitest run src/components/drive/TelemetryChart.test.tsx` 8 项通过、`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (122)

- feat(tub-editor): Tub 编辑器只显示录制视频库当前浏览视频的遥测曲线
  - 背景：Tub Editor 的 Data Graph 此前始终绘制整个 tub 全部记录的 steering/throttle 曲线；用户在录制视频库（TubLibrary）浏览某条录制时，下方编辑器仍把所有录制混在一起，无法专注查看当前视频的遥测。
  - `web_ui/frontend/src/store/useStore.ts`：新增 `activeSessionId` / `activeSessionRecords` 状态与 `setActiveSession` action；`setTub` 时清空会话态；导出 `TubRecord` 类型供跨模块类型断言。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：选中会话后把该会话 records 写入 store；`currentIndex` 联动语义从「物理 `_index`」统一为「当前会话帧下标」（正向写 `frame`、反向按帧下标跳帧），与编辑器自洽。
  - `web_ui/frontend/src/components/TubEditor.tsx`：派生 `records = activeSessionId != null ? activeSessionRecords : 全局 records`，图表/缩放/选区/删除恢复随当前会话切换；删除/恢复后刷新会话 records；底部滑块已删除红条与选区绿条在会话作用域下按会话物理 `_index` 跨度定位。
  - 测试同步：`TubLibrary.test.tsx` 新增「选中会话 records 写入 store」断言；`npx vitest run` 21 文件 115 项、`npx tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (121)

- fix(tub-library): 录制视频库播放帧率过低——播放循环绕过 React 状态直接画 canvas，节流 UI 更新
  - 背景：TubLibrary 播放循环每帧调 `setFrame(next)`（60 次/秒），每次触发整个组件树 re-render + 3 个 useEffect（draw/prefetch/index sync），主线程开销 5-10ms/帧吃掉 16.7ms 帧预算，导致 rAF 回调延迟、大量掉帧，实际播放帧率远低于 60fps 目标。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - 新增 `UI_UPDATE_EVERY_N_FRAMES=6` 常量，播放时每 6 帧才 `setFrame()` 更新 React 状态（~10fps），帧计数器/进度条/统计/全局 index 联动均降频。
    - 新增 `imageUrlsRef` + 预计算 effect：`records` 变化时一次性算好所有帧的图片 URL 存入 ref，播放循环每帧不再重复调 `findImagePath` + `getImageUrl`。
    - 新增 `prefetchFromIndex` useCallback：把预取逻辑从独立 effect 移入播放循环内调用，去掉每帧 effect 开销。
    - 播放循环重写：每帧从 `imageUrlsRef` 取 URL → 查 `imageCacheRef` → 直接 `ctx.drawImage()` 画到 canvas，不触发 React re-render；播放结束/暂停时才 `setFrame(frameRef.current)` 同步 React 状态到实际显示帧。
    - draw effect 加 `isPlayingRef.current` 守卫，播放期间跳过该 effect（由播放循环直接画 canvas）。
    - 删除独立 prefetch effect（已被 `prefetchFromIndex` 替代）。
    - `isPlaying` effect 在 `!isPlaying` 时补 `setFrame(frameRef.current)`，让暂停/播放结束时进度条/统计对齐。
  - 测试同步：`npx vitest run TubLibrary` 3 项通过；`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动，无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (120)

- fix(drive): 全屏/叠加态去掉白色边框与灰色蒙版，遥测曲线只保留纯线条与标题
  - 背景：整屏放大后，摄像头画面四角取景框与遥测曲线的 `border-white/10` 白框、`bg-slate-950/50 backdrop-blur-sm` 灰色蒙版显得杂乱；用户要求去掉白框、删掉蒙版。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：四角取景框改为仅在摄像头未连接（`!webRtcVisible && status !== 'connected'`）时显示，连上/全屏时不再出现。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：overlay 模式容器 className 由 `rounded-lg border border-white/10 bg-slate-950/50 backdrop-blur-sm p-2` 改为 `p-2`，去掉白框与灰色蒙版，只保留标题与曲线线条。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (119)

- fix(drive): 车端离线时也回占位帧，修复 Drive 页反复「正在连接摄像头 → 摄像头未连接」
  - 背景：上一轮占位帧修复只在「车端在线但无首帧」时回占位帧，「车端离线」时仍保持静默（`sleep(0.1)` 不发任何字节）；浏览器 `<img src="/drive/video">` 收不到首帧，既不 `onLoad` 也不 `onError`，前端 `VideoStream` 会一直卡「正在连接摄像头」，长时间无数据甚至被浏览器判为加载失败（`onError`）显示「摄像头未连接」。本机存在「车端 WebSocket 连 8001、默认入口 8000」的端口分裂时，8000 后端恒判车端离线，必现该循环。
  - `web_ui/backend/routers/drive.py`：`_frame_generator` 去掉「车端离线静默」分支——只要没有真实帧可推（车端离线，或在线但尚未推首帧），都按 2fps 推占位帧，让 `<img>` 立即 `onLoad`；仅在占位帧生成失败（Pillow 不可用）时才静默。
  - 测试同步：`web_ui/backend/tests/test_drive.py` 的 `test_video_stream_stays_silent_when_offline` 改为 `test_video_stream_emits_placeholder_when_offline`，断言离线也立即返回有效 JPEG 占位帧；backend `pytest -q` 100 passed。
  - 注：仅 DD 后端改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist；收尾后需重启后端部署验证。

## 2026-08-21 (118)

- fix(drive): 遥测曲线改用原生 Chart.js 直改 dataset + `update('none')`，消除切换标签页卡顿与点击无响应（Issue #135）
  - 背景：Drive 页两张实时遥测曲线用 react-chartjs-2 的 `<Line>`，每次数据变化都会重设 `chart.options`，触发 chart.js 的 `_configure` + Proxy 全量重解析（CPU profile 里 `ownKeys`/`configure`/`qs` 等占满主线程，100Hz 遥测下主线程占用约 87%、longtask 约 3 次/秒每次约 300ms），导致点 Donkey / Drift Console 要等数分钟甚至无响应，只有开新窗口才有反应。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：弃用 react-chartjs-2 `<Line>`，改为 `<canvas>` + 原生 `Chart` 实例；重绘时直接改写 dataset 数据数组（`parsing:false`/`normalized:true`）并调用 `chart.update('none')`，跳过动画/布局/配置解析，每次重绘降至亚毫秒级；环形缓冲 256→128，重绘节流 ~5fps 保持不变；新增 `syncDisplay` 让勾选隐藏曲线后立刻带上已有历史。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：遥测继续走旁路 feed（100Hz 不落 state）；overlay 曲线默认显隐由「全部分组曲线」改为「仅 `defaultOn` 曲线」，把默认绘制曲线从 12 条降到 5 条。
  - `web_ui/frontend/src/store/useTelemetryStore.ts`（新增）：zustand 旁路遥测 store（`latest`/`push`/`reset`），遥测帧不触发 React 重渲染。
  - `web_ui/frontend/src/hooks/useDriveWebsocket.ts`：`car_connection`/`car_state` 值不变时 `return prev`，避免控制循环 60Hz 回广播造成 60Hz 重渲染。
  - `web_ui/frontend/src/hooks/useDriveWebRtcVideo.ts`：`setMetrics` 逐帧改 500ms 节流。
  - 测试同步：`TelemetryChart.test.tsx` 改为断言原生 chart 实例的 dataset 数据（mock `Chart` 构造器 + `canvas.getContext`）；`npm run check`（tsc）通过；`npx vitest run` 21 文件 114 项通过；`npm run build` 通过，入口 `index-CExCDR9k.js`、DrivePage chunk `DrivePage-CCOrU13W.js`。
  - 验证：Playwright + CDP CPU 4x 节流 + 假车 100Hz 遥测实测——longtask 由 24~25 次 / 约 7000ms 降到 0~2 次 / 约 0~119ms；点 Donkey 到内嵌 iframe 出现由 >10s 超时降到约 0.4~0.9s。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后需重建 dist 并部署到本机 8000。

## 2026-08-21 (117)

- fix(layout): DD 左上角 logo 边框改为随主题，对齐 Drifter Console headerLogo（浅色灰边）
  - 背景：上一轮把 logo 边框硬编码为 `border-[#2b3441]`，在浅色主题下显得是「黑边」；而 Drifter Console 的 headerLogo 边框是随主题的——深色 `#2b3441`、浅色 `#d5dce4`（灰）。用户看到 DC 浅色下的灰边、DD 却是深灰黑边。
  - `web_ui/frontend/src/components/Layout.tsx`：logo `<img>` className 由 `w-8 h-8 rounded-lg border border-[#2b3441]` 改为 `w-8 h-8 rounded-lg border header-logo`，边框色交由主题 CSS 决定。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：末尾各新增 `html.theme-mus4 .header-logo { border-color:#2b3441 }` 与 `html.theme-light .header-logo { border-color:#d5dce4 }`，完全对齐 DC headerLogo 的深/浅边框值。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过、`npx vitest run` → 21 文件 114 项全绿。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (116)

- fix(drive): 摄像头画面去掉整框（边框+圆角矩形），改为四角圆弧取景框，避免无画面时四角出现黑角
  - 背景：视频流容器此前是 `bg-zinc-950 border border-zinc-800 rounded-lg` 的整块圆角矩形；摄像头未连接时，圆角矩形边框与圆角裁切在四角留下黑角，观感突兀。用户要求只显示四角圆弧、不显示整框。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：根容器 className 去掉 `border border-zinc-800 rounded-lg`（保留 `bg-zinc-950 overflow-hidden`）；新增 4 个 `absolute` 角标 `<span>`（`top/left`、`top/right`、`bottom/left`、`bottom/right`，`h-6 w-6`、`border-2 border-zinc-700`、`rounded-*-lg`、`z-40 pointer-events-none`），只画圆角弧线、不画整框。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (115)

- fix(launcher): DD 内嵌 Donkey 删除「Donkey」标题，版本号移到「当前工作目录」右侧
  - 背景：内嵌视图精简到只剩菜单后，页头还残留「Donkey」标题与版本号；用户要求删掉标题、把版本号挪到当前工作目录那一行右侧。
  - `donkeycar/launcher/server.py`：`isEmbedded` 清理逻辑中，隐藏选择器由 `.logoLink, .ghLink, .sectionTitle` 扩展为 `.logoLink, .ghLink, .headerRow h1, .sectionTitle`（删掉「Donkey」标题）；新增 `var badge = document.querySelector('.versionBadge')` 并 `cwdBar.appendChild(badge)`，把版本号移到 `.cwdBar` 末尾（label/路径右侧）；单独打开 Donkey（:8090）时标题与版本号位置均保持不变。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_embedded_hides_topbar_chrome` 断言同步更新（隐藏选择器含 `.headerRow h1`、版本号移动 `cwdBar.appendChild`、`titleLink`/`versionBadge` 仍在 HTML）；`python -m pytest tests/test_launcher*.py -q` → 143 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-21 (114)

- fix(connector): Car Connector「车辆设置」改为只嵌车端 DC 的设置视图（`?embedded=1&settings=1`），不再把整个 DC 主页（Mode/Park/Drift/电池等显示卡）塞进来
  - 背景：Car Connector 之前的「车辆设置」iframe 直接加载车端根路径 `?embedded=1`，把 DC 主页的状态显示卡（Mode RC、Park、Logged、Drift Off、电池电量等）也一并带进来；用户指出这些是「显示」而非「设置」，正确需求是只放设置类板块（Wi-Fi 配网、OTA、开发模式、漂移设置、Judge、摇杆校准）。
  - `web_ui/frontend/src/components/CarSettingsPanel.tsx`：iframe `src` 由 `http://${selectedIp}/?embedded=1` 改为 `http://${selectedIp}/?embedded=1&settings=1`，并同步更新组件头注释。车端配合 Firmware 侧新增 `?settings=1` 仅设置视图（见 Firmware `WebConsoleAssets.h`）。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：本改动依赖 Firmware v1.8.28 的 `?settings=1` 视图；Firmware 已同步 OTA 至车辆（192.168.3.46，版本 v1.8.28）。

## 2026-08-21 (113)

- fix(drive): 整屏放大键改为原生全屏（`requestFullscreen`），与 Drifter Console 遥测曲线全屏一致
  - 背景：上一轮「整屏放大」用的是 CSS `fixed inset-0` 假全屏覆盖层，未真正进入浏览器全屏（浏览器地址栏/页面其它元素仍在）；用户要求参考 Drifter Console 遥测曲线右下角全屏按钮，做到真正全屏。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：新增 `videoContainerRef` 指向摄像头容器；`toggleFullscreen` 改为 `document.fullscreenElement === el ? document.exitFullscreen() : el.requestFullscreen()`；新增 `fullscreenchange` 监听同步 `fullscreen` 状态（含 ESC 退出），继续驱动曲线高度与图标；容器 className 去掉 `fixed inset-0 z-50 bg-black` 假全屏分支，改为恒定的 `relative flex-1 min-h-0 aspect-video lg:aspect-auto bg-black`。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (112)

- fix(console): DD 顶栏 OTA/DEV 开关边框厚度与深浅/中英文切换按钮对齐为双层边框
  - 背景：Drifter Console（DC）顶栏的 OTA 与 DEV 按钮此前只吃到 `html.theme-* .bg-zinc-800` 的 `outline:1px` 描边（`outline-offset:-1px`），观感是单层 1px 边框；而旁边的深浅切换、中英文切换、静音按钮走 `border-color + box-shadow:inset 0 0 0 1px` 的双层边框，两者边框厚度/颜色明显不一致。
  - `web_ui/frontend/src/themes/theme-mus4.css`：把 `.console-ota-btn`、`.console-dev-toggle` 纳入与 `.theme-switcher-btn`/`.language-switcher-btn`/`.console-mute-btn` 同款基础覆盖（`outline:none; background:#111820; border-color:#344154; box-shadow:inset 0 0 0 1px #2b3441; color:#b9c5d3`），并新增 OTA/DEV hover（`#5cc8ff` 双层）、DEV `[aria-checked="true"]` 开启态（`rgba(92,200,255,.25)` 底 + `#5cc8ff` 双层）、OTA `:disabled` 置灰（`#8fa1b5`）。
  - `web_ui/frontend/src/themes/theme-light.css`：同步浅色皮肤（基础 `#f4f6f9/#ccd5df/#d5dce4/#3f4f63`、hover `#0c9bd6` 双层、DEV 开启 `#5cc8ff` 双层、OTA 禁用 `#5b6b7d`）。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过；`npx vitest run src/components/ConsoleControls.test.tsx` 12 passed。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (111)

- fix(launcher): DD 内嵌 Donkey 的「当前工作目录」只去框、保留文字（上一轮误删整块）
  - 背景：上一轮把 `.cwdBar` 与 `.panel` 一起去框时，误将 `.cwdBar` 放进 `display:none` 隐藏列表，导致「当前工作目录」文字与路径在内嵌视图里整块消失；用户要求只删框、不删文字。
  - `donkeycar/launcher/server.py`：`isEmbedded` 清理逻辑中，隐藏选择器由 `.logoLink, .ghLink, .cwdBar, .sectionTitle` 改为 `.logoLink, .ghLink, .sectionTitle`（`.cwdBar` 不再隐藏）；去框循环由单个 `.panel` 改为 `['panel', 'cwdBar']`，对两者只做 `background/border/padding` 清零，保留 `display:flex` 与文字内容（label「当前工作目录」+ 路径）。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_embedded_hides_topbar_chrome` 断言同步更新——隐藏选择器不含 `.cwdBar`、去框选择器为 `['panel', 'cwdBar']`，并新增 `cwd-path` / `cwd.label` 仍在的断言；`python -m pytest tests/test_launcher*.py -q` → 143 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-21 (110)

- fix(drive): 整屏放大键间距对齐——下边距与右边距一致（均 12px）
  - 背景：上一轮把放大键上移到 `bottom-48`/`bottom-64`，离油门/加速度曲线框太远显空；要求放大键右边到视频右边框、下边到曲线框上边框的距离一致。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：非全屏 `bottom-48` → `bottom-44`、全屏 `bottom-64` → `bottom-60`，使下边距与 `right-3`（12px）对齐。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (109)

- fix(layout): DD 左上角 logo 对齐 Drifter Console 独立页图标（恢复 1px #2b3441 边框）
  - 背景：DC 独立页头图标为 32×32、`border-radius:8px`、`border:1px solid #2b3441` + `/favicon.png` 头盔图（与 DD `/logo.png` 为同一张图）；上一轮按「去掉黑边」去掉了边框，现按用户要求直接照搬 DC 图标，因此恢复该边框。
  - `web_ui/frontend/src/components/Layout.tsx`：标题左侧 logo 的 `img` className 由 `w-8 h-8 rounded-lg` 改为 `w-8 h-8 rounded-lg border border-[#2b3441]`，并同步注释为「与 Drifter Console headerLogo 完全一致」。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过、`npx vitest run` → 21 文件 114 项全绿。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (108)

- fix(drive): 整屏放大键再上移，避开下方油门/加速度曲线框
  - 背景：上一轮把放大键移到视频右下角 `bottom-36`/`bottom-[13rem]`，仍叠在油门/加速度曲线框顶部——overlay 曲线块除 h-28/h-44 曲线区外还含标题行与 p-2 内边距，实际整体更高。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：非全屏由 `bottom-36` 改为 `bottom-48`、全屏由 `bottom-[13rem]` 改为 `bottom-64`，使按钮底部落在曲线框顶部之上约 28px，不再遮挡。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后重建 dist 并部署 8000。

## 2026-08-21 (107)

- fix(launcher): DD 内嵌 Donkey 隐藏与顶栏/标题重复的 chrome，单独 :8090 不受影响
  - 背景：DD 内嵌 Donkey（`?embedded=1`）时，页头仍显示 Donkey 图标、GitHub 图标、深浅色切换、中英文切换、当前工作目录框与「菜单」标题，且菜单外层有一圈 panel 框——这些与 DD 顶栏/标题重复，用户要求在内嵌视图中删掉、只留菜单内容。
  - `donkeycar/launcher/server.py`：`const isEmbedded = readEmbedded()` 后新增内嵌态 chrome 清理——`isEmbedded` 时对 `.logoLink`、`.ghLink`、`.cwdBar`、`.sectionTitle` 隐藏（`display:none`），对 `#themeBtn`、`#langBtn` 隐藏，并对 `.panel` 去框（`background/border/padding` 清零）以保留 `menu-grid` 菜单内容；单独打开 Donkey（:8090）时上述元素全部保留。
  - 测试同步：`tests/test_launcher_menu_actions.py` 新增 `test_embedded_hides_topbar_chrome`，断言内嵌隐藏逻辑（`if (isEmbedded)` / 选择器 / 去框样式）与单独打开时各元素仍在 HTML；`python -m pytest tests/test_launcher*.py -q` → 143 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-21 (106)

- feat(donkeycar): `evaluate` 数据统计模式新增转向幅度三档占比 + 左右对称性指标
  - 背景：目标 4 定位到 angle corr≈0 的根因是转向数据本身——85% 直行、中间幅度（0.05<|angle|≤0.5）仅约 3.3%、且右转 91.5% vs 左转 7.9% 极度不对称；原 `evaluate` 只有 `abs_lt_0.05_ratio`，无法一眼看出「中间幅度缺失」与「左右不对称」这两个数据质量缺口。
  - `donkeycar/management/base.py`：`Evaluate.run()` 无 `--model` 分支的 `angle_stats` 新增 `mid_ratio`（0.05≤|angle|≤0.5）、`hard_ratio`（|angle|>0.5）、`left_ratio`（angle<0）、`right_ratio`（angle>0），保留 `abs_lt_0.05_ratio`（=直行占比）。三档占比相加为 1，左右占比 left+right+zero 相加为 1。
  - 测试同步：`donkeycar/tests/test_evaluate_command.py` 新增对 `mid_ratio`/`hard_ratio`/`left_ratio`/`right_ratio` 的断言，`pytest -q` 4 passed。
  - 注：仅新增 CLI 统计字段，不影响本机 Web UI，无需部署/OTA。

## 2026-08-21 (105)

- fix(layout): DonkeyDrifter 左上角 logo 去掉外边框（#2b3441），与 Donkey 图标视觉一致
  - `web_ui/frontend/src/components/Layout.tsx`：标题左侧 `<img>` 的 className 由 `w-8 h-8 rounded-lg border border-[#2b3441]` 改为 `w-8 h-8 rounded-lg`，去掉 1px 深色外边框；同步更新注释（「1px #2b3441 边框」→「无外边框」）。
  - 测试同步：`npm run build`（tsc + vite）通过；前端 vitest 21 文件 114 项全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-21 (104)

- fix(drive): 整屏放大键由视频右上角移到右下角（油门/加速度曲线框上方），避免与右上角帧率显示干涉
  - 背景：上一轮「整屏放大」功能把放大键放在了视频画面右上角，与同区域右上角的帧率（FPS）文字重叠干涉；用户要求挪到不干涉的位置——视频画面右下角、再往上一点，即油门/加速度曲线框的上方。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：放大按钮定位由右上角改为 `absolute right-3`，垂直位置非全屏 `bottom-36`（浮在右板块曲线 h-28 上方）、全屏 `bottom-[13rem]`（浮在 h-44 曲线上方）；其余整屏放大逻辑不变。
  - 测试同步：`cd web_ui/frontend && npm run build`（tsc + vite）通过，入口 `index-DSgVDX7x.js`、DrivePage chunk `DrivePage-CY-vFxm4.js`。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA；收尾后需重建 dist 并部署到本机 8000。

## 2026-08-21 (103)

- fix(drive): 车端在线但未推首帧时 MJPEG `/drive/video` 立即回占位帧，修复进入 Drive 页偶发一直卡「正在连接摄像头」、需很久才连上（Issue #221 补充修复）
  - 背景：后端 `_frame_generator` 在「无帧或车端离线」时只 `sleep(0.1)` 空转、不发送任何字节；浏览器 `<img src="/drive/video">` 收不到首帧，既不触发 `onLoad` 也不触发 `onError`，前端 `VideoStream` 的 `status` 永远停在 `loading`，于是「正在连接摄像头」长时间挂着；上一轮 5s 超时只能让它在「正在连接 / 未连接」之间空转，无法真正结束等待。
  - `web_ui/backend/routers/drive.py`：新增 `_make_placeholder_frame()`（Pillow 生成 640×360 深色「等待画面」占位 JPEG）+ 模块级 `_PLACEHOLDER_FRAME` 缓存 + `_multipart_part()` 分片构造辅助 + `PLACEHOLDER_FRAME_INTERVAL=0.5`；`_frame_generator` 改为「有真实帧且在线 → 推真实帧；离线 → 保持静默（前端走 /drive/stats 显示车端离线）；在线但无首帧 → 按 2fps 推占位帧让 `<img>` 立即 `onLoad`」。
  - 测试同步：`web_ui/backend/tests/test_drive.py` 新增 3 项（在线无帧推占位帧 / 在线有帧推真实帧 / 离线静默不推流），backend `pytest -q` 100 passed。
  - 注：仅 DD 后端改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-21 (102)

- fix(trainer): 训练收尾保存 loss 元数据报 `'dict' object has no attribute 'history'`，改为按 dict 直接取值
  - 根因：`donkeycar/parts/keras.py` 的 `train()` 返回 `history.history`（普通 dict），但 `pipeline/training.py` 保存 loss 元数据时仍按 `tf.keras.callbacks.History` 对象取 `history.history.get(...)`，触发 `AttributeError`；该段在 `try/except` 内仅打 error，模型训练本身与 `database.json`（直接存 dict）不受影响，只缺 `*_meta.json` 侧车文件。
  - `donkeycar/pipeline/training.py`：`history.history.get('loss'/'val_loss', [])` 改为 `history.get('loss'/'val_loss', [])`。
  - 验证：模块可正常导入，`dict.get` 逻辑输出正确（本机无 GPU，走 float32）。目标 2 的 41 轮训练已产出 `pilot_2`（best val_loss 0.1595）。
  - 注：仅 donkeycar 库训练路径改动，不影响本机 Web UI，无需部署/OTA；Firmware 无改动。

## 2026-08-20 (101)

- fix(donkeycar): KerasCategorical 运行时解码由 argmax 改为 softmax 期望值，避免恒输出直行/停车
  - 背景：categorical 模型输出 15（angle）/20（throttle）类 softmax 分布，但 `KerasCategorical.interpreter_to_output` 之前用 `linear_unbin`（内部 `np.argmax`）解码，把概率分布坍缩成单一分箱、输出跳变；在本机模拟器数据（85% 直行）下 angle 恒预测直行、throttle 恒预测多数类，corr≈0。
  - `donkeycar/utils.py`：新增 `linear_unbin_softmax(arr, N, offset, R)`——用概率加权平均求期望分箱索引再反缩放回连续值（one-hot 输入下与 `linear_unbin` 结果一致，向后兼容）。
  - `donkeycar/parts/keras.py`：`KerasCategorical.interpreter_to_output` 的 angle/throttle 解码改调 `linear_unbin_softmax`；类 docstring 同步更新。`KerasBehavioral` 继承同一 `interpreter_to_output`，一并受益。
  - 测试同步：`donkeycar/tests/test_util_data.py` 新增 `TestLinearUnbinSoftmax` 4 项（one-hot 等价 / 均匀分布取中心 / 偏斜分布加权平均 / throttle 期望值），`test_util_data.py` 23 passed；另以 `object.__new__` 轻量验证 `interpreter_to_output` 对 0.5/0.5 两分箱输出 0.0、均匀 throttle 输出 0.2375。
  - 注：仅 donkeycar 库改动，不影响本机 Web UI，无需部署/OTA。

## 2026-08-20 (100)

- fix(launcher): KCW 入口注入 `?kimi_origin=<origin>`，钉住前端 API 基地址，修复任务执行时 getSessionSnapshot 报 "TypeError: Load failed"
  - 背景：上一轮把入口 origin 回退为局域网 IP 优先（PR #266），但用户点 Kimi 后执行任务仍报「无法加载当前会话内容 / TypeError: Load failed」，请求打到 `http://tony007.local:58640`（mDNS 旧 origin）。根因：KCW 0.36.1 前端 API 基地址判定为 URL `?kimi_origin` → `sessionStorage["kimi-desktop-server-origin"]` → `window.location.origin`；launcher 未注入 `kimi_origin`，浏览器残留早期 mDNS 阶段写进 sessionStorage 的 `tony007.local` 仍把 API 指到连不上的 mDNS host。
  - `donkeycar/launcher/kimi_web.py`：新增 `_mark_origin()`（追加 `?kimi_origin=http://<entry_host>:<port>/`，同名参数先去重再追加），三处返回点由 `_mark_onboarded(_lan_url(url))` 改为 `_mark_origin(_mark_onboarded(_lan_url(url)))`；模块 docstring 增加第 4 条 issue #168 约束说明。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestMarkOrigin`（追加 / 覆盖旧 origin / 保留路径与其它 query 三例），`test_reuses_live_instance_without_spawning` / `test_spawn_success_captures_url_and_keeps_proc` / `test_spawn_failure_falls_back_to_reuse` 三处返回 URL 断言补 `kimi_origin`；`test_launcher_kimi_web.py` + `test_launcher_dsh_web.py` 共 84 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-20 (99)

- feat(donkeycar): 新增 `evaluate` 命令，量化评估模型 angle/throttle 预测质量并检查数据分布
  - `donkeycar/management/base.py`：新增 `Evaluate(BaseCommand)`（`parse_args` / `_metrics` / `run`）并在 `commands` 注册 `'evaluate': Evaluate`。两种模式：传 `--model` 时用 `TubDataset` 读记录、`model.run(img)` 推理，对 angle/throttle 输出 `corr / mae / rmse / mean_err / count`；不传 `--model` 时输出 `user/angle`、`user/throttle` 的分布统计（mean/std/min/max，另给 angle 的 `abs_lt_0.05_ratio`）；`--out` 写 JSON。用于客观判断模型是否真正学到转向/油门信号（corr≈0 即退化为预测均值/多数类），并判断训练数据是否均衡。
  - `donkeycar/tests/test_evaluate_command.py`：新增 4 项测试（`parse_args` 参数解析、`_metrics` 完美预测与常量标签无相关、无模型模式经 mock 跑数据统计并写 JSON），`pytest -q` 4 passed。
  - 注：仅新增 CLI 命令，不影响本机 Web UI，无需部署/OTA。

## 2026-08-20 (98)

- feat(drive): Drive 遥测曲线左右分栏（转向/姿态 vs 油门/加速度）+ 整屏放大，移除暂停/清空按钮
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：`CurveConfig` 新增 `group` 字段并导出 `CurveGroup` 类型与 `curvesByGroup` 辅助；`TelemetryChart` 新增 `title`/`group`/`chartHeightClassName` 可选参数，`TelemetryLegend` 新增 `group` 参数（按分组只渲染该组曲线与复选框）；删除暂停/清空/全屏按钮及其状态逻辑（`paused`/`handlePauseToggle`/`handleClear`/`fullscreen`/`toggleFullscreen`），全屏改为由父组件统一管理整块画面。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：曲线显隐改为左右两组独立状态（`steeringVisibleKeys`/`throttleVisibleKeys` + 各自 toggle）；视频容器内渲染两个 `TelemetryChart` overlay 浮层（左=转向/姿态、右=油门/加速度），图例分左右两组放视频容器下方；新增整屏放大按钮（右上角），全屏时视频容器 `fixed inset-0 z-50 bg-black` 放大摄像头 + 遥测曲线，曲线高度 `h-44`。
  - `web_ui/frontend/src/i18n/messages/driveviz.ts`：新增 `chartTitleSteering`（转向 / 姿态）与 `chartTitleThrottle`（油门 / 加速度），删除不再使用的 `paused`/`pause`/`resume`/`clear`。
  - 测试同步：`TelemetryChart.test.tsx` 删除暂停/清空/全屏用例，新增「group 模式下只渲染该分组的曲线与图例」用例，7 项通过；前端 vitest 21 文件 116 项、`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。


## 2026-08-20 (97)

- fix(theme): Donkey 与 DonkeyDrifter 深浅色手动切换改为仅内存态、不写存储——修复「手动切换后刷新仍保持所选主题，无法重新跟随系统」的问题，使 D / DD / DC 三页一致：默认跟随系统、每次进入/刷新都重新按浏览器 prefers-color-scheme 解析
  - 背景：D（launcher 8090）与 DD（8000）此前把主题选择持久化到 localStorage/sessionStorage，手动点过太阳/月亮后刷新仍保持所选主题、不再跟随系统；本次与 DC（Firmware v1.8.27）对齐为不持久化。
  - `web_ui/frontend/src/lib/theme.ts`：删除 `THEME_STORAGE_KEY`，新增模块级内存态 `let currentThemeMode: ThemeMode = 'system'`；`readStoredTheme` 改为返回内存态；`setTheme` 改为只更新内存态并 `applyTheme`（不写 localStorage/sessionStorage）。
  - `web_ui/frontend/index.html`：首屏防闪烁脚本改为直接 `matchMedia('(prefers-color-scheme: dark)')` 解析，不读任何存储。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：删除 `THEME_STORAGE_KEY` 导出；注释更新为「仅内存、不持久化、每次进入/刷新重新跟随系统」。
  - `donkeycar/launcher/server.py`：删除 `THEME_STORAGE_KEY` 常量与 v3 迁移/localStorage 读取；首屏脚本改为直接按系统解析；`setTheme` 改为仅 `applyTheme`（删 localStorage.setItem）；`initTheme` 改为 `applyTheme('system')` + 系统监听（删 localStorage 读取）。
  - 测试同步：`web_ui/frontend/src/components/ThemeSwitcher.test.tsx` 重写为断言「setTheme 不写 localStorage/sessionStorage（`window.localStorage.length===0` 与 `window.sessionStorage.length===0`）」；`tests/test_launcher_theme_single_button.py` 更新首屏脚本断言、删除 v3/localStorage 断言、新增 `applyTheme('system')` 与「无 localStorage 读取」断言。
  - 注：Firmware 侧 DC 同步改动见 Firmware `CHANGELOG.md` v1.8.27。

## 2026-08-20 (96)

- fix(launcher): DD 内嵌 Donkey 的 11/12 号彻底删除（整行含序号），6/7 仍置灰占位
  - 背景：上一条 (94) 把 6/7/11/12 都做成了内嵌置灰占位；用户要求 11/12（Kimi Code Web / DeepSeek Harness）彻底删掉（整行连同序号都不显示），6（DonkeyDrifter）/7（Drifter Console）保持置灰占位不变。
  - `donkeycar/launcher/server.py`：`menuItems` 的 11/12 号由 `ddTopbarOnly:true` 改为 `ddHidden:true`；`renderMenu()` 在遍历开头新增 `if (isEmbedded && item.ddHidden) return`（内嵌时整行不渲染，序号 11/12 直接空出）；`selectItem()` 新增 `if (isEmbedded && item.ddHidden) return`（内嵌时数字键无响应）。6/7 仍 `ddTopbarOnly:true`（内嵌置灰占位），单独打开 Donkey（:8090）时 6/7/11/12 均完整可点击。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_menu_6_7_11_12_embedded_only_placeholder` 重写为 `test_menu_6_7_grayed_11_12_hidden_embedded`（断言 6/7 `ddTopbarOnly`、11/12 `ddHidden` + `isEmbedded && item.ddHidden` 守卫）；launcher 相关 139 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-20 (95)

- fix(console): DonkeyDrifter 顶栏 DEV 开关开启态对齐 Drifter Console 原版效果（#5cc8ff + 内描边）
  - `web_ui/frontend/src/components/ConsoleControls.tsx`：`ConsoleDevToggle` 的 `enabled` 分支由 `bg-cyan-500/25 border-cyan-500/60 text-cyan-400` 改为 `bg-[#5cc8ff]/25 border-[#5cc8ff] text-[#5cc8ff] shadow-[inset_0_0_0_1px_#5cc8ff]`，完全对齐 DC 页面 `.devOn` 的 `background:rgba(92,200,255,.25);border-color:#5cc8ff;box-shadow:inset 0 0 0 1px #5cc8ff;color:#5cc8ff`。
  - `web_ui/frontend/src/components/ConsoleControls.test.tsx`：用例 `highlights in cyan when enabled` 改名为 `highlights like the DC DEV toggle when enabled`，断言更新为 `bg-[#5cc8ff]/25` / `border-[#5cc8ff]` / `text-[#5cc8ff]` / `shadow-[inset_0_0_0_1px_#5cc8ff]`。
  - 测试同步：`npm run build`（tsc + vite）通过；`ConsoleControls.test.tsx` 11 项通过；全量 vitest 21 文件 117 项中 116 通过（`App.test.tsx` 的 Tub Manager 保持挂载用例在并行跑时偶发 waitFor 超时，单跑该文件 6 项全通过，属既有 flaky，与本次无关）。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (94)

- fix(launcher): DD 内嵌 Donkey 的 6 号（DonkeyDrifter）也置灰占位——6/7/11/12 均仅内嵌时占位，单独打开 Donkey 仍完整
  - 背景：6 号「DonkeyDrifter」在内嵌于 DonkeyDrifter 的 Donkey 菜单里是自引用（用户当前已在 DD 内），属冗余入口；用户要求检查并删除，且只删 DD 内嵌的 Donkey、单独 Donkey 页（:8090）不动。
  - `donkeycar/launcher/server.py`：`menuItems` 的 6 号新增 `ddTopbarOnly:true`，并加 `phDescZh/phDescEn`（「当前已在 DonkeyDrifter 内 / Already inside DonkeyDrifter」）；`renderMenu()` 与 `selectItem()` 的占位描述由硬编码「已并入 DonkeyDrifter 顶栏」改为优先取 `item.phDescZh/phDescEn`，缺省回退到「已并入 DonkeyDrifter 顶栏 / Merged into DonkeyDrifter top bar」（7/11/12 无 phDesc、走回退）。
  - 11/12 号上一轮已加 `ddTopbarOnly`（内嵌置灰），本次无额外改动。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_menu_7_11_12_embedded_only_placeholder` 重写为 `test_menu_6_7_11_12_embedded_only_placeholder`（新增 6 号 name、`当前已在 DonkeyDrifter 内`/`Already inside DonkeyDrifter`、`no === 6`/`launchDrive()` 接线断言）；launcher 相关 139 passed。
  - 注：仅 launcher 改动，Firmware 无改动、无需 OTA；前端无改动、无需重建 dist。

## 2026-08-20 (93)

- feat(console): DonkeyDrifter 顶栏静音键切换成功后经 postMessage 即时同步内嵌 Drifter Console，无需等 5s 轮询或手动刷新（Issue #117 续）
  - `web_ui/frontend/src/components/ConsoleControls.tsx`：新增导出常量 `MUTE_CHANGED_EVENT = 'dd-console-mute-changed'`；`ConsoleMuteButton.toggle()` 在 POST 成功并 `fetchMute()` 后 `window.dispatchEvent(new CustomEvent(MUTE_CHANGED_EVENT, { detail: { muted: next === 1 } }))`，广播最新静音态。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：给内嵌 iframe 增加 `ref={iframeRef}`，新增 `useEffect` 监听 `MUTE_CHANGED_EVENT`，回调里 `iframeRef.current?.contentWindow?.postMessage({ type: MUTE_CHANGED_EVENT, muted }, '*')`，让车端原版 DC 页面即时更新静音图标；不重载 iframe、不丢曲线/终端状态（静音是高频轻量操作）。
  - 测试同步：`ConsoleControls.test.tsx` 新增「切换后广播 MUTE_CHANGED_EVENT 且 detail.muted 正确」用例；前端 `npm run build`（tsc + vite）通过。
## 2026-08-20 (92)

- fix(drive): 遥测曲线勾选框默认全部选中
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`visibleKeys` 初始值由 `CURVES.filter((c) => c.defaultOn)` 改为 `CURVES` 全量，Drive 页遥测曲线图例默认勾选全部曲线（之前默认只勾选 5 条，其余 7 条需手动开启）。
  - 测试同步：`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (91)

- feat(connector): Car Connector 新增「车辆设置」iframe 区块，1:1 嵌入车端 Drifter Console 的设置功能（Issue #234 后续）
  - `web_ui/frontend/src/components/CarSettingsPanel.tsx`：新增自包含组件，复用 `discoverConnectorConsoles` 做设备发现 + 设备选择下拉 + 重扫按钮，用 iframe 直连 `http://<ip>/?embedded=1` 呈现车端配网 / OTA / 开发模式 / 漂移设置 / Judge / 摇杆校准等设置；DonkeyDrifter 的 `/console` 入口保持不变。
  - `web_ui/frontend/src/pages/CarConnectorPage.tsx`：在页面末尾接入 `<CarSettingsPanel />`。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：新增 `connector.carSettingsTitle` / `connector.carSettingsSubtitle`（zh/en）。
  - 测试同步：前端 `npm run build`（tsc + vite）通过。

## 2026-08-20 (90)

- fix(drive): 遥测曲线图例移到视频画面外部下方，勾选框不再遮挡摄像头
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：导出 `CURVES` 与新的 `TelemetryLegend` 组件；`TelemetryChart` 新增受控 `visibleKeys`/`onToggleCurve` 可选参数（不传则内部自管，保持兼容）；`overlay` 覆盖模式不再在图内渲染图例。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：持有曲线显隐状态（`visibleKeys` + `toggleCurve`），把 `TelemetryLegend` 放到视频容器下方（`mt-3 shrink-0`），曲线图本体仍以半透明浮层覆盖在画面底部。
  - 测试同步：`npm run build`（tsc + vite）通过、`TelemetryChart.test.tsx` 9 项通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (89)

- fix(launcher): 7/11/12（Drifter Console / Kimi Code Web / DeepSeek Harness）仅在 DD 内嵌 Donkey 时置灰占位，单独打开 Donkey（:8090）恢复完整可点击入口
  - 背景：上一条 (84) 把 7/11/12 改为 `placeholder:true` 占位行，但 launcher 同一 `server.py` 同时服务 DD 内嵌 `/donkey` 与独立 Donkey 页（:8090），导致单独打开 Donkey 时 7/11/12 也被置灰；用户要求只改 DD 内嵌的 Donkey、单独 Donkey 页不受影响。
  - `donkeycar/launcher/server.py`：新增 `readEmbedded()` 解析 `?embedded=1` 与常量 `const isEmbedded`；`menuItems` 的 7/11/12 恢复为完整条目（原始 `name`/`cat`/`descZh`/`descEn`/`favorite`）并加 `ddTopbarOnly:true` 标记；`renderMenu()` 与 `selectItem()` 的占位守卫由 `item.placeholder` 改为 `item.placeholder || (isEmbedded && item.ddTopbarOnly)`，占位文案统一为「已并入 DonkeyDrifter 顶栏 / Merged into DonkeyDrifter top bar」；`selectItem()` 恢复 `no===7→openDrifterConsole()`、`no===11→launchKimiCodeWeb()`、`no===12→launchDshWeb()` 三个动作分支；帮助文案 `help.keyNumbers`（HTML+i18n zh/en）由「7、11、12 已并入…」改回中性「数字键 1-12：选择对应菜单项」，避免单独打开时误导。
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`：iframe src 由 `${getDonkeyUrl()}?lang=${lang}` 改为 `${getDonkeyUrl()}?embedded=1&lang=${lang}`，标记 DD 内嵌模式。
  - 测试同步：`tests/test_launcher_menu_actions.py` 的 `test_menu_7_11_12_merged_into_dd_topbar` 重写为 `test_menu_7_11_12_embedded_only_placeholder`（断言 7/11/12 恢复完整 name、`ddTopbarOnly:true`、`readEmbedded`/`embedded=1`/`isEmbedded`、`isEmbedded && item.ddTopbarOnly`、`no===7/11/12` 动作分支恢复）；launcher 相关 139 passed、前端 vitest 21 文件 117 项、`tsc -b --noEmit` 全部通过。
  - 注：仅 DD/launcher 改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (88)

- fix(layout): DonkeyDrifter 顶栏改为纯色背景，消除与内容区之间的半透明背景边界横线（Issue #234 后续）
  - `web_ui/frontend/src/components/Layout.tsx`：`<header>` 去掉 `bg-zinc-900/50 backdrop-blur supports-[backdrop-filter]:bg-zinc-900/50`，改为 `bg-zinc-950`，与下方内容区同色，视觉上完全融合，不再有一条横向分界线。
  - 测试同步：前端 `npm run build`（tsc + vite）通过。

## 2026-08-20 (87)

- fix(drive): 遥测曲线覆盖浮层由摄像头画面上方移到下方，贴着画面底部
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`TelemetryChart` 的 overlay 定位由 `absolute inset-x-3 top-14 z-20` 改为 `absolute inset-x-3 bottom-3 z-20`，曲线浮层贴到摄像头画面底部，避开顶部延迟/FPS 角标，视觉更贴合用户预期。
  - 测试同步：`npm run build`（tsc + vite）通过，产物含 `bottom-3`、不含 `top-14`。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (86)

- fix(layout): DD 顶栏左右内边距由 0 调整为 12px，logo/标题与 DEV 对齐到 DC 内容左缘
  - `web_ui/frontend/src/components/Layout.tsx`：上一条 (83) 把顶栏内层容器改成全宽无内边距后过于贴边；本次改为 `px-3`（12px），与 Drifter Console 内嵌页 `body{margin:12px}` 的左侧最外框左缘对齐，右侧 DEV 同样 12px 贴右。
  - 测试同步：前端 vitest 全量 21 文件 117 项通过、`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (85)

- feat(launcher): Donkey 菜单与 Drifter Console 内嵌时经 iframe src 的 `?lang=` 跟随 DonkeyDrifter 语言——修复「DD 已切英文、内嵌 Donkey/DC 仍是中文」的跨源语言不同步问题
  - 背景：DD（:8000）顶栏 `LanguageSwitcher` 切换语言只写 DD 自己 origin 的 `localStorage['donkeydrifter.ui.lang']`；内嵌的 launcher（:8090）与车端 DC（:80）是跨源 iframe，各自读自己 origin 的 localStorage / 车端 `/api/language`，DD 切语言不会传导过去。
  - `donkeycar/launcher/server.py`：`readStoredLanguage()` 前新增 `readUrlLanguage()`（解析 `?lang=zh|en`），`readStoredLanguage` 优先返回 `?lang=`，无参数时再走 localStorage/浏览器语言，使 launcher 首次加载即与 DD 语言一致。
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`：iframe src 由 `getDonkeyUrl()` 改为 `${getDonkeyUrl()}?lang=${lang}`；切换 DD 语言时 src 变化触发 iframe 重载，内嵌 Donkey 菜单随之切换。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：iframe src 由 `/?embedded=1` 改为 `/?embedded=1&lang=${lang}`，把 DD 语言传给车端 DC。
  - 测试同步：`tests/test_launcher_menu_actions.py` 新增 `test_menu_reads_dd_lang_url_param`；launcher 相关 139 passed，前端 vitest 21 文件 117 项、`tsc -b --noEmit` 全部通过。
  - 注：Firmware 侧同步改动（DC 读 `?lang=`）见 Firmware `CHANGELOG.md` v1.8.25。

## 2026-08-20 (84)

- feat(launcher): Donkey 菜单 7/11/12 号（Drifter Console / Kimi Code Web / DeepSeek Harness）并入 DonkeyDrifter 顶栏，改为置灰占位行且序号不递补
  - 背景：Donkey（launcher，8090 菜单页）里的 7/11/12 号入口与 DonkeyDrifter 顶栏标签页里的高级入口重复——DC / KCW / DSH 三个入口在顶栏已经能进，Donkey 菜单内保留即冗余；用户要求删除后序号空出、不递补。
  - `donkeycar/launcher/server.py`（MENU_HTML 内嵌前端）：`menuItems` 的 7/11/12 号改为 `placeholder:true`（`name:"—"`、`cat:null`、`descZh/descEn` 标注「已并入 DonkeyDrifter 顶栏」、无常用标）；`renderMenu()` 新增占位行渲染分支（不渲染分类 pill、不渲染常用标、不可点击）；`selectItem()` 增加 `if (item.placeholder)` 守卫（点击仅轻提示已并入顶栏）并移除 `no===7/11/12` 三个动作分支；新增 `.menuItem.placeholder` 深/浅色样式；帮助文案三处（HTML + i18n zh + i18n en）同步「7、11、12 已并入 DonkeyDrifter 顶栏」。
  - 刻意保留 `openDrifterConsole`/`launchKimiCodeWeb`/`launchDshWeb` 函数定义与后端 `/api/launch/*` 端点（DD 后端仍会转发 KCW/DSH 到这些端点）。
  - 测试同步：`tests/test_launcher_menu_actions.py` 把 `test_menu_6_renamed_and_dc_moved_to_7` 重写为 `test_menu_7_11_12_merged_into_dd_topbar`（断言 placeholder 标记、双语「已并入…」、`no === 7/11/12` 不再出现、`no:8`/`no:12` 仍在）；launcher 相关测试共 138 passed。
  - 注：本次改动位于 launcher 共享源，`donkeycar/launcher/server.py` 同时服务「独立 Donkey 页（8090）」与 DD 内嵌 `/donkey`（iframe 到同一 launcher），两处页面一起生效，无法只改其中一边。Firmware 无改动、无需 OTA。

## 2026-08-20 (83)

- fix(layout): DD 顶栏 logo/标题贴左、右侧控件（含 DEV）贴右，与 Donkey 页左侧菜单左缘对齐
  - `web_ui/frontend/src/components/Layout.tsx`：顶栏内层容器去掉 `container mx-auto px-4`，改为全宽无横向内边距，使标题左侧 logo/标题贴到窗口最左、右侧版本号/GitHub/静音/主题/语言/OTA/DEV 贴到最右，与全宽 Donkey 内嵌页左侧菜单左缘对齐。
  - 测试同步：前端 vitest 全量 21 文件 117 项通过、`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (82)

- feat(drive): 遥测曲线以半透明浮层覆盖在摄像头画面上方，摄像头铺满并裁边放大
  - `web_ui/frontend/src/pages/DrivePage.tsx`：左列视频由「按高度反推宽度居中」改为 `relative flex-1` 填满剩余空间（移动端 `aspect-video`、桌面端 `lg:aspect-auto`），`VideoStream` 传 `objectFit="cover"` 铺满并裁边放大、消除左右空边；`TelemetryChart` 改为 `overlay` 覆盖模式，`absolute inset-x-3 top-14` 贴在画面上方。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：新增 `objectFit` 参数（默认 `contain`），内部 `img`/`video` 按 `cover`/`contain` 切换 `object-cover`/`object-contain`。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：新增 `overlay` 覆盖模式——半透明底 `bg-slate-950/50` + `backdrop-blur-sm`、紧凑高度 `h-28`、默认收起曲线开关（全屏后仍可调）。
  - 测试同步：`npm run build`（tsc + vite）通过，产物含 `object-cover`/`top-14`/`h-28`/`bg-slate-950/50`/`backdrop-blur-sm`。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (81)

- feat(console): DD 顶栏 OTA 改为当前页弹窗上传、DEV 开启加确认/悬浮提示，并让 DEV 状态即时同步到内嵌 DC
  - `web_ui/frontend/src/components/ConsoleControls.tsx`：`ConsoleOtaButton` 由 `<a href="http://<ip>/update" target="_blank">` 改为按钮打开本地上传弹窗（文件选择 + 上传/状态 + 成功/失败文案），用 `consolePostForm(ip, 'update', FormData)` 经同源代理上传固件，成功后提示设备重启；`ConsoleDevToggle` 增加开启确认弹窗（关闭直接生效），仅在 `enabled=false` 时点开启弹出 `console.devTitle/devBody` 确认框，确认后才 POST '1'；DEV 按钮加自定义悬浮提示（`console.devHint`，对齐 DC 文案）；成功切换后派发 `dd-console-devmode-changed` 事件。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：监听 `dd-console-devmode-changed` 事件并重载 iframe（`reloadKey`），让内嵌车端 DC 立即反映最新 dev_mode。
  - `web_ui/frontend/src/i18n/messages/console.ts`：新增 `console.devTitle/devBody/devConfirm/devHint/console.cancel` 中英文案（对齐 DC `dev.title/dev.body/button.confirmDev/devHint`）。
  - `web_ui/backend/routers/console.py`：OTA `POST /update` 单独放宽超时 `PROXY_TIMEOUT=10` → `OTA_TIMEOUT=300`，避免大固件上传超时；`_forward_sync` 增加 `timeout` 参数（默认 10s）。
  - 测试同步：`ConsoleControls.test.tsx` 11 项（新增 OTA 弹窗上传/DEV 确认/DEV 悬浮提示/关闭免确认断言）、`tests/test_console.py` 4 项（新增 update 走长超时断言）；前端 vitest 全量 21 文件 117 项、`tsc -b --noEmit`/`npm run build`、后端 pytest 97 项全部通过。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (80)

- fix(drive): 虚拟摇杆把手英文改为横排两行（Virtual / Joystick），中文保持竖排（Issue #232 后续）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`useTranslation` 增加 `lang`；把手文字按语言渲染——`lang === 'en'` 时去掉 `writing-mode:vertical-rl`，改为 `flex flex-col` 把 `drive.virtualJoystick` 按空格拆成两行横排（第一行 Virtual、第二行 Joystick），中文仍走竖排分支；注释同步更新为「中文竖排、英文横排两行」。
  - 测试同步：前端 vitest 21 文件 114 项通过、`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (79)

- fix(layout): 去掉 DonkeyDrifter 顶栏与内容区之间的分隔横线（Issue #234 后续）
  - `web_ui/frontend/src/components/Layout.tsx`：`<header>` 去掉 `border-b border-zinc-800`，顶部导航/标题与下方内容视觉融合，不再有一条横向分隔线。
  - 测试同步：前端 `npm run build`（tsc + vite）通过。

## 2026-08-20 (78)

- fix(web-ui): DD 主题切换改为会话级持久化，避免手动选择永久覆盖「跟随系统」
  - `web_ui/frontend/src/lib/theme.ts`：主题持久化存储由 `localStorage` 改为 `sessionStorage`（`readStoredTheme` 读取与 `setTheme` 写入两处），手动选择仅在当前标签页会话内生效，关闭标签页后重新跟随系统，消除「点过一次主题按钮后永远不再跟随系统」的问题。
  - `web_ui/frontend/index.html`：首屏内联脚本同步改读 `sessionStorage`，旧 `localStorage` 残留不再影响首屏主题。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：注释更新为会话级持久化语义。
  - 测试同步：`ThemeSwitcher.test.tsx` 断言由 `localStorage` 改为 `sessionStorage`；`vitest` ThemeSwitcher 8 项通过、`npm run build`（tsc + vite）通过。

## 2026-08-20 (77)

- fix(drive): 摄像头按可用高度反推宽度并略降曲线图高度，画面更大且消除左右黑边
  - `web_ui/frontend/src/pages/DrivePage.tsx`：左列改为 `flex flex-col` + 桌面端 `lg:h-[calc(100vh-9rem)]`，摄像头区 `flex-1` 撑满剩余高度；`VideoStream` 由 `w-full + max-h` 改为 `lg:h-full lg:w-auto lg:max-w-full` 居中，按实际画面比例反推宽度，替换原先高度压缩时 `object-contain` 产生的左右黑边。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：曲线区高度 `h-48` → `h-40`，为摄像头让出更多纵向空间。
  - 测试同步：`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (76)

- fix(drive): 限制摄像头高度，让 Drive 页摄像头与下方遥测曲线同屏可见
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`VideoStream` 增加 `lg:max-h-[calc(100vh-32rem)]` 视口高度上限。摄像头按实际画面比例自适应后，在常见桌面屏上画面过高会把 `TelemetryChart` 顶出首屏；加此上限后曲线无需滚动即可同屏显示。`VideoStream` 内部画面为 `object-contain`，高度被压缩时完整居中、只留黑边不裁切。
  - 测试同步：`npm run check`（tsc）通过、`npm run build`（vite）通过，产物含该类名与 `max-height: calc(100vh - 32rem)` 规则。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (75)

- fix(web-ui): Donkey 内嵌页改为全屏铺满，并修正 Donkey 模式下的顶栏高亮、侧栏遮挡与帮助小球
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`：去掉 DD 侧标题栏与 `space-y-3` 包装，iframe 铺满顶栏以下全部可视区域（`h-[calc(100vh-3.5rem)]` + `h-full w-full border-0`），用户看到与真实 Donkey 启动页（8090）一致的完整界面。
  - `web_ui/frontend/src/App.tsx`：`isConsole` 扩展为 `isFullBleed`（`/console` 或 `/donkey`），`/donkey` 同样隐藏左侧 Loaders/Connectors 浮动抽屉，避免遮挡内嵌 launcher。
  - `web_ui/frontend/src/components/Layout.tsx`：新增 `isDonkey`/`isFullBleed`；`/donkey` 时流程锚点（Drive 等）一律不高亮；`<main>` 在 `/donkey` 改 `py-0` 全屏比例；`/donkey` 隐藏 DD 右下角 FAB，让 launcher 自带的 Donkey 帮助小球显示、不与 DD FAB 重叠。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DonkeyEntryLink` 增加 `/donkey` 激活态（`text-cyan-500`），修复「在 Donkey 页时 Drive 为蓝色、Donkey 为灰色」。
  - 测试同步：`EnterButtons.test.tsx` 新增 Donkey 激活态断言；`App.test.tsx` 新增 `/donkey` 隐藏 SidePanel 与 FabActions 的断言；前端 vitest 21 文件 114 项、`npm run check`（tsc）、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (74)

- fix(flow): Drive/TM/Trainer/PA 大页节标题的灰色小字由垂直居中改为基线对齐，与标题视觉平行（Issue #233）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 内层容器由 `items-center` 改为 `items-baseline`，小字 span 去掉多余的 `leading-none`，与基准组件 `SectionCardTitle`（视频录制库/Top编辑器）的小字 class 保持一致，消除小字相对 `text-xl` 大标题偏高、不平行的问题。
  - 测试同步：`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (73)

- fix(drive): 虚拟摇杆抽屉展开/收起动画收窄过渡属性，减少卡顿（Issue #232 后续）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：抽屉面板由 `transition-all` 改为 `will-change-[width] transition-[width]`，展开/收起只过渡 width，不再同时过渡 border 等 layout 属性，降低每帧 reflow/paint 负担。
  - `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：跑马灯副标题外层由 `transition-all` 改为 `transition-[opacity,margin-left]`，去掉 max-width 的 layout 过渡（宽度瞬时切换、由 `overflow-hidden` 裁剪），避免 hover 触发跑马灯时与抽屉展开动画叠加产生额外 reflow。
  - 测试同步：前端 vitest 21 文件 112 项通过、`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (72)

- fix(console): Drifter Console 连接条微调——「未发现设备」文案缩短、版本号样式对齐 DD 顶栏版本号、连接条与 iframe 视觉融合（Issue #234）
  - `web_ui/frontend/src/i18n/messages/console.ts`：`console.noDevice` 中英两处缩短为「未发现设备」/「No device found」，去掉「请确认同一网络」半句。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：
    - 工具条去掉 `border-b border-zinc-800 bg-zinc-900/50`，改为与下方 iframe 同底色、无分隔线。
    - 版本号由 `font-mono text-xs text-zinc-400` 改为对齐顶栏 `VersionBadge` 的 `text-zinc-500 text-xs uppercase tracking-wider`，渲染为 `v{version}`（version 存纯版本号，去 V 前缀）。
  - 测试同步：前端 `npm run build`（tsc + vite）通过。
## 2026-08-20 (71)

- fix(launcher): Kimi Code Web 入口 origin 由 mDNS 主机名优先回退为局域网 IP 优先，恢复被 mDNS 迁移孤立的置顶与「完全自主」权限偏好（Issue #168 后续）
  - 背景：KCW 的置顶（`kimi-web.pinned-sessions`）、权限模式（`kimi-web.permission`）、onboarding 等 UI 偏好都存浏览器 localStorage、按 origin 隔离。前几轮为抗 DHCP 换 IP 漂移把入口 origin 稳定到 `tony007.local:58640`，但这次迁移本身把老 origin（局域网 IP `192.168.3.57:58640`）里的偏好孤立了——用户表现为「置顶全没了、原来是完全自主模式现在变逐条确认」。服务端无法跨 origin 读写浏览器 localStorage，唯一能恢复老偏好的办法是让入口 origin 回到老 IP。
  - `donkeycar/launcher/kimi_web.py`：`_entry_host()` 由 `return _mdns_hostname() or _lan_ip()` 改为 `return _lan_ip() or _mdns_hostname()`——局域网 IP 优先、mDNS 主机名兜底；同步更新模块 docstring、`_mdns_hostname()`/`_lan_url()`/`_mark_onboarded()`/`_allowed_host_values()` docstring 说明回退原因。`--allowed-host` 仍同时放行 mDNS 与局域网 IP，两种入口都能过 40301。
  - 测试同步：`tests/test_launcher_kimi_web.py` 的 mDNS 优先断言改为 IP 优先（loopback/本机 IP/local instance 三处），新增 mDNS 兜底用例（无局域网 IP 时回退 mDNS），删除已不可达的 mDNS rebind 门用例；`test_launcher_kimi_web.py` + `test_launcher_dsh_web.py` 共 81 passed。
  - 注：纯 DD launcher 改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (70)

- fix(console): Drifter Console 内嵌 iframe 改用 `?embedded=1` 参数加载，只隐藏 DD 嵌入视图里的车端 DC 标题栏，车端 DC 页面本身标题栏保持显示（Issue #234）
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：iframe `src` 由 `http://<ip>/` 改为 `http://<ip>/?embedded=1`。
  - 配套 Firmware 改动见 Firmware 仓库当日条目（v1.8.20 恢复 DC 标题栏显示、新增 `body.embedded .headerRow{display:none}` 与 embedded 参数检测）。

## 2026-08-19 (69)

- feat(console): Drifter Console 由 DD 风格重绘改为 iframe 1:1 嵌入车端原版，并在连接条「连接」按钮右侧显示车端固件版本号（Issue #234）
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：整页重写——删除 571 行 DD 风格重绘（状态 key=value 表格、遥测卡片、终端、Wi-Fi STA、OTA、开发模式、静音），改为 iframe 直接加载 `http://<ip>/`，排版与显示功能与车端 Web Console 完全一致；仅保留一条极简「发现/手动连接」工具条（设备选择下拉 + 重扫 + 手动 IP + 连接）。
  - 连接条版本号：`useEffect([selectedIp])` 调用车端 `api/status`，用 `version=(\S+)` 提取固件版本、去 `V` 前缀后以 `v1.8.19` 格式显示在「连接」按钮右侧（`font-mono text-xs text-zinc-400`）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DrifterConsoleEntryLink` 由「扫描车端 + `window.open` 新标签页打开车端原版」改为 `<Link to="/console">` 当前标签页内进入。
  - `web_ui/frontend/src/App.tsx`：新增 `/console` 懒加载路由与空闲预取；`isConsole` 时隐藏左侧 `SidePanel`（Loaders/Connectors 浮动抽屉不再遮挡 iframe），其它页面保持正常显示。
  - `web_ui/frontend/src/components/Layout.tsx`：`isConsole` 时流程锚点（Drive/TM/Trainer/PA）一律不高亮，Drifter Console 由 `DrifterConsoleEntryLink` 自身高亮，修复「打开 DC 时 Drive 仍为蓝色、DC 仍为灰色」；`<main>` 在 `/console` 改为 `py-0` 全屏比例。
  - `web_ui/frontend/src/i18n/messages/console.ts`：缩短「未发现设备，请确保连接同一网络」连接中提示文案。
  - 测试同步：前端 `npm run check`（tsc）与 `npm run build` 通过、vitest 全量通过。
  - 注：配套 Firmware 改动见 Firmware 仓库当日条目（v1.8.19 隐藏 DC 主页面 header 行）。

## 2026-08-19 (68)

- feat(web-ui): Donkey 菜单改为当前页内嵌显示，顶栏控件（静音/DEV/Car Connector）样式对齐 DC 与 OTA
  - `web_ui/frontend/src/App.tsx`：新增 `/donkey` 懒加载路由与空闲预取，指向新内嵌页 `DonkeyMenuPage`。
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`（新增）：以 iframe 嵌入 launcher(:8090) 的 Donkey 菜单页，点击顶栏 Donkey 不再新开标签页（与 Drifter Console 的 `/console` 一致）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DonkeyEntryLink` 由 `<a target="_blank">` 改为 `<Link to="/donkey">`，图标由 `Car` 改为 `Menu`；导出 `entryLinkCls` 供 Layout 复用。
  - `web_ui/frontend/src/components/ConsoleControls.tsx`：`ConsoleMuteButton` 静音态改 DC 蓝 `#5cc8ff`（边框/图标同色）并补 `aria-pressed`；`ConsoleDevToggle` 由滑块改为与 OTA 同款文字胶囊按钮（开启 cyan 高亮、关闭同 OTA 灰）。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.console-mute-btn` 并入主题/语言按钮的双层内圈视觉（修复与语言切换按钮边框厚度不一致），并加静音激活态蓝色覆盖。
  - `web_ui/frontend/src/components/Layout.tsx`：Car Connector 导航项改用 `entryLinkCls`（与 KCW/DSH 同字号/弱化色）并加左侧 `Settings` 齿轮图标，桌面/移动端同步。
  - 测试同步：`EnterButtons.test.tsx` 断言 Donkey 改走 `/donkey` 内嵌路由；`ConsoleControls.test.tsx` 新增 DEV 胶囊与静音蓝态断言；前端 vitest 全量 21 文件 112 项、`npm run check`（tsc）、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (67)

- fix(drive): Drive 页虚拟摇杆抽屉面板移到把手左侧、标题不换行、副标题改为跑马灯（Issue #232 第五轮微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：抽屉内部 `flex items-start gap-2` 中「面板内容」与「浮动触发把手按钮」对调，展开后顺序变为 视频画面 → 虚拟摇杆面板 → 把手开关，把手仍在面板右侧（展开时位于视频右侧更外侧）；`SectionCardTitle` 传入 `subtitleMarquee`。
  - `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：新增可选 `subtitleMarquee?: boolean` prop；标题 `<span>` 加 `whitespace-nowrap`，保证「虚拟摇杆」四字单行完整显示；副标题在 `subtitleMarquee` 为 true 时改为跑马灯渲染（外层 `overflow-hidden`、内层 `inline-block whitespace-nowrap` + `animate-[marquee-x_9s_ease-in-out_infinite]`），默认 false，不影响其他页面。
  - `web_ui/frontend/src/index.css`：新增 `@keyframes marquee-x`（`0% translateX(0)` → `72%`/`88% translateX(calc(-100% + 10rem))` 停顿 → `100% translateX(0)` 重播），实现副标题从左到右播放、到右端稍停后重播。
  - 测试同步：前端 vitest 21 文件 110 项通过、`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (66)

- fix(web-ui): DonkeyDrifter 页主题按钮去掉「跟随系统」显示器图标，改为深/浅两态互切（默认仍跟随浏览器，但不显示跟随系统状态）（Issue #230 最终形态，DD 前端）
  - 背景：DD 前端（8000）主题按钮此前为 跟随系统/浅色/深色 三态，其中「跟随系统」显示显示器（电脑）图标；用户要求默认仍跟随浏览器，但按钮只保留太阳/月亮两态、去掉电脑图标。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：删除 `Monitor` 图标与 `NEXT_MODE`/`MODE_LABEL` 三态逻辑，改为按当前生效主题（`useResolvedTheme()`）在浅/深之间互切，图标仅太阳/月亮；aria-label 仅 `切换到浅色主题`/`切换到深色主题`。
  - `web_ui/frontend/src/lib/theme.ts`：删除仅三态按钮使用的 `useThemeMode` 与 `THEME_MODE_CHANGE_EVENT`；`setTheme` 不再广播 mode 事件，`useResolvedTheme` 订阅逻辑不变；`readStoredTheme` 仍默认 `system`（无存储时跟随浏览器并实时监听）。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：由三态用例改为两态用例（8 项），覆盖默认跟随系统、浅/深互切、持久化、手动选择后不再跟随。
  - 测试同步：`ThemeSwitcher` 8 项通过、`npm run check`（tsc）通过、`npm run build` 通过；完整前端 vitest 中 `App.test.tsx` 有 3 项因 `services/api` mock 缺 `getDonkeyUrl` 失败，为既有问题（PR #257 引入 `getDonkeyUrl` 未同步 mock），与本次改动无关。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (65)

- fix(web-ui): Drive 页顶部工具栏移入视频列，录制按钮右边缘与摄像头画面右边界对齐；修复 App.test mock 缺 getDonkeyUrl
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏（左组 Park/模式/模型，右组录制条数/录制）由页面全宽独立一行移入「视频+遥测」左列（`flex-1 min-w-0`）内，右组右边缘随视频列收缩/扩展，抽屉展开时不再越过摄像头画面右边界；工具栏与视频之间加 `mb-4` 间距。录制与录制条数间隙保持 `gap-2 lg:gap-3` 不变。
  - `web_ui/frontend/src/App.test.tsx`：`vi.mock('./services/api')` 补 `getDonkeyUrl`（Issue #257 顶栏 Donkey 入口引入 `getDonkeyUrl` 后漏更新 mock，导致 3 项 App 测试失败）。
  - 测试同步：前端 vitest 21 文件 112 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (64)

- feat(web-ui): 把 DC 头部静音/OTA/DEV/Donkey 四控件整合进 DonkeyDrifter 顶栏，重设计为 DD 风格，静音与车端 DC 双向同步
  - 背景：用户要求 DD 页面顶栏承担原 Drifter Console 头部的一部分控制——静音键放在 GitHub 图标右侧、主题切换左侧并与 DC 双向同步；OTA/DEV 开关放在语言切换右侧；Donkey 入口移入顶部导航栏并加图标（参考 Kimi/DeepSeek 入口样式）。
  - `web_ui/frontend/src/hooks/useConsoleDevice.ts`（新增）：模块级去重 + `sessionStorage` 缓存 ESP32 IP，导出 `useConsoleDevice()`（返回 `{ip, resolving}`），供静音/OTA/DEV 复用设备发现结果。
  - `web_ui/frontend/src/components/ConsoleControls.tsx`（新增）：`ConsoleMuteButton`（lucide `Volume2/VolumeX`，5s 轮询 `/api/console/proxy/<ip>/api/mute` 双向同步）、`ConsoleOtaButton`（新标签页打开 `http://<ip>/update`）、`ConsoleDevToggle`（DEV 滑块，5s 轮询 `/api/devmode`，直接切换无确认弹窗，与内嵌 `/console` 页一致）。
  - `web_ui/frontend/src/services/api.ts`：新增 `getDonkeyUrl()`（`${protocol}//${hostname}:8090/`）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：新增 `DonkeyEntryLink`（lucide `Car` 图标 + 导航链接样式，参考 Kimi/DeepSeek 入口）。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面右上角顺序 `VersionBadge → GitHubLink → ConsoleMuteButton → ThemeSwitcher → LanguageSwitcher → ConsoleOtaButton → ConsoleDevToggle`；桌面导航最左侧加入 `DonkeyEntryLink`；移动端第二行与汉堡菜单面板同步接入。
  - `web_ui/frontend/src/i18n/messages/common.ts`：新增 `common.enterButtons.donkey` / `donkeyTitle`（zh/en）；`web_ui/frontend/src/i18n/messages/console.ts`：新增 `console.muteAria` / `unmuteAria` / `otaOpen` / `unreachable`（zh/en）。
  - 测试同步：新增 `ConsoleControls.test.tsx`（6 项）；`EnterButtons.test.tsx` 补 Donkey 入口断言并 mock `getDonkeyUrl`；前端 `npm run check`（tsc）、vitest 相关 13 项、`npm run build` 全部通过。
  - 注：Firmware 侧同步移除 DC 头部 Donkey/OTA/DEV 并补静音轮询（v1.8.17），见 Firmware CHANGELOG。

## 2026-08-19 (63)

- fix(web-ui): Drive 页遥测曲线图改「有新帧才重绘 + 10fps 节流」，消除空闲 60fps 空转长任务——修复 #135 切换标签页卡顿（尤其 Drive → Drifter Console）
  - 根因：`TelemetryChart` 用 `requestAnimationFrame` 每帧无条件 `setRenderTick` 触发 chart.js 重绘（60fps），即使遥测为空也持续渲染。CPU 4x 实测 Drive 页空闲 10s 产生 25 个 longtask（峰值 ~1s），主线程被连续占满，点击其它标签时路由切换/卸载被饿死，表现为「点了很久才动、一动就瞬跳」。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：移除 rAF 60fps 空转循环，改为「收到新遥测帧写入环形缓冲后，按 `CHART_REDRAW_INTERVAL_MS`（100ms，~10fps）节流 `setRenderTick`」；空闲无遥测时 chart.js 不再重绘。
  - 实测（CPU 4x）：Drive 页空闲 10s longtask 0（修复前 25 个、峰值 ~1s）；Drive → `/console` 路由切换 336ms、切换后 FlowPage 干净卸载、无 longtask；FlowPage 四段导航滑动仍精准落位（err 0/1/1/0）、每段仅 1 个 ~150-180ms longtask。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (62)

- fix(web-ui): Drive 页 Park 锁定移到驾驶模式选择器左侧
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶栏左组顺序由「驾驶模式 → 模型 → Park 锁定」改为「Park 锁定 → 驾驶模式 → 模型」，Park 锁定作为状态指示置于手动/半自动/全自动选择框左侧。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (61)

- fix(web-ui): Drive 流程节标题副标题垂直对齐并复刻 SectionCardTitle 悬停动画（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的标题 `h2` 补 `leading-none`、副标题补 `leading-none`，消除小字相对标题偏高；副标题展开宽度 `max-w-[400px]` → `max-w-[300px]`，与 `SectionCardTitle` 动画参数完全一致（`transition-all duration-300 ease-in-out`）。

## 2026-08-19 (60)

- fix(launcher): Donkey 菜单页主题按钮去掉「跟随系统」显示器图标，改为深/浅两态互切（默认仍跟随浏览器，但不显示跟随系统状态）（Issue #230 最终形态）
  - 背景：上一步三态修复后，主题按钮为 跟随系统/浅色/深色 三态，其中「跟随系统」显示显示器（电脑）图标；用户要求默认仍跟随浏览器，但按钮只保留太阳/月亮两态、去掉电脑图标。
  - `donkeycar/launcher/server.py`：
    - 删除 `icon-monitor` 显示器 SVG 与相关 CSS；图标显隐改由生效主题 `html[data-theme]` 驱动（浅色显太阳、深色显月亮），不再写 `html[data-mode]`。
    - `toggleTheme()` 由三态循环改回深↔浅两态互切（按当前生效主题取反）；`renderThemeBtn()` 的 aria-label/title 改为仅 `theme.toggleLight` / `theme.toggleDark`。
    - `initTheme()` 仍保留 `system` 默认态（无存储时跟随浏览器 `prefers-color-scheme` 并监听变化）；首屏防闪烁脚本只写生效主题 `html[data-theme]`，v3 一次性清除旧残留逻辑不变。
    - i18n 删除 `theme.followSystem` / `theme.toggleSystem`（中英）。
  - `tests/test_launcher_theme_single_button.py`：由三态用例改为两态用例，断言移除 `icon-monitor`/`data-mode`/`followSystem`/`toggleSystem`，保留默认跟随浏览器与 v3 迁移覆盖。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：仅 Donkey launcher（8090）改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (59)

- fix(drive): Drive 页右侧抽屉改为贴视频画面右侧并 sticky 顶部对齐，滚动时留在顶部不跟走（Issue #232 第四次微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：移除 `createPortal` 与基于 scroll/resize 的把手 `top` 动态对齐逻辑（`cameraWrapRef`/`drawerRef`/`handleRef` 及对应 `useEffect` 全部删除）；视频+遥测与抽屉改为 `flex` 左右并排（`lg:flex-row`），抽屉 `aside` 用 `lg:sticky lg:top-16` 锚定在视频右侧并随滚动保持在顶部，收起时面板 `w-0 border-0`、展开时 `w-[min(24rem,calc(100vw-3.5rem))]`；把手由 `absolute right-full` 改为并排独立按钮；面板四角圆角 `rounded-lg` 对齐视频边框（`border border-zinc-800`）。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v4` 功能分支（worktree `session-issue232-v4` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (58)

- fix(web-ui): Drive 流程节标题悬停副标题字号进一步调小到 `text-xs`（12px）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 悬停副标题字号 `text-sm` → `text-xs`，让灰色小字更明显变小。

## 2026-08-19 (57)

- fix(web-ui): Drive 页顶栏右组顺序调整 + Park 锁定对齐模型选择器高度并缩短文案
  - `web_ui/frontend/src/pages/DrivePage.tsx`：右组由「录制按钮 → 已录制条数」改为「已录制条数 → 录制按钮」；Park 锁定徽标由小号 `px-2 py-0.5 rounded` 改为与 `ModelSelector` 同高同大小的 `px-3 py-1.5 rounded-lg border`（红色语义保留）。
  - `web_ui/frontend/src/i18n/messages/drive.ts`：`drive.recordedCount` 中文「已录制条数 {count}」→「已录制条数: {count}」；`drive.parkLocked` 中文「Park 锁定 · 油门被钳 0」→「Park 锁定」、英文「Park locked · throttle clamped to 0」→「Park locked」。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (56)

- fix(launcher): Donkey 菜单页「跟随系统」仍不生效——清除旧二选一遗留的显式主题，首次访问自动恢复跟随系统（Issue #230）
  - 根因：上一版三态修复后，用户浏览器里 8090 origin 的 `localStorage['donkeydrifter.ui.theme']` 仍残留旧二选一时期的显式 `light`/`dark`，页面加载时 `initTheme()` 优先读到显式值，`mode` 不再是 `system`，因此仍不跟随系统。
  - `donkeycar/launcher/server.py`：首屏防闪烁脚本加入一次性迁移——首次访问若 `donkeydrifter.ui.theme.v3 !== '1'`，先 `removeItem('donkeydrifter.ui.theme')` 清掉旧显式残留并写入 `donkeydrifter.ui.theme.v3='1'`，之后尊重用户后续手动选择（仅清一次旧残留）。
  - `tests/test_launcher_theme_single_button.py`：新增首屏迁移字符串断言，覆盖旧残留清除逻辑。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：仅 Donkey launcher（8090）改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (55)

- fix(web-ui): Drive 流程节标题悬停副标题字号回调为 `text-sm`，与全站副标题标准一致（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的悬停副标题（如「驾驶并采集训练数据」）字号由 `text-base` 改为 `text-sm`，避免灰色小字过大。

## 2026-08-19 (54)

- fix(drive): Drive 页右侧抽屉把手真正贴屏幕最右并对齐摄像头画面顶部（Issue #232 第三次微调）
  - 根因：上层 section 的 `content-visibility:auto` 带来 paint containment，导致把手 `fixed right-0` 实际相对 section（摄像头画面右缘）而非 viewport 定位。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：整个抽屉（把手+面板）改用 `createPortal(..., document.body)` 挂到 body，脱离 section containment；新增 `cameraWrapRef`/`drawerRef`/`handleRef`，在 scroll/resize 时用 `requestAnimationFrame` 量出「摄像头画面顶部 - 抽屉顶部」并直接写把手 `style.top`（ref 直写 DOM，避免每次滚动触发整页重渲染、复现 #135 卡顿），使把手顶部与摄像头画面顶部水平对齐。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v3` 功能分支（worktree `session-issue232-v3` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (53)

- fix(web-ui): Drive 流程节标题副标题改为悬停淡入并放大字号，抽屉「虚拟摇杆」标题统一到 SectionCardTitle 标准（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的副标题（如 Drive 的「驾驶并采集训练数据」）由常驻 `<p class="text-sm">` 改为 `group-hover` 悬停淡入的 `<span>`，与全站卡片小标题交互一致；字号由 `text-sm` 放大到 `text-base`。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：右侧抽屉内「虚拟摇杆」标题由手写 group-hover 结构改用 `SectionCardTitle` 组件，字号/字重/颜色统一到全站标准（16px / font-semibold / text-white）。
  - 测试同步：前端 vitest 20 文件 105 项通过、`npm run check`（tsc）、`npm run build` 通过。

## 2026-08-19 (52)

- fix(web-ui): Drive 页顶栏左右分组——左侧驾驶模式/模型/Park 锁定，右侧录制/已录制条数
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏由单组改为左右两组，`justify-between` 分居两端——左组 `DriveModeSelector` → `ModelSelector` → `rc_park` 驻车锁定徽标；右组录制按钮 → 已录制条数。模型选择器按逻辑与驾驶模式同属「车怎么开」配置，故归入左组。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过（新 `DrivePage-*.js` bundle）。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (51)

- fix(launcher): Donkey 菜单页主题不随浏览器深浅色同步——主题按钮改为三态（跟随系统 / 浅色 / 深色），手动选择后可切回"跟随系统"（Issue #230 同源，扩展到 Donkey 启动页）
  - 背景：Donkey 菜单页（8090 launcher）与 DD web_ui 修复前存在同一问题：手动单击主题按钮后显式主题被持久化到 localStorage（`donkeydrifter.ui.theme`），从此不再跟随浏览器，且按钮是"深/浅"二选一、没有"跟随系统"入口。
  - `donkeycar/launcher/server.py`：
    - 首屏防闪烁脚本接受 `system`，并把模式与生效主题分别写到 `html[data-mode]` / `html[data-theme]`。
    - 主题按钮新增显示器图标（`icon-monitor`），图标显隐由 `html[data-mode]` 驱动：跟随系统显显示器、浅色显太阳、深色显月亮；移除按钮上的 `data-i18n-aria/title`，改由 `renderThemeBtn()` 统一生成动态 aria-label/title，并在语言切换后重新渲染。
    - `applyTheme()` 同时写 `data-mode` 与 `data-theme`；`toggleTheme()` 由"深↔浅"二选一改为三态循环 `跟随系统 → 浅色 → 深色 → 跟随系统`；`initTheme()` 仍按存储值（含 `system`）初始化并监听 `prefers-color-scheme` 变化。
    - i18n 新增 `theme.followSystem` / `theme.toggleSystem`（中英）。
  - `tests/test_launcher_theme_single_button.py`：由"二选一"用例改为三态用例，覆盖 `data-mode` 图标显隐、三态循环、首屏 `system` 解析与 `data-mode`/`data-theme` 写入等。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：本次在 `Tony-issue230-donkey-theme-sync` 功能分支（worktree 作业）完成，仅动 DD 的 launcher 页面，Firmware 无改动、无需 OTA。

## 2026-08-19 (50)

- feat(drive): Drive 页右侧抽屉的「虚拟摇杆」触发把手改为竖排文字，贴屏幕最右缘（Issue #232 微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：把手按钮由横向 `flex items-center` 改为 `flex flex-col items-center`，展开/收起 chevron 置顶，`t('drive.virtualJoystick')` 用 `[writing-mode:vertical-rl]` 竖排、`tracking-wider leading-none` 收紧字距；按钮 `px-1.5 py-2 rounded-l-md` 收窄为竖向窄条，仍通过 `absolute right-full` 贴屏幕右缘。
  - 测试同步：前端 vitest 全量 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v2` 功能分支（worktree `session-issue232-v2` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (49)

- feat(console): Drifter Console 完全集成进 DonkeyDrifter——当前标签页内进入 + UI 重绘为 DD 风格（Issue #234）
  - 前置修正：DD 入口按钮文案 `DrifterConsole` → `Drifter Console`（`web_ui/frontend/src/i18n/messages/common.ts` zh/en 两处）。
  - 交互：`components/EnterButtons.tsx` 的 `DrifterConsoleEntryLink` 由「扫描车端 + `window.open` 新标签页打开车端原版 DC」改为 `<Link to="/console">` 当前标签页内进入 DD 内嵌页面；`App.tsx` 新增 `/console` 懒加载路由与空闲预取。
  - 内嵌页面 `pages/DrifterConsolePage.tsx`：以 DD 组件（Card/CardTitle/Button/Input + zinc/cyan 主题）实现设备发现/手动 IP、状态 key=value 表格、遥测卡片（模式/驻车/漂移/电压/油门/转向/陀螺仪/6 通道/舵机/电调/中点/漂移补偿/偏航/油门模式）、终端（web/serial 命令 + `/api/log` 轮询）、Wi-Fi STA（扫描/连接/状态）、OTA 固件上传（`/update` multipart）、开发模式/静音开关。
  - 新增 `services/console.ts`：车端 HTTP 经 DD 后端同源代理的访问层；新增 `i18n/messages/console.ts` 并注册到 `messages/index.ts`。
  - 后端新增 `routers/console.py`：`/api/console/proxy/{ip}/{path:path}` 通用反向代理（GET/POST/PUT/DELETE/PATCH，仅 IPv4、urllib 转发、原样透传状态码/Content-Type/body，含车端 4xx/5xx 透传）；`main.py` 注册 `/api/console`。
  - 测试同步：后端新增 `tests/test_console.py`（路由注册 / IPv4 校验 / 转发方法体头透传 3 项），后端 pytest 96 passed；前端 `EnterButtons.test.tsx` 断言 Drifter Console 改为 `/console` 路由链接，vitest 20 文件 104 项、`tsc -b --noEmit`、`npm run build` 全过。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (48)

- feat(web-ui): 全站卡片小标题统一为「左侧图标 + 悬停灰色副标题」，抽出 `SectionCardTitle` 组件（Issue #233）
  - 需求：以 TM「录制视频库」小标题为基准，把 DD 所有页面的卡片小标题统一成同款 UI——左侧语义图标 + 悬停淡入灰色副标题；副标题文案补充进 i18n 中英双语。
  - 新增 `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：复用 `CardTitle`，统一渲染图标 + 标题 + 可选副标题（`group-hover` 淡入展开，`transition-all duration-300`），并支持 `children` 追加标题行内徽标。
  - 全站替换：
    - `TubLibrary.tsx`、`TubEditor.tsx`：基准实现改为复用 `SectionCardTitle`。
    - `TubLoader.tsx`、`ConfigLoader.tsx`、`SimulatorConfig.tsx`：补齐悬停副标题。
    - `PilotArenaPage.tsx`：当前数据 / 飞行员名称 / 图像处理 / Tub 绘图 / 变换前 / 变换后。
    - `CarConnectorPage.tsx`：连接配置 / 拉取 Tub / 推送 Pilots / 远程驾驶 / 任务日志。
    - `TrainerPage.tsx` 及 trainer 组件：训练配置 / 云端训练 / 本机训练 / 环境检测 / 训练状态 / 训练日志 / 已训练模型。
    - `DrivePage.tsx`：虚拟摇杆区块标题。
  - i18n 新增副标题文案（`arena.ts` / `common.ts` / `connector.ts` / `drive.ts` / `trainer.ts` / `tubnav.ts` 中英双语）。
  - 测试同步：`npm run check`（tsc）、`npm run build`、前端 vitest 20 文件 104 项全部通过。
  - 注：本次在 `Tony-issue233-section-card-titles` 功能分支（worktree `session-issue233` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (47)

- feat(drive): 虚拟摇杆折叠框改为贴屏幕最右的抽屉，收起时摄像头画面与遥测曲线占满整页宽度（Issue #232）
  - 需求：原布局是 `grid grid-cols-1 lg:grid-cols-3`，摄像头+遥测占左 2/3、控制面板占右 1/3；折叠只是隐藏右列内部内容、右列容器仍在，画面不会放大。改为右侧抽屉后，收起时控制面板完全退出布局流，画面占满整页宽度；展开时抽屉从屏幕最右往左滑出，画面同步缩小让位。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：
    - 移除三列 grid，摄像头+遥测改为单列全宽容器；抽屉展开时在 lg 屏加 `lg:mr-[24rem]` 让位（`transition-all` 与抽屉滑动同 duration/easing，画面随抽屉缩放）。
    - 控制面板改为 `fixed right-0` 右侧抽屉（`top-[143px] lg:top-16 h-[calc(100vh-143px)] lg:h-[calc(100vh-4rem)] z-40`，与左侧 SidePanel 的偏移/层级对齐），展开 `w-[min(24rem,calc(100vw-3.5rem))]`、收起 `w-0`；面板内容区 `overflow-y-auto` 可滚动。
    - 抽屉左缘新增常驻浮动触发把手（`absolute right-full`，`rounded-l-md`）：收起时贴屏幕右缘、展开时随抽屉左缘移动；`ChevronLeft`/`ChevronRight` 表示展开/收起方向，title 复用 `drive.expandJoystick`/`drive.collapseJoystick` 文案。
    - 输入源选择、摇杆、油门条、可编程按钮、参数面板、快捷键提示整体迁入抽屉；`joystickOpen` 状态与折叠语义保持不变。
  - 测试同步：前端 vitest 全量 20 文件 104 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer` 功能分支（worktree `session-issue232` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (46)

- fix(web-ui): 页面主题不随浏览器深浅色同步——主题切换改为三态（浅色 / 深色 / 跟随系统），手动选择后可切回"跟随系统"（Issue #230）
  - 背景：首次访问默认跟随浏览器 `prefers-color-scheme`；但手动单击主题切换按钮后，显式主题被持久化到 localStorage（`donkeydrifter.ui.theme`），从此不再跟随浏览器；且切换按钮是"深/浅"二选一，用户没有入口选回"跟随系统"。
  - `web_ui/frontend/src/lib/theme.ts`：新增 `THEME_MODE_CHANGE_EVENT` 与 `useThemeMode()`（订阅当前模式 `system/light/dark`）；`setTheme()` 在持久化并应用后广播模式变化事件，供切换按钮反映三态。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：单按钮改为三态循环 `跟随系统 → 浅色 → 深色 → 跟随系统`；图标随模式显示 `Monitor` / `Sun` / `Moon`，aria-label 说明当前模式与下一次点击动作；挂载时仍按本地存储再应用一次，与 index.html 首屏内联脚本保持一致。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：由"静音式二选一"用例改为三态用例，覆盖默认跟随系统、循环三态、切回跟随系统后恢复同步、手动选择后不再跟随、持久化挂载与未知值回退等 10 项。
  - 测试同步：前端 vitest 全量 20 文件 106 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次在 `Tony-issue230-theme-sync` 功能分支（worktree 作业）完成，仅动 DD 前端，Firmware 无改动、无需 OTA。

## 2026-08-19 (45)

- fix(web-ui): 把 Drive 页 Park 锁定徽标从顶栏控制组中间移到顶栏右侧，作为独立状态指示（不再夹在模式选择器与模型选择器之间）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：移除顶栏左组里 `DriveModeSelector` 与 `ModelSelector` 之间的 Park 徽标；在顶栏右端（`justify-between` 空位）单独渲染，`rc_park === 1` 时显示红色「Park 锁定 · 油门被钳 0」，并加 `whitespace-nowrap` 防止窄屏换行。
  - 测试同步：前端 `npm run check`、`vitest`（20 文件 104 项）与 `npm run build` 全过，无新增测试文件。
  - 注：本次在 `Tony-park-btn-pos` 功能分支（worktree `park-btn-pos` 作业）完成；仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (44)

- fix(drive): 修正 complete 模板 DriveApiBridge 输出错位，让 car/mode_cmd 真正到达 ArdModeCmd（Issue #223 后续）
  - 根因：`DriveApiBridge.run_threaded` 返回 7 元组 `(angle, throttle, mode, recording, buttons, reconnect_simulator, car_mode_cmd)`，但 `donkeycar/templates/complete.py` 的输出列表只有 6 项、缺 `reconnect_simulator` 占位，导致第 6 个返回值 `reconnect_simulator` 错接到 `car/mode_cmd`、真正的车控模式命令（第 7 个返回值）被丢弃，「前端选模式 → 车端切模式」仍不生效。
  - `donkeycar/templates/complete.py`：DriveApiBridge outputs 由 6 项补为 7 项，按返回顺序加入 `reconnect_simulator`，使 `car/mode_cmd` 落到第 7 位。
  - 测试同步：`donkeycar/tests/test_template_drive_api_bridge.py` 新增 `test_complete_template_drive_api_bridge_outputs_include_car_mode_cmd` 断言输出顺序；`test_template_drive_api_bridge.py` + `test_actuator.py` 共 34 passed / 2 skipped。
  - 注：本次在 `Tony-issue223-fix-mode-outputs` 功能分支（worktree `issue223-mode-protocol` 作业）完成；仅 DD 模板改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (43)

- fix(web-ui): 导航切换改为快速平滑滑动并修复卡死后瞬跳与滚动锚定顶走（Issue #135 第六轮）
  - 需求：点导航标签后不是瞬跳，而是像快进的手动翻页一样滑到目标分区；此前实测点击后主线程冻结、动画被压成一次瞬跳，部分场景滚动被浏览器按回原地。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：
    - 自定义 rAF 滑动替代 `scrollIntoView(smooth)`：时长按距离 250–750ms + easeOutCubic，快而有翻页感；动画进度按每帧限幅增量（≤48ms）推进，主线程被数据加载占住几秒导致 rAF 全程饿死时，恢复后不会一步跳到终点（"点了很久才动、一动就瞬跳"的根源）。
    - section 常驻 `overflow-anchor:none` + 滑动期间锁 html/body：目标/途经 section 因 content-visibility 展开产生布局位移时，Chrome 滚动锚定会把视口反向顶走或把程序化滚动按回原地（实测 drive→tub 被钉在顶部约 2s、pilot→drive 先反向跳 665px 再滑回）。
    - 落定后 250/750/1500ms 三次校验：目标被布局展开推走 >32px 时补一次短滑，保证精准落位。
    - 滑动期间冻结 scroll-spy、点击瞬间激活目标 section：途经分区不再反复启停视频流/WebRTC/WebSocket（此前 IO 翻转风暴的放大链）；手动滚动时 spy 提交去抖 100ms，消除边界抖动。
    - 用户滚轮/触摸/按键立即接管：取消滑动并作废在途会话与后续校验；prefers-reduced-motion 或首次深链直接落位。
  - 实测（Playwright CPU 4x 节流）：Drive↔TM↔Trainer↔PA 四段切换全部精准落位（err=0）、滑动 0.8–1.2s 单调平滑、每段仅 1 个 ~140–175ms longtask（第五轮基线单段 836ms 峰值且落位错 936–3182px）。
  - 测试同步：前端 vitest 20 文件 104 项全过、`tsc --noEmit` 与 `npm run build` 通过（无新增测试文件，滑动动画由 Playwright 实测脚本覆盖）。
  - 注：本次在 `Tony-issue135-nav-glide-round6` 功能分支（worktree `.worktrees/issue135-r6` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (42)

- fix(drive): 车控模式下行协议对齐 Firmware#111——DD 下发 `MODE <m>` 而非 `C<m>`（Issue #223 端到端修复）
  - 根因：Issue #223 DD 侧 `Arduino.set_car_mode()` 写 `C<m>\n`，但 Firmware #111 的 `CommandDispatcher` 只解析 `MODE ` / `MODE:` 前缀，两端协议不一致，导致「前端选模式 → 车端切模式」这条链路永远不通。
  - `donkeycar/parts/actuator.py`：`set_car_mode()` 下发帧由 `C{mode}\n` 改为 `MODE {mode}\n`；docstring 与 `ArdModeCmd` 注释同步由 `C<m>` 改为 `MODE <m>`。
  - 测试同步：`donkeycar/tests/test_actuator.py` `test_arduino_set_car_mode_writes_cmd_frame` 断言由 `C2\n` 改为 `MODE 2\n`；本文件 28 passed / 2 skipped。
  - 注：本次在 `Tony-issue223-fix-mode-protocol` 功能分支（worktree 作业）完成，仅 DD 改动、Firmware 无改动、无需 OTA。

## 2026-08-19 (41)

- fix(launcher): 打开 Kimi Code Web 仍反复弹「选择语言/主题」欢迎页、置顶看似丢失——入口 URL 追加 `?kimi_onboarded=1` 跳过首次 onboarding 并写入 localStorage（Issue #168 后续）
  - 根因：KCW 前端把 onboarding 完成态存 `localStorage` 键 `kimi-web.onboarded`、按 origin 隔离；置顶也是 `kimi-web.pinned-sessions`、同样按 origin。前几轮已把 origin 稳定到 `tony007.local:58640`（固定端口 + mDNS 主机名），但迁移到新 origin 后，老 origin 的 onboarding 标记不会跟随——用户每次打开都停在欢迎页、且因不敢点「下一步」而永远进不去，误以为置顶又丢了。
  - 修复：`donkeycar/launcher/kimi_web.py` 新增 `_mark_onboarded(url)`，给入口 URL 追加 `?kimi_onboarded=1`（KCW 前端在 URL 带该参数时会把 `kimi-web.onboarded` 写进当前 origin 的 localStorage 并直接进主界面，之后不带该参数也不再弹欢迎页，等效于 KCW 自己的桌面→Web 迁移通道）；`launch_kimi_code_web` 三条成功返回路径（复用、冷启动、冷启动兜底复用）统一套用 `_mark_onboarded(_lan_url(url))`。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestMarkOnboarded`（追加参数保留 `#token=` 片段、保留已有 query、已有参数不去重）3 项；`TestLaunchKimiCodeWeb` 3 处 URL 断言更新为带 `?kimi_onboarded=1`。`test_launcher_kimi_web.py` + `test_launcher_dsh_web.py` 共 81 项通过。
  - 注：本次在 `Tony-kcw-onboarding-skip` 功能分支（worktree 作业）完成。仅 DD 改动，Firmware 无改动、无需 OTA。

## 2026-08-18 (40)

- fix(trainer): 训练器 SSH 凭据不再明文落盘/入库，my-PC 默认配置不再指向云服务器（Issue #219）
  - 根因：`train_my_pc.conf` 与 `train_online.conf` 明文存 `password = dkc@2026`，且 my-PC 配置直接复制云服务器 `haowenpi.com`/`ubuntu`；`donkeycar/management/train_online.py` 的 `_load_config()` 在配置缺失时硬编码生成云服务器默认值，是 my-PC 被污染的来源。
  - 后端：
    - `donkeycar/management/train_online.py`：`_load_config()` 默认 host/user/password 全部置空，去掉硬编码云服务器与密码；`connect_ssh(credentials=None)` 支持调用方传入会话内凭据（host/user/password/key_filename），空密码改走默认 SSH 密钥认证。
    - `web_ui/backend/web_online_trainer.py`、`web_ui/backend/trainer_engine.py`：新增 `ssh_credentials` 参数并透传到 `connect_ssh`，凭据仅内存传递、不落盘。
    - `web_ui/backend/routers/trainer.py`：新增 `SSHCredentials` 模型；`OnlineTrainRequest`/`MyPcTrainRequest` 增加 `ssh` 字段；`GET /trainer/config` 不再返回真实密码（固定 `""`）；`POST /trainer/config` 不再写 `password`；训练启动把 `ssh` 凭据透传给引擎。
  - 前端：
    - `store/useStore.ts`：`trainerOnlineConfig` 默认去掉明文密码与云服务器（改空）；`trainerMyPcConfig` 保持空默认。
    - `services/api.ts`：`TrainerConfig` 去掉 `password`、新增 `SSHCredentials`；`startOnlineTrain`/`startMyPcTrain` 增加 `ssh` 参数。
    - `hooks/useTrainingJob.ts`：非敏感项仍写 conf，密码改随训练请求 `ssh` 会话内传递。
    - `components/trainer/RemoteConfigForm.tsx`、`pages/TrainerPage.tsx`、`i18n/messages/trainer.ts`：my-PC 首次使用显示填写引导提示。
  - 配置与 gitignore：`web_ui/backend/train_online.conf` 移除密码并取消 git 跟踪；新增 `web_ui/backend/train_my_pc.conf.example` 空模板；`.gitignore` 忽略两个 `.conf`。
  - 测试同步：`tests/test_trainer_mypc.py` 新增/更新——ssh 凭据透传、config 不写密码、get 返回空密码、自动创建的默认配置不含明文密码；trainer 相关 17 项通过；前端 `tsc -b --noEmit` 通过。
  - 注：历史已提交过该明文密码（`train_online.conf`、前端构建产物、`train_online.py`、`useStore.ts` 等多处），建议轮换该密码；历史清洗（filter-repo + 强推）属破坏性/共享操作，需用户另行授权后处理，本次未动历史。本次在 `Tony-issue219-trainer-ssh-credentials` 分支（worktree 作业）完成。

## 2026-08-18 (39)

- feat(drive): Drive 模式选择器与车端模式双向同步，删除「固件模式」徽标并上移 Park 徽标（Issue #223）
  - 需求：驾驶页模式选择器（user/local_angle/local）与车端实际运行模式双向同步；删除顶部只读「固件模式」徽标，Park 锁定徽标上移到模式选择器旁。
  - 协议契约（下行 Pi→ESP32，仅定义契约 + 落地 DD 侧；Firmware 侧 #111 尚未实现，端到端打通需等 Firmware）：Serial1 `Arduino.ard_device` 写 `C<m>\n`，m∈{0,1,2}（0=手动/1=半自动/2=全自动），加 `ard_lock`，非法值忽略并 warning。
  - `donkeycar/parts/drive_api_bridge.py`：新增粘滞 `car_mode`（非 latch，避免主循环漏读单次值）；`_handle_message` 收到 `car_mode` 校验 0/1/2 后存值，非法值 warning；`run_threaded` 输出元组追加第 7 元素 `car/mode_cmd`。
  - `donkeycar/parts/actuator.py`：`Arduino` 新增 `set_car_mode()`（校验 0/1/2 + `ard_lock` + `write(f"C{mode}\n")`）；新增 `ArdModeCmd` Part（变化去重后调 `controller.set_car_mode`，缺 controller 抛 ValueError）。
  - `donkeycar/templates/complete.py`：`DriveApiBridge` outputs 追加 `'car/mode_cmd'`；`ARDUINO_CONTROLLER` 分支在 `ArdRc` 后新增 `ArdModeCmd` 接线（`inputs=['car/mode_cmd']`）。
  - `web_ui/backend/routers/drive.py`：`control_fields` 追加 `car_mode`，前端 `car_mode` 透传到 bridge。
  - 前端：`DriveModeSelector.tsx` 新增 `driveModeToRcMode`/`rcModeToDriveMode` 映射（user↔0、local_angle↔1、local↔2）；`DrivePage.tsx` 发送时附带 `car_mode`、新增 effect 按 `telemetry.rc_mode` 反向同步本地模式；删除「固件模式」徽标区、Park 徽标上移到模式选择器旁；`i18n/messages/drive.ts` 删除 `drive.firmwareMode`/`drive.unknownMode`（保留 `drive.parkLocked`）。
  - 测试同步：`test_drive_api_bridge.py` 输出元组断言更新为 7 元素；`test_drive_api_bridge_telemetry.py` 新增 car_mode 粘滞返回与非法值拒绝；`test_actuator.py` 新增 `set_car_mode` 写 `C2\n`/非法不写、`ArdModeCmd` 去重、缺 controller 抛错；`web_ui/backend/tests/test_drive.py` 新增 car_mode 转发；`DriveModeSelector.test.tsx` 新增两组映射测试。已验证：`test_drive_api_bridge.py`+`test_drive_api_bridge_telemetry.py`+`test_actuator.py` 共 83 passed/2 skipped、`test_drive.py`+`test_drive_telemetry_forward.py` 共 24 passed、`test_template_drive_api_bridge.py` 5 passed；前端 vitest 20 文件 102 passed、`npm run check`/`npm run build` 通过。
  - 注：本次在 `Tony-issue223-drive-mode-sync` 功能分支（worktree `.worktrees/issue223-drive-mode-sync` 作业）完成，PR 合并前 rebase 到最新 `origin/Tony` 解 CHANGELOG 冲突（条目重编号为 (39)）。Firmware 无改动，无需 OTA。

## 2026-08-18 (38)

- fix(web-ui): Drive 页摄像头偶发卡死在「正在连接摄像头...」——MJPEG 首帧无超时、WebRTC 收到 track 却无首帧、carOnline 门控竞态三处叠加（Issue #221）
  - 背景：进入 Drive 页后偶发既没切到 WebRTC、也没回退到 MJPEG，永远停在「正在连接摄像头...」，FPS 显示 `-`。三条失效路径：① MJPEG `<img src="/drive/video">` 只有 `onError` 才重试，后端无首帧时既不触发 `onLoad` 也不触发 `onError`，`status` 永远 `loading`；② WebRTC 在 `ontrack` 即置 `connected`、`videoReady` 要等 `onloadeddata`，首帧不解码时 `webRtcConnected=true` 会重置 MJPEG 回退计时器但 `webRtcVisible` 永为 false（黑屏 + 遮罩不消失）；③ `carOnline` 初值 `null` 被 `?? false` 压成 `false`，挂载时不启动 WebRTC，随后 `null→true` 又触发整体 `closePeer` 重启会话。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：新增 `DRIVE_VIDEO_MJPEG_FIRST_FRAME_TIMEOUT_MS=5000`，MJPEG `loading` 首帧超时按 `onError` 同路重试；fallback 门控由 `webRtcConnected` 改为 `webRtcVisible`；`carOnline` 直接传 `null`（不再 `?? false`）。
  - `web_ui/frontend/src/hooks/useDriveWebRtcVideo.ts`：新增 `DRIVE_WEBRTC_VIDEO_READY_TIMEOUT_MS=8000` 与 `videoReadyTimeoutMs` 选项，`ontrack` 后首帧迟迟不解码则超时降级重试；`carOnline` 类型放宽为 `boolean | null`，挂载生命周期与 `carOnline` 门控拆成两个 effect（`shouldRunRef` 只在「应运行」状态翻转时 start/stop，挂载 cleanup 复位兼容 StrictMode）。
  - 测试同步：`VideoStream.test.tsx` 新增「MJPEG 首帧超时后自动重试」；`useDriveWebRtcVideo.test.tsx` `HookProbe` 透传 `videoReadyTimeoutMs` 并新增「收到 track 但首帧未就绪时超时降级」。前端 vitest 全量 20 文件 102 项、`tsc -b --noEmit` 通过；相关文件 eslint 0 error、无新增警告。
  - 注：本次在 `Tony-fix-issue-221` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (37)

- fix(tm): 摄像头画面与边框贴合——容器 aspect-ratio 跟随当前帧实际宽高比，消除画面与边框空隙（Issue #220）
  - 根因：TM 摄像头预览容器固定 `aspect-video`（16:9），而摄像头帧实际比例（如 640×240=8:3）不同，canvas `object-contain` 等比缩放后在边框内留黑边。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - 新增 `frameAspect` 状态，`draw()` 内用 `image.width / image.height` 更新；无图/加载态回落 16:9（`setFrameAspect(null)`）；
    - 容器由 `aspect-video` class 改为内联 `style={{ aspectRatio: frameAspect != null ? String(frameAspect) : '16 / 9' }}`，保留边框/圆角/FPS 角标样式；
    - 顺带移除未使用的 `fields` 变量（修复既有 lint 报错）。
  - 验证：`npm run check`（tsc）通过；`npm run lint` 0 error（7 个既有 warning 与本次无关）；`npm run test` 100/100 通过。Firmware 无改动、无需 OTA。
  - 注：本次在 `Tony-fix-issue-220-tm-camera-fit` 功能分支（worktree 作业）上完成，PR #224 合入 `Tony`。

## 2026-08-18 (36)

- feat(trainer): 「我这台电脑」训练模式开箱即用——新增一键环境检测（SSH/平台/Python/donkeycar）与 Windows/Mac 适配引导（Issue #218）
  - 背景：mypc 训练档此前只是"能用 SSH 的高级用法"，用户需自己开 SSH、装 donkeycar、手写 `train_my_pc.conf`，页面无引导；远端命令是 POSIX 风格（`tar`/`cd`/bash），Windows 原生 SSH 基本要 WSL，Mac 未适配，且连接/缺依赖时只看到训练 job 失败、无修复提示。
  - `web_ui/backend/mypc_probe.py`（新增）：轻量、无副作用的预检模块——SSH 连通性检测、`uname -s`/`wsl.exe` 平台探测（Linux/macOS/Windows + WSL）、Python 解释器探测（先验配置 `python_path`，再按 `python3`/`python`/`~/miniconda3/envs/donkey/bin/python`/`/opt/homebrew/bin/python3` 等常见顺序自动探测）、`donkeycar` 包与 `donkey` CLI 校验；每项返回 `ok/warn/fail` + 可操作修复提示，汇总 `suggestions`。
  - `web_ui/backend/routers/trainer.py`：新增 `POST /api/trainer/mypc/probe`（`asyncio.to_thread` 跑阻塞的 paramiko 探测），入参为 host/user/password/port/remote_dir_base/python_path。
  - `web_ui/frontend/src/services/api.ts`：新增 `MyPcProbeResult`/`MyPcProbeCheck` 类型与 `probeMyPc()`。
  - `web_ui/frontend/src/components/trainer/MyPcProbePanel.tsx`（新增）：mypc 表单下的「环境检测」面板——检测按钮、加载态、逐项结果（绿勾/黄警告/红叉/蓝信息 + 修复提示）、检测到的 Python 一键回填表单、修复建议列表。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：mypc 模式在 RemoteConfigForm 下接入 MyPcProbePanel，`onApplyPythonPath` 回填 `python_path`。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：zh/en 各新增 10 条检测相关词条（`myPcProbe*`）。
  - `docs/guide/web-drive-console-user-guide.md`：新增「本机训练（This Computer）」章节，说明首次使用准备（SSH 开启方式）、Windows（推荐 WSL）/macOS/Linux 平台支持与默认 Python 路径、连接失败/缺依赖时的排查指引。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_mypc_probe.py`（6 项：Linux 就绪、SSH 失败、macOS 自动探测、Windows 无 WSL、缺 donkeycar、配置 python_path 优先）；`test_trainer_mypc.py` 新增探测路由端点测试。后端 pytest 全量 89 项、前端 vitest 20 文件 100 项、`tsc -b --noEmit` 全部通过。
  - 注：本次在 worktree `.worktrees/issue218-trainer-mypc-ootb` 基于最新 `origin/Tony` 建功能分支 `Tony-issue218-trainer-mypc-ootb` 作业，主工作区在 `Tony-joystick-default-collapsed` 分支有并行会话未提交改动（`main.py` SPA 深链 + 未跟踪 `train_my_pc.conf`），全程未触碰。Firmware 无改动，无需 OTA。

## 2026-08-18 (35)

- feat(web-ui): 虚拟摇杆面板默认折叠——每次进入/刷新 Drive 页都折叠为「虚拟摇杆」标题一行
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`joystickOpen` 初始状态由 `useState(true)` 改为 `useState(false)`；点击标题行展开/收起交互不变。
  - 验证：`npm run build`（含 `tsc -b`）通过；无 Firmware 改动、无需 OTA。
  - 注：主工作区有并行会话在制改动，本次在 worktree（`.worktrees/joystick-default-collapsed`）基于最新 `origin/Tony` 重做（cherry-pick 原提交），分支 `Tony-joystick-default-collapsed-v2`。

## 2026-08-18 (34)

- fix(launcher): KCW 入口 URL 用 mDNS 主机名后被 kimi 的 DNS-rebinding 栅栏 403 拦截——冷启动加 `--allowed-host` 放行入口 host，复用前重探入口 host 跳过未放行的旧实例（Issue #168 后续）
  - 根因：上一轮把 KCW 入口 URL 的 host 从 DHCP 局域网 IP 改为稳定 mDNS 主机名 `tony007.local` 以稳定 origin；但 `kimi web --host`（绑 0.0.0.0）只自动放行本机接口 IP（`192.168.3.57` 返回 200），mDNS 主机名是主机名而非接口 IP、不会被自动放行——浏览器用 `Host: tony007.local` 访问即被 40301（Invalid Host header）拦下。实测 `127.0.0.1:58640` 与 `192.168.3.57:58640` 均 200、`tony007.local:58640` 403 复现。
  - `donkeycar/launcher/kimi_web.py`：
    - `_mdns_hostname()` 主机名统一小写化（`hostname.split('.')[0].lower()`），让 URL / 浏览器 Host 头 / `--allowed-host` 三者保持同一小写形式（浏览器本就把 host 小写化放进 Host 头，origin 的 host 也按小写归一，不影响 localStorage 归属）；
    - 新增 `_allowed_host_values()` 收集入口 host（mDNS 主机名）与局域网 IP（mDNS 解析不到时的回退 host），去重；
    - `_spawn_and_capture()` 冷启动命令逐项追加 `--allowed-host <host>`，放行 mDNS 主机名与局域网 IP；
    - `_live_instance_url()` 复用本机实例、把 host 改写为入口 host 后，若入口 host 与已探测 host 不同则再对入口 host 探一次——老实例（没带 `--allowed-host`）对局域网 IP 通、对 mDNS 403，直接跳过而不是返回打不开的 URL。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestMdnsHostnameAndAllowedHosts`（小写化 + allowed-host 三种组合 4 项）、`test_entry_host_must_pass_rebind_gate`（复用重探跳过 403 实例）、`test_spawn_passes_mdns_and_lan_allowed_hosts`；更新 `test_spawn_success_captures_url_and_keeps_proc` 的启动命令断言。本文件 48 项、launcher 相关 86 项全部通过。
  - 验证：手动以 `kimi web --no-open --host --port 58646 --allowed-host tony007.local --allowed-host 192.168.3.57` 起测试实例，`curl http://tony007.local:58646/api/v1/meta`（小写）与 `http://TONY007.local:58646/...`（大写）均 200，修复生效。
  - 注：本次在 `Tony-kcw-allowed-host` 功能分支（worktree 作业）上完成。Firmware 无改动，无需 OTA。

## 2026-08-18 (33)

- fix(launcher): DSH 局域网 mDNS 主机名入口被 `/api` 通用信任栅栏 403——`--trusted-host` 同时声明局域网 IP 与 mDNS 主机名（Issue #164 追加）
  - 根因：`_lan_url()` 把 dsh web 入口 URL 的 host 从回环/局域网 IP 改写为 mDNS 主机名 `TONY007.local`（`_entry_host()` mDNS 优先，issue #168 稳定 origin 设计）；但 `--trusted-host` 之前只传了局域网 IP（`_lan_ip()`）。浏览器打开 `http://TONY007.local:<port>` 时 `Host` 头是 `tony007.local:<port>`，dsh-client-connection 的 `/api` 通用信任栅栏（`isTrustedApiRequest(req, trustedHosts)`，`trustedHosts` 由 `webserver.host=0.0.0.0` 自动派生的局域网 IP + `--trusted-host` 组成）里没有 `TONY007.local` → 所有 `/api/*` 请求 403（`host.listDirectory` 只是第一个暴露的症状，随后设置页/其他功能同样不可用）。
  - `donkeycar/launcher/dsh_web.py`：
    - 从 `kimi_web` 引入 `_mdns_hostname`；
    - `_spawn_and_capture()` 参数由 `lan_ip` 改为 `trusted_hosts`（authority 列表），逐项追加 `--trusted-host`；
    - `launch_dsh_web()` 新增 `mdns_fn` 测试钩子（默认 `_mdns_hostname`），构造 `trusted_hosts = [lan_ip, mdns]`（去空、去重）后传给 `_spawn_and_capture`；
    - 模块 docstring 的 `--trusted-host` 说明同步更新。
  - 测试同步：`tests/test_launcher_dsh_web.py` `_fake_lan_ip` fixture 默认 patch `dsh_web._mdns_hostname` 返回 None（隔离真实 mDNS 探测）；新增 `test_spawn_adds_mdns_host_to_trusted_host`（断言 `--trusted-host 192.168.3.10 --trusted-host TONY007.local`）；文件 30 项全部通过。
  - 验证：本地复现——仅 `--trusted-host 192.168.3.57` 时，`Host: TONY007.local` 的 `/api/host.listDirectory` 返回 403、`Host: 192.168.3.57` 返回 200；补上 `--trusted-host TONY007.local` 后 mDNS host 返回 200（修复生效）。
  - 注：本次在 `Tony-issue164-dsh-auto-enter-projects` 功能分支（worktree 作业）追加提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。此前 (32) 的 UUID polyfill 与本次 mDNS trusted-host 是 issue #164 的两个独立根因，均需线上 launcher 更新部署后生效。

## 2026-08-18 (32)

- fix(launcher): DSH 局域网非安全上下文 `crypto.randomUUID` 缺失导致连接永不就绪、不自动进 Projects——client.js 注入 UUID 兜底（Issue #164 收尾）
  - 根因：DSH 客户端 `dsh-client-connection/lib/client.js` 用 `crypto.randomUUID()` 铸造 RPC id（`AbstractApiClient.mintRpcId()`），但浏览器经局域网 IP（`http://192.168.3.x:<port>`）访问时处于非安全上下文，`crypto.randomUUID` 为 undefined，调用抛 `TypeError` → `ConnectionController.loop()` 的 `host.describe` 被 reject → 连接永远到不了 connected → `workspaces.startInitialSelection()` 不触发 → 停在"选择工作区"不自动进 Projects（回环 `127.0.0.1` 是 secure context，正常）。
  - `donkeycar/launcher/dsh_web.py`：
    - 新增 `_connection_client_path()`（定位 client.js，与 `_connection_index_path` 同布局）；
    - 新增 `_PATCH_UUID_OLD`/`_PATCH_UUID_NEW` 锚点与 `_patch_client_uuid_polyfill()`——启动前在 client.js 顶部 CommonJS 桩之后注入 `getRandomValues` 版 RFC4122 v4 UUID 兜底，幂等自愈（已打过的跳过、源码升级未命中旧锚点也跳过、失败只告警）；
    - `launch_dsh_web()` 冷启动前在 `_patch_privileged_methods()` 之后调用 `_patch_client_uuid_polyfill()`。
  - 测试同步：`tests/test_launcher_dsh_web.py` 新增 `TestPatchClientUuidPolyfill`（补丁注入/幂等/未命中跳过/缺包跳过/launch 调用时机 5 项），文件 29 项全部通过。
  - 验证：headless Chromium 打开 `http://192.168.3.57:36600/`，`isSecureContext=False` 但 `typeof crypto.randomUUID=function`（polyfill 生效）、页面自动进入 `projects`、不再显示"选择工作区"，console 无错误；回环 `127.0.0.1` 行为一致。
  - 注：本次在 `Tony-issue164-dsh-auto-enter-projects` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。此前错误的 `sec-fetch-site` 放宽补丁已一并删除（实测浏览器发 WebSocket 不带该头，与真实根因无关）。

## 2026-08-18 (31)

- feat(launcher): D 启动菜单 0 号「Drifter Console」移到 7 号、删 0 号位，6 号改名 DonkeyDrifter（小字「打开 DonkeyDrifter」）
  - 需求：D 启动页菜单中 0 号「Drifter Console」（打开 DC）移到 7 号位置、删掉 0 号位；6 号「Donkey Drifter」改名「DonkeyDrifter」，小字（desc）改为「打开 DonkeyDrifter」。
  - `donkeycar/launcher/server.py`（MENU_HTML）：
    - `menuItems`：删除 0 号「Drifter Console」条目；6 号 name「Donkey Drifter」→「DonkeyDrifter」、descZh/descEn「打开 DonkeyDrifter」/「Open DonkeyDrifter」；7 号由占位行改为「Drifter Console」（cat drive、favorite true）；编号 1-12。
    - `selectItem()`：删除 `no === 0 → openDrifterConsole()` 分支，新增 `no === 7 → openDrifterConsole()`；移除占位行轻提示分支。
    - `renderMenu()`：移除占位行渲染分支与 `.menuItem.placeholder` CSS（占位概念随 7 号恢复为真实 DC 项而移除）。
    - 键盘：数字键 `0` 不再触发 `selectItem(0)`（0 号位已删）；`2-9` 仍直选对应项，`1`+`0/1/2` 仍组合选 10/11/12。
    - 帮助文案：`数字键 0-12：选择对应菜单项（7 号已并入 6 号）` → `数字键 1-12：选择对应菜单项`（zh/en 同步）。
  - 测试同步：`tests/test_launcher_menu_actions.py` 删除 `test_menu_6_7_merged_placeholder`，新增 `test_menu_6_renamed_and_dc_moved_to_7`；模块 docstring 与注释同步。launcher 相关测试 155 项全部通过，MENU_HTML 内嵌 JS `node --check` 通过。
  - 注：本次在 `Tony-menu-reorder-dc-7` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (30)

- perf(web-ui): 流程页导航切换仍卡顿——四个 section 常驻挂载导致整页每次滚动都重算/重绘 + 父组件重渲染连坐所有子页面，加 `content-visibility` 与 `React.memo` 隔离（Issue #135 五轮）
  - 背景：#201/#204 已把 Drive 视频流/WS/遥测图/PA 循环按主导 section 门控，但四个 section（Drive/TM/Trainer/PA）仍常驻挂载在同一个滚动页里，且 `FlowPage` 的 `inView` 每次变化会触发父组件重渲染、默认连带所有子页面一起重渲染——切导航平滑滚动时既有视口外 section 的布局/绘制开销，又有 TM/Trainer 等重页面的无效重渲染。Playwright CPU 4x 实测：切换 PA→Drive 单次 longtask 峰值 836ms。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：新增 `SECTION_STYLE`（`content-visibility: auto` + `contain-intrinsic-size: auto 640px`）应用到四个 `<section>`——DOM 与组件状态保留（保住 #135 常驻保活），但浏览器跳过视口外 section 的布局/绘制，只按占位尺寸撑开滚动高度。
  - `web_ui/frontend/src/pages/TubManagerPage.tsx` / `TrainerPage.tsx` / `DrivePage.tsx` / `PilotArenaPage.tsx`：四个页面组件用 `React.memo` 包裹（无 props 的 TM/Trainer 永不随父组件重渲染；带 `active` 的 Drive/PA 仅在 `active` 变化时重渲染）。
  - 效果：Playwright CPU 4x 实测导航切换 longtask 峰值从 836ms 降至约 170ms；视频流滚出卸载回归通过（Drive 滚到 TM 后 `img[src*=drive/video]`/`video` 卸载、占位符出现）；nav href 正确（`#/drive`/`#/tub`/`#/trainer`/`#/pilot`）。
  - 测试同步：前端 vitest 全量 20 文件 100 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次在 `Tony-issue135-nav-lag-round5` 功能分支（worktree 作业，基于最新 origin/Tony）完成，仅动前端。Firmware 无改动，无需 OTA。已部署到 8000（从该 worktree 起后端），用户需硬刷新浏览器。

## 2026-08-18 (29)

- fix(web-ui): 修复 DD 前端深链（`/connector`、`/drive` 等）刷新/直达返回 404——根静态文件挂载改为 SPA fallback 兜底
  - 根因：`main.py` 用 `app.mount("/", StaticFiles(html=True))` 服务根目录静态文件，它注册在 `@app.get("/{full_path:path}")` SPA fallback 之前，拦截了所有路径——前端深链（无扩展名、非真实文件）被 StaticFiles 判为 404，fallback 永远轮不到，导致用户在 `/connector` 等页面刷新或直接访问时得到 `{"detail":"Not Found"}`（Issue #177 收尾时用户反馈"看不到改动/无法连接服务器"暴露）。
  - `web_ui/backend/main.py`：去掉根目录 `StaticFiles` 挂载，`spa_fallback` 改为——① 真实存在的根目录静态文件（favicon、robots.txt 等）经 `realpath` 越界校验后直接 `FileResponse`；② 不存在的 API 路径（`api`/`api/*`）保持 404；③ 其余一律回退到 `index.html` 交给前端路由。`/assets/*` 仍由独立 mount 服务，不受影响。
  - 测试同步：后端 pytest 全量 82 项通过；手动验证 `/connector`、`/drive`、`/` 返回 200、`/assets/*.js` 200、`/api/provisioning/status` 404、`/api/connector/config` 200。

## 2026-08-18 (28)

- fix(trainer): Trainer 三档标签改为「本机 / 车载电脑 / 云端」，让「本机」明确指用户自己的电脑、「车载电脑」指跑 DD 后端的 Linux 机器（Issue #170 收尾）
  - 背景：上一轮「我的电脑 / Linux 电脑」仍不够直观——「我的电脑」与「本机」语义易混，且「Linux 电脑」过于技术化、普通用户难以和"本机"区分。改为「本机」（用户浏览器/SSH 客户端所在机）、「车载电脑」（跑 DD 后端的机器）、「云端」（远端服务器）三档。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「我的电脑」→「本机」、`tabLocal`「Linux 电脑」→「车载电脑」、`startMyPcTraining`→「在本机上训练」、`startLocalTraining`→「在车载电脑上训练」、`myPcTraining`→「本机训练」；en 同步 `This Computer / Car Computer / Train on This Computer / Train on Car Computer / This Computer Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档渲染与点击断言同步新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming3` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (27)

- fix(trainer): Trainer 三档标签由「客户端/本机/云端」改为「我的电脑 / Linux 电脑 / 云端」，消除用户对前后两档语义的混淆（Issue #170 收尾）
  - 背景：上一轮「客户端/本机」对普通用户不够直观——「本机」在用户自己电脑上操作时易被误读为"我的电脑"，与「客户端」难以区分。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「客户端」→「我的电脑」、`tabLocal`「本机」→「Linux 电脑」、`startMyPcTraining`→「在我的电脑上训练」、`startLocalTraining`→「在 Linux 电脑上训练」、`startCloudTraining`→「在云端训练」、`myPcTraining`→「我的电脑训练」；en 同步 `My Computer / Linux PC / Train on My Computer / Train on This Linux PC / Train on Cloud / My Computer Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档渲染与点击断言同步新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming2` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (26)

- feat(web-ui): DeepSeek Harness 入口同样改为导航链接样式，放在 Kimi Code Web 右侧（Issue #175 延续）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：删除已无引用的 `DshButton` 胶囊组件与 `useResolvedTheme` 导入，DeepSeek Harness 统一走 `DshEntryLink` 导航链接样式。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面导航行末尾 Kimi Code Web 右侧新增 `DshEntryLink`；右上角胶囊区移除 `DshButton`（现在只保留版本号/GitHub/主题/语言切换）；手机端汉堡菜单高级入口分组顺序不变（Drift Console / Kimi Code Web / DeepSeek Harness）。
  - 测试同步：`EnterButtons.test.tsx` 删除 DSH 胶囊样式断言，DSH 成功/失败路径测试由 `DshButton` 迁至 `DshEntryLink`；vitest 全量 20 文件 99 项、`tsc -b --noEmit` 全部通过。
  - 注：Firmware 无改动，无需 OTA。

## 2026-08-18 (25)

- fix(web-ui): 流程页滚动卡顿收尾补刀——遥测图 60fps 空转、PA 播放循环、Drive UI 50ms 同步与同导航项重复点击滚动（#178 后续）
  - 背景：#201 已把 Drive 的视频流/WebSocket 按主导 section 门控（滚走即断），但仍有几处后台空转：`TelemetryChart` 的 `requestAnimationFrame` 循环在 section 滚走后仍每帧 `setRenderTick` 重绘（无数据也空转 60fps）；`PilotArenaPage` 播放时滚走仍持续 rAF 推帧与预测轮询；`DrivePage` 的 50ms UI 同步 `setInterval` 未随 `active` 停表；且顶部导航点「与当前 path 相同的项」时 `location.pathname` 不变、滚动 effect 不触发，用户点后无反应。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：新增 `active` prop（默认 true）——`active=false` 时跳过遥测写缓冲与 rAF 重绘循环，滚回后自动恢复。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：50ms UI 同步 `useEffect` 加 `if (!active) return` 并补 `active` 依赖；`<TelemetryChart>` 传入 `active={active}`。
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：播放 rAF 循环与评测调度 `useEffect` 加 `!active` 早退并补 `active` 依赖（播放中滚走即冻结，滚回续播）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：滚动 effect 依赖从 `location.pathname` 改为 `pathname + location.key`——点同一导航项（path 不变但 location.key 变）也能再次 `scrollIntoView`，修复"点了没反应"。
  - 测试同步：前端 vitest 全量 20 文件 101 项、`tsc -b --noEmit`、`npm run build` 全部通过；eslint 改动文件 0 警告。Playwright headless 实测：点 Trainer 后 Drive 区 video/img 卸载、点同 path 导航项可再次滚回目标 section。
  - 注：本次在 `Tony-issue178-flow-perf` 分支完成，基于已合入 Tony 的 #201 增量修改，仅动前端。无 Firmware 改动，无需 OTA。

## 2026-08-18 (24)

- fix(launcher): DC 点击进入 DD 报"无法连接服务器"——web 进程启动失败仍报 launched 并重定向死端口，改为报错 + 跳转页就绪轮询（用户口述报障，journalctl 实锤）
  - 背景：`donkey web` 冷启动时前端生产构建失败（源码在制改动致 `tsc -b && vite build` 报错）直接退出，但 `_wait_for_web_ready` 对"进程提前退出"只带 warning 不报错，`_launch_drive` 仍返回 `launched` + 兜底前端端口 5188；而生产模式（bundled web ui，#135）前端由后端 8000 端口托管、5188 从不监听——跳转页拿到 URL 立即重定向，Safari 报"无法连接服务器"。三个叠加缺陷：进程死了仍报 launched / 兜底端口在生产模式必死 / 跳转页无就绪轮询（2026-08-12 加过的轮询被 c613ce73 菜单页重写吞掉）。
  - `donkeycar/launcher/server.py` `_launch_drive`：`_wait_for_web_ready` 返回 warning 时区分两种情况——web 进程已退出（`poll()` 非 None）必然失败，改返回 `status:"error"` 并附具体原因与日志查看命令，不再起车进程、不写 PID 文件；进程仍在但超时、且登记未出现时，生产模式兜底前端端口从入参 5188 修正为后端端口（开发模式 vite 确实监听 5188，保持不变）。
  - `donkeycar/launcher/server.py` `LAUNCH_DRIVE_HTML`：跳转前加就绪轮询（30 次 × 1s，`mode:'no-cors'` fetch 探测目标可连，复用菜单页 launchDrive 既有模式），就绪才重定向；超时不通则停下显示"Web UI 未就绪，未跳转（可稍后重试）"并透出 warning，不盲目跳死端口；i18n 补 `waiting`/`notready` 中英词条。
  - 测试同步：`tests/test_launcher_drive_launch.py` 新增 3 项——web 进程提前退出报 error 且不起车进程不写 PID、生产模式超时前端端口修正为后端端口、开发模式超时保持入参端口；`tests/test_launcher_language_autodetect.py` 跳转页双语断言同步（新词条、3 处 failed 文案、轮询语句）。本文件 12 项全部通过，launcher/webui 相关 135 passed（terminal 2 项失败为 origin/Tony 基线遗留，与本次无关）；另起临时 launcher 实例实测 `/launch/drive` 页面含轮询逻辑与双语提示。
  - 注：本次改动在 `Tony-fix-launch-dead-port` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`（合并时 CHANGELOG 与多条会话条目解冲突，最终重编号为 (24)）。Firmware 无改动，无需 OTA。

## 2026-08-18 (23)

- fix(launcher): DC 上位机终端"放一会儿仍被断开"根因修复——移除应用层 PING/PONG 判死，改用内核 TCP keepalive 保活与死链检测（Issue #173 后续）
  - 背景：#173 首轮把 PTY 会话与 WS 连接解耦、断线宽限期 + sid 重连 + 自动退避重连，但服务端仍保留 #151 的"60s 无 PONG 判死"心跳——浏览器标签页冻结 / 手机锁屏时应用层 PONG 会停，服务端照样在 60s 后主动断开，用户视角"放一会儿仍断"依旧存在。
  - `donkeycar/launcher/terminal.py`：删除 `_heartbeat_loop` 应用层心跳线程与 `_PING_INTERVAL`/`_PONG_TIMEOUT` 判死逻辑；新增 `_enable_tcp_keepalive`，在 WS 连接套接字上启用内核 TCP keepalive（`SO_KEEPALIVE` + Linux `TCP_KEEPIDLE=30`/`TCP_KEEPINTVL=15`/`TCP_KEEPCNT=3`）。keepalive 探测由内核发送、对端内核 ACK，与应用层无关：冻结/锁屏的浏览器内核照常 ACK，不再被误判断线；探测包同时刷新 NAT 表项防空闲断链；只有真正的死链才会在约 75s 后让 socket 报错触发会话 detach。主读循环仍响应客户端 PING（回 PONG），只是不再主动发 PING。
  - `donkeycar/launcher/terminal_static/terminal.html`：注释同步（断线原因改为"任何原因，含 TCP keepalive 判死"）。
  - `donkeycar/tests/test_launcher_terminal.py`：删除"服务端心跳 PING"与"空闲超时断开"两个 #151 用例，新增 `test_terminal_ws_idle_keeps_connection`（空闲不判死断连）与 `test_enable_tcp_keepalive_sets_socket_options`（keepalive 参数落地）。
  - `tests/test_launcher_terminal.py`：静态断言从旧的 `lost`/`failed`/`reconnect` 文案改为新的"断线自动退避重连 + session sid 接回 + 清屏"断言。
  - 测试同步：两个 terminal 测试文件 26 项通过。

## 2026-08-18 (22)

- fix(launcher): KCW 入口 URL host 用 mDNS 主机名，置顶/模式/语言主题不再随 DHCP 换 IP 被清空（Issue #168 后续）
  - 背景：Issue #168 已固定端口 58640、缺省 cwd 落到 Projects 工作区，但浏览器把 KCW 的置顶等 UI 偏好存在 localStorage、按 origin（协议+host+端口）隔离；host 用上位机 DHCP 局域网 IP（近期从 .41 漂到 .57）时，IP 一变 origin 就变，置顶聊天仍会"全部消失"。
  - `donkeycar/launcher/kimi_web.py`：
    - 新增 `_mdns_hostname()`（`socket.gethostname()` 拼 ``<hostname>.local``，仅当 mDNS 解析到本机局域网 IP 时才采用）与 `_entry_host()`（mDNS 优先、局域网 IP 回退）。
    - `_lan_url()`：回环/通配 host 与本机局域网 IP 统一改写为稳定入口 host，mDNS 可用时入口 URL 的 host 稳定、不随 IP 漂移。
    - `_live_instance_url()`：本机实例（登记回环/通配或本机 IP）组装入口 URL 时改用 `_entry_host()`；其它远程 host 不受影响。
    - 模块 docstring 更新为"三处约束"（cwd 校验 / 固定端口 / mDNS host）。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 4 项 mDNS 优先与 foreign host 不误改断言，autouse fixture 默认钉 `_mdns_hostname` 为 None 保持既有断言稳定；本文件 42 passed、launcher 相关 116 passed。
  - 注：本次改动在 `Tony-kcw-origin-stable` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (21)

- fix(web-ui): 修复流程页滚出 Drive 后视频流/WebSocket 仍在后台运行，拖慢整页切换（Issue #135 收尾）+ 后端静态资源缓存头
  - 根因：#178 把 Drive/TM/Trainer/PA 合并为纵向滚动大页后，Drive 区的视频流与 WebSocket 未按 section 可见性门控——用户滚到 TM/Trainer/PA 后，Drive 的 MJPEG 图片流、WebRTC 视频、车端 WebSocket 遥测仍在后台持续收发与 setState 重渲染，持续占主线程，导致无论切到哪个标签都卡顿（#135 用户仍报"非常卡顿"）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：滚动 spy 的 `inView` 判定从「`isIntersecting` 有任何交集即视为可见」改为「可见比例最大的主导 section 才算活跃」——原先 section 之间有 `space-y` 间距与 `scroll-mt` 滚动边距，滚走后仍留 32px 交集使 `active` 永不翻 false；改为主导 section 后，滚到 TM 时 Drive 的 `active` 正确变为 false。
  - `web_ui/frontend/src/hooks/useDriveWebsocket.ts`：新增 `enabled` 选项（默认 true）；`enabled=false` 时主动断开 WebSocket、清定时器、`setConnected(false)`、`setCarState.online=false`，不再后台收发；重新 `enabled=true` 时重连。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`useDriveWebsocket({ enabled: active })`；`useGamepadDrive` / `useGyroDrive` 的 `enabled` 追加 `active &&`；`<VideoStream>` 改为 `active` 条件渲染（滚走卸载视频组件、停止 MJPEG/WebRTC 与 1s 统计轮询），非活跃时渲染同宽高比占位符避免布局跳动。
  - `web_ui/backend/main.py`：新增 `apply_cache_headers` 与 `cache_control_middleware`——`/assets/*` 带内容哈希的静态资源返回 `Cache-Control: public, max-age=31536000, immutable`；`text/html`（index.html/SPA fallback）返回 `Cache-Control: no-cache`，避免浏览器启发式缓存旧 index.html 导致"前端已修复但仍在跑旧 bundle"（#135 用户侧反复卡顿的重要诱因）。
  - 测试同步：新增 `web_ui/backend/tests/test_cache_headers.py`（3 项：assets immutable / html no-cache / API 不受影响）；`web_ui/frontend/src/hooks/useDriveWebsocket.test.tsx` 新增 `enabled=false 不建立连接`（1 项）。后端 pytest 全量 82 项、前端 vitest 全量 20 文件 102 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 实测（8021 测试实例 + chrome-headless-shell）：滚到 TM 后 Drive 区 `img[src*=drive/video]`/`video` 均卸载、占位符出现（修复前仍挂载）；`useDriveWebsocket` enabled 门控单测确认不建连。无 Firmware 改动，无需 OTA。

## 2026-08-18 (20)

- fix(web-ui): DD 驾驶页虚拟摇杆折叠后面板真正缩小——消除 grid 拉伸导致的"内容只剩一行但框未变小"
  - 背景：控制面板在 `grid grid-cols-1 lg:grid-cols-3` 中作为第三列 grid item，默认 `align-self: stretch` 被拉伸到与左侧摄像头区（视频流 + 遥测图，较高）同高；折叠后内容虽只剩标题一行，但灰色面板框仍保持满高，下方"空出来"的区域实际是面板内部空白，视觉上"没变小"。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：控制区外层 div 加 `self-start`，让面板高度随内容收缩——折叠后只剩标题一行、下方真正空出；展开时顶部对齐、高度由内容决定。
  - 测试同步：前端 vitest 全量 100 项通过，`tsc -b --noEmit` 通过。

## 2026-08-18 (19)

- fix(trainer): Trainer 训练位置三档文案由口语化长名改为正式短名——客户端 / 本机 / 云端（Issue #170 收尾微调）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「我这台电脑」→「客户端」、`tabLocal`「当前这台 Linux 电脑」→「本机」、`startMyPcTraining`「开始训练（我这台电脑）」→「开始客户端训练」、`startLocalTraining`「开始本地训练」→「开始本机训练」、`myPcTraining`「在我这台电脑上训练」→「客户端训练」；en 同步 `Client / Local / Start Client Training / Start Local Training / Client Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档文案断言同步为新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (18)

- feat(web-ui): 顶栏高级入口改为导航链接样式——Drift Console 移到品牌右侧/Drive 左侧、Kimi Code Web 移到 Car Connector 右侧，弱化处理一眼可辨为高级选项（Issue #175）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：重写——原 `EnterButtons` 三合一胶囊组件拆分为 `DrifterConsoleEntryLink` / `KimiCodeWebEntryLink` / `DshEntryLink`（导航链接样式：`text-xs` 小字号 + `text-zinc-500` 淡色 + 图标 `SquareTerminal`/`Sparkles`/`FlaskConical`，无胶囊外壳、不做路由激活态）与 `DshButton`（DeepSeek Harness 胶囊按钮，保留在顶栏右侧，样式不变）；点击逻辑（扫描车端/launcher 启动/空白页句柄防弹窗拦截）与 loading 态原样保留，公共启动流程抽为 `useLauncherEntry` hook，console 扫描抽为 `useDrifterConsoleEntry` hook。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面导航行顺序改为 品牌 → DrifterConsole → Drive → TM → Trainer → PA → CC → KimiCodeWeb，右侧区只留 `DshButton`；手机端原第二行 EnterButtons 删除，三个高级入口以分隔线分组的弱化链接收进汉堡菜单。
  - `web_ui/frontend/src/App.test.tsx`：`services/api` mock 补 `discoverConnectorConsoles` / `launchKimiCodeWeb` / `launchDsh`（新入口组件渲染期取这些引用，mock 缺导出会抛错进 ErrorBoundary）。
  - 测试同步：`EnterButtons.test.tsx` 重写为按新组件覆盖（弱化样式断言、DSH 胶囊样式断言、成功/失败路径 8 项）；vitest 全量 19 文件 96 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue175-webui-nav-links` 功能分支（独立 worktree）上完成。Firmware 无改动，无需 OTA。

## 2026-08-18 (17)

- fix(web-ui): DD 驾驶页虚拟摇杆折叠后只留标题一行——选择框随折叠一起收起，展开时恢复
  - 背景：上一轮把输入源选择框挪进摇杆面板标题栏并让摇杆区可折叠后，折叠态标题栏右侧仍常驻输入源选择框，且面板内「可编程按键 / 控制参数 / 快捷键说明」也仍在显示，折叠后并非用户期望的"只剩一行"。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：标题栏的 `InputSourceSelector` 包进 `joystickOpen` 条件渲染（展开才显示）；原先只包摇杆圆盘区的条件渲染扩大为包住整个面板主体（竖向油门条 + 摇杆圆盘 + 控制参数条 + 可编程按键 + 参数面板 + 快捷键说明），折叠态只保留"虚拟摇杆"标题 + 展开/收起箭头一行；标题栏 `mb-4` 改为折叠时 `mb-0`，避免底部留白。
  - 测试同步：前端 vitest 全量 19 文件 98 项通过，`tsc -b --noEmit` 通过；Playwright 实测折叠态面板文本仅剩「虚拟摇杆」，展开态选择框/油门/控制参数/快捷键说明全部恢复。

## 2026-08-18 (16)

- feat(trainer): Trainer 页训练位置从「本地/云端」两档扩为三档——我这台电脑 / 当前这台 Linux 电脑 / 云端（Issue #170）
  - 背景：旧「本地」档 = 在 DD 后端所在 Linux 机器上训练；旧「云端」档 = SSH 到 `train_online.conf` 配置的远端训练；缺少"在用户自己这台电脑（SSH 客户端/浏览器所在机）上训练"的选项。方案：「我这台电脑」档复用云端 SSH 管线，但方向相反——后端 SSH 回访用户电脑，用独立配置 `train_my_pc.conf`。
  - `web_ui/frontend/src/components/trainer/ModeTabs.tsx`：两档扩为三档（`mypc` 我这台电脑 / `local` 当前这台 Linux 电脑 / `online` 云端），导出 `TrainerMode` 类型。
  - `web_ui/backend/routers/trainer.py`：新增 `MyPcTrainRequest` 与 `POST /train/mypc`（缺省 `config_file=train_my_pc.conf`）。
  - `web_ui/backend/trainer_engine.py`：`TrainingJob.mode` 与 `create_job` 支持 `mypc`；`stop_job` 对 `mypc` 走 `stop_event`（同 online）；新增 `run_mypc` 复用 `run_online` 的 SSH 管线。
  - `web_ui/frontend/src/hooks/useTrainingJob.ts`：抽出 `startSshTraining` 共用 SSH 启动逻辑，新增 `startMyPc`（写 `train_my_pc.conf`）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：`mode` 三档；online/mypc 各一套独立表单状态，mount 时分别加载 `train_online.conf` / `train_my_pc.conf`；启动按钮按档位显示文案。
  - `web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx`：新增 `titleKey` prop（云端/我这台电脑标题复用）。
  - `web_ui/frontend/src/store/useStore.ts`：新增 `trainerMyPcConfig` + `setTrainerMyPcConfig` 并持久化。
  - `web_ui/frontend/src/services/api.ts`：新增 `startMyPcTrain`。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：新增/更新 mypc 相关词条（`tabMyPc`/`tabLocal`/`tabCloud`/`startMyPcTraining`/`myPcTraining`，zh/en）。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_mypc.py`（3 项：mypc 路由建 job、缺省参数、stop 触发 stop_event）+ `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`（3 项：三档渲染/选中高亮/点击回调）。后端 pytest 全量 79 项、前端 vitest 全量 20 文件 101 项、`tsc -b --noEmit` 全部通过。
  - 注：本次改动在 `Tony-issue170-trainer-3mode` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (17)

- feat(web-ui): Drive/TM/Trainer/PA 合并为纵向滚动大页面，点导航锚点平滑滚动到对应区域（Issue #178）
  - 需求：DD 四个页面（Drive/TM/Trainer/PA）原为独立路由（`/`、`/drive`、`/trainer`、`/pilot`），改为一个纵向连续滚动的大页面，顺序自上而下 Drive→TM→Trainer→PA，点顶部导航滑到对应 section，形成「开车采数据→管数据→训练→评测」的流程引导；Car Connector 保持独立路由、不在合并范围。
  - `web_ui/frontend/src/App.tsx`：删除 Home 占位页与 KeepAliveTubManager；路由改为「`/connector` → CarConnectorPage」+「`/*` → FlowPage」兜底——同一兜底路由保证 `#/drive`、`#/tub`、`#/trainer`、`#/pilot` 四个 hash 深链导航切换时只改 pathname、不重挂载 FlowPage（保住 #135 常驻保活）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`（新增）：四 section 固定顺序堆叠，每段带编号徽标 + 标题 + 流程描述 + 分隔线；IntersectionObserver 滚动联动（scroll spy，可见比例最大者为 activeSection）；按 pathname 平滑 scrollIntoView 到对应 section（懒加载 chunk 未就绪时 rAF 轮询等待；jsdom 无 scrollIntoView 时跳过）。
  - `web_ui/frontend/src/store/useFlowStore.ts`（新增）：zustand 存 activeSection，供 Layout 高亮当前导航。
  - `web_ui/frontend/src/pages/TubManagerPage.tsx`（新增）：TubManagerPage 从 App.tsx 迁出，作为流程页 TM section，自身逻辑不变。
  - `web_ui/frontend/src/components/Layout.tsx`：四项导航改为锚点（`/drive`、`/tub`、`/trainer`、`/pilot`），激活态随滚动联动；CC 仍是独立路由高亮；手机菜单点击即收起（含同 path 重复点击）。#179 的标题链接改动保持不变。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：新增 `active` prop，`useDriveHotkeys`/`useKeyboardDrive` 仅在 drive section 可见时启用，避免同页常驻后 R/M/U/S/A/I/J/K/L 在其它区域误触；移除页内 `drive.title` 标题（上移到 section 头）。
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：新增 `active` prop，空格播放/暂停仅在 pilot section 可见时启用；移除页内 `arena.pageTitle`/`arena.pageDescription` 标题块（上移到 section 头）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：移除页内 `trainer.title` 标题行，ModeTabs 右对齐保留。
  - `web_ui/frontend/src/i18n/messages/common.ts`：新增 flow.drive/tubManager/trainer/pilotArena.desc 四条流程描述（zh/en）。
  - 测试同步：`App.test.tsx` 的 keep-alive 回归测试改为断言「TM 在流程页各 section 间常驻、切 /connector 卸载、回切因已加载不重拉 tub」；vitest 全量 19 文件 98 项、`tsc -b --noEmit`、eslint（改动文件）、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue178-unified-flow-page` 功能分支完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (15)

- fix(launcher): DC 终端长时间无交互断线丢会话——PTY 会话与 WS 连接解耦，断线宽限期 + 按 sid 重连接回 + 断线输出回放补发 + 前端自动退避重连（Issue #173）
  - 背景：DC（Drifter Console）Web 终端的 PTY 会话与 WebSocket 连接一一绑定，浏览器闲置/休眠/网络抖动导致 WS 断开后服务端直接关闭 PTY，重新打开终端只能开新会话，现场输出与运行中进程全部丢失。
  - `donkeycar/launcher/terminal.py`：
    - `TerminalSession` 与连接解耦：不再持有固定 writer，新增 `attach(writer)`（接入新连接并补发回放缓冲）/ `detach(writer=None)`（定向解除，只 detach 属于本次连接的 writer，防旧连接收尾误清新 writer 的竞态）；断线期间子进程输出经 `_stash()` 存入回放缓冲（`_REPLAY_CAP` 1MiB 环形上限）。
    - 新增模块级 `_sessions` 注册表（sid→session，`_sessions_lock` 保护）、`_acquire_session(requested_sid)`（按 sid 复用存活会话或新建）、惰性启动的 `_ensure_sweeper()` 后台清扫线程（30s 周期调用 `_sweep_once()`）与 `_sweep_once(now)`（可单测的清扫单批）——断线后宽限期 `_SESSION_GRACE=900s` 内可重连接回，超时且无 writer 的会话才销毁回收。
    - `handle_terminal_ws` 解析查询参数 `?session=<sid>`，建连后首帧下发 `{"type":"session","id":..,"reattached":..}`；WS 断开只 `detach` 不 `close`，PTY 进程与输出缓冲保留；会话真正 `close()` 时从注册表注销。
  - `donkeycar/launcher/terminal_static/terminal.html`：记录服务端下发的会话 ID（`lastSid`），重连 URL 带 `?session=` 请求接回；断线后自动退避重连（500ms 起指数退避 ×2 封顶 10s，`visibilitychange`/`online` 事件立即重试）；收到 exit 帧置 `exited=true` 不再自动重连；重连未接回（新会话）时 `term.reset()` 清屏避免新旧输出混杂；断线 overlay 点击改为触发 `connect()` 而非整页 `location.reload()`；i18n 删 lost/failed 词条、新增 reconnecting。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` fixture 适配新构造签名（`TerminalSession()` 手动注册 + attach），`_open_terminal_ws` 支持 `session_id` 参数，新增 `_read_json_control` 助手与 3 个 #173 测试——建连 session 帧下发、断线重连 reattach 保现场并补发回放缓冲、宽限期后 `_sweep_once` 销毁回收。本文件 22 项全部通过，launcher/server/terminal 相关 43 passed 2 skipped。
  - 注：本次改动在 `Tony-terminal-reattach` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (14)

- feat(web-ui): Trainer「高级选项」折叠行文案精简为「高级」（Issue #183 后续微调）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`trainer.advancedOptions` 值 zh「高级选项」→「高级」、en「Advanced Options」→「Advanced」，词条 key 不变。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：折叠行注释同步（Advanced Options → Advanced）。
  - 后续微调（同分支，PR #207）：高级折叠行改薄——去掉 `py-2` 纵向内边距、方向箭头 `w-4 h-4`→`w-3.5 h-3.5`、加 `transition-colors`，对齐 Drive 页虚拟摇杆折叠头薄款样式。
  - 测试同步：仅文案/样式变更，无测试引用旧文案；`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-trainer-advanced-label` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (13)

- feat(ui): DD/D 两个页面标题文字可点击跳转官网，效果与点击 logo 图标一致（Issue #179，跨仓库功能：DD/DC/D 三页面标题可点）
  - `web_ui/frontend/src/components/Layout.tsx`：顶栏「DonkeyDrifter」标题文字与 logo 合并进同一个 `<a href="https://www.donkeydrift.com" target="_blank" rel="noopener">`（logo `<img>` 与文字之间以 `gap-3` 保持原 12px 间距）；链接在 `font-bold text-xl` 容器内，文字继承深浅主题标题色，Tailwind reset 下无下划线/变色，仅新增指针手势。
  - `donkeycar/launcher/server.py`（Donkey 启动页）：`MENU_HTML` 中 `<h1>Donkey</h1>` 改为 `<h1><a class="titleLink" href="https://www.donkeydrift.com" target="_blank" rel="noopener">Donkey</a></h1>`；CSS 新增 `.titleLink{color:inherit;text-decoration:none}`——颜色继承 h1、无下划线，行为对齐 logoLink。
  - 测试同步：无标题专属测试需新增；验证 `tsc -b --noEmit` 通过、vitest App/components 14 文件 78 项通过、launcher `tests/test_launcher_menu_actions.py` 37 项通过。
  - DC（Drifter Console，ESP32 Web Console）侧同类改动在 Firmware 仓库同步提交（v1.8.9，已 OTA 上车）。
## 2026-08-18 (12)

- feat(launcher): 菜单 6/7 两项打通 DD 的入口合并为 6 号「Donkey Drifter」，7 号位置灰占位、其余序号一律不变（Issue #181）
  - 背景：launcher 菜单（`menuItems`，编号 0–12）中 6「Drive」与 7「Web」最终都进入同一 DD 应用（6 走 `/api/launch/drive` 进 Drive 页，7 走 `/api/launch/web` 起 DD 前后端跳首页）；用户要求合并为一个「Donkey Drifter」入口（进 DD Drive 页面），7 号位空出占位，8–12 序号保持原位不递补。
  - `donkeycar/launcher/server.py`（MENU_HTML）：
    - `menuItems`：6 号改名「Donkey Drifter」（cat 保持 drive、favorite 保持常用），desc 改为「进入 DonkeyDrift（Drive 页面）/ Enter DonkeyDrift (Drive page)」；7 号改为 `placeholder: true` 占位行（name "—"、无分类、无 favorite、desc「已合并至 6 号『Donkey Drifter』/ Merged into #6 Donkey Drifter」）；8–12 条目原样未动。
    - `renderMenu()`：占位行渲染分支——不可点击（无 onclick）、无分类 pill、无 favorite 标、`.menuItem.placeholder` 样式（置灰 opacity .45、虚线边框、无 hover/选中效果，深浅两主题各配覆盖）。
    - `selectItem()`：占位项只弹「已合并至 6」轻提示（复用 showError），不触发任何动作；删除原 `no === 7 → launchWebUI()` 分支（数字键 7 经同一入口，行为同步）。
    - 删除前端 `launchWebUI()` 函数与 `overlay.startingWeb` i18n 词条（zh/en）；帮助文案 `help.keyNumbers` 双语更新为「（7 号已并入 6 号）」。
    - 服务端：删除 `POST /api/launch/web` 路由与 `_launch_web_ui()`（排查确认无其它消费方——DD 前端/DC 均未调用，仅菜单自身与测试）；`/api/launch/drive` 与 `GET /launch/drive`（DC 入口）不动。
  - 测试同步：`tests/test_launcher_menu_actions.py` 删除 `TestLaunchWebUI`（3 项）及 `_fake_subprocess`/`_FakePopen` 助手、`_launch_web_ui` 导入；端点测试改为下线后 404 断言；前端断言类新增 `test_menu_6_7_merged_placeholder`（改名、占位标记、Web 链路不残留、8 号仍在原位）。pytest 全量 209 passed（`test_tub_manager_auto_refresh` 1 项既有失败在干净 origin/Tony 上同样失败，与本改动无关）；MENU_HTML 内嵌 JS 逐块 `node --check` 通过；临时实例实测 `/` 返回新菜单、`POST /api/launch/web` 404。


## 2026-08-18 (11)

- fix(web-ui): DD FAB 浮球群残留的菜单式语言入口移除，语言入口统一为顶栏静音式单按钮（Issue #139 遗留）
  - 背景：Issue #139 修复（PR #146）把 DD 顶栏 `LanguageSwitcher` 与 D 启动页语言入口改成了静音式单按钮，但 DD 右下角 FAB 浮球群（`FabActions.tsx`，镜像自 DC）里仍残留 🌐 语言球 + 弹出式 langMenu（中文/English 两项菜单），违反验收要点"移除原菜单式语言切换入口，不残留死代码"；DC 侧同源 FAB 群在 Firmware 侧修复时已彻底移除语言球只留 helpFab，DD 侧对齐。
  - `web_ui/frontend/src/components/FabActions.tsx`：删除 langFab（🌐 语言球）、langMenu 弹出菜单、`LANG_SEGMENTS`、`langMenuOpen` 状态与 `toggleLangMenu`/`chooseLanguage`，FAB 群只剩 fabToggle（发光圆点）+ helpFab（?）；`collapse` 外点收起逻辑同步简化。组件头注释更新为 `.fabToggle + .fabActions (.helpFab) + .helpModal`，注明语言入口在顶栏 LanguageSwitcher。
  - `web_ui/frontend/src/i18n/messages/fab.ts`：删除已无引用的 `fab.language` 词条（zh/en 各一条），头注释同步。
  - 测试同步：`FabActions.test.tsx` 新增 1 项"FAB 群不渲染任何语言按钮/菜单"（queryByRole 语言 + queryByText 🌐/中文/English 全空）；vitest 全量 19 文件 98 项通过，`npm run build` 通过。

## 2026-08-18 (10)

- feat(web-ui): Trainer 本地训练「高级选项」由勾选框改为点击展开的折叠面板（Issue #183）
  - 需求：Trainer 页本地训练配置的「高级选项」原为 checkbox 勾选形态，改为下拉折叠面板——点击整行在下方展开高级字段，再点收起，不再有勾选框。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：勾选框替换为与 Drive 页「控制参数」面板（`ParameterPanel.tsx`）同款的整行按钮 + 右侧 ChevronDown/ChevronUp 方向箭头（lucide-react），点击切换 `advancedEnabled`，带 `aria-expanded` 无障碍标注；样式用 ParameterPanel 同款 `text-zinc-400 hover:text-zinc-200` 类名，深浅主题经 theme-light.css 类名级重映射自动适配。
  - 语义保持：`advancedEnabled` 仍是"高级覆盖生效"开关（展开=启用、收起=不启用），持久化（useStore）、`TrainerPage.tsx` 按 myconfig.py 覆盖自动置 true（面板默认展开）与训练时写 myconfig 的联动全部不动；收起时已填值保留不重置。i18n 沿用 `trainer.advancedOptions`，无新增词条。
  - 测试同步：无 LocalConfigForm 专属测试，无需新增；前端 vitest 全量 19 文件 97 项、`tsc -b --noEmit`、eslint（改动文件）、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-trainer-advanced-collapse` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (9)

- fix(web-ui): Drive 页控制参数滑块轨道浅色模式下仍为黑色——theme-light 增补伪元素变体类名覆盖（Issue #169）
  - 根因：`ParameterPanel` 的 `ParamSlider` 把轨道色写在伪元素变体类上（`[&::-webkit-slider-runnable-track]:bg-zinc-800` / `[&::-moz-range-track]:bg-zinc-800`），Tailwind 生成的类名不是字面 `.bg-zinc-800`，`theme-light.css` 的类名级重映射（`html.theme-light .bg-zinc-800`）匹配不到，轨道在任何主题下都吃硬编码 zinc-800 黑色。
  - `web_ui/frontend/src/themes/theme-light.css`：组件级微调区新增两条覆盖规则——`html.theme-light .\[\&\:\:-webkit-slider-runnable-track\]\:bg-zinc-800::-webkit-slider-runnable-track` 与对应的 `::-moz-range-track`，颜色 `#e2e8f0`（文件中 raised controls 档，本就为滑块轨道设计的浅色）；只覆盖颜色不动尺寸，thumb（24×16px 纯白椭圆）与轨道高度（6px）均未改。
  - 测试同步：无 ParameterPanel 专属测试，无需新增；已核验产物 CSS 中 Tailwind 生成的转义类名与覆盖选择器逐字匹配、规则排序在后优先级压过原规则；vitest drive 组件 + ThemeSwitcher 6 文件 42 项、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue169-drive-slider-track-light` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (10)

- refactor(web-ui): 清理 CC 页与 DC 重复的配置/选项——删除「扫描局域网找车」与无 UI 消费的 `/api/provisioning/*` 配网路由（Issue #177）
  - 背景：车端 IP 的发现/配网职责归 DC（Drifter Console，Wi-Fi 配网 + Network 卡片展示 AP/STA IP），CC（Car Connector）页另起一套「host + 局域网扫描找车」流程与之重复；DD 后端还挂了一套前端从未调用过的 `/api/provisioning/*` 配网路由，同为重复入口。
  - `web_ui/frontend/src/pages/CarConnectorPage.tsx`：「连接配置」卡删除「扫描局域网」按钮、候选 IP 列表与相关状态/回调（`foundCars`/`discovering`/`handleDiscoverCars`），host 改为纯手填；SSH 凭据、检查连接等 CC 独有职责保留。
  - `web_ui/frontend/src/services/api.ts`：删除 `discoverConnectorCars`（POST `/connector/discover`）；`discoverConnectorConsoles`（`/connector/discover_console`，launcher 页入口按钮）保留——它是"打开 DC"的入口而非配网配置。
  - `web_ui/backend/routers/connector.py`：删除 `POST /api/connector/discover`（扫 22 端口找 SSH 主机）端点。
  - `web_ui/backend/main.py` + 删除 `web_ui/backend/routers/provisioning.py`：整组 `/api/provisioning/*`（status/connect/scan/serial/scan）配网路由下线——Wi-Fi 配网由 DC 单一入口承担；`donkeycar/parts/provisioning.py`（WifiManager/ProvisioningPart 车端部件）不受影响。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：zh/en 各删除 6 条只服务于扫描找车的词条（`connector.scanning`/`scanLan`/`foundHosts`/`carIpSelected`/`discoverFound`/`scanFailed`）。
  - 测试同步：`web_ui/backend/tests/test_connector.py` 删除 `/api/connector/discover` 路由断言与 2 个 discover 端点测试；`web_ui/backend/tests/test_provisioning.py` 随路由整体删除；后端 pytest 全量 76 项通过，前端 vitest 19 文件 97 项通过，`tsc --noEmit` 通过。

## 2026-08-18 (8)

- feat(web-ui): DD 驾驶页输入源选择框移入虚拟摇杆面板标题栏，摇杆区域支持折叠/展开
  - 背景：`InputSourceSelector`（摇杆/键盘/手柄/陀螺仪输入源切换）原挂在顶部工具栏（DriveModeSelector 前），与右侧虚拟摇杆面板分离——用户希望选择框与虚拟摇杆放在一起，且摇杆区域可折叠以腾出屏幕空间。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏删除 `InputSourceSelector`；右侧控制面板标题栏改为左侧可点标题按钮（"虚拟摇杆" + ChevronUp/ChevronDown 图标，点击切换 `joystickOpen`，默认展开），右侧放 `InputSourceSelector`——折叠后选择框仍可见可切换；摇杆主体区（`VerticalThrottleBar` + `VirtualJoystick` + `ControlBars`）包在 `joystickOpen` 条件渲染内，折叠时整块收起只留标题栏。原标题栏"支持鼠标/触屏"小字随之移除（i18n 词条 `drive.mouseTouchSupport` 保留未删）。
  - `web_ui/frontend/src/i18n/messages/drive.ts`：zh/en 各新增 `drive.collapseJoystick`（折叠虚拟摇杆/Collapse virtual joystick）、`drive.expandJoystick`（展开虚拟摇杆/Expand virtual joystick），用作折叠按钮的 aria-label/title。
  - 测试同步：前端 vitest 全量 20 文件 95 项通过，`tsc -b --noEmit` 通过；Playwright 截图验证展开/折叠两态布局正常（选择框始终在标题栏右侧、折叠后摇杆圆盘收起）。
## 2026-08-18 (7)

- fix(web-ui): 顶部导航切换 Tub Manager 严重卡顿三轮修复——TM 页常驻保活 + 懒加载 chunk 空闲预取 + 后台快捷键/播放守卫（Issue #135，二轮 dev→生产模式后用户仍报卡顿）
  - 根因（Playwright + PerformanceObserver(longtask) 对用户 8000 生产实例实测确认）：react-router 每次导航到 `/` 都完整卸载重挂载 TubManagerPage——TubLibrary（2282 条记录列表 + 图片 LRU）与 TubEditor（chart-vendor 图表）整树重建，每次切换产生 77-99ms 主线程 longtask，其余页面 0ms；用户真实浏览器（更多扩展、非无头）放大到数百 ms 体感卡顿。
  - `web_ui/frontend/src/App.tsx`：新增 `KeepAliveTubManager` 组件挂在 Routes 之外（Layout main 内、Suspense 外，ErrorBoundary 仍包住）——TubManagerPage 首次进入后常驻不卸载，用 `location.pathname === '/'` 切换 `hidden` class（面板挂 `<div data-tub-manager>` 且切走时 hidden，DOM 保留、状态不丢）；原 `<Route path="/">` 改为 `element={null}`；新增 `useIdlePrefetch` hook 空闲时（requestIdleCallback）预取 Drive/Trainer/Pilot/Connector 4 个懒加载 chunk，消除冷切换时的脚本解析卡顿。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：新增 `isTubManagerRoute = useLocation().pathname === '/'` 守卫——空格键播放/暂停监听仅在 TM 页生效（切走不串页）；新增切走自动停播 effect（`isPlayingRef.current = false` + `setIsPlaying(false)`，防止后台页面持续预取图片耗资源）。
  - `web_ui/frontend/src/components/TubEditor.tsx`：全局键盘监听同样加 `isTubManagerRoute` 守卫。
  - 测试同步：`web_ui/frontend/src/App.test.tsx` 新增 keep-alive describe（mock 4 个懒加载页面组件）——TM 面板切走仍挂载且 hidden、切回恢复可见、不重拉 tub；`web_ui/frontend/src/components/TubLibrary.test.tsx` render 包 `MemoryRouter` 适配新 `useLocation` 依赖。vitest 全量 19 文件 95 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 实测（8021 测试实例 + chrome-headless-shell，tub=/home/dkc/projects/mycar/data，2282 帧）：修复前 TM 每次切换 longtask 77-99ms；修复后热切换全部归零（R2 及 Drive↔TM 来回 x3 全 0ms），仅首轮冷加载一次性 70-84ms；功能抽查确认切走面板 hidden 仍挂载、切回立即可见、2282 帧数据完整保留不重拉。

## 2026-08-18 (6)

- feat(launcher/web-ui): DC 与 DD 页面新增「DeepSeek Harness」入口按钮；DSH 启动端点缺省进入 Projects 工作区；修复 DSH 设置页 Agents 预设/提供方目录 403（Issue #164 后续）
  - **DSH 启动端点与设置页 403 修复**：
    - `donkeycar/launcher/dsh_web.py`：新增幂等自愈补丁 `_patch_privileged_methods()`——dsh（rc.6/rc.7 相同）的 `dsh-client-connection/lib/index.js` 把 `settings.*`/`credentials.*`/`llm.discoverModels`/`agentPreset.read` 等特权方法硬编码 `isTrustedApiRequest(request, [])`（空信任表，`--trusted-host` 对其无效，上游有意设计），导致 LAN Host 访问 DSH 设置页时「正在加载/权限不可用」「加载提供方目录失败」。补丁在启动前把安装文件中的 `PRIVILEGED_METHODS.has(method) && !isTrustedApiRequest(request, [])` 替换为 `...trustedHosts)`（同函数闭包变量，即沿用 `--trusted-host` 信任表）；幂等（新代码段已存在则跳过）、dsh 升级还原文件后自动重打（未命中旧代码段则跳过仅告警）；`_connection_index_path()` 从 dsh bin realpath 定位 `<pkg>/node_modules/@deepseek-ai/dsh-client-connection/lib/index.js`，找不到返回 None 安全跳过。实机验证：打补丁重启后 LAN Host（192.168.3.57:3987）下 `settings.describe` 返回 200；伪造 Host（evil.example.com）仍 403；回环 200，安全性保持。
    - `donkeycar/launcher/server.py`：`_handle_launch_dsh` 未指定 cwd 时缺省 `/home/dkc/projects`——DSH 新会话默认工作区即 Projects（dsh-host-apiproxy 用 `process.cwd()` 作为新会话默认目录，已验证 workspace.list 返回 `/home/dkc/projects`），打开 DSH 后自动进入 Projects 工作区。
  - **DD 页面（DonkeyDrifter Web UI）新增 DSH 按钮**：
    - `web_ui/backend/routers/launch.py`：抽出 `_forward_launch(request, launcher_path)` 共用转发逻辑，新增 `@router.post("/dsh")` 转发 launcher `/api/launch/dsh`。
    - `web_ui/frontend/src/services/api.ts`：新增 `launchDsh`（复用 `LaunchKimiCodeWebResult`）。
    - `web_ui/frontend/src/components/EnterButtons.tsx`：新增 `dshLaunching` 状态与 `enterDsh`（about:blank 句柄 + 65s AbortController，交互与 Kimi Code Web 按钮同款）；按钮顺序 kimi → dsh → console（consoleFirst 时 console → kimi → dsh）。
    - `web_ui/frontend/src/i18n/messages/common.ts`：zh/en 各加 5 条 `common.enterButtons.dsh*` 词条。
    - 测试同步：`EnterButtons.test.tsx` 三按钮顺序断言更新 + 新增 dsh 启动成功/失败 2 项；`tests/test_launcher_dsh_web.py` 新增 TestPatchPrivilegedMethods（5 项：定位 index.js、命中替换、幂等、未命中跳过、锁保护）+ `test_endpoint_defaults_cwd_to_projects`。launcher 侧 24 passed，前端 vitest 全量 97 passed，`npm run build` 通过。
  - DC（ESP32 Web Console）侧同款按钮见 Firmware v1.8.7（`#openDshBtn`，POST `/api/launch/dsh`）。
## 2026-08-18 (5)

- fix(web-ui): Car Connector 页面删除顶部大标题——进入 CC 页不再显示重复的 "Car Connector" 标题
  - 背景：顶部导航已有 Car Connector 入口，页面内再显示同名大标题属于冗余信息，用户要求删掉。
  - `web_ui/frontend/src/pages/CarConnectorPage.tsx`：删除页面顶部 `<h1>{t('connector.pageTitle')}</h1>` 大标题，页面直接从「连接配置」卡片开始。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：删除已无引用的 `connector.pageTitle` 词条（zh/en 各一处）。
  - 测试同步：无测试引用 `connector.pageTitle`，无需改动；vitest 全量 19 文件 94 项、`tsc -b`、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-cc-remove-title` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (4)

- feat(web-ui): Trainer 页面 Tub 路径自动填充——进入页面自动定位正确 tub，无需每次手填
  - 背景：Trainer 本地训练的 Tub 路径输入框默认值硬编码 `./data`，与 Tub Manager / Tub Navigator 当前加载的 tub 脱节，用户每次训练前要手工复制路径。
  - `web_ui/backend/routers/trainer.py`：新增 `GET /tubs?working_dir=<dir>`——扫描 `<working_dir>/data` 本体、`data` 下每个含 `manifest.json` 的子目录（覆盖解压后的 `data/tub_xxx` 形式）及 `<working_dir>/data*` 兄弟目录，返回候选列表（`relative_path` ./data 风格 + `absolute_path`）与当前已加载的 `current_tub_path`（复用 `routers/tub.py` 全局状态）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：mount / `configPath` / `tubPath` 变化时拉取候选并自动选中，优先级：当前加载的 tub（`store.tubPath` > 后端 `current_tub_path`，匹配后转为相对路径显示）> `./data`（若为合法 tub）> 唯一候选；用户手动编辑过（ref 标记 dirty）后不再自动覆盖。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：Tub 路径改为「下拉选候选 + 文本框可手改任意路径」，当前已加载的 tub 在下拉中标注「当前已加载」。
  - `web_ui/frontend/src/services/api.ts`：新增 `listTrainerTubs()` 与 `TrainerTub` 类型；`web_ui/frontend/src/i18n/messages/trainer.ts`：新增 `trainer.tubPathManual` / `trainer.tubLoaded`（zh/en）。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_tubs.py` 4 项（data 目录与子 tub、无 data 为空、跳过非 tub 目录并识别 data* 兄弟、报告已加载 tub）；pytest 后端全量 85 项、前端 vitest 全量 20 文件 95 项、`tsc -b --noEmit`、eslint、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-trainer-tub-autofill` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (3)

- feat(web-ui): Tub 导航器合入录制视频库——TM 页只保留「录制视频库」一个预览面板，TubNavigator 组件整体删除
  - `web_ui/frontend/src/components/TubLibrary.tsx`：集成原 Tub 导航器全部能力——
    - FPS 角标：播放中按实际换帧数每秒统计（#128 同款逻辑），画面冻结时角标跟随下降，暂停清零；
    - 转向/油门数值面板：读当前帧 `user/angle`（回退 `pilot/angle`）与 `user/throttle`（回退 `pilot/throttle`），无值显示「无」；
    - 帧控制排：首条/上一帧/播放/下一帧/末帧 + 刷新（`requestTubRefresh` 全量重拉，#135 手动刷新）+ 删除；
    - 标题 hover 展开「浏览 Tub 记录」副标题（`tub.subtitle`）；
    - 空格键播放/暂停快捷键（输入框聚焦时不触发）；
    - 全局图表联动（原 TN 核心职责）：换帧/播放把当前帧绝对索引 `_index` 写入全局 `currentIndex`（播放中 ~30ms 节流），Tub Editor 图表红线跟随；反向订阅 store，图表点选帧落在当前场次范围内时跳转预览（播放中不打断）；
    - 性能沉淀迁移：图片 LRU 缓存 240 条上限（#135）、预取 60 帧窗口 + 6 并发（#128）；
    - 播放行为改为单次播放（播放到末帧即停），按用户指示不迁移「播放后停止/循环播放」切换键与 M 键快捷键。
  - `web_ui/frontend/src/components/TubNavigator.tsx` / `TubNavigator.test.tsx`：删除（功能已由 TubLibrary 承接）。
  - `web_ui/frontend/src/App.tsx`：TubManagerPage 移除 `<TubNavigator />`，只渲染 TubLibrary + TubEditor。
  - `web_ui/frontend/src/App.test.tsx`：`vi.mock` 从 TubNavigator 换成 TubLibrary 桩组件。
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`：删除纯 TN 键（`tub.title`/`tub.noRecordsLoaded`/`tub.timeline`/`tub.dragging`/`tub.indexLabel`/`tub.noImage*`/`tub.loop*`/`tub.playOnce*` 等 20 键 zh+en），保留 TubLibrary 在用的 `tub.subtitle`/`tub.steering`/`tub.throttle`/帧控制与刷新键、TubLoader/SimulatorConfig 全部键。
  - `web_ui/frontend/src/themes/theme-light.css`：注释里 TubNavigator index badge 措辞更新为 TubLibrary FPS badge。
  - 测试同步：`TubLibrary.test.tsx` 原有 2 项（自动选最新、pin 置顶）保持不变且通过；vitest 全量 17 文件 89 项通过，`npm run build`（tsc -b + vite build）通过。

## 2026-08-18 (2)

- fix(launcher): DC 打开 Kimi Code Web 后进入"全新状态"——复用路径不看运行目录、入口 URL origin 漂移导致 localStorage 偏好清空、缺省 cwd 落用户主目录（Issue #168）
  - `donkeycar/launcher/kimi_web.py`：①复用路径校验实例运行目录——实例登记条目无 cwd 字段，新增 `_proc_cwd(pid)` 读 `/proc/<pid>/cwd` 真实路径，`_live_instance_url` 新增 `cwd` 参数，给定 cwd 时逐一比对（`os.path.realpath` 规范化），不匹配（如在 mycar 里跑的 TUI 内嵌 server）或读不到（进程消失/无权限）都跳过不误复用，由调用方在目标目录另起；②冷启动固定专属端口——新增常量 `KIMI_WEB_PORT = 58640`，拉起命令追加 `--port 58640`（避开 kimi 默认 58627：TUI 内嵌 server 默认占它，撞上后 kimi 自动顺延端口反而漂移），入口 URL origin 固定 `http://<LAN IP>:58640`，KCW 存在 localStorage 的置顶/自主模式/语言主题等偏好不再"被清空"；③`launch_kimi_code_web` 快路径与冷启动失败兜底均以 `cwd=` 关键字调用 `live_url_fn`（首参是 instances_dir，位置传参会把 cwd 误绑到实例目录上导致复用永远失败——真实环境联调发现并已修）。
  - `donkeycar/launcher/server.py`：`_handle_launch_kimi_code_web` 缺省 cwd 从用户主目录改为 Projects 工作区 `/home/dkc/projects`（DC 按钮空体 POST 不带 cwd，此前落到主目录导致 KCW 进的是工作区列表而非 Projects；DD 菜单显式传同一目录不受影响）；显式传 cwd 仍优先；docstring 同步。
  - 测试同步：`tests/test_launcher_kimi_web.py` 更新与新增——`_live_instance_url` cwd 匹配复用/不匹配跳过/`/proc` 读不到视为不匹配 3 项；冷启动命令含 `--port <KIMI_WEB_PORT>` 断言；复用钩子改为只收关键字参数（抓位置传参回归）；端点测试 fixture 记录收到的 cwd，新增空体 POST 与显式 cwd 两项断言缺省值为 `/home/dkc/projects`。pytest `tests/test_launcher_kimi_web.py` 38 项、launcher 相关全量 113 项通过。
  - 真实环境验证：重启 launcher 服务后 DC 同款空体 POST 连发 3 次均返回 `http://192.168.3.57:58640/#token=…`（第 1 次冷启动、后 2 次日志确认复用同端口同实例），新实例 `/proc/<pid>/cwd` 确认为 `/home/dkc/projects`；固件侧无需改动（DC 按钮 JS 与 CORS 逻辑不变）。

## 2026-08-18 (1)

- fix(web-ui): DD 驾驶页输入源切换器「手柄/陀螺仪」永远灰色不可选——连接/支持检测被 `enabled` 门控形成先有鸡还是先有蛋的死锁
  - 根因：`InputSourceSelector` 中手柄项需 `gamepadConnected`、陀螺仪项需 `permissionState !== 'unsupported'` 才可点，但 `DrivePage` 传入的 `useGamepadDrive({ enabled: inputSource === 'gamepad' })` 与 `useGyroDrive({ enabled: inputSource === 'gyro' })` 都在 `!enabled` 时直接 return——未选中该输入源时检测逻辑根本不运行，状态停在初始值（`connected=false` / `permissionState='unsupported'`），按钮永远灰着点不了，形成死锁。
  - `web_ui/frontend/src/hooks/useGamepadDrive.ts`：`gamepadconnected`/`gamepaddisconnected` 监听拆为独立 effect，组件挂载即注册（不受 `enabled` 门控），选中手柄前插手柄即可点亮可选项；控制轮询 RAF 循环仍只在 `enabled` 时运行。
  - `web_ui/frontend/src/hooks/useGyroDrive.ts`：新增挂载即执行的支持性检测 effect（不受 `enabled` 门控）：无 `DeviceOrientationEvent` → `unsupported`；存在 `requestPermission`（iOS 13+）→ `prompt`；其余（Android/桌面）→ `granted`。原 `enabled` 门控的 orientation 监听 + RAF 循环不变。
  - 测试同步：新增 `web_ui/frontend/src/hooks/useGamepadDrive.test.tsx`（2 项：未 enabled 时连接检测仍运行、全部断开后复位）、`useGyroDrive.test.tsx`（3 项：非 iOS 挂载即 granted、iOS 初始 prompt、不支持时 unsupported）。前端 vitest 全量 20 文件 95 项通过，`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-fix-input-source-disabled` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。

## 2026-08-17 (17)

- fix(launcher): Drifter Console 恢复 0 号置顶（#164 用户后续指示，撤销同日 (15) 条目的 DC 挪位）
  - `donkeycar/launcher/server.py`：menuItems 恢复 0 号 Drifter Console（`favorite: true`，置顶），DeepSeek Harness 保持 12 号（常用），编号回到 0-12；`selectItem` 恢复 `no===0 → openDrifterConsole()` 分支，删除 13 号分支；键盘恢复 0 键直达（`key==='0' → selectItem(0)`），两位输入只保留 10/11/12（按 1 后 0/1/2），删除 1+3 组合；i18n `help.keyNumbers` 改回「数字键 0-12」（zh/en + HTML data-i18n）。
  - 测试：`tests/` 全量 202 passed 无回归（菜单 HTML 无针对编号的断言，无需改测试）。

## 2026-08-17 (16)

- fix(terminal): 上位机终端页 WebSocket 连接加 10s 超时，连接卡死不再无限停在「正在连接上位机终端…」（#101，配合 Firmware v1.8.6 DC 侧探测超时）
  - `donkeycar/launcher/terminal_static/terminal.html` `connect()`：新增 `connectTimer` 10 秒定时器，超时时若 `ws.readyState===WebSocket.CONNECTING` 则清掉 `onclose`、主动 `ws.close()`，并 `showOverlay(t('failed')+' · '+t('reconnect'))` 提示连接失败可点击重连；`ws.onopen` 首行 `clearTimeout(connectTimer)` 取消定时器；`ws.onclose` 同样先 `clearTimeout` 再提示「连接丢失 · 新会话」。
  - 文案复用原 T 词典已有的 `failed` / `reconnect` 词条，中英文均无需新增。
  - 测试同步：`tests/test_launcher_terminal.py` 更新 `onclose` 断言为含 `clearTimeout` 版本；新增 `test_terminal_page_has_connect_timeout()` 断言 connectTimer/CONNECTING/ws.close/showOverlay 及中英文案存在。pytest `tests/test_launcher_terminal.py` 4 项、`donkeycar/tests/test_launcher_terminal.py`+`tests/test_launcher_menu_actions.py` 56 项全部通过。

## 2026-08-17 (15)

- feat(launcher): 启动器菜单新增「DeepSeek Harness」12 号项（常用），点击拉起/复用 `dsh web` 并跳转；Drifter Console 挪至 kimi 右侧 13 号（Issue #164）
  - `donkeycar/launcher/dsh_web.py`（新文件）：`launch_dsh_web(cwd, timeout_s=60)` 启动/复用 DeepSeek Harness web。dsh CLI 拒绝 `--host 0.0.0.0`（安全限制），用 `--patch` 临时层覆盖 webserver 配置（`host: 0.0.0.0` + `port: !!js ctx.webStartup.port ?? 3080`，port 不能省否则配置校验报缺值）实现局域网可达；`--port 0` 由 OS 分配空闲端口避免与默认 3080 冲突；`--trusted-host <本机局域网 IP>` 放行 dsh `/api` 的浏览器信任栅栏（裸 host 匹配任意端口）。就绪 banner 一行（`dsh web: http://127.0.0.1:<port> (LAN: …)`）抓 URL 后改写为局域网 IP（复用 kimi_web 的 `_lan_url`，issue #125 同款）；复用路径靠本模块 `_SPAWNED` 登记 + GET / 探测（dsh 无实例登记文件），死进程/僵死端口自动剔除后冷启动。`_resolve_dsh_binary` 先 PATH 后当前 Python 解释器同目录（systemd 干净 PATH 回退）。
  - `donkeycar/launcher/server.py`：do_POST 新增 `/api/launch/dsh` 路由与 `_handle_launch_dsh`（可选 JSON body `cwd`，非法 cwd 直接报错不回退，响应带 `_KIMI_WEB_CORS_HEADERS` 供 DC 跨域）；menuItems 重排为 1-13——1-11 不变，新增 12 号 DeepSeek Harness（`favorite: true`），DC 从 0 号置顶改 13 号（kimi 右侧）；`selectItem` 新增 12→`launchDshWeb()`、13→`openDrifterConsole()`，删除 no===0 分支；键盘两位输入扩展支持 12/13（按 1 后 400ms 内按 2/3），删除 key==='0' 分支；前端新增 `launchDshWeb()`（POST `/api/launch/dsh`，cwd 固定 `/home/dkc/projects`，成功跳转 `data.url`）；i18n `help.keyNumbers` 改「数字键 1-13」（zh/en + HTML data-i18n），新增 `overlay.startingDshWeb`（zh/en）。
  - 测试同步：新增 `tests/test_launcher_dsh_web.py` 21 项——patch 文件内容、复用不起子进程、冷启动抓 URL 且改写 LAN IP、命令行含 `--patch`/`--port 0`/`--trusted-host`、无局域网 IP 省略 trusted-host、cwd 透传、cwd 非法、binary 缺失、超时杀进程、提前退出报现场、`_SPAWNED` 死条目/僵死探测剔除、端点 200/400/500 与 CORS 头、cwd 透传；`tests/` 全量 201 passed 无回归。

## 2026-08-17 (14)

- fix(web-ui): DD 语言/主题切换按钮字体逐值对齐 DC/D——三页面按钮完全一致（#92 四轮返工：字体差异收口）
  - 根因（两处）：其一，D 页面（本机 8090）launcher 为改版前启动的旧进程，内存仍是旧 zinc 配色（#27272a），仓库源码已正确，重启进程即恢复，无需改码；其二，DD 根布局 `div.font-sans` 被主题 css 的 `.font-sans` 规则重映射为 `system-ui` 前置栈，语言/主题按钮经 preflight `font:inherit` 继承该栈，与 D/DC 显式锁定的 `:root` 栈（`-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",…,"Apple Color Emoji","Segoe UI Emoji"`）不同，用户实测字体不一致。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.theme-switcher-btn, .language-switcher-btn` 皮肤规则追加字体锁定——`:root` 完整字体栈 + `font-synthesis:none;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale` + `font-size:12px;font-weight:600`（主题按钮原为 16px/400，一并统一为 12px/600）。
  - 验证：Playwright 三页面实测（D=127.0.0.1:8090、DD=dev 服务器、DC=车 192.168.3.46 v1.8.5）深浅两主题语言按钮 10 项计算样式（背景/边框/内圈/字色/字体栈/字号/字重/宽/高/圆角）D vs DC、DD vs DC 全部 IDENTICAL；vitest 14 项、pytest 全量 183 项、`npm run build` 通过。Firmware 侧无改动，车上 v1.8.5 即最新，无需 OTA。


## 2026-08-17 (13)

- feat(web-ui): 补齐 DD 中文翻译——`common`、`arena`、`driveviz` 三个 i18n 命名空间的 zh 词条全部翻译为中文，顶部导航栏按要求保持英文不译
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh 从"镜像当前中英混合 UI"改为完整中文——App shell（出错了/刷新 Tub 失败/错误前缀/加载中）、ConfigLoader（配置加载器标题、选择车辆目录、浏览、加载、配置已加载、未加载配置、各类加载失败、路径占位与 aria）、FileBrowserModal（选择目录、返回、未找到目录、取消、选择当前目录）、SidePanel（加载器/连接器）、GitHubLink（`DonkeyDrift GitHub 仓库`）。顶部导航五项（Tub Manager/Trainer/Drive/Pilot Arena/Car Connector）按用户要求保持英文。
  - `web_ui/frontend/src/i18n/messages/arena.ts`（Pilot Arena）：zh 补译——User/Pilot 标签（用户/Pilot）、Angle/Throttle（角度/油门）、Brightness/Blur（亮度/模糊）、Pre/Post Transformations（前置/后置变换）、Tub Plot（Tub 曲线图）、Record index（记录索引）；`configLabel`/`recordsLabel`/plot 数据集名（user angle 等）等技术术语保留原文。
  - `web_ui/frontend/src/i18n/messages/driveviz.ts`（Drive 可视化）：zh 补译——Connecting/Disconnected（连接中/已断开）、Camera feed（摄像头画面）、12 条遥测曲线名（油门/转向/陀螺仪 X/Y/Z/加速度 X/Y/Z/RC 转向/RC 油门/Pilot 角度/Pilot 油门）。
  - en 词条与组件代码均未改动。
  - 测试同步：`TelemetryChart.test.tsx` 数据集断言（dataset testid、waitForDataset、复选框标签）改用中文曲线名；`VideoStream.test.tsx` alt/aria 断言改 `摄像头画面`/`WebRTC 摄像头画面`；`GitHubLink.test.tsx` 链接名断言改 `DonkeyDrift GitHub 仓库`。前端 vitest 全量 18 文件 90 项通过，`tsc -b` 与 `npm run build` 通过。
  - 注：本次改动在 `Tony-complete-zh-translations` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。

## 2026-08-17 (12)

- style(web_ui/trainer): 已训练模型删除按钮改为红色（#148 后续）
  - `web_ui/frontend/src/components/trainer/ModelsList.tsx`：模型行删除按钮配色从 `text-zinc-500 hover:text-red-400` 改为常红 `text-red-400 hover:text-red-300`，与删除语义一致、更醒目。
  - 测试：`npm run build`（tsc -b + vite build）通过。

## 2026-08-17 (11)

- fix(launcher): 上位机终端 WebSocket 增加服务端心跳保活与空闲超时判死，长时间空闲不再悄悄断连丢会话（#151）
  - 根因：`donkeycar/launcher/terminal.py` 的 WebSocket ↔ PTY 桥无任何 keepalive——只在收到客户端 PING 时回 PONG，从不主动发 PING；长时间无数据的空闲连接被 NAT 表项老化/浏览器回收悄悄断开，而协议规定断连即杀 PTY 子进程，原 shell 会话连同现场全部丢失。
  - `donkeycar/launcher/terminal.py`：新增 `_heartbeat_loop` 心跳线程（`terminal-ws-heartbeat`，随 `handle_terminal_ws` 每连接一条）——每 `_PING_INTERVAL=25s` 向客户端发 WebSocket PING 帧（浏览器协议层自动回 PONG，无需前端配合，周期性帧同时刷新 NAT 表项）；主读循环每收到一帧刷新 `last_rx`，超过 `_PONG_TIMEOUT=60s` 无任何客户端帧则置 `writer.closed` 并 `shutdown(SHUT_RDWR)` 唤醒阻塞的主读循环，走原有 finally 清理 PTY 会话；连接结束时 `stop_hb` 事件退出心跳线程。模块 docstring 帧协议说明同步补心跳帧与保活语义。
  - `donkeycar/launcher/terminal_static/terminal.html`：断连 overlay 从「连接已断开 · 点击重连」改为明确提示现场丢失——新增 `lost`/`newSession` 双语文案（zh：「连接已断开 · 终端会话已丢失 · 点击重连（将开启新会话）」；en 同义），`ws.onclose` 改用新文案；shell 正常 exit 的 overlay 维持原文案。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` 新增 2 项端到端用例（`_open_terminal_ws` 握手辅助 + 缩短心跳参数后断言收到服务端 PING、空闲超时后服务端主动断开读到 EOF）；`tests/test_launcher_terminal.py` 新增断连 overlay 会话丢失文案静态断言 1 项。相关测试 22 项全部通过。

## 2026-08-17 (10)

- feat(web_ui/trainer): 已训练模型列表每行最右侧新增删除按钮（Issue #148）
  - `web_ui/frontend/src/components/trainer/ModelsList.tsx`：模型行操作按钮区（Copy 按钮之后）新增 Trash2 图标按钮，样式与现有按钮一致（`p-1 text-zinc-500 hover:text-red-400 transition-colors`），点击 `e.stopPropagation()` 后 `setConfirmDelete(m)` 打开已有删除确认弹窗；lucide-react 导入补 `Trash2`。删除链路此前已完整实现（`deleteModel` API、`deleting`/`confirmDelete` state、`handleDelete`、确认弹窗及中英文 i18n 文案），本次仅补缺失的触发入口。
  - 测试：`npm run build`（tsc -b + vite build）通过；vitest 全量 89/90 通过，唯一失败的 `TubNavigator.test.tsx` 为并行会话在制修改（stash 本改动后复测同样失败），与本改动无关。

## 2026-08-17 (9)

- feat(web-ui): 完成 Tub Manager（TM）页面中文翻译——`tubnav` 与 `tubeditor` 两个 i18n 命名空间的 zh 词条全部翻译为中文（#157）
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`（TubNavigator + TubLoader + SimulatorConfig）：zh 从"镜像当前中英混合 UI"改为完整中文——导航器标题/副标题、未加载记录、转向/油门、时间轴、拖动中、索引标签、无图像/图像加载失败、首条/上一条/下一条/末条及 aria、播放/停止及 aria、循环/单次播放模式 aria、刷新 aria（`刷新 Tub 记录`）；TubLoader 标题/副标题/路径占位/输入框 aria/浏览/加载/请先加载配置/加载成功/未加载 Tub/选择目录/两类加载失败；SimulatorConfig 的 simHost/simMode/discover/save 四个 aria 与 `notAvailable`（`无`）。文件头注释同步改为"zh 为完整中文翻译"。
  - `web_ui/frontend/src/i18n/messages/tubeditor.ts`（TubEditor）：zh 同上改完整中文——标题/副标题、实时更新、空图表占位/空态、开始/结束索引 aria 与占位、`至`、删除中…/删除、恢复中…/恢复、缩放标签、tooltip 帧/转向/油门、数据集名 转向/油门、六条英文错误提示（范围内无记录/删除失败/恢复失败/范围无效/无可用记录/无有效记录）。文件头注释同步更新。
  - en 词条与组件代码均未改动。
  - 测试同步：`web_ui/frontend/src/components/TubNavigator.test.tsx:39` 刷新按钮定位串从 `Refresh tub records` 改为新 zh aria `刷新 Tub 记录`；前端 vitest 全量 18 文件 90 项通过。

## 2026-08-17 (8)
- style(web_ui/launcher): 三页面语言按钮配色统一为 DC/D 主题按钮（深浅切换）样式（#92 后续统一，与 Firmware v1.8.5 同批）
  - `donkeycar/launcher/server.py`（D 启动页）：`.langBtn` 基类（语言 `#langBtn` 与主题 `#themeBtn` 共用）从 DD 原生 zinc 配色（#27272a/#3f3f46/#d4d4d8，浅色 zinc-100/200/500/900）改为主题按钮配色——深色 `background:#111820;border:1px solid #344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63`、hover `#1a2330`；32×32 圆形、DD 字体栈、字号/字重不变；`#themeBtn` 的 ID 颜色覆盖与基类重合（保留仅承载布局与图标尺寸），浅色段同步换值。
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`（DD）：按钮加皮肤类 `language-switcher-btn`；`web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css` 末尾新增皮肤规则（与并行主题按钮分支同款模式）——深色 #111820/#344154/#2b3441 内圈/#b9c5d3、hover #e8edf2；浅色 #f4f6f9/#ccd5df/#d5dce4 内圈/#3f4f63、hover #1a2330；`outline:none` 抵消 `.bg-zinc-800` 通用 inset 描边，保证 border+内圈双层视觉与 DC/D 一致。
  - 测试：pytest 全量 182 项通过（`.langBtn` 无精确串断言）；vitest `LanguageSwitcher.test.tsx` 6 项通过（不锁类名）；`npm run build` 通过。D/DD 页面主机（192.168.3.41:8090）本轮不在线，D/DD 侧按源码逐值对齐 + DD 构建验证，最终视觉由用户验收。
## 2026-08-17 (7)

- style(web-ui): DD 主题切换按钮显式复刻 DC/D 渲染值，三页面（DC/D/DD）主题按钮逐值一模一样（#140 后续统一收口）
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：按钮追加 `theme-switcher-btn` 钩子类，渲染值不再依赖主题 css 对 Tailwind zinc 类的重映射。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：新增 `.theme-switcher-btn` 显式规则并置于文件末尾——深色 `outline:none;background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `#f4f6f9/#ccd5df/#d5dce4/#3f4f63`、hover `#1a2330`。修复要点：ThemeSwitcher 是 `<button>`，此前不匹配主题 css 的 `div.rounded-full.bg-zinc-800.border` 胶囊规则，漏吃到通用 `.bg-zinc-800` 的 `outline:1px solid` 压边描边而非 DC/D 的 border+inset 内圈双层视觉；显式规则同时压过该 outline，与 DC/D 完全一致（DC：Firmware v1.8.4 `.themeButton`；D：launcher `#themeBtn`，本仓 (6) 条目）。图标不变（lucide Moon/Sun 16px、stroke 2、currentColor，深色显月亮/浅色显太阳）。
  - 测试：前端 vitest 全量 90 项通过、`tsc -b` 通过、`npm run build` 通过，构建产物 dist/assets/index-*.css 中 `.theme-switcher-btn` 规则逐值核实与 DC/D 一致。语言按钮不受影响（未动 LanguageSwitcher）。

## 2026-08-17 (6)

- style(launcher): D 启动页主题按钮皮肤与 DD 渲染值逐值统一——三处（DC/D/DD）深浅切换按钮一模一样（#140 后续统一，与 Firmware v1.8.4 同批）
  - `donkeycar/launcher/server.py`：`#themeBtn` 此前复用 `.langBtn` 基类（同批 #149 语言按钮改版后基类变为 DD 原生 zinc 值 #27272a/#3f3f46），主题按钮与 DD 实际渲染脱钩；现改用 ID 覆盖独立锁定 DD 主题按钮渲染值（已核实 DD 构建产物：深色 `theme-mus4` 将 `bg-zinc-800/border-zinc-700/text-zinc-300` 重映射为 #111820/#344154/#b9c5d3，浅色 `theme-light` 为 #f4f6f9/#ccd5df/#3f4f63）：深色 `background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63`、hover `#1a2330`；图标 16px lucide Moon/Sun、深色显月亮/浅色显太阳不变。语言按钮 `.langBtn` 本批不动。
  - 测试同步：`tests/test_launcher_theme_single_button.py` 新增深/浅两套皮肤逐值断言（8 条精确串），pytest 全量 173 项通过。

## 2026-08-17 (5)

- style(launcher): 语言/主题按钮字体逐值复刻 DD（#92 返工：字体栈补齐）
  - `donkeycar/launcher/server.py`：`.langBtn`（语言 `#langBtn` 与主题 `#themeBtn` 共用）补 DD `web_ui/frontend/src/index.css` :root 完整字体栈（`-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji"`）及 `font-synthesis:none;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale`，按钮渲染字体与 DD 完全一致，不再继承页面级 `system-ui,sans-serif`（用户实测指出 D 按钮字体与 DD 不同）。
  - 测试：launcher 相关 42 项通过（无 `.langBtn` 精确串断言，仅 docstring 提及）；D 启动页设备（192.168.3.41:8090）本轮不在线，按源码逐值对齐，最终视觉由用户验收。

## 2026-08-17 (4)

- fix(launcher): `donkey web` 默认以生产模式启动 Web UI，顶部导航切换从 ~500ms 降到 ~50ms（#135 二轮修复）
  - 根因：`donkey web` 此前始终用 `npm run dev` 起 Vite dev 服务器给最终用户，dev 模式跑未优化代码 + React dev 运行时，实测顶部导航切换 400-550ms（Playwright + CPU profile 证实热点在 chart.js option 解析，为生产构建的 10 倍）；首轮修复（commit 30012564，loadedTubPath 守卫）的前端优化仍在但无法抵消 dev 模式开销，issue 被重开。生产构建由后端直接托管 dist 后实测同一 tub 仅 43-63ms（10k 记录大 tub 同样 43-77ms）。
  - `donkeycar/management/base.py`：
    - `_launch_web_ui` 重写为默认生产模式——新增 `_frontend_needs_build()`（dist/index.html 缺失或 src/public/配置文件比 dist 新则需重建），需要时先 `npm run build`，随后 uvicorn 不带 `--reload` 单进程同时托管 API 与 dist 静态文件（`frontend_port = backend_port`、`frontend_proc = None`）。
    - 新增 `--dev` 参数（Web 与 Drive 命令）：显式传入时走原有逻辑（Vite dev 服务器 + uvicorn `--reload`），供前端开发使用；端口选择逻辑同步调整为仅 dev 模式下独立选 frontend_port。
    - `run()` 的 supervise 进程列表过滤 `None` 前端进程；Drive 命令同步加 `--dev` 防止 `args.dev` AttributeError。
    - `donkeycar/launcher/server.py` 无需改动：实例登记读 `~/.donkeycar/webui.json`，生产模式下登记的 frontend_port 即 backend_port，`/` 探测依然成立。
  - 验证：新增 `tests/test_web_production_mode.py` 9 项（默认生产模式 build→单进程/无 --reload/frontend_port==backend_port、dist 新鲜跳过 build、build 失败 SystemExit、--dev 起 Vite、`_frontend_needs_build` 4 例、`--dev` 默认 False）；pytest 全量 182 项通过、前端 vitest 全量 90 项通过；端到端实测（8020 端口直接调 `_launch_web_ui`）：SPA 与 API 同端口正常服务、无前端子进程。用户需重启现有 Web UI 实例后生效。

## 2026-08-17 (3)

- fix(web-ui): Tub Library（录制视频库）Pin 按钮与删除按钮间距过大，收拢为右侧相邻按钮组（#131 迭代）
  - `web_ui/frontend/src/components/TubLibrary.tsx`：列表行原为 `justify-between` 三段布局，中间文本块与 Pin、删除图标分列两端之间，导致 Pin 悬在行中部、与垃圾桶距离过远；现将 Pin 与删除两个 `<span>` 包进同一 `flex items-center gap-1 shrink-0` 容器，两图标固定相邻、整体靠右，行内文本仍占左侧剩余空间。
  - 测试：前端 vitest 全量 90 项通过、`npm run build` 通过（TubLibrary 置顶/删除既有用例不受影响）。

## 2026-08-17 (2)

- style(launcher): 三页面（DC/D/DD）语言切换按钮样式统一为 DD 原生样式（#92 后续统一，与 Firmware 侧同批）
  - `donkeycar/launcher/server.py`：`.langBtn` 从主题重映射值（#111820 底、#344154 边框、1px #2b3441 内描边、#c3cbd6 字色、13px、hover #e8edf2、active 高亮态）改为逐值复刻 DD `LanguageSwitcher` 原生渲染——32×32 圆形、#27272a 底、1px #3f3f46 边框、12px/600、#d4d4d8 字色、hover #f4f4f5，无内描边/active 态；JS `applyLanguage` 移除 `classList.toggle('active',…)`；浅色覆盖改用同族 zinc 值（底 #f4f4f5、边框 #d4d4d8、字色 #52525b、hover #18181b）。`.langBtn` 同时被 `#themeBtn` 主题按钮复用，主题按钮样式随之统一；样式块注释同步更新为 DD 原生值说明。
  - 测试同步：launcher 相关 42 项通过（`test_launcher_language_autodetect.py`/`test_launcher_menu_actions.py`/`test_launcher_theme_single_button.py`，后两者仅 docstring 提及 `.langBtn` 无样式断言）。

## 2026-08-17 (1)

- feat(web-ui,launcher): 深浅主题切换改为静音式单按钮，单击深/浅互切，默认跟随浏览器深浅（#140）
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：从"浅色/跟随系统/深色"三段式分段控件改为静音式单图标按钮（与 #139 语言切换同形态：32×32 圆形胶囊）——图标反映当前生效主题（深色显月亮、浅色显太阳，lucide `Moon`/`Sun`），单击在深↔浅之间互切；默认跟随浏览器 `prefers-color-scheme` 与 localStorage 持久化（沿用键 `donkeydrifter.ui.theme`）由 `src/lib/theme.ts` 已有实现承担，未手动单击前不写入存储、实时跟随浏览器切换，手动单击后持久化显式选择且不再跟随；`aria-label` 提示切换目标主题。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：测试重写为单按钮断言 8 例——月亮/太阳图标与 aria-label 反映当前主题、单击切浅色并持久化、双击回深色、默认跟随系统深浅实时变化（跟随期间不写存储）、手动单击后不再跟随系统、挂载恢复持久化皮肤、非法存储值回退跟随系统。
  - `donkeycar/launcher/server.py`（D 启动页 :8090）：移除 `#themeTabs` 浅色/跟随系统/深色三态菜单及 `renderThemeTabs`、`theme.light/auto/dark` 双语文案，改为 `#themeBtn` 静音式单图标按钮（复用 `.langBtn` 圆形样式，内联 lucide 太阳/月亮 SVG 按 `html[data-theme]` 显隐），单击 `toggleTheme()` 按当前生效主题取反并经 `setTheme` 持久化；`renderThemeBtn()` 同步更新 aria-label/title 为切换目标主题（新增 `theme.toggleLight/toggleDark` 双语文案）；首屏防闪烁与 'system' 态跟随浏览器逻辑不变。
  - 测试：前端 vitest 全量 90 项通过、`tsc -b` 通过；新增 `tests/test_launcher_theme_single_button.py` 源码断言 3 例（单按钮入口与三态移除、toggle 深浅互切与持久化、默认跟随浏览器/手动后不跟随），pytest 全量 173 项通过。

## 2026-08-16 (19)

- feat(web-ui,launcher): 语言切换改为静音式单按钮，默认跟随浏览器语言（#139）
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`：从中文/English 两段式 pill 控件改为单图标按钮——显示当前语言（中文显示"中"、英文显示"EN"），单击在中/英之间切换；`aria-pressed` 反映当前是否中文、`aria-label` 提示切换目标语言；跟随浏览器语言与 localStorage 持久化逻辑由 i18n Provider 已有实现，无需改动。
  - `web_ui/frontend/src/components/LanguageSwitcher.test.tsx`：测试同步更新为单按钮断言（按钮文字、aria-pressed、单击切换、双击回切、持久化、浏览器语言跟随），6 项通过。
  - `donkeycar/launcher/server.py`（D 启动页 :8090）：移除桌面端 `langTabs` 分段式语言切换和移动端 `langFab`+`langMenu` 弹出菜单，统一改为 `#langBtn` 单按钮——显示"中"/"EN"，单击调 `toggleLanguage()` 切换；新增 `.langBtn` CSS（深色/浅色变体）、移除 `.langTabs`/`.langFab`/`.langMenu` 全部相关 CSS 与 JS（`toggleLanguageMenu`/`closeLanguageMenu`）；`applyLanguage()` 中更新按钮文字与 active 状态；跟随浏览器语言与 localStorage 持久化逻辑不变。
  - DD 前端 `npm run build` 通过、`npm test` 93 项通过；D 启动页 `pytest tests/test_launcher_language_autodetect.py` 2 项 + `tests/test_launcher_menu_actions.py` 37 项通过。

## 2026-08-16 (18)

- feat(web-ui): Pilot Arena 自动扫描模型，唯一模型时自动选中并加载预测（#136）
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：
    - 新增 `autoScanDoneRef`/`autoLoadDoneRef` 两个 ref 跟踪每个 viewer 的自动扫描/自动加载状态。
    - 新增 useEffect：当 `hasRecords` 且 `configPath` 可用时，自动为每个未扫描过的 viewer 调用 `refreshModels`（即自动执行"扫描模型"），无需手动点击。
    - 新增 useEffect：扫描结果只有一个模型时（`models.length === 1`），自动调用 `loadViewer`（即自动执行"加载并预测"），画面上出现预测转向线。
    - 多个模型时只自动扫描填充列表，不自动选择/加载，保留现有手动流程。
    - `unloadViewer` 中同步清理 `autoScanDoneRef`/`autoLoadDoneRef`，移除 viewer 后重建不会残留状态。
  - 前端 `npm run build` 通过。

## 2026-08-16 (17)

- feat(web-ui): 完成 Trainer 页面中文翻译（#137）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：全部 zh 词条（约 65 条）从英文原文翻译为中文，包括标题、标签页、配置项、日志、状态、删除确认弹窗等；带插值参数的词条（`{name}`/`{count}`/`{path}`/`{loss}`/`{message}`）占位符保持不变；状态标签译为 待开始/运行中/已完成/失败/已停止。
  - 文件头注释更新：原"zh values mirror the current UI strings verbatim"已失效，改为说明 zh 为完整中文翻译。
  - en 词条保持不变。前端 `npm run build` 通过。

## 2026-08-16 (16)

- feat(web-ui): DD 顶部导航标签顺序调整为 Drive → TM → Trainer → PA → CC（#138）
  - `web_ui/frontend/src/components/Layout.tsx`：`navItems` 数组重新排序为 Drive（`/drive`）→ Tub Manager（`/`）→ Trainer（`/trainer`）→ Pilot Arena（`/pilot`）→ Car Connector（`/connector`），桌面导航与手机汉堡菜单共用该数组同步生效；路由路径不变，仅改显示顺序。
  - 前端 `npm run build` 通过。

## 2026-08-16 (15)

- feat(launcher): D 页（launcher 菜单）1-5、7-10 号菜单项全部接线，点按不再弹"未实现"，与 TUI 各命令行为对齐（#126）
  - `donkeycar/launcher/server.py` 后端新增（对齐 `donkeycar/management/tui.py` 各 Command，不 import tui 依赖链，按需精简实现）：
    - 菜单 1 `_create_car`：`donkey createcar --path ~/projects/<folder>`，项目名白名单 `^[A-Za-z0-9_\-]+$`（400）、目录已存在不覆盖（409）、成功后切换当前项目并持久化 `last_project_path`（写 `~/.donkeyrc`，失败静默不阻塞）。
    - 菜单 2 `_open_project` + `_find_valid_projects_local`：只允许打开 `~/projects` 下一层的有效项目（manage.py+myconfig.py），越界或无效一律 400。
    - 菜单 3 `_clear_data`：data 不存在/为空返回 skipped；可选 zip 备份到 `data_backups/data_backup_<ts>.zip`；清空走"先 move 到 `.data_trash_<ts>` 再 rmtree"，任一步失败自动回滚（对齐 TUI trash 逻辑）。
    - 菜单 4 `_backup_data`：tar.gz 备份到 `<project>/data_cache/data-<yymmdd>-<NNN>.tar.gz`（arcname 相对路径不带 `data/` 前缀，序号当日递增）；磁盘剩余 < 数据体积×1.1+1MB 时拒绝（507），失败清理半成品。
    - 菜单 5 `_restore_data` + `_list_backups`：备份名白名单 `^data-\d{6}-\d{3}\.tar\.gz$`（防穿越）、损坏归档校验（500）、解压前磁盘检查、现有 data 先移 trash 失败回滚；`_is_safe_member_local` 拒绝绝对路径/`..` 穿越；兼容 `tar czf x.tar.gz data/` 带前缀归档（全成员 data/ 前缀则解到上级目录）。与 TUI 恢复的已知差异：不做 DataMigrator 嵌套数据整理（flatten_nested_data，依赖链重），按原样恢复。
    - 菜单 7 `_launch_web_ui`：与 #127 实例登记打通——`find_live_instance()` 存活直接复用返回 URL；否则默认端口 8000/5188 新起 `donkey web`（捆绑 web_ui --path），PID 写入登记文件供 Drive 链路清理复用。
    - 菜单 8/9/10 终端命令下发（前端经 terminal `?cmd=` 执行，后端提供支撑端点）：`GET /api/train/next-model` 扫 `<project>/models/pilot_<数字>` 取 max+1 供菜单 9 拼 `donkey train --tub ./data --model ./models/pilot_N --type linear`；菜单 8 为 `cd '<project>' && donkey ui`，菜单 10 为 `python -m donkeycar.management.train_online`。
    - 新路由：GET `/api/projects`、`/api/data/backups`、`/api/train/next-model`；POST `/api/launch/web`、`/api/createcar`、`/api/projects/open`、`/api/data/clear|backup|restore`；`LauncherHandler._read_json_body()` 统一 JSON 请求体解析（坏 JSON 400）。
  - `donkeycar/launcher/server.py` 前端（MENU_HTML）：
    - `selectItem` 全 12 项分发接线（1→createCar、2→openProject、3→clearData、4→backupData、5→restoreData、7→launchWebUI、8→launchDonkeyUI、9→launchTrainLocal、10→launchTrainOnline），删除 `overlay.notImplemented` 分支（I18N 键保留作无害兜底）。
    - 新增 I18N zh/en 键：`overlay.startingWeb/working/done`、`menu.createcar.prompt/exists`、`menu.open.prompt/none`、`menu.clear.confirm/confirmNoBackup`、`menu.train.openTerminal`、`menu.donkeyui.openTerminal`。
    - 交互：createCar prompt 项目名+已存在探测询问覆盖；openProject 列表编号选择；clearData 两次确认（含"不备份继续"分支）；restoreData 备份列表选择+确认；launchWebUI 复刻 Drive 的 30×1s 就绪轮询后跳转；8/9/10 经 `window.open('/terminal?cmd='+encodeURIComponent(cmd))` 下发。
  - `donkeycar/launcher/terminal_static/terminal.html`：支持 `?cmd=` 查询参数（decodeURIComponent + `+`→空格），WebSocket hello 之后自动发送并回显该命令一次，用于菜单 8/9/10 的终端命令自动执行。
  - 测试：新增 `tests/test_launcher_menu_actions.py` 37 项——`_launch_web_ui`（复用/新起/PID 登记/缺 donkey 二进制）、`_create_car`（非法名/已存在 409/成功切换项目/命令行与 TUI 一致/失败带 stderr）、`_open_project`（越界/无效/成功）、数据往返（backup→clear→restore 文件回来）、restore 穿越名/损坏归档/data 前缀归档、`_next_train_model` 递增、HTTP 端点（内存 ThreadingHTTPServer 全路由）、前端静态断言（接线函数、I18N 键、terminal.html autoCmd）；fixture 统一打桩 `_save_last_project_path_local` 防止测试写真实 `~/.donkeyrc`。全量 `pytest tests/` 136 项通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/terminal_static/terminal.html`、`tests/test_launcher_menu_actions.py`（新增）

- feat(web-ui): 录制视频库支持 Pin 置顶（#131 迭代）
  - `web_ui/frontend/src/components/TubLibrary.tsx`：每条录制项右侧（删除图标左边）新增 Pin 按钮（lucide `Pin`）——点击置顶到列表最上方，已置顶项图标填充并高亮 cyan 色，再点取消；置顶组与非置顶组内部均保持时间降序（最新在上）。
  - 置顶状态按 tubPath 存 `localStorage`（key `tubLibrary.pinned.<tubPath>`，存 session_id 数组），纯前端状态、不涉及后端 API；localStorage 不可用（隐私模式等）时置顶仅本次会话内生效，不报错。删除录制时同步从置顶集合移除该 session。
  - i18n：`tublibrary.ts` 新增 `tubLibrary.pinAria`（置顶这条录制 / Pin this recording to top）、`tubLibrary.unpinAria`（取消置顶 / Unpin this recording）。
  - 测试：`TubLibrary.test.tsx` 新增置顶用例——点击较旧录制的 Pin 后移到列表首位并写入 localStorage，取消置顶后恢复最新在前顺序；前端 `npm test` 18 文件 92 例、`npm run build` 均通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`、`web_ui/frontend/src/components/TubLibrary.test.tsx`、`web_ui/frontend/src/i18n/messages/tublibrary.ts`

## 2026-08-16 (14)

- fix(complete,actuator): RC 手动驾驶时将手柄实际控制量合并进 tub 录制通道（#133）
  - 根因：固件 MANUAL 模式下车由 RC 接收机直驱，Web/手柄通道 `user/angle`、`user/throttle` 全程为 0，TubWriter 只录这两个键，导致问题 tub（11656 帧）9942 条有效记录全为 0.0、Tub Editor 曲线贴 0 轴；固件串口 T 帧上行的实际控制量已由 ArdRc 发布到 `rc/steering`、`rc/throttle`（-1..1）但未进录制通道。
  - `donkeycar/parts/actuator.py`：新增 `RcRecordMerge` part——仅 `rc/mode==0`（MANUAL）、非 park 锁定且 rc 值有效（数值、非 bool）时用 `rc/steering`、`rc/throttle` 覆盖 `user/angle`、`user/throttle` 供 TubWriter 记录；SEMI/FULL AUTO、park、`rc/mode` 未知（仿真等）时原样透传，不改变既有录制行为，避免"RC 怠速值覆盖跳 0"问题复发。
  - `donkeycar/templates/complete.py`：TubWriter 注册前接入 RcRecordMerge（与 mycar 运行实例对齐）；ARDUINO_CONTROLLER 传动链补齐 ArdRc 块（发布 `rc/steering`、`rc/throttle`、`rc/mode`、`rc/park`）。
  - 不新增 tub 字段，既有 tub manifest inputs/types 一致性断言不受影响；修复不回溯历史数据，既有全 0 tub 需重新录制；SEMI_AUTO（rc/mode==1）录制仍走旧逻辑。
  - 测试：新增 `tests/test_rc_record_merge.py` 8 项单元测试（MANUAL 合并、SEMI/FULL AUTO/park/未知模式/无效值透传、bool 拒绝、模板接线断言），全部通过；真实 donkeycar Vehicle 循环仿真验证 MANUAL 下合并、SEMI 下透传；回归 `pytest tests` 107 项通过、与改动相关套件（test_actuator/test_template/test_tubwriter/test_vehicle/test_launch）39 过 2 跳、`donkeycar/tests` 排除 test_launch 全过——完整连跑在本机及 origin/Tony 基线均于 test_provisioning 附近忙转挂起，系既有环境问题，与本次改动无关。
  - 涉及文件：`donkeycar/parts/actuator.py`、`donkeycar/templates/complete.py`、`tests/test_rc_record_merge.py`（新增）

## 2026-08-16 (13)

- feat(web-ui): Loader 多 mycar 项目时自动 Browse 上次用过的项目（#129 增强）
  - 后端 `web_ui/backend/routers/config.py`：新增 `~/.donkeycar_web_loader.json` 状态文件（命名惯例同 connector 的 `~/.donkeycar_web_connector.json`）——`POST /api/config/load` 加载成功后记录 `last_car_path`；`GET /api/config/discover_projects` 返回 `last_project`（上次项目在扫描根之外但仍含 config.py+manage.py 时一并并入 projects 供前端参考；状态文件损坏/缺失时回退 None 不报错）。
  - 前端 `web_ui/frontend/src/components/ConfigLoader.tsx`：自动发现逻辑扩展——唯一项目→自动加载；多个项目且 `last_project` 在列表中→自动加载上次项目（与 localStorage 记忆互补，跨浏览器/清缓存后仍有效）；否则回退手动 Browse。`api.ts` 的 `discoverProjects` 返回类型同步补 `last_project`。
  - fix(web-ui): 顺手修复 `handleManualLoad` 中硬编码的本机路径 `/home/dkc/projects/mycar/data` 特判——其它机器上曾持久化该 tub 路径时会被误判为“需要保留的旧 tub”，现仅按 `<path>/data` 归一化比较。
  - 测试：后端 `test_config.py` 新增 `last_project` 链路 1 项（无记录 None→load 成功记录→扫描根之外并入→损坏文件回退）；前端 `ConfigLoader.test.tsx` 扩至 6 项（新增：多项目时自动加载上次项目、上次项目不在列表回退手动）。后端全量 pytest 77 项、前端全量 vitest 86 例（16 文件）、`tsc --noEmit` 均通过。
  - 涉及文件：`web_ui/backend/routers/config.py`、`web_ui/backend/tests/test_config.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/ConfigLoader.tsx`、`web_ui/frontend/src/components/ConfigLoader.test.tsx`
- feat(web-ui): 进入录制视频库后自动选中最新一条录制
  - `web_ui/frontend/src/components/TubLibrary.tsx`：`refreshSessions` 拉到列表后，若当前无选中（或选中的录制已不存在，如刚被删除）则自动选中 `sessions[0]`（API 已按最新在前排序），进入页面即可直接预览最新录制；已有有效选中时保持不变。
  - 测试：新增 `web_ui/frontend/src/components/TubLibrary.test.tsx` 2 项——加载后自动请求最新录制的记录并显示帧计数、未加载 tub 时不请求列表；前端 `npm run build` 无错误，`npm test` 18 文件 89 例通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`、`web_ui/frontend/src/components/TubLibrary.test.tsx`（新增）

## 2026-08-16 (12)

- fix(web-ui,templates): 修复 Tub Navigator 播放录制视频卡顿（#128），并让 WEBCAM 接受 CAMERA_FRAMERATE 配置
  - 排查结论（issue 内已实测）：录制侧帧间隔均匀（17ms 中位、>25ms 零次）无丢帧；卡顿全部在播放侧——后端每帧全量磁盘读 + 前端帧推进与图片加载解耦导致画面冻结跳帧。
  - 后端 `web_ui/backend/routers/tub.py`（`GET /api/tub/image`）：
    - 新增按 `(mtime_ns, size)` 校验的字节级 LRU 缓存（128 MiB 预算），命中直接从内存回图不再碰磁盘；超预算淘汰最旧条目。
    - 响应加 `ETag` 与 `Cache-Control: private, max-age=86400`，支持 `If-None-Match` 304 协商；重复播放同一 tub 时浏览器 disk cache 参与命中。
    - 原先两处 `FileResponse` 路径统一收敛为缓存读取逻辑，404 分支不变。
  - 前端 `web_ui/frontend/src/components/TubNavigator.tsx`：
    - 预取窗口 10 帧 → 60 帧（PREFETCH_AHEAD，覆盖 ~1s），并用 pump 模式加并发上限（PREFETCH_CONCURRENCY=6，对齐 HTTP/1.1 同源连接数），预取完成一个补位一个，不再几十个请求挤占连接。
    - 解码位图缓存复用 #135 的 LRU 上限（`touchImageCache`，240 条、命中刷新位置、超限淘汰最旧），预取写入同一缓存，长 tub 播放不再无限吃内存。
    - FPS 角标改为统计 canvas 实际换帧率（drawImage 时按 URL 去重累计），画面冻结时角标如实下降，可自检卡顿；原先统计 rAF 回调频率（恒 ~60）的问题一并去除。
    - 绘制路径去掉多余的一层 `requestAnimationFrame` 包裹，未就绪帧的加载回调直接绘制，减少一帧延迟。
  - 附带修复 `donkeycar/templates/complete.py`、`basic.py`：`Webcam` 创建传入 `framerate=cfg.CAMERA_FRAMERATE`（原先 WEBCAM 用默认 20Hz，60fps 主循环里同一帧被重复记录约 3 次）；顺带修复 complete.py stereo 分支 `Webcam(..., iCam=...)` 传了不存在的参数（一实例化即 TypeError）改为 `camera_index=0/1`，basic.py 用 `getattr(cfg, 'CAMERA_INDEX', 0)` 兜底（cfg_basic 未定义该项）。
  - 测试：新增 `tests/test_tub_image_cache.py` 5 项（ETag/Cache-Control 头、缓存命中不读磁盘、If-None-Match 304、文件变更失效、LRU 超预算淘汰）与 `tests/test_webcam_framerate.py` 3 项（complete/basic 模板 Webcam 必传 framerate、stereo 分支不得再用 iCam）；rebase 到 #135 后发现其漏更新的 `tests/test_tub_manager_auto_refresh.py` 断言仍指向旧路由刷新逻辑（在 Tony 上即失败），同步改为断言 `loadedTubPath`/`tubRefreshToken` 新逻辑；前端 `tsc -b --noEmit` 通过、vitest 89 例（18 文件）通过、eslint 无告警、后端 `tests/` 125 项全过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/frontend/src/components/TubNavigator.tsx`、`donkeycar/templates/complete.py`、`donkeycar/templates/basic.py`、`tests/test_tub_image_cache.py`（新增）、`tests/test_webcam_framerate.py`（新增）、`tests/test_tub_manager_auto_refresh.py`

## 2026-08-16 (11)

- feat(web-ui): 录制视频库列表改为最新录制排在最上面
  - `web_ui/backend/routers/tub.py`：`GET /sessions` 返回排序由 `first_index` 升序改为降序（最新一次录制排第一，最旧排最后）；前端 TubLibrary 按返回顺序渲染，无需改动。
  - 测试：`web_ui/backend/tests/test_tub_sessions.py` 分组测试补充排序断言（最新的 `first_index` 更大、必须排在首位）；4 项通过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/backend/tests/test_tub_sessions.py`

## 2026-08-16 (10)

- revert(tub-editor): 回退 #130 的选区框最小宽度修复，恢复 TubEditor 原有选区绘制与单击判定逻辑（用户要求撤销）
  - `git revert d63fe8e2`：`web_ui/frontend/src/components/TubEditor.tsx` 恢复原始实现（移除 `MIN_SELECTION_BOX_WIDTH` 最小框宽与 `handleMouseUp` 的 `indexDelta === 0` 判定），删除随该修复新增的 `web_ui/frontend/src/components/TubEditor.test.tsx`；同时移除原「2026-08-16 (4)」中对应的日志条目。
  - 测试：删除测试文件后不影响其它用例，前端 vitest 全量通过。
  - 涉及文件：`web_ui/frontend/src/components/TubEditor.tsx`、`web_ui/frontend/src/components/TubEditor.test.tsx`（删除）

## 2026-08-16 (9)

- feat(web-ui): 录制视频库移除循环播放按键，改为始终循环播放
  - `web_ui/frontend/src/components/TubLibrary.tsx`：删除 `isLooping` 状态与播放/暂停旁的循环切换按钮（含 `Repeat` 图标导入），播放到最后一帧后始终回到第 0 帧继续播放，不再播完自动停止；循环相关 i18n 键（`tub.loop*`）为 Tub Navigator 共用，未改动。
  - 测试：无已入库测试断言该循环按钮；前端 `npm run build`（tsc -b + vite）无错误，`npm test` 18 文件 89 例通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`

## 2026-08-16 (8)

- fix(web-ui): 修复 DD 顶部导航（Tub Manager / Trainer / Drive 等）切换非常卡顿的问题（#135）
  - 根因：`TubManagerPage` 的 effect 以 `location.pathname === '/'` 为条件，每次从其它页切回 Tub Manager 都全量重拉整个 tub（上千条记录时需全量下载 + 整包写 store + TubNavigator/TubEditor 两个重组件全量重渲染，期间还有全屏 loading 遮罩），切换体验即"每次都卡"。
  - `web_ui/frontend/src/store/useStore.ts`：新增 `loadedTubPath`（当前 store 中已加载完成的 tub 路径标记，`setTub` 时写入）与 `tubRefreshToken`（手动刷新令牌）及 `requestTubRefresh()`（清空已加载标记并递增令牌）；均不参与 persist。
  - `web_ui/frontend/src/App.tsx`：`TubManagerPage` 改为仅在 `tubPath !== loadedTubPath`（首次加载或 tub 变更，含刷新页面后从持久化恢复 tubPath 的场景）或 `tubRefreshToken` 递增（手动刷新）时拉取数据，并补 `cancelled` 清理避免组件卸载后 setState；顶部导航来回切换不再触发网络请求与全量重渲染。
  - `web_ui/frontend/src/components/TubNavigator.tsx`：图片缓存增加上限 `MAX_IMAGE_CACHE_ENTRIES = 240` 与 LRU 淘汰（Map 插入序，命中刷新位置、超限淘汰最旧），长会话播放/预取不再让缓存无限增长拖慢切换；播放控制行新增手动"刷新"按钮（调用 `requestTubRefresh`，loading 时旋转禁用），替代原来导航切换隐式重拉的刷新途径。
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`：新增 `tub.refresh` / `tub.refreshAria` / `tub.refreshTitle` 中英文案。
  - 测试：新增 `web_ui/frontend/src/App.test.tsx`（4 例：首次加载拉取并标记 loadedTubPath、已加载不重拉、requestTubRefresh 触发重拉、无 tubPath 不拉取）与 `web_ui/frontend/src/components/TubNavigator.test.tsx`（1 例：刷新按钮触发 requestTubRefresh 且清空 loadedTubPath）；前端 vitest 全量 83 例（16 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 涉及文件：`web_ui/frontend/src/App.tsx`、`web_ui/frontend/src/store/useStore.ts`、`web_ui/frontend/src/components/TubNavigator.tsx`、`web_ui/frontend/src/i18n/messages/tubnav.ts`、`web_ui/frontend/src/App.test.tsx`（新增）、`web_ui/frontend/src/components/TubNavigator.test.tsx`（新增）

## 2026-08-16 (7)

- feat(web-ui): Tub 页面新增"录制视频库"分区，按 session 列出每次录制的视频并可整条播放/删除（#131）
  - 需求：Web UI Tub 页面新增录制视频库——左侧列出 mycar 录制的每条视频（同一 Tub 内按 `_session_id` 分组，一次 drive 启动 = 一条录制），右侧播放器逐帧播放该 session 图像，支持整条删除（带确认弹窗），删除后 Navigator/Editor 等其它板块不再显示对应帧。
  - 后端 `web_ui/backend/routers/tub.py`：
    - `GET /sessions?tubPath=`：以只读 Tub 迭代 live records 按 `_session_id` 分组，返回每条录制的 `session_id`/`record_count`/`first_index`/`last_index`/`start_time_ms`/`end_time_ms`，按 `first_index` 排序（写入时间序），用完即 `close()`。
    - `GET /session_records?tubPath=&sessionId=`：返回单条录制全部 live records，供播放器逐帧取图（图片仍走既有 `GET /api/tub/image`，未改动）。
    - `POST /delete_session`：收集该 session 所有 `_index`（空则 404），用可写 Tub 实例调 `delete_records(indexes)` 做 manifest 软删（与逐帧删除同机制）；若删的是当前已加载 tub，则重建全局 `current_tub`/`current_records`，其它板块数据即刻同步。
    - 新增 `SessionDeleteRequest`（`tub_path` + `session_id`）Pydantic 模型。
  - 前端：
    - `web_ui/frontend/src/services/api.ts`：新增 `TubSession`/`TubRecord` 接口与 `listTubSessions`/`getSessionRecords`/`deleteTubSession` 三个 API 函数。
    - `web_ui/frontend/src/components/TubLibrary.tsx`（新增）：左列 session 列表（选中高亮、每项带删除图标、显示 `_timestamp_ms` 格式化的开始时间与帧数）+ 右侧 canvas 播放器：预取 30 帧（Navigator 仅 10 帧）、图片未就绪时停在当前帧等待而不跳帧（吸取 #128 播放卡顿教训）、支持播放/暂停/循环/逐帧步进/进度条拖动；底部整条删除按钮触发自绘确认弹窗（fixed 遮罩 + zinc-900 卡片，项目无现成 Modal 组件），确认后调 `delete_session` 并刷新列表 + 重新 `loadTub` 同步全局 store。
    - `web_ui/frontend/src/i18n/messages/tublibrary.ts`（新增）：zh/en 各 19 条 `tubLibrary.*` 文案；`web_ui/frontend/src/i18n/messages/index.ts` 注册该模块。
    - `web_ui/frontend/src/App.tsx`：TubManagerPage 中 `<TubNavigator />` 之后插入 `<TubLibrary />`。
  - 测试：新增 `web_ui/backend/tests/test_tub_sessions.py` 4 项——两次独立 Tub 实例各写 3+2 帧模拟两条录制，验证 sessions 列表分组/排序/时间戳、session_records 过滤、delete_session 软删后 sessions 与全局加载记录均不再包含已删帧（注意同一 Tub 实例不会产生新 session_id，测试须每次新开实例）；4 项通过。前端 `npm run build`（tsc -b + vite）无错误，`npm test` 14 文件 78 例通过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/backend/tests/test_tub_sessions.py`（新增）、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/TubLibrary.tsx`（新增）、`web_ui/frontend/src/i18n/messages/tublibrary.ts`（新增）、`web_ui/frontend/src/i18n/messages/index.ts`、`web_ui/frontend/src/App.tsx`
## 2026-08-16 (6)

- fix(launcher): D 页点 6 打开 Drive 后页面加载不出来——跳转不等前端就绪 + 端口可能被二次改选（#134）
  - 根因：`_launch_drive` 在 `Popen` 返回后立即报 launched，跳转页重定向到尚未监听的 vite 端口（Vite 冷启动/首次 npm 依赖检查需数秒甚至更久），浏览器连接拒绝/白屏；且 launcher 预选端口与 `donkey web` 内部二次改选后的实际端口可能不一致，跳转到错误端口。
  - `donkeycar/launcher/server.py`：新增 `_wait_for_web_ready(web_proc, frontend_port, backend_port, timeout=90s)`——等 `donkey web` 就绪写入实例登记（`~/.donkeycar/webui.json`，登记里是 vite/uvicorn 实际监听端口，天然覆盖端口被占二次改选；以 `started_at` 不早于本次调用起点判定为本次启动写入），再 GET 实际 frontend_port 的 `/` 直到可访问才返回；web 进程提前退出或超时不报错，透出 warning 照常跳转。
  - `_launch_drive`：新起 web 时先等就绪、回读实际端口再返回 launched（跳转页拿到响应时前端已能服务页面）；车进程改在就绪后启动，`DRIVE_API_SERVER_URL` 连接实际后端端口；返回 url/端口均为实际值；复用存活实例路径行为不变（不起 web、不等就绪）。
  - `donkeycar/webui_instance.py`：新增 `probe_http_ok` 公开别名（原 `_probe_http_ok`），供 launcher 跨模块复用 HTTP 探测。
  - 测试：新增 `tests/test_launcher_drive_launch.py` 9 项——`_wait_for_web_ready` 新登记回读实际端口、vite 二次改选跟随登记端口、web 提前退出带 warning、登记不出现超时带 warning、早于调用起点的陈旧登记不认；`_launch_drive` 冷启动顺序（先 web 后车、env 连实际后端、url 用实际前端端口）、就绪超时透出 warning、复用实例跳过 web 与等待、无 mycar 项目直接报错；全量 `pytest tests/` 108 项通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/webui_instance.py`、`tests/test_launcher_drive_launch.py`（新增）

## 2026-08-16 (5)

- feat(web-ui): Loader 自动发现唯一 mycar 项目并自动加载，无需人工 Browse（#129）
  - 后端 `web_ui/backend/routers/config.py`：新增 `GET /api/config/discover_projects?root=<dir>` 接口与 `find_car_projects()` 扫描函数——BFS 扫描 root 下含 `config.py` + `manage.py` 的目录（默认 root 为用户 home，最多下探 2 层，跳过隐藏目录与 `node_modules`/`venv`/`__pycache__` 等），返回 `{projects, count}`；扫描经 `run_in_threadpool` 不阻塞事件循环。
  - 前端 `web_ui/frontend/src/services/api.ts`：新增 `discoverProjects()` API 封装。
  - 前端 `web_ui/frontend/src/components/ConfigLoader.tsx`：新增自动发现 effect——store 无 `config` 且无已记住 `configPath` 时调用 `discoverProjects()`，恰好发现 1 个项目则复用 `handleBrowserSelect` 链路自动加载（config + `<carPath>/data` tub）；多个项目或扫描失败时静默回退现有手动 Browse 流程；`useRef` 防重复触发。
  - 测试：后端 `web_ui/backend/tests/test_config.py` 新增 3 项（唯一项目发现、多项目/无项目、隐藏目录跳过+项目内不下钻+缺 manage.py 不算项目）；前端新增 `web_ui/frontend/src/components/ConfigLoader.test.tsx` 4 项（唯一项目自动加载 config+tub、多项目不自动加载、发现失败静默回退、已有 configPath 跳过发现）。后端全量 pytest 76 项、前端全量 vitest 82 例（15 文件）、`tsc --noEmit` 均通过。
  - 涉及文件：`web_ui/backend/routers/config.py`、`web_ui/backend/tests/test_config.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/ConfigLoader.tsx`、`web_ui/frontend/src/components/ConfigLoader.test.tsx`（新增）

## 2026-08-16 (3)

- fix(launcher): 修复 DC/DD/D 三处「打开 Kimi Code Web」与 DC 终端手动 `/web` 返回的链接打不开的问题（#125）
  - 根因：`kimi_web.py` 返回的 URL host 是上位机本机视角的 `localhost`/`127.0.0.1`，消费方是用户电脑/手机上的浏览器，`localhost` 指向浏览器自己自然打不开；且冷启动的 `kimi web` 默认只绑回环（banner `Network: off`），即使改写 host 局域网也访问不到。
  - `donkeycar/launcher/kimi_web.py`：
    - 冷启动命令改为 `kimi web --no-open --host`（`--host` 裸传 = 绑 `0.0.0.0`，实测 kimi ≥ 0.36 支持），局域网设备可达。
    - 新增 `_is_loopback_host`/`_lan_url`：返回前把回环/通配 host（`localhost`/`127.x`/`::1`/`0.0.0.0`）改写为本机局域网 IP（复用配网模块 `detect_lan_ip` 的 VPN/TUN 感知探测），保留端口、路径与 `#token=` 片段；探测不到局域网 IP 或 host 本就远程可达时原样返回。复用、冷启动、失败兜底三条返回路径统一改写。
    - `_live_instance_url`：登记 host 是回环的实例（如 TUI 内嵌 server）先对局域网 IP 探测 `/api/v1/meta`，通了（实际监听 0.0.0.0 只是登记写了 127.0.0.1）改用局域网 host 返回；不通视为不可复用，由调用方另拉监听 0.0.0.0 的新实例。
  - `donkeycar/launcher/server.py`：`_handle_launch_kimi_code_web` docstring 同步（移除过时的"注入 /web"描述，注明 URL 已改写为局域网 IP）；端点行为无变化，DC/DD/D 三端消费同一返回值，改 launcher 一处全部修复。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `_fake_lan_ip` autouse fixture 隔离真实网络探测；新增 `TestLanUrl` 6 项（回环/通配 host 识别、改写保留端口与 token、远程 host 不动、无局域网 IP 原样返回）与 `_live_instance_url` 回环实例双探测 3 项；既有断言按局域网改写更新（复用/冷启动/兜底返回 URL、启动命令含 `--host`）；全量 `pytest tests/` 108 项通过。
  - 端到端实测：本机（192.168.3.x 网段）真实拉起 `kimi web`，返回 `http://192.168.3.57:<port>/#token=...`，局域网 IP 上 HTTP 探测可达（未带 token 的 `/api/v1/meta` 返回 401，证明服务真实监听）。
  - 涉及文件：`donkeycar/launcher/kimi_web.py`、`donkeycar/launcher/server.py`、`tests/test_launcher_kimi_web.py`

## 2026-08-16 (2)

- fix(launcher,web,management): Web UI 实例登记与复用，修复 D 页按 6 号（Drive）后 Tub Manager 打不开、需再按 7 号（Web）才可用的问题（#127）
  - 根因：launcher `_launch_drive` 启动前 `pkill -f "donkey web"` 与 PID 文件全杀互杀已运行的 Web UI；且各链路动态选端口（backend 从 8100 漂移），与 7 号默认端口（8000/5188）不一致，浏览器/前端代理指向漂移端口导致页面不可用。
  - 新增 `donkeycar/webui_instance.py` 共享模块（模式参考 `kimi_web.py`）：
    - 实例登记 `~/.donkeycar/webui.json`（pid/backend_port/frontend_port/started_at，原子写入）：`read_instance`/`write_instance`/`remove_instance(only_pid)`——`only_pid` 仅清除属于自己 pid 的登记，避免误删他人后来覆盖的登记。
    - `find_live_instance()`：登记 pid 存活 + 后端 `/docs` 与前端 `/` 探测均通才算存活；失效自动清陈旧登记。
    - 车进程 PID 文件（`~/.donkeycar/drive.pid`）读写与 `kill_previous_car_processes()`：读 `/proc/<pid>/cmdline` 只杀 `manage.py drive` 车进程（释放摄像头等硬件），web 前后端进程保留复用；非 Linux 无 /proc 时退化为按 PID 全杀（与旧行为一致）。
  - `donkeycar/management/base.py`：
    - `Web.run`：先 `find_live_instance()`，存活则复用并按 `--route` 打开已有前端端口，不再重复拉起；新起路径等后端端口就绪再登记实例，退出 `finally` 按 `only_pid` 清除。
    - `Drive.run`：先只杀车进程（web 进程保留），存活实例则复用其 backend_port 注入 `DRIVE_API_SERVER_URL`、只起新车进程（PID 文件只记车进程）；无实例才新起 Web UI 并登记。
  - `donkeycar/launcher/server.py`：`_launch_drive` 删除 `_kill_orphaned_donkey_processes()`（pkill 互杀元凶）及本地 PID 副本函数，收敛到 `webui_instance`；复用存活实例只起车进程，无实例用默认端口 8000/5188 新起 `donkey web`（不再 8100 漂移）；`_get_status` 未跟踪进程时优先读实例登记，其它链路启动的 Web UI 也算 running。
  - `donkeycar/management/tui.py`：`DriveCommand.execute()` 同步复用逻辑（删除本地 PID 副本函数，探测存活实例→复用只起车进程→无则默认端口 8000 新起）；`monitor_processes` 兼容复用时无 web 进程；命令预览对复用场景显示"复用已有实例，不重复启动"。
  - 测试：新增 `tests/test_webui_instance.py` 18 项——登记读写与容错、`only_pid` 条件清除、`find_live_instance` 判定链（pid 不存活/探测失败清陈旧登记）、PID 文件往返、`kill_previous_car_processes` cmdline 过滤只杀车进程与非 Linux 退化全杀、`Web.run`/`Drive.run` 复用路径（mock 后断言不重复 Popen、车端 URL 指向复用后端端口、PID 文件只记车进程）；全量 `pytest tests/` 99 项通过。
  - 涉及文件：`donkeycar/webui_instance.py`（新增）、`donkeycar/management/base.py`、`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`、`tests/test_webui_instance.py`（新增）

## 2026-08-16 (1)

- feat(launcher,web-ui): 点击 D/DD 页面左上角 logo 图标，在新标签页打开 https://www.donkeydrift.com
  - `donkeycar/launcher/server.py`（D 页 MENU_HTML）：`.headerLogo` 的 `<img>` 包进 `<a class="logoLink" href="https://www.donkeydrift.com" target="_blank" rel="noopener">`；`.headerLogo` 规则旁新增 `.logoLink{display:inline-flex}`，避免锚点行内基线问题，flex 的 `.headerRow` 视觉布局不变。
  - `web_ui/frontend/src/components/Layout.tsx`（DD 顶栏）：标题左侧 `<img src="/logo.png">` 包进 `<a href="https://www.donkeydrift.com" target="_blank" rel="noopener" className="flex items-center">`，img 原有 className 原样保留，布局/样式无可见变化。
  - 测试同步：无已入库测试断言该 logo 标记，无需修改；launcher 相关 pytest（test_launcher_terminal/test_launcher_service_unit/test_launcher_language_autodetect/test_launcher_kimi_web）30 项通过，前端 vitest 78 例（14 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 验证：worktree 临时 8190 端口启动 D 页，`curl /` 确认锚点与 CSS 均输出；DD 构建产物 `dist/assets/*.js` 含 donkeydrift.com。
  - 涉及文件：`donkeycar/launcher/server.py`、`web_ui/frontend/src/components/Layout.tsx`

## 2026-08-15 (11)

- fix(packaging): 排查并修复 macOS 上 `pip install donkeycar\[pc\]` 后 `donkey` 命令功能与 DonkeyDrifter 不一致的问题
  - 根因分析（实证验证）：
    - `donkeycar[pc]` 与 `donkeycar\[pc\]` 两种写法装出的东西**完全相同**——bash/zsh 会消耗 `\`，pip 收到的需求字符串一致；zsh 下裸 `[pc]` 触发 glob 报 `no matches found`，`\[pc\]` 只是让方括号存活到 pip 的转义写法。
    - 若反斜杠真的传给 pip（PowerShell/cmd/复制 Markdown 转义源码），新旧 pip（实测 26.1.2 / 23.3.2）均把它当本地目录，安装直接失败，不存在"装出功能不同版本"的路径。
    - 真正根因：PyPI 上 `donkeycar` 是官方上游包（autorope）。macOS 上执行该命令装的是**官方 donkeycar**——它覆盖 DonkeyDrifter 提供的 `donkeycar` 兼容包并重新生成 `donkey` console script，`tui`/`web`/`drive`/`installweb` 等 DonkeyDrifter 命令全部消失，裸 `donkey` 从进入 TUI 退化为打印 usage。
  - 修复：
    - `donkeydrifter/__init__.py`：导入时探测环境中是否存在名为 `donkeycar` 的发行包（本项目发行名是 donkeydrifter，正常安装不会注册该名），命中即向 stderr 输出醒目警告与恢复指引（`pip uninstall -y donkeycar` 后重装 `donkeydrifter[macos]`/`[pc]`）；元数据异常不阻塞导入。
    - `README.md`：Quick Start 改为 `pip install "donkeydrifter[pc]"`（引号形式，zsh 安全）；新增"安装 donkeydrifter 而非 donkeycar"醒目警告与冲突恢复命令；新增 Platform extras 小节说明 `pc`/`macos` 差异与 zsh 三种等价写法。
    - `docs/guide/donkeycar-compatibility.md`：新增"PyPI 包名与 donkey 命令"章节（两个发行包对照表、覆盖症状、恢复步骤）与"关于 `[pc]` vs `\[pc\]`"章节（三种 shell 行为实测结论）。
  - 测试：新增 `tests/test_upstream_override_warning.py` 3 项——无 donkeycar 发行包时零输出、误装后 stderr 含版本号与恢复指引、元数据异常不破坏导入；全部通过。
  - 涉及文件：`donkeydrifter/__init__.py`、`tests/test_upstream_override_warning.py`、`README.md`、`docs/guide/donkeycar-compatibility.md`

## 2026-08-15 (10)

- feat(web_ui): D/DD 切换胶囊外框统一为 DC 粗框语言——border 1px 外圈 + box-shadow inset 1px 内圈（两条相加，视觉 2px），取代与 border 重叠只剩 1px 的 outline 负偏移描边
  - `donkeycar/launcher/server.py`（D 页 MENU_HTML；主题 #themeTabs 与语言 #langTabs 两胶囊共用 .langTabs）：
    - 深色基础：`outline:1px solid #2b3441;outline-offset:-1px` → `box-shadow:inset 0 0 0 1px #2b3441`；浅色变体（`html[data-theme="light"] .langTabs`）：`outline-color:#d5dce4` → `box-shadow:inset 0 0 0 1px #d5dce4`。色值不变，只改描边实现。
  - `web_ui/frontend/src/themes/theme-mus4.css`、`web_ui/frontend/src/themes/theme-light.css`（DD ThemeSwitcher/LanguageSwitcher）：
    - 通用 `.bg-zinc-800` outline 规则不动——影响面太大（Button secondary 的 shadow-sm、Input 的 focus ring、多处 h-2 细轨道条都会被 inset 阴影波及）；新增专用选择器 `html.theme-mus4/theme-light div.rounded-full.bg-zinc-800.border{outline:none;box-shadow:inset 0 0 0 1px …}`，只命中两个切换胶囊容器（ModeTabs 容器是 bg-zinc-900，不误伤；DriveModeSelector 等其它控件族不在本次范围）。
  - 配套：Firmware 仓库同把 DC 的 RGB 开关（.langTabs）升级为同一粗框语言（v1.7.89），三处 D/DD/DC 切换键框体语言完全一致。
  - 测试同步：无已入库测试断言皮肤 CSS/模板样式，无需修改；全量验证：`tests/` + `web_ui/backend/tests/` pytest 151 项通过，前端 vitest 78 例（14 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 验证：D 页（worktree 临时 8091 实例）与 DD（vite preview 构建产物）Playwright 深/浅截图复核，两组胶囊均为 2px 粗框，与 DC 一致。
  - 部署注意：合并后需在上位机 `git pull` 并重启 `donkeydrifter-launcher.service`（D 页），DD 需重新 `npm run build`。
  - 涉及文件：`donkeycar/launcher/server.py`、`web_ui/frontend/src/themes/theme-mus4.css`、`web_ui/frontend/src/themes/theme-light.css`

## 2026-08-15 (9)

- feat(web_ui): DD 标题区入口按键文案去掉"打开 "/"Open "前缀——"打开 DrifterConsole"→"DrifterConsole"、"打开 Kimi Code Web"→"Kimi Code Web"（en 同步 "Open DrifterConsole"/"Open Kimi Code Web"→去前缀），中英文保持一致
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh/en 两段各改 `common.enterButtons.drifterConsole`、`common.enterButtons.kimiCodeWeb` 两条；tooltip（`kimiCodeWebTitle`/`drifterConsoleTitle`）、失败提示（`kimiCodeWebFailed`）等其它含"打开/open"的词条一律不动。
  - `web_ui/frontend/src/components/EnterButtons.tsx` 确认无硬编码兜底文案、无渲染时前缀拼接（按钮直接渲染 i18n key），无需改动；桌面版头部与手机版汉堡菜单共用这两个 key，一处改两处同时生效。
  - 测试同步：`EnterButtons.test.tsx` 断言的是 i18n key 而非具体文案，无需修改；全量验证：后端 pytest 78 项通过，前端 vitest 78 例（14 文件）通过，`tsc -b --noEmit` 无错误，eslint 0 error（6 个 warning 均为既有、位于本次未触碰文件）。
  - 涉及文件：`web_ui/frontend/src/i18n/messages/common.ts`

## 2026-08-15 (8)

- fix(launcher): 修复 DC/DD/D 三处"打开 Kimi Code Web"全部失效（about:blank / 启动超时）——kimi 0.36.0 起 TUI 不再进 alternate-screen，旧的"PTY 注入 `kimi` → `/web`"自动化永远等不到就绪信号，每次必等满 60s 超时（避让：并行会话已合入 #118 占用 (7)，本条改号为 (8)）
  - `donkeycar/launcher/kimi_web.py` 重写启动链路（响应契约 `{"status","url"}` 不变，DC/DD/D 前端与 D 侧转发零改动）：
    - 快路径（复用）：扫描 `~/.kimi-code/server/instances/*.json` 登记（心跳新鲜 + pid 存活 + 带 `~/.kimi-code/server.token` 探测 `/api/v1/meta` 200），命中即返回 `http://<host>:<port>/#token=<token>` 入口 URL，毫秒级；kimi TUI 的内嵌 server 同样可复用。
    - 慢路径（冷启动）：无存活实例时直接拉起官方子命令 `kimi web --no-open`（0.36 起 `kimi server` 是其废弃别名），从 stdout ready banner 抓 `Local:`/`#token=` URL；二进制优先取 `~/.kimi-code/bin/kimi`（systemd 干净 PATH 下也能找到），实测冷启动 1.8s（原 TUI 链路常态 60s 超时）。失败路径杀净子进程并兜底再试一次复用（覆盖端口被登记滞后实例占用）。
    - 移除 PTY/TUI 自动化（`_BufferWriter`/`_wait_tui_ready`/`_wait_web_url`/`session_factory`），`extract_web_url`/`strip_ansi` 保留；`server.py` 仅 `launch_kimi_code_web(cwd=)` 一处调用，签名兼容。
  - `tests/test_launcher_kimi_web.py` 同步重写：保留 ANSI/URL 提取与端点 CORS 用例，新增实例复用过滤（心跳/pid/探测）、复用不起子进程、冷启动抓 URL、cwd 透传、二进制缺失、失败兜底复用、超时杀进程等用例（_FakeProc 真实管道模拟 stdout）。
  - 验证：`tests/` 全量 76 项通过；本机实测 POST 端点链路——复用路径 0.00s 返回、真实冷启动 1.8s 抓回 `#token=` URL。
  - 部署注意：合并后需在上位机 `git pull` 并重启 `donkeydrifter-launcher.service` 才生效。

## 2026-08-15 (7)

- feat(launcher): 终端页把输入行首词 postMessage 给 Drifter Console，用于 Serial 终端标签页改名
  - `donkeycar/launcher/terminal_static/terminal.html`：
    - 新增行捕获：`term.onData` 在转发 WebSocket 后追加 `trackLine(d)`——可打印字符入 `lineBuf`，退格 `\x7f`/`\b` 删尾字符，Ctrl+C/ESC 清空缓冲（方向键等转义序列不会拼出假名字），回车 `\r`/`\n` 触发 `commitLine()`。
    - `commitLine()`：取 trim 后第一个空白前的词（输入 `abc defg hijk` 上报 `abc`），截断 16 字符，非空才 `window.parent.postMessage({type:'donkeydrifter.term.name',name},'*')`（跨源 iframe，父页按 `e.source` 匹配自己的标签）。
    - TUI 防误改：`scanAltScreen()` 在 PTY 输出流扫描 `ESC[?1049h/l` 维护 `inAlt`，备用屏幕缓冲区期间（kimi/claude/codex 等全屏 TUI）清空并暂停行捕获。
  - 配套：固件侧（Firmware 仓库）新增 message 监听按 iframe 改名标签，重编号时自定义名优先。
  - 测试同步：新增 `tests/test_launcher_terminal.py` 静态断言 2 项通过；node --check 校验 script 块通过。

## 2026-08-15 (6)

- fix(launcher): D 页切换胶囊补浅色变体，深浅双色值全部改为 DD 主题重映射后的真实渲染值
  - 背景：(5) 误把 Tailwind 工具类的原始色值当作 DD 实际效果——DD 的 `src/themes/theme-mus4.css`/`theme-light.css` 会在两套主题下重映射这些工具类（如 `.bg-zinc-800` 深色实为 `#111820`、浅色实为 `#f4f6f9`），导致 (5) 的胶囊在深色下偏亮、浅色下完全保持深色（无浅色变体）。
  - 深色（theme-mus4 实际渲染值）：胶囊底色 `#27272a→#111820`、边框 `#3f3f46→#344154` 并补 1px `#2b3441` 内描边（outline -1px），未激活文字 `#a1a1aa→#8fa1b5`、hover `#e4e4e7→#e8edf2`，激活 `#0891b2→#5cc8ff` + 文字 `#fff→#061019` + 字重 400→800。
  - 浅色（theme-light 实际渲染值，新增）：胶囊 `#f4f6f9` + border `#ccd5df` + 内描边 `#d5dce4`，未激活文字 `#5b6b7d`、hover `#1a2330`；激活态深浅一致（`#5cc8ff`/`#061019`/800）。
  - hover/底色规则均以 `:not(.active)` 排除激活键，杜绝浅色下覆盖激活色（级联 (0,2,2)>(0,2,1) 曾把激活文字冲成 #5b6b7d/#1a2330）。
  - 测试同步：纯模板内 CSS 改动，无断言涉及；全量 pytest 98 项通过。Playwright 无头对拍：Donkey 胶囊与 DD（vite dev 实跑）在深色/浅色下的计算样式逐项一致（容器底色/边框/内描边/padding/gap/圆角、激活底色/文字色/字重、未激活文字色、字号），含浅色激活键悬停态。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-15 (5)

- feat(launcher): D 页顶栏主题/语言切换胶囊复刻 DD 样式、整行垂直居中，11 号 Kimi Code Web 设为常用
  - `donkeycar/launcher/server.py` 菜单数据：11 号 "Kimi Code Web" `favorite: false → true`，菜单卡片显示「常用」标签。
  - 顶栏切换胶囊（`.langTabs`）逐值复刻 DD 的 `ThemeSwitcher.tsx`/`LanguageSwitcher.tsx` Tailwind 规格：容器 `bg-zinc-800(#27272a)` + 1px `border-zinc-700(#3f3f46)` + `p-1`/`gap-1`（原为 `#171c24` + 内阴影描边、固定高 24px）；按钮 `px-3 py-1`、`text-xs`（12px/16px）、字重 400（原 800），激活 `bg-cyan-600(#0891b2) text-white`（原 `#5cc8ff`），未激活 `text-zinc-400(#a1a1aa)` 且 hover 仅文字变 `zinc-200(#e4e4e7)` 不改背景，加 `transition-colors` 过渡。
  - 与 DD 行为一致：浅色模式下胶囊保持深色外观——删除 `html[data-theme="light"] .langTabs` 五条例外覆盖（DD 的胶囊为固定 Tailwind 色，无 light 变体）。
  - 顶栏整行垂直居中：`.headerRow` `align-items:flex-end → center`，删除 `.ghLink`/`.versionBadge` 的 `translateY(-1px)` 补偿与 `.headerLogo` 的 `align-self` 补丁；手机端两行布局不变。
  - 测试同步：纯模板内 CSS/数据改动，无断言涉及；全量 pytest 98 项通过。Playwright 无头实测：桌面深/浅下整行（图标/标题/GitHub/版本号/两个胶囊）垂直中心均为 29.0px 零偏差，手机端两行各自居中（28px/85px）；胶囊计算样式与 DD 逐项一致（含浅色保持深色）；11 号「常用」标签渲染确认。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-15 (4)

- fix(web_ui): 顶栏胶囊与导航文本禁止换行——头部空间不足时"中文"/"跟随系统"竖排两行把切换键撑到 50px、导航 "Tub Manager" 折行
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`、`ThemeSwitcher.tsx`：分段按钮加 `whitespace-nowrap`；`Layout.tsx` 导航链接 `linkClass` 加 `whitespace-nowrap`。修后两个切换键恢复 34px，与"打开"按键同高；无头浏览器实测整行（图标/标题/导航/版本号/GitHub 图标/进入按键/切换键）垂直中心偏差全部 0.0px。
  - 测试同步：纯类名调整，无断言涉及；全量 vitest 78 例通过。
  - 涉及文件：`web_ui/frontend/src/components/LanguageSwitcher.tsx`、`web_ui/frontend/src/components/ThemeSwitcher.tsx`、`web_ui/frontend/src/components/Layout.tsx`

## 2026-08-15 (3)

- fix(web_ui): DD 标题区"打开 Drifter Console" / "打开 Kimi Code Web"按键高度由 24px（h-6）提至 34px，与右侧中英文切换键精确同高（LanguageSwitcher 总高 = 内部键 24px + 外壳 p-1×2 + border×2）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：按钮类名 `h-6` 改为 `h-[34px]` 并附注释，其余样式不动；桌面端与手机端（consoleFirst）两处实例同时生效。
  - 配套：Firmware 仓库 v1.7.76 把 DC 头部三个"打开"按键同样提至 34px（`#enterDonkeyBtn,#enterDonkeyDrifterBtn,#openKimiCodeWebBtn{height:34px}` 专属规则，OTA 按钮保持 24px），已 OTA 上车确认。
  - 测试同步：纯样式类名调整，无断言涉及高度；`EnterButtons.test.tsx` 7 例及全量 vitest 回归通过。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`

## 2026-08-15 (2)

- feat(launcher,web_ui): 实现"打开 Kimi Code Web"（issue #103/#104；配套 Firmware 侧 #59，固件 v1.7.74）
  - `donkeycar/launcher/kimi_web.py`（新增）：自动化核心——复用 `terminal.TerminalSession` 建独立 PTY bash 会话（writer 换成本模块的 `_BufferWriter` 缓冲输出，不动现有 WebSocket 桥），注入 `kimi` → TUI 就绪判定（alternate-screen 进入序列 `\x1b[?1049h` + 输出静默 2s，上限 60s）→ 注入 `/web` → 从注入点之后的输出剥 ANSI 捕获 URL（`Session:` 深链优先，`Local:`/`URL:`/`Network:` 次之，任意 http(s) 兜底）；`command not found`/`Trust this folder`/`No active session`/内嵌 server 失败均有专门报错；整体超时 120s；成功时会话保持存活（kimi web server 挂在该 PTY 前台），失败一律 close 不留孤儿。
  - `donkeycar/launcher/server.py`：新增 `POST /api/launch/kimi-code-web`——请求体可选 JSON `{"cwd": "/abs/path"}`（缺省上位机主目录；目录不存在直接报错，绝不回退）；成功 `200 {"status":"ok","url"}`、失败非 200 `{"status":"error","error"}`；**所有响应带 `Access-Control-Allow-Origin: *`**（DC 页面由 ESP32 提供服务，浏览器跨域 fetch :8090 依赖此头，仅此端点放行）；`_serve_json` 新增 `extra_headers` 参数承载。
  - D 页面（MENU_HTML）新增 **11 号菜单项"打开 Kimi Code Web"**（#104）：点击/数字键（先 1 再 1 二段输入）触发 `launchKimiCodeWeb()`，POST 固定带 `{"cwd":"/home/dkc/projects"}`（issue 要求先进入 projects 主文件夹），等待期间 overlay 显示"正在启动 Kimi Code Web（kimi 启动较慢，请耐心等待）..."，拿到 URL 后**当前标签页**跳转（区别于 #103 的新标签页）；help 文案数字键范围 0-10 改为 0-11。
  - `web_ui/backend/routers/launch.py`（新增）：`POST /api/launch/kimi-code-web` 转发路由——DD 前端与后端同源，相对路径到达本后端后原样转发到 launcher `http://localhost:8090`（125s 超时；连接失败回 502 中文错误；launcher 的业务错误 JSON 原样透传），`main.py` 挂载 `/api/launch` 前缀。
  - DD 前端（#103）：`services/api.ts` 新增 `launchKimiCodeWeb(signal)`（`validateStatus` 全放行，业务错误交给调用方按 status 判断）；`EnterButtons.tsx` 的 kimi 按钮接功能——防重复点击、点击同步上下文先 `window.open('about:blank','_blank')` 拿句柄规避弹窗拦截、`AbortController` 125s 超时、成功 `win.location.href=url`、失败关句柄并 alert；`i18n/messages/common.ts` 补 zh/en 词条（title/启动中…/失败/网络错误）。
  - 测试同步：`tests/test_launcher_kimi_web.py`（新增）19 项——strip_ansi/extract_web_url 纯函数、`_FakeSession` 脚本化 PTY（成功保活/cwd 透传/cwd 非法不建会话/command not found/Trust folder/No active session/超时回收/默认 session_factory）、内存 HTTP 服务器端点路由与 CORS 断言；`EnterButtons.test.tsx` 占位断言改为行为断言（成功填入预开标签页、失败关页+alert），共 7 例。全量回归：pytest 71 项、vitest 78 项通过。
  - 涉及文件：`donkeycar/launcher/kimi_web.py`、`donkeycar/launcher/server.py`、`web_ui/backend/routers/launch.py`、`web_ui/backend/main.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/EnterButtons.test.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`tests/test_launcher_kimi_web.py`

## 2026-08-15 (1)

- fix(launcher): 新开 Serial 上位机终端会话默认工作目录改为 `~/projects`（Closes #102）
  - 背景：/terminal 上位机终端新会话此前落在用户主目录 `~`（`terminal.py` `_spawn()` 的 `cwd or os.path.expanduser("~")`），每次用 kimi 等工具前都要手动 `cd`。
  - `donkeycar/launcher/terminal.py`：新增 `_default_cwd()`——优先返回 `os.path.expanduser("~/projects")`（不硬编码 `/home/dkc`），目录不存在时回退 `~`；`_spawn()` 默认 cwd 改走该函数，显式传 cwd 的调用方行为不变。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` 新增「默认工作目录」一节 3 个用例（`~/projects` 存在时默认指向它、不存在回退 `~`、真实 bash PTY 会话 `pwd` 端到端验证），全部用 `monkeypatch.setenv("HOME", tmp_path)` 隔离机器状态；launcher 相关 27 项测试通过。
  - 涉及文件：`donkeycar/launcher/terminal.py`、`donkeycar/tests/test_launcher_terminal.py`

## 2026-08-14 (21)

- docs(readme): 重写仓库根 README
  - `README.md` 整体重写：补充平台定位（本仓库与 Firmware 仓库的 MUS4 ESP32 固件配套，构成完整漂移车平台）。
  - 新增 Features 一节：模板、数据训练、模拟器、Web UI、Launcher、MUS4 集成。
  - 新增 Repository Layout 一节，说明仓库目录结构。
  - Quick Start 注明要求 Python 3.11。
  - 仓库链接修正为 `github.com/DonkeyDrift/DonkeyDrift`。
  - 新增 Related Repositories 一节，指向 Firmware 仓库。
  - 保留原有 fork 声明、Donkeycar 兼容性说明与 License/致谢结构。
  - 测试同步：纯文档改动，无代码与测试变更，未运行测试。
  - 涉及文件：`README.md`

## 2026-08-14 (20)

- feat(launcher): 新增 `/terminal` 上位机 Web 终端——浏览器里得到上位机完整 bash 终端
  - 背景：Drifter Console 的 cmdTarget 下拉框此前只有 Web 一项（Serial 日志源在固件 v1.7.29 后与 Web 同源重复被去掉）。本改动把 Serial 选项恢复并升级为真正的上位机终端：固件侧选中 Serial 时以 iframe 嵌入 `http://<host_ip>:8090/terminal`，可在浏览器里直接使用上位机 bash（kimi/claude/codex/donkey 等全屏 TUI 程序可用）。
  - `donkeycar/launcher/terminal.py`（新增）：WebSocket↔PTY 桥——每个 ws 连接 fork 一个 PTY 跑 login shell，双向转发 stdin/stdout，支持浏览器端窗口缩放（resize 消息同步 TIOCSWINSZ）、连接关闭时回收子进程、shell 退出时主动通知前端。
  - `donkeycar/launcher/terminal_static/`（新增）：xterm.js 自包含终端页（`index.html` + 本地 vendored `xterm.js`/`xterm.css`/`addon-fit.js`，无 CDN 依赖，车内无互联网可用）。
  - `donkeycar/launcher/server.py`：新增 `/terminal` 终端页路由、`/terminal/static/*` 静态资源与 `/terminal/ws` WebSocket 端点。
  - 安全口径（用户已决策）：与固件控制台免密（Firmware v1.7.71）同口径——家用局域网场景不加认证，谁连上谁可用；后续如需暴露到非信任网络再补鉴权。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py`（新增）14 项——PTY 桥回显/resize/退出通知、路由与静态资源、server 集成。launcher + provisioning 全量 120 项通过。
  - 验证：systemd --user 重启部署后实测 `ws://192.168.3.41:8090/terminal/ws` 命令回显/窗口缩放/Ctrl-C/shell 退出通知全通；Playwright 无头浏览器对车上真实页面 E2E 九项全过（默认选中 Serial、选项顺序 serial→web、终端 iframe 自动加载并挂载 xterm、键入命令真实执行回显、切换 Web 恢复日志视图、localStorage 记住选择且刷新后恢复）。
  - 配套固件改动在 Firmware 仓库（PR #56，v1.7.72）：cmdTarget 恢复 Serial 选项（第一位、默认、记忆），选中后日志区切换为该终端 iframe。
  - 涉及文件：`donkeycar/launcher/terminal.py`、`donkeycar/launcher/terminal_static/`（index.html/xterm.js/xterm.css/addon-fit.js）、`donkeycar/launcher/server.py`、`donkeycar/tests/test_launcher_terminal.py`

## 2026-08-14 (19)

- feat(web_ui): DonkeyDrifter 手机版标题区三行布局——版本号常驻可见，进入按钮/主题/语言移入标题区
  - 背景：手机版（<lg）此前把版本号、进入按钮、主题/语言切换全部收进汉堡菜单，不展开菜单就看不到版本号。
  - `Layout.tsx`：手机版标题区改为三行——第一行 logo+标题、GitHub 图标紧跟标题右侧、版本号在 GitHub 右边（菜单收起也常驻），右端仅汉堡按钮；第二行进入按钮（DrifterConsole 在左；与当日 (18) 合并后 Donkey 键已删除，右侧为"打开 Kimi Code Web"占位键）；第三行左边浅色/跟随系统/深色切换、右边中文/English 切换。汉堡菜单展开后仅保留 5 个导航项（版本号/按钮/切换全部移出）。桌面版（≥lg）布局与按钮顺序零改动。
  - `EnterButtons.tsx`：新增 `consoleFirst` 属性，仅手机版标题区使用；桌面端默认顺序不变。（与当日 (18) 合并后 `consoleFirst` 语义以 (18) 为准：交换 kimi/console）
  - `SidePanel.tsx`：左侧 Loaders/Connectors 抽屉为 fixed 定位、顶部偏移原写死 top-16（64px，对应单行顶栏），三行标题区（实测 135px）把抽屉顶部约 70px 压进 sticky 顶栏下方被遮挡；改为手机版 `top-[143px]`（135px+8px 间距）、高度 `calc(100vh-143px)`，≥lg 保持 top-16 不变。
  - 测试同步：`EnterButtons.test.tsx` 补 2 项顺序断言，该文件共 6 项通过（与当日 (18) 合并后以 Tony 侧重写版 6 例为准）。
  - 验证：`tsc -b --noEmit` 零错误；vitest 全量 77/77 通过；Playwright 390px 手机视口（菜单开/关）与 1400px 桌面视口截图确认——手机版符合目标布局、桌面版零变化、抽屉下移后 Loaders 不再被遮挡。
  - 涉及文件：`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/EnterButtons.test.tsx`、`web_ui/frontend/src/components/SidePanel.tsx`

- fix(web_ui): 恢复被 main 合线（3a57408f）回退的主题回退逻辑
  - 根因：6b7e39bf（主题默认改回跟随系统）的三处改动在 main 合回 Tony 的 merge（3a57408f）中被旧版本覆盖回退——`theme.ts` `readStoredTheme()` catch 分支（localStorage 异常时）变回 `return 'dark'`、`ThemeSwitcher.test.tsx` 两处断言（默认态用例标题、非法存储值回退"深色"）。实现与测试互相矛盾，导致 `falls back to 深色 for unknown stored values` 在 Tony 上持续红（76/77）。
  - 修复：恢复 6b7e39bf 语义——catch 回退 `'system'`、非法存储值断言改回"跟随系统"、默认态用例标题改回"跟随系统 active by default"。`index.html` 首屏脚本与 launcher `server.py` 三处默认值未被回退，无需改动。
  - 验证：vitest 全量 77/77 通过。
  - 涉及文件：`web_ui/frontend/src/lib/theme.ts`、`web_ui/frontend/src/components/ThemeSwitcher.test.tsx`

## 2026-08-14 (18)

- feat(web_ui): 头部入口按钮——删除"打开 Donkey"，新增"打开 Kimi Code Web"占位键，"进入"改名"打开"
  - EnterButtons 组件移除 Donkey 按钮及 enterDonkey 跳转逻辑，i18n 删除 `common.enterButtons.donkey` / `donkeyTitle` 键。
  - 新增"打开 Kimi Code Web"占位按钮（功能预留，无 onClick/跳转）：桌面版头部排在"打开 DrifterConsole"左侧；手机版汉堡菜单内（`<EnterButtons consoleFirst />`）排在其右侧——`consoleFirst` 语义由交换 donkey/console 改为交换 kimi/console。
  - 按钮文案"进入 DrifterConsole"→"打开 DrifterConsole"（zh），"Enter DrifterConsole"→"Open DrifterConsole"（en），其余词条不变。
  - 测试：`EnterButtons.test.tsx` 重写为 6 例（双键渲染、桌面默认顺序、手机 consoleFirst 顺序、Kimi 占位点击无动作、DC 扫描成功新开标签、扫描失败 alert），vitest 6/6 通过；全量 77 例中唯一失败的 ThemeSwitcher 用例为 Tony 基线被 main 合线回退的既有问题（另一会话修复中），与本次无关。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`web_ui/frontend/src/components/EnterButtons.test.tsx`

## 2026-08-14 (17)

- feat(launcher): Donkey 菜单页手机版顶栏两行布局 + 英文版菜单标题对齐修复
  - 手机版（≤640px）顶栏改为两行：第一行与电脑版完全一致（logo 图标 → Donkey 标题 → GitHub 图标 → 版本号），第二行最左为浅色/跟随系统/深色切换键、最右为中文/English 切换键；实现为新增仅手机端显示的 `.headerBreak` 换行元素 + `@media (max-width:640px)` 内 `#themeTabs{margin-left:0}` / `#langTabs{margin-left:auto}`，桌面端布局零改动。
  - 英文版菜单 0/1 号标题（Drifter Console / Create Car）错位修复：根源是英文分类标签 Manage/Data/Drive/Filter/Train 宽度不一，中文版二字标签天然等宽无此问题；新增 `html[lang="en"] .catPill{width:70px;justify-content:center}` 仅对英文版固定分类 pill 等宽，中文版像素级不变，电脑版与手机版同效。
  - 验证：`py_compile` 通过；8091 临时实例 + Playwright 实测——英文版 0/1/2 号标题 x 坐标均为 162（修复前错位），中文版保持 137.1 不变；手机端 390px 下主题键 x=12（最左）、语言键 x=270（贴右边框）；桌面端顶栏仍为单行。中英文 × 桌面/手机四种组合截图确认。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (16)

- fix(launcher): systemd 单元改 `KillMode=process`，launcher 重启不再连坐杀死 drive 进程
  - 根因：`donkeydrifter-launcher.service` 此前用默认 `KillMode=control-group`，每次停止/重启 launcher（部署新代码、手工 restart）都会按 cgroup 整体回收，把经 launcher 启动的 `donkey web`（后端 8100 + 前端 5188）与 `manage.py drive` 一并杀掉，正在使用的 DonkeyDrifter 驾驶界面随即掉线且不会自动恢复（launcher 无重启后自动重拉 drive 的逻辑）；且 `manage.py drive` 的 WS 重连循环会拖住 SIGTERM，导致 stop 触发 90s 超时报 `Failed with result 'timeout'`。今日 17:05/17:29/17:47 三次重启均复现"进不去 DonkeyDrifter"。
  - 修复：`donkeycar/launcher/donkeydrifter-launcher.service` 新增 `KillMode=process`——停止/重启只向 launcher 主进程发信号，drive 子进程继续存活；下次 `POST /api/launch/drive` 仍按 `~/.donkeycar/drive.pid` 先杀旧进程再启动，不累积孤儿。顺带消除 stop 超时（不再等子进程退出）。
  - 已同步本机已安装单元 `~/.config/systemd/user/donkeydrifter-launcher.service` 并 `systemctl --user daemon-reload`（无需重启服务，下次 stop/restart 即生效）；实机验证：daemon-reload 后 `systemctl --user restart`，8090 数秒内恢复，`manage.py drive`（8100）与 vite（5188）进程全程存活、页面持续 200。
  - 测试：新增 `tests/test_launcher_service_unit.py`（断言 `KillMode=process`、保留 `Restart=always`、无 `control-group` 回退、unit 基本形态不变）。
  - 涉及文件：`donkeycar/launcher/donkeydrifter-launcher.service`、`tests/test_launcher_service_unit.py`（新增）

## 2026-08-14 (15)

- feat(web_ui): UI 语言首访自动跟随浏览器语言
  - `web_ui/frontend/src/i18n/index.tsx` 初始化顺序改为：localStorage 已存选择优先，无存则读取 `navigator.language`——`zh` 开头（zh-CN/zh-TW 等）用中文，其余一律英文；自动检测结果不落盘，仅用户手动切换时写入 localStorage `donkeydrifter.ui.lang` 并在后续访问优先生效（关机/重启后仍记住手动选择）。
  - 测试同步：`LanguageSwitcher.test.tsx` 扩为 5 项（中文浏览器默认中文、英文浏览器首访自动英文且不落盘、点击切换并持久化、恢复已存选择、已存选择优先于浏览器语言），新增 `setBrowserLanguage` mock 辅助；`FabActions.test.tsx` 默认中文用例补浏览器语言 mock 保持确定性。
  - 验证：`tsc -b --noEmit` 零错误、`vitest` 14 个文件 75/75 通过、`npm run build` 成功。
  - 涉及文件：`web_ui/frontend/src/i18n/index.tsx`、`web_ui/frontend/src/components/LanguageSwitcher.test.tsx`、`web_ui/frontend/src/components/FabActions.test.tsx`

## 2026-08-14 (14)

- fix(launcher,provisioning): 修复 Drifter Console 上看不到上位机 IP
  - 根因①：launcher 常驻 HOSTIP 上报（`server.py` `_report_hostip_to_esp32`，30s 周期）候选端口仅 `/dev/ttyACM0/1`、`/dev/ttyUSB0`，不覆盖本车 ESP32 配网串口 `/dev/ttyS6`（UART 直连），一个都不命中等于从没发过；且裸 `open()` 不配置 termios，按端口残留波特率（默认 9600）发送，固件 115200 收到全乱码。
  - 根因②：ModemManager 会探测 `ID_MM_CANDIDATE=1` 的串口并篡改 termios（实测车上 `/dev/ttyS6` 在 `manage.py` 持有期间被从 115200 改成 9600），`ProvisioningPart` 只在打开时配置一次，被篡改后持续乱码，HOSTIP 帧固件无法解析。
  - 修复：`server.py` 候选端口补 `/dev/ttyS6` 置顶；改为每次发送前 open → tcsetattr 115200 8N1（CLOCAL|CREAD、关 ONLCR 输出翻译）→ write → tcdrain → close，被篡改下一周期自愈；IP 探测由 `hostname -I` 简易解析换用 `provisioning.detect_lan_ip()`（VPN/TUN 感知，与配网模块同一逻辑）。`provisioning.py` `_write_line()` 独立串口模式发送前重新断言波特率（Arduino 共享串口不动，由 actuator 管理）。
  - 测试：新增 `donkeycar/tests/test_launcher_hostip.py` 11 例（端口优先级与回退、115200/8N1 标志位断言、无 IP 不触碰串口、端口全灭静默、写失败换口、无 termios 平台回退）；`test_provisioning.py` 补 2 例（独立模式重设波特率、Arduino 共享模式不动波特率）。
  - 验证：本地 pytest 相关 106 项通过；实机调用修复版上报后 ESP32 `/api/status` 出现 `host_ip=192.168.3.41`（本机 IP）；分支 CI 全绿。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/parts/provisioning.py`、`donkeycar/tests/test_launcher_hostip.py`（新增）、`donkeycar/tests/test_provisioning.py`

- test(tui): 同步菜单名大写排版改动，修复 Tony CI 红
  - #88 把菜单功能名改为首字母大写（"drive"→"Drive"）后漏改 `test_main_menu_sixth_item_is_drive_page` 期望，Tony 主干 CI 持续红；期望值修正为 "Drive"。
  - 涉及文件：`donkeycar/tests/test_tui_menu.py`

## 2026-08-14 (13)

- feat(web_ui,launcher): 三端主题默认由深色改回"跟随系统"（DonkeyDrifter web_ui + Donkey launcher；Drifter Console 见 Firmware v1.7.67 / Firmware#49）
  - `web_ui/frontend/src/lib/theme.ts`：`readStoredTheme()` 无存储或存储值非法时回退由 `'dark'` 改回 `'system'`（跟随系统）；用户显式点选浅色/深色后仍以存储值为准。
  - `web_ui/frontend/index.html`：首屏防闪烁脚本默认改为 `'system'`，经 `matchMedia('(prefers-color-scheme: dark)')` 解析，matchMedia 不可用时回退深色。
  - `donkeycar/launcher/server.py`：三处默认值同步——首屏内联脚本（无存储/非法值一律 matchMedia 解析）、`let uiTheme = 'system'`、`initTheme()` 兜底 `stored = 'system'`。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：默认态断言同步翻转（默认激活"跟随系统"、默认跟随系统主题变化、非法存储值回退"跟随系统"）。
  - 验证：vitest 全量 73 项通过；Playwright 实测全新浏览器（无任何存储）系统浅色 → `theme-light`、系统深色 → `theme-mus4`，切换键激活态为"跟随系统"。

## 2026-08-14 (12)

- feat(launcher): 菜单页与启动中转页语言跟随浏览器自动检测
  - `donkeycar/launcher/server.py` 菜单页（MENU_HTML）：新增 `detectBrowserLanguage()`（`navigator.language` 小写后以 `zh` 开头→中文，其余一律→英文，异常兜底中文）；`readStoredLanguage()` 改为 localStorage `donkeydrifter.ui.lang` 显式选择优先、无存储时回退浏览器检测（原先无存储时硬编码中文）。用户手动切换仍写 localStorage 持久化、跨重启优先于自动检测——与 DD web_ui（Tony-webui-lang-autodetect 在制）和 DC 固件 v1.7.66 同一语义。
  - 启动中转页 `LAUNCH_DRIVE_HTML` 补自包含中英 i18n：经同一 localStorage 键读取显式选择、无存储跟随浏览器；「正在启动/启动失败/未知错误/网络错误」四条文案双语化并全部经 `t()` 渲染，`<html lang>` 动态设置。
  - 测试同步：新增 `tests/test_launcher_language_autodetect.py` 2 项（菜单页检测接线与回退语义、中转页双语字典对齐及 `t()` 全覆盖、无残留硬编码中文）。
  - 验证：新增 2 项 pytest 通过；临时实例（127.0.0.1:18090）实测 `/` 与 `/launch/drive` 均正确下发新代码；两页全部 `<script>` 块经 `node --check` 语法校验通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`tests/test_launcher_language_autodetect.py`

## 2026-08-14 (11)

- feat(web_ui): 手机版/竖屏平板响应式适配（<1024px 与手机一致）
  - 根因修复：`index.html` viewport 由写死 `width=520` 改为 `width=device-width`；`index.css` 删除 `html,body,#root` 的 `min-width: 520px`（此前手机一律按 520px 排版再整体缩小，"显示不全"即由此而来）。
  - 页头（`Layout.tsx`）：<lg 改为汉堡菜单——logo+标题常驻，右侧仅保留 GitHub 图标与汉堡按钮；菜单面板内含 5 个导航项、"进入 Donkey"/"进入 DrifterConsole"按钮、主题/语言切换、版本徽章，路由切换自动收起。≥lg 桌面布局不变（与旧版构建同宽度截图逐像素比对一致）。新增 i18n 词条 `common.nav.menu`（中「菜单」/英 "Menu"）。
  - Drive 页：顶部工具栏（输入源/模式/模型/录制/计数）改 `flex-wrap` 允许换行。
  - SidePanel 抽屉：打开宽度由固定 `w-96` 改为 `min(24rem, 100vw-3.5rem)`，窄屏下触发按钮不再被推出屏外。
  - 网格与小布局：Trainer 标题行补 `flex-wrap`；LocalConfigForm/RemoteConfigForm/CarConnectorPage 共 5 处无前缀 `grid-cols-2` 改 `grid-cols-1 lg:grid-cols-2`；CarConnectorPage 任务日志长行补 `break-all`；PilotArena 当前数据卡片 `md:grid-cols-3`→`lg:` 并补 `min-w-0 break-all` 防长路径撑破；TubNavigator 图像区 `md:`→`lg:`、首尾帧按钮组 `grid-cols-4`→`grid-cols-2 lg:grid-cols-4`；TubEditor 工具条补 `flex-wrap`。
  - 验证：vitest 全量 73 项通过；`npm run build`（tsc+vite）通过；Playwright 实测 390×844（手机）/768×1024（竖屏平板）/1280×800（桌面）× 5 个路由共 15 组全部零横向溢出；dist 已部署 8100 供手机浏览器实测。
  - 涉及文件：`web_ui/frontend/index.html`、`web_ui/frontend/src/index.css`、`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/components/SidePanel.tsx`、`web_ui/frontend/src/components/TubEditor.tsx`、`web_ui/frontend/src/components/TubNavigator.tsx`、`web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`、`web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`web_ui/frontend/src/pages/CarConnectorPage.tsx`、`web_ui/frontend/src/pages/DrivePage.tsx`、`web_ui/frontend/src/pages/PilotArenaPage.tsx`、`web_ui/frontend/src/pages/TrainerPage.tsx`

## 2026-08-14 (10)

- feat(launcher): 菜单新增「Drifter Console」项（0 号置顶、常用），一键打开车上控制台
  - 新增 `donkeycar/launcher/dc_discovery.py`：Drifter Console 局域网发现模块。固件 v1.7.14 起默认禁用 mDNS/NetBIOS/LLMNR 名称发现（`DISABLE_WIFI_NAME_DISCOVERY`），无法依赖主机名，改为探测 `/api/status` 的 MUS4 特征字段（`version=`/`ap_ip=`）定位车辆：先探车辆 AP 固定地址 192.168.4.1，未命中再并行扫描本机所在 /24 网段（48 线程、单地址 0.6s 超时），结果缓存 60 秒。
  - `server.py` 新增 `POST /api/launch/dc` 返回 DC URL；menuItems 将 Drifter Console 编号 0 置顶（其余项编号不变）；键盘 0 由「返回上一页/关闭标签页」改为选中 0 号，删除 history.back()/window.close() 分支；帮助按键说明更新为数字键 0-10（中英 + HTML 兜底同步）。
  - `tui.py`「驾驶」分类新增 DrifterConsoleCommand（is_favorite=True，无需 mycar 目录），经同一发现模块定位后用默认浏览器打开；TUI 菜单编号不变（0 在 TUI 仍为退出）。
  - 验证：`POST /api/launch/dc` 实测 1.8s 返回 `http://192.168.3.46/`（`/api/status` 确认为车上 MUS4 v1.7.66）；Playwright 实测点击 0 号/按 0 键跳转 DC、按 1,0 选中 10 号；截图确认 0 号置顶排版。
  - 涉及文件：`donkeycar/launcher/dc_discovery.py`（新增）、`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

- feat(launcher): 菜单功能名排版改为首字母大写、空格分词
  - 规则：每个单词首字母大写，单词间用空格连接不再用下划线；"UI" 两字母全大写。11 项依次为 Create Car / Open / Clear Data / Backup Data / Restore Data / Drive / Drifter Console / Web / Donkey UI / Train Local / Train Online；网页菜单与 TUI 命令显示名同步修改。
  - 注：TUI 参数历史以功能名为键，改名后对应功能的历史参数会重置一次。
  - 验证：临时实例 + Playwright 截图实测 11 项名称渲染正确；TUI 菜单列表逐项核对一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

## 2026-08-14 (9)

- feat(launcher): CWD 栏标签改为双语全称，不再用缩写
  - 中文由 "CWD" 改为「当前工作目录」，英文改为 "Current Working Directory"（i18n 词条 `cwd.label`）。
  - 验证：本机测试实例 + Playwright 截图实测中/英文显示正确。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(launcher): 删除页头 "DonkeyDrifter Web Launcher" 文字
  - 页头仅保留 logo + Donkey 标题 + GitHub 图标 + 版本徽章，右侧副标题文字及其 i18n 词条移除。
  - 验证：本机测试实例 + Playwright 截图实测页头渲染正常。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(launcher): 调整菜单常用项标记：去掉 createcar/clear_data，新增 donkey_ui/train_local
  - 网页菜单（`launcher/server.py` menuItems）：1 号 createcar、3 号 clear_data 的 favorite 改为 false；8 号 donkey_ui、9 号 train_local 改为 true；现常用项为 6/7/8/9/10（drive、web、donkey_ui、train_local、train_online）。
  - 终端 TUI（`management/tui.py`）对应 Command 的 is_favorite 同步修改，与网页菜单保持一致。
  - 验证：本机临时实例（8091）+ Playwright 截图实测菜单徽标渲染正确；8090 重启后抽查页面内容一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

- feat(launcher): 精简帮助弹窗内容
  - 键盘操作分区删除「?：显示此帮助信息」「0：返回上一页」「ESC：关闭弹窗」三条（仅删帮助文案，键盘实际功能未动）。
  - 删除「说明」分区及其唯一一条「目前仅支持通过浏览器启动「驾驶」功能（选项 6）」；中英文 i18n 词条同步移除。
  - 帮助弹窗现仅保留「键盘操作」分区下数字键 1-10 选菜单一条。
  - 验证：本机临时实例 + Playwright 截图实测帮助弹窗渲染正确；8090 重启后线上页面无残留词条。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (8)

- feat(web_ui,launcher): 主题默认改为深色，"跟随系统"仅在用户显式点选后生效
  - 按用户要求调整默认：此前 DD web_ui / D launcher 无持久化选择时默认"跟随系统"（首屏即按系统偏好渲染）；现默认深色，matchMedia 系统主题解析与变化监听仅在用户点选"跟随系统"后才生效。DC（Drifter Console，Firmware 仓库）同款修改在同名分支 `Tony-theme-default-dark` 另行进行。
  - DD（web_ui）：`src/lib/theme.ts` `readStoredTheme()` 无存储或存储值非法时由回退 `'system'` 改为回退 `'dark'`（`'system'` 仍是合法持久化值）；`index.html` 首屏防闪烁内联脚本同步——无有效存储值直接取深色，仅存储值为 `'system'` 时才经 matchMedia 解析。
  - D（launcher）：`donkeycar/launcher/server.py` 三处默认由 `'system'` 改为 `'dark'`——首屏防闪烁内联脚本、`let uiTheme` 初值、`initTheme()` 的 stored 兜底值；两处注释同步更新。
  - 测试：`web_ui/frontend/src/components/ThemeSwitcher.test.tsx` 默认激活分段断言由"跟随系统"改为"深色"并补"默认挂载即应用 `theme-mus4` 皮肤"断言，未知存储值回退断言同步改为"深色"，新增"默认状态下系统主题变化不生效"用例；vitest 全量 73 项通过，`server.py` 通过 py_compile。
  - 涉及文件：`web_ui/frontend/src/lib/theme.ts`、`web_ui/frontend/index.html`、`web_ui/frontend/src/components/ThemeSwitcher.test.tsx`、`donkeycar/launcher/server.py`

## 2026-08-14 (7)

- feat(web_ui): 页头 "DonkeyDrifter" 标题左侧新增 logo 图标
  - 图标文件取自主目录 `logo.png`（经 MD5 比对与 Donkey 启动页 8090 的 `/favicon.png` 为同一文件），新增为 `web_ui/frontend/public/logo.png`，构建后随 dist 以 `/logo.png` 提供。
  - 样式对齐 Donkey 启动页 headerLogo：32×32（`w-8 h-8`）、`rounded-lg`(8px)、1px `#2b3441` 边框、与标题间距 12px（`gap-3`）、flex 垂直居中；页头高度与导航布局不变。
  - 验证：Playwright 实测 8100 实页深/浅双主题页头截图，图标显示与参考样式一致；`/logo.png` HTTP 200；`npm run build` 与 `vitest`（14 文件 72 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/public/logo.png`（新增）

## 2026-08-14 (6)

- fix(web_ui): 控制参数滑块 thumb 加宽对齐最初 Safari 原生尺寸（24×16px 纯白椭圆）
  - 用户反馈 14×12px 版本比"最初"小、比例不对：最初版本（d3349014）未自定义 thumb，其尺寸由浏览器原生渲染决定。本机实测 Firefox 153 原生为 ~16px 圆形、Linux WebKit(WPE) 为 18px 圆形，均与用户描述的"宽大于高的白色椭圆"不符；最终查 WebKit 源码 `RenderThemeCocoa.mm` 确认 Safari 原生 thumb 硬编码尺寸为 `kDefaultSliderThumbWidth=24` / `kDefaultSliderThumbHeight=16`，即 24×16px 白色椭圆，与用户描述的最初样式一致（高度 16≈15.4 被认可、宽度 24>18 补齐差距）。
  - thumb 由 14×12px 改为 `w-[24px] h-[16px]`（纯白不透明 rounded-full 椭圆形状不变），居中 margin 按公式 (轨道 6px − thumb 16px)/2 更新为 `-mt-[5px]`；轨道样式（6px 锌色）未动。
  - 验证：Playwright Chromium + WebKit 双引擎实测 8100 实页（深/浅双主题），thumb 精确渲染 24.00×16.00、纯白 (255,255,255) 不透明、与轨道垂直居中偏差 0.00px、轨道 6.00px 未变；`npm run build` 与 `vitest`（14 文件 72 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14 (5)

- feat(launcher): 常用项标注由 `[*]` 改为「常用」，删除帮助面板星号说明行
  - 菜单常用项徽标文字由 `[*]` 改为「常用」（英文「Common」），紫色徽标样式不变，经 i18n 词条 `menu.favorite` 随语言切换。
  - 帮助面板「说明」分组删除"带 [*] 标记的为常用功能"一行（中英文词条同步移除）。
  - 验证：本机测试实例 + Playwright 截图实测中/英文菜单徽标与帮助面板，无 JS 报错。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (4)

- feat(launcher): Donkey 菜单页接入 Drifter Console 全套控件、浅色主题与页头徽章
  - 右下角帮助小点：逐字复刻 DC 的 FAB 簇——18px 发光小点点击展开 🌐 语言球（向上）与 ? 帮助球（向左），帮助面板锚定右下角（× 关闭、点遮罩关闭），保留 ESC/? 键盘交互；原居中帮助弹窗移除。
  - 顶栏右侧新增 DC langTabs 胶囊分段控件：浅色/跟随系统/深色 三态主题 + 中文/English 语言切换。
  - 浅色主题整套配色对齐 DC/DD 浅色版（背景 `#eef1f5`、白渐变卡片、强调色 `#0c9bd6`、语义色浅色变体 绿 `#1fae6b`/琥珀 `#b57d0e`/红 `#e5484d`/紫 `#b14ae0`）；主题落 `<html data-theme>`，localStorage key `donkeydrifter.ui.theme`，"跟随系统"经 matchMedia 实时解析并监听；head 内联脚本防首屏闪烁。
  - i18n 走 `data-i18n` 属性扫描（textContent/aria-label/title），菜单项、分类 pill、帮助面板、启动遮罩文案全部双语；localStorage key `donkeydrifter.ui.lang`。
  - 页头 "DonkeyDrifter Web Launcher" 右侧新增 GitHub 图标（SVG 与 DD `GitHubLink.tsx` 逐字一致，新标签页打开 DonkeyDrift 仓库）与版本徽章（DD VersionBadge 样式，版本源与 DD 后端 `/api/config/version` 同为 `donkeycar._version.__version__`）；删除底部"输入编号选择功能，?帮助，0退出"提示行及其 CSS/i18n 词条。
  - 验证：本机测试实例 + Playwright 8 场景截图（深/浅 × 中/英、FAB 展开、帮助面板、语言菜单、跟随系统+浅色系统偏好）全部正确，页面无 JS 报错。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(launcher): 修复 Safari 标签页图标显示为首字符"1"而非头盔 logo
  - 根因（两层）：① Safari 固定标签页不用 PNG favicon，需专用 mask-icon（单色 SVG），缺失时按访问地址首字符显示符号（IP 访问显示"1"）；② 2026-08-14 (2) 为破 Chrome 缓存给图标链接加的 `?v=N` 查询串触发 WebKit 图标处理异常——日志显示 Safari 成功拉到图标（200）仍回退首字符符号，而 DD/DC 均为无参数 `/favicon.png` 且工作正常。
  - 修复：用 cv2 从 `logo.png` 描摹黑色头盔线条生成单色 mask-icon SVG（`fill-rule=evenodd` 保留镂空细节）；生成 180×180 `apple-touch-icon.png` 与多尺寸 `favicon.ico`（16/32/48）；`_serve_favicon` 泛化为 `_serve_icon` + `_ICON_FILES` 路由表（正确 Content-Type + 补 `Last-Modified`，与 Vite 行为一致）；所有图标链接去掉查询串与 DD/DC 对齐，取代 (2) 的 `?v=2` 方案。
  - 验证：本机测试实例四个图标 URL 均返回 200 与正确 Content-Type；SVG 描摹经浏览器放大渲染目检与原 logo 一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.svg`（新增）、`donkeycar/launcher/donkey_touch_icon.png`（新增）、`donkeycar/launcher/donkey_favicon.ico`（新增）

## 2026-08-14 (3)

- fix(launcher): Donkey 菜单页容器去掉 900px 限宽，全宽贴合浏览器两边
  - 问题：`MENU_HTML` 的 `.container` 原为 `max-width:900px; margin:0 auto`，宽屏浏览器下页面左右两侧大片空白，与 DonkeyDrifter / Drifter Console 随浏览器宽度贴合两边的全宽设计语言不一致。
  - 修复：`.container` 改为 `width:100%; margin:0`，页头、CWD 栏、菜单面板、底部提示随浏览器宽度整行铺满（保留 body 12px 边距）。
  - 验证：本机 8091 端口测试实例 + Playwright 截图实测，1920px 宽屏下菜单整行铺满到两边，800px 窄视口下排版正常无溢出。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (2)

- fix(launcher): 修复 Donkey 页浏览器标签页 favicon 不显示 + 页头新增 logo 图标
  - 根因：浏览器将早期"该页无图标"的状态缓存在本地 favicon 数据库中（重启系统不会清除），导致服务端虽已正确提供图标，标签页仍不显示。
  - 修复：两处 HTML 模板（`MENU_HTML`、`LAUNCH_DRIVE_HTML`）的 favicon 链接改为 `/favicon.png?v=2`，URL 变化强制浏览器重新拉取，绕过旧缓存；favicon 响应增加 `Cache-Control: no-cache`。
  - 新增 `/favicon.ico` 路由，与 `/favicon.png` 共用同一 PNG（即 projects 主文件夹的头盔 logo，MD5 `82ddb5cf…`）。
  - 菜单页页头 Donkey 标题左侧新增 32px 可见 logo（`.headerLogo`，复用 `/favicon.png`），圆角描边样式与菜单序号徽标一致。
  - 验证：本地测试实例实测页面输出正确、`/favicon.png?v=2` 与 `/favicon.ico` 均返回 200 且字节与 logo.png 一致。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(web_ui): 滑块恢复为 #47 用户确认的 14×12px 纯白椭圆 thumb（撤销 #71 的原生回退）
  - 用户确认"最初的椭圆形"= #47 的自定义纯白椭圆（14×12px rounded-full）；#71 按字面恢复 pre-#43 原生 thumb 后在 Chrome 渲染为半透明圆环（可见轨道），非用户所要。
  - 恢复 #68 状态：`h-3 bg-transparent` + 轨道伪元素 `h-1.5 mt-[3px]` + thumb `w-[14px] h-[12px] bg-white rounded-full border-none -mt-[3px]`（居中公式 (6−12)/2=−3px）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14

- fix(web_ui): 控制参数滑块恢复最初的原生样式（用户指示"直接复制最初的白色小点和轨道"）
  - ParamSlider 的 input 恢复为最初未改动版本：`w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer`（input 自身即轨道，thumb 完全原生渲染），移除全部 `::-webkit-slider-thumb` / `::-webkit-slider-runnable-track` 等伪元素自定义样式。
  - 与最初版本唯一差别：`accent-cyan-500` → `accent-white`，保证任何浏览器下 thumb 都是纯白（Safari 下两者均渲染为白色原生椭圆）。
  - 实测（Playwright Chromium + WebKit）：该布局下原生 thumb 与轨道中心偏差 0.0px，无白色背景条（input 背景已被 bg-zinc-800 覆盖），thumb 渲染在轨道之上。
  - 验证：`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

- fix(web_ui): 滑块 input 补 `bg-transparent`，消除白色背景条（用户所见"第三根线"）
  - 根因（实测验证）：Chrome/Safari 对 `appearance:none` 的 range input 默认绘制**白色背景**，上一版把 input 高度从 6px 改为 12px 且未覆盖背景后，深色面板上出现一条 12px 白色横条，轨道嵌在其中，视觉上成了"三根线"，白色 thumb 叠在白条上也难以辨认形状。
  - 修复：input 增加 `bg-transparent`；thumb 保持 `w-[14px] h-[12px]` 纯白椭圆（即 #47 用户认可的"最开始的椭圆形"尺寸）不变。
  - 验证：Playwright Chromium + WebKit 双引擎截图对比，加 `bg-transparent` 后白色横条消失，只剩锌色轨道（原始"两根线"观感）+ 居中白色椭圆 thumb；`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14 (1)

- feat(web_ui): 新增 MUS4 Light 浅色皮肤并接入主题切换(切换按钮 47ee39fb 随本分支一并合入)
  - 新皮肤 `web_ui/frontend/src/themes/theme-light.css`:与深色皮肤 `theme-mus4.css` 同源同构,以 `html.theme-light` 前缀覆盖 Tailwind 工具类;色板直接对标固件自带浅色主题(`Firmware/MUS4_FW/libraries/mus4_web/src/WebConsoleAssets.h` 的 `html[data-theme="light"]` 与 `CHART_THEMES.light`)——页面 `#eef1f5`、面板 `#fff` + `135deg #fff→#edf1f6` 渐变 + 细框 `#ccd5df`,状态文字/细框/图表线用固件浅色饱和色(蓝 `#0c9bd6`、绿 `#1fae6b`、红 `#e5484d`、琥珀 `#d99a17`),FILL 实色填充语言(蓝 `#5cc8ff` 等 + 近黑文字 `#061019`)保持不变;深色皮肤所有颜色逐字节未动。
  - 主题设施 `web_ui/frontend/src/lib/theme.ts`:localStorage 持久化(key `donkeydrifter.ui.theme`)、`<html>` 皮肤 class 切换、`useResolvedTheme()` 订阅钩子(canvas/图表配色用);`web_ui/frontend/index.html` 内联脚本首屏前应用主题防闪烁(跟随系统经 matchMedia 解析);`web_ui/frontend/src/components/ThemeSwitcher.tsx` 接入真实切换;"跟随系统"经 `matchMedia('(prefers-color-scheme: dark)')` 实时解析并监听系统主题变化自动跟随。
  - canvas/图表/内联样式/Tailwind 任意值类等皮肤 CSS 覆盖不到的 JS 配色全部改为主题感知(深色值逐字节保留在三元分支中):`drive/TelemetryChart.tsx`、`TubEditor.tsx`、`pages/PilotArenaPage.tsx`、`FabActions.tsx`、`EnterButtons.tsx`、`drive/DriveModeSelector.tsx`、`drive/ModelSelector.tsx`、`drive/InputSourceSelector.tsx`、`drive/VideoStream.tsx`、`TubNavigator.tsx`、`ui/Button.tsx`。
  - 测试同步:`ThemeSwitcher.test.tsx` 新增皮肤 class 应用/挂载恢复/跟随系统解析/系统主题实时跟随等 7 个用例;`drive/DriveModeSelector.test.tsx` 新增浅色配色切换用例;vitest 全量 14 文件 72 用例通过,`tsc -b` 与 `vite build` 通过,Playwright 5 页 × 深浅双主题截图复核。
  - `theme-mus4.css` 仅更新文件头注释(皮肤机制说明),无样式改动。

## 2026-08-12 (13)

- fix(web_ui): 滑块 thumb 改为 14×12px 纯白椭圆并精确垂直居中于轨道
  - 根因（实测验证）：WebKit/Blink 在轨道被自定义样式后，将原生 thumb 的**顶边对齐轨道顶边**，导致 thumb 中心比轨道中心低 (thumb高−轨道高)/2（Chromium 实测偏下 4.9px，WebKit 实测偏下 6.9px），上一版仅靠 `h-3` + 轨道 `mt-[3px]` 无法修正。
  - 修复：thumb 用自定义样式 `w-[14px] h-[12px] bg-white rounded-full border-none`（横向椭圆，与 Safari/macOS 原生 thumb 形状一致，纯白不透明完全遮挡轨道），居中 margin 按公式计算：`margin-top = (轨道高 6px − thumb 高 12px) / 2 = -3px`，非试凑值。
  - 验证：Playwright Chromium + WebKit 双引擎截图像素级测量，thumb 中心与轨道中心偏差均为 0.0px；`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (12)

- fix(web_ui): 滑块 thumb 垂直居中于轨道
  - input 高度从 `h-1.5`（6px）改为 `h-3`（12px）容纳原生 thumb；轨道仍 `h-1.5`（6px）但加 `mt-[3px]` 在 12px 空间中垂直居中，thumb 原生渲染（`accent-white`）在 12px 空间中自然居中于轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (11)

- fix(web_ui): 滑块 thumb 恢复原生渲染，仅将轨道移到独立伪元素层
  - 移除全部自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（多轮尝试均未匹配原生形状/大小）。
  - 保留 `accent-white`（原生 thumb：形状/大小/位置完全不变，纯白色）。
  - 轨道样式从 input 背景移到 `::-webkit-slider-runnable-track` / `::-moz-range-track` 伪元素，确保轨道画在 thumb 下方而非覆盖其上。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (10)

- fix(web_ui): 滑块 thumb 宽度从 16px 缩至 14px（w-4 → w-3.5），高度/位置不变
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (9)

- fix(web_ui): 滑块 thumb 改为 16×12px 椭圆形匹配 Safari 原生渲染
  - PR #55 的 `w-3 h-3`（12×12px）是正圆形，且不加 margin 在 Safari 中位置不对。
  - 用户浏览器（Safari/macOS）原生 thumb 是椭圆形（宽大于高），改为 `w-4 h-3`（16×12px）+ `rounded-full`（椭圆）+ `-mt-[3px]`（垂直居中：(12-6)/2=3px）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (8)

- feat(launcher): Donkey 菜单页采用 Drifter Console 设计语言
  - `MENU_HTML` 完全重写为 DC 暗色仪表盘风格：背景 `#101318`、`system-ui` 字体、DC headerRow（h1 "Donkey" + version 副标题）、DC panel（`#171c24` bg + `#2b3441` border）、菜单项从 table 改为 DC state card（`linear-gradient` + `#344154` border）、分类标签用 DC 语义色 pill（管理=cyan, 数据=green, 驾驶=amber, 筛选=purple, 训练=red）、编号用 Consolas monospace cyan 徽章、DC reconnect overlay、DC dialog 风格帮助弹窗。
  - `LAUNCH_DRIVE_HTML`：`<title>` 改为 "Donkey"，添加 favicon link。
  - `do_GET` 新增 `/favicon.png` 路由 + `_serve_favicon()` 方法。
  - 新增 `donkeycar/launcher/donkey_favicon.png`：使用 projects 原有头盔 PNG 图标（与 `287205692.png` 一致）。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.png`

## 2026-08-12 (7)

- fix(web_ui): 修正滑块 thumb 尺寸为 12×12px 匹配原生渲染
  - PR #53 的 `w-3 h-2`（12×8px）尺寸过小且加了不必要的 `-mt-px` 偏移，与原生 thumb 形状不符。
  - 通过 Playwright 截图对比确认：原生 thumb 约 12px 圆形、Chrome 在 `appearance: none` 下自动居中、无需手动 margin。
  - 本次改为 `w-3 h-3 rounded-full bg-white border-none`，不加 margin，与原生渲染尺寸/位置/形状一致。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (6)

- fix(web_ui): 修复滑块 thumb 无法遮挡轨道的问题（渲染层级分离）
  - 问题根因：`bg-zinc-800` 直接画在 `<input>` 元素背景上，可能与原生 thumb 的渲染层级冲突，导致轨道穿透 thumb 显示。
  - 将轨道样式从 input 背景移到 `::-webkit-slider-runnable-track` / `::-moz-range-track` 伪元素，确保轨道作为独立层绘制在 thumb 下方。
  - thumb 使用自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb`：`w-3 h-2 rounded-full bg-white border-none -mt-px`（12×8px 椭圆形、垂直居中、纯白不透明），完全遮挡下方 6px 轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (5)

- fix(launcher): 菜单页检测 `#drive` hash 自动启动 DonkeyDrifter
  - Drifter Console 固件 v1.7.62 起，"进入 DonkeyDrifter"按钮改为 `<a href="http://<ip>:8090/#drive" target="_blank">`，与"进入 Donkey"使用相同的 `/` 路径（仅 hash 不同），规避 Safari 无法加载 `/launch/drive` 的问题。
  - `donkeycar/launcher/server.py`：`MENU_HTML` 初始化代码检测 `location.hash === '#drive'`，自动调用 `launchDrive()` 启动驾驶。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(web_ui): 添加进入 Donkey 和进入 DrifterConsole 按钮
  - 新增 `EnterButtons` 组件，样式与 Drifter Console 的 otaButton 一致。
  - 进入 Donkey：打开 `http://<host>:8090/` Launcher。
  - 进入 DrifterConsole：扫描局域网 ESP32 设备并打开 Web Console。
  - 后端新增 `/connector/discover_console` 端点。
  - 布局：GitHub 图标右侧、语言切换键左侧。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`、`EnterButtons.test.tsx`、`Layout.tsx`、`i18n/messages/common.ts`、`services/api.ts`、`web_ui/backend/routers/connector.py`、`web_ui/backend/tests/test_connector.py`

- feat(launcher): Donkey 菜单页采用 Drifter Console 设计语言
  - `MENU_HTML` 完全重写为 DC 暗色仪表盘风格：DC panel + state card 菜单项 + 语义色 pill 分类标签 + DC reconnect overlay + DC dialog 帮助弹窗。
  - `LAUNCH_DRIVE_HTML`：title 改为 Donkey，添加 favicon link。
  - `do_GET` 新增 `/favicon.png` 路由 + `_serve_favicon()` 方法。
  - 新增 `donkey_favicon.png`（200×200 cyan D 图标）。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.png`

## 2026-08-12 (4)

- fix(web_ui): 控制参数滑块拖拽点改为纯白色（仅改颜色，不改形状）
  - 移除 PR #47 添加的全部自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（改变了原生椭圆形），改为 `accent-white`：浏览器原生渲染形状完全不变，仅将 accent-color 从 `#5cc8ff`（MUS4 主题覆写后的 accent-cyan-500）改为 `#ffffff` 纯白。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (3)

- fix(web_ui): 控制参数滑块拖拽点改为纯白不透明椭圆形
  - 上一版（#45）恢复 `accent-cyan-500` 浏览器原生渲染后，原生 thumb 仍透出下方深色轨道。
  - 本次使用自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式：`w-3.5 h-3 rounded-full bg-white`，椭圆形（14×12px）、垂直居中（无 `-mt-1` 偏移）、纯白不透明，完全遮挡下方轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (2)

- fix(launcher): `/launch/drive` 跳转页等待 vite 就绪后再重定向
  - 背景：POST `/api/launch/drive` 启动 `donkey web`（vite 开发服务器）时会先杀旧进程再启新进程，POST 立即返回后页面立即重定向到端口 5188，但新 vite 需数秒才就绪，导致 Safari 显示"无法连接服务器"。
  - `donkeycar/launcher/server.py`：`LAUNCH_DRIVE_HTML` 的 JS 改为先轮询前端 URL（`fetch` + `mode:'no-cors'`，最多 30 次 × 1s = 30s），就绪后再 `window.location.href` 跳转；等待期间显示进度计数器 `(N/30)`。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(web_ui): 恢复 Drive 页面控制参数滑块为浏览器原生样式
  - 上一版（#43）为滑块添加了自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（`w-3.5 h-3.5 rounded-full -mt-1 shadow-[0_0_0_2px_#09090b]`），导致拖拽点由原生椭圆形变成正圆形、垂直方向偏上、且 shadow 环仍透出轨道。
  - 本次移除全部自定义 thumb 样式，恢复为 `accent-cyan-500` 浏览器原生渲染：拖拽点恢复为椭圆形、垂直居中、完全不透明（看不到下方轨道）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-11 (10)

- fix(web_ui): Drive 页面控制参数面板三个显示问题修复
  - 滑块拖拽点透出轨道：白色拖拽点（`::-webkit-slider-thumb` / `::-moz-range-thumb`）添加 `shadow-[0_0_0_2px_#09090b]`，用面板背景色（zinc-950）在拖拽点周围生成 2px 实心环，遮住背后深色轨道（zinc-800），拖拽点保持纯白。
  - "重置默认"按钮文字换行：ParameterPanel 宽度从 `max-w-[320px]` 加宽到 `max-w-[360px]`（内边距 `px-3` 不变，按钮到边框距离不变）；三个按钮文本各自包裹 `<span className="whitespace-nowrap">` 双重保险防止换行。
  - 导出/导入图标大小不一致：三个图标（RotateCcw / Download / Upload）从 Tailwind `w-3 h-3` 类改为 lucide-react `size={12}` prop，统一尺寸设置方式。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`、`web_ui/frontend/src/pages/DrivePage.tsx`

## 2026-08-11 (9)

- feat(launcher): 新增 GET `/launch/drive` 端点，返回极简跳转 HTML 页面
  - 背景：Drifter Console（ESP32 Web Console）的"进入 DonkeyDrifter"按钮原先用 `location.href` 导航到 POST-only 的 `/api/launch/drive`，GET 请求返回 404；且跨域 fetch 会被浏览器 CORS 拦截。
  - `donkeycar/launcher/server.py`：`do_GET` 新增 `/launch/drive` 路由，返回 `LAUNCH_DRIVE_HTML` 页面；页面加载后自动 fetch POST `/api/launch/drive`（同源），拿到 drive URL 后 `window.location.href` 重定向到 Drive 页面。Drifter Console 侧改为 `window.open('http://'+ip+':8090/launch/drive','_blank')` 在新标签页打开。

## 2026-08-11 (8)

- feat(launcher): 输入 6 后在新标签页打开 Drive 页面，保留 Launcher 菜单
  - 此前按 6 后 `window.location.href` 直接在当前标签页跳转，Launcher 菜单被替换掉。
  - `donkeycar/launcher/server.py`：`launchDrive()` 中改为 `window.open(url, '_blank')` 在新标签页打开；若被弹窗拦截器阻止则回退到当前页跳转。

## 2026-08-11 (7)

- fix(web_ui): DrivePage 在非安全上下文下 `crypto.randomUUID()` 崩溃导致"Something went wrong"
  - 问题：通过局域网 IP（非 localhost、非 HTTPS）访问 Drive 页面时，`crypto.randomUUID()` 不可用（返回 undefined），`createDriveClientId()` 调用时抛 TypeError；其 catch 块再次调用同一 API，异常未被捕获，传播到 React ErrorBoundary 显示"Something went wrong"。
  - `web_ui/frontend/src/services/api.ts`：新增 `generateUuid()` 辅助函数，优先使用 `crypto.randomUUID()`，不可用时回退到 `crypto.getRandomValues()`（非安全上下文也可用）；替换 `createDriveClientId()` 和 `createDriveWebRtcSession()` 默认参数中的 2 处 `crypto.randomUUID()` 调用。

## 2026-08-11 (6)

- fix(tubplot): 修复 Ubuntu 上 Tub 数据图表不显示--matplotlib 自动检测图形会话 DISPLAY 并切换 TkAgg 后端
  - 问题：`donkey tubplot` / `donkey tubhist` / `donkey cnnactivations` 在 Ubuntu 上运行时 `plt.show()` 不弹窗。根因是 matplotlib 在 `DISPLAY` 未设置时（SSH、Web 后台子进程等）默认回退到 `agg` 非交互式后端。
  - `donkeycar/management/base.py`：新增 `_ensure_display_and_backend()`（检测当前后端为 `agg` 时尝试切换 `TkAgg`）和 `_detect_graphical_display()`（从 `/proc/<pid>/environ` 读取 Xwayland/Xorg 进程的 `DISPLAY` 和 `XAUTHORITY`，支持 Wayland 下 Xwayland）；在 `ShowPredictionPlots`、`ShowHistogram`、`ShowCnnActivations` 三个类的 pyplot 导入前调用。
  - `mycar/manage.py`（本机）：菜单选项 4 和 Web 控制台启动 tubplot 时为子进程设置 `DISPLAY=:0`。
  - 验证：`donkey tubplot`（无 `--noshow`）GUI 窗口正常弹出（进程阻塞等待关闭）；`donkey tubhist` 同上且正确保存 PNG；`pytest test_tubplot` 通过。

## 2026-08-11 (5)

- feat(web_ui): DonkeyDrifter 页面 header 新增版本号显示，放在 GitHub 图标左侧
  - 背景：Drifter Console（ESP32 Web Console）已有版本号显示，DonkeyDrifter Web UI 缺失；用户要求参考 DC 样式补上。
  - `web_ui/backend/routers/config.py`：新增 `GET /version` 端点，从 `donkeycar._version.__version__` 返回 `{"version": "0.1.2"}`。
  - `web_ui/frontend/src/services/api.ts`：新增 `getVersion()` 异步函数调用 `/config/version`。
  - `web_ui/frontend/src/components/VersionBadge.tsx`（新）：版本徽章组件，挂载时请求版本号，加载中/出错时不渲染，正常时以 `text-zinc-500 text-xs uppercase tracking-wider` 样式显示 `v{version}`（参考 DC 的 `.version` 样式）。
  - `web_ui/frontend/src/components/Layout.tsx`：在 `<GitHubLink />` 左侧放置 `<VersionBadge />`。
  - 测试同步：`web_ui/backend/tests/test_config.py` 新增 `test_get_version_returns_version_string`；`web_ui/frontend/src/components/VersionBadge.test.tsx`（新）含 3 项用例（渲染版本号含 v 前缀、加载中不渲染、出错不渲染）。
  - 验证：后端 2/2 通过，前端 VersionBadge 3/3 通过，全套 54/54 通过。

## 2026-08-11 (4)

- fix(launcher): 新增孤儿进程清理--通过 pkill 按进程名搜索杀掉所有 donkey web / manage.py drive 进程
  - 背景：PID 文件方式只能杀掉最后一次启动的进程；如果用户在终端多次启动 DonkeyDrifter（或直接运行 `donkey web` 未写 PID 文件），旧进程会成为孤儿占用硬件资源。
  - `donkeycar/launcher/server.py`：新增 `_kill_orphaned_donkey_processes()`，使用 `pkill -f "donkey web"` 和 `pkill -f "manage.py drive"` 先 SIGTERM 后 SIGKILL 清理所有匹配进程；`_launch_drive()` 在 `_kill_previous_drive_processes()` 之后调用该函数作为兜底。
  - 验证：4 项测试全部通过（PID 文件杀进程、孤儿进程清理、5 次反复点击循环、混合场景）。

## 2026-08-11 (3)

- fix(launcher): 每次启动 drive 前强制杀掉上一次的进程，不再返回 already_running
  - 问题：此前 Launcher 检测到自己跟踪的进程仍在运行时直接返回 `already_running` 而不杀掉重启，导致用户反复点击"进入 DonkeyDrifter"或菜单输入 6 时无法清理旧进程（可能占用摄像头等硬件资源）。
  - `donkeycar/launcher/server.py`：`_launch_drive()` 移除 `already_running` 早退逻辑，改为每次调用都先执行 `_kill_previous_drive_processes()`（通过 `~/.donkeycar/drive.pid` 追踪并 SIGTERM→SIGKILL），再清理 launcher 内部进程引用，然后启动新进程。
  - 验证：代码逻辑检查通过（无 already_running、仅一次 kill 调用）；服务重启后 API 正常响应。

## 2026-08-11 (2)

- fix(launcher): Launcher 服务启动时通过串口向 ESP32 报告本机 IP（HOSTIP|<ipv4>），配合 Firmware v1.7.57 按钮动态获取 IP
  - `donkeycar/launcher/server.py`：新增 `_get_local_ip()`（优先返回 192.168.x.x 局域网 IP，排除 VPN/TUN 接口）、`_report_hostip_to_esp32()`（尝试 /dev/ttyACM0、/dev/ttyACM1、/dev/ttyUSB0 写入 HOSTIP 帧）、`_hostip_reporter_loop()`（每 30 秒上报一次的后台线程）、`_start_hostip_reporter()`；`run_server()` 启动时调用后者拉起 daemon 线程。
  - 说明：此为 best-effort 机制；当 `manage.py drive` 运行时，其 `ProvisioningPart` 会通过 Arduino 共享串口正确上报 HOSTIP，Launcher 的独立串口写入仅在没有车辆进程时作为补充。

## 2026-08-11

- feat(launcher): 新增 `donkeycar/launcher/` 模块--浏览器端 DonkeyDrifter 启动服务，无需打开终端即可从 ESP32 Drifter Console 一键进入 DonkeyDrifter
  - 背景：此前进入 DonkeyDrifter 需在终端输入 `donkey` 再输入 `6`，启动 `donkey web` + `manage.py drive` 两个子进程。新方案在宿主机上运行常驻 Launcher 服务（端口 8090），ESP32 Web Console 的"进入 donkey"/"进入 DonkeyDrifter"按钮直接跳转到该服务。
  - `donkeycar/launcher/server.py`：基于标准库 `http.server` 的轻量 HTTP 服务（无 Flask/FastAPI 依赖）。`GET /` 提供仿 TUI 菜单页面（dark theme、rich 风格表格、10 项菜单与 tui.py 一致、键盘数字选择）；`GET /api/status` 返回进程状态 JSON；`POST /api/launch/drive` 启动 `donkey web`（指定 `--backend-port` + `--frontend-port`，不带 `--open`）和 `manage.py drive`（注入 `DRIVE_API_SERVER_URL` 环境变量），PID 写入 `~/.donkeycar/drive.pid`，返回前端 URL（`http://<host>:<frontend_port>/#/drive`）。
  - `donkeycar/launcher/__main__.py`：入口点，支持 `--port`（默认 8090）和 `--host`（默认 0.0.0.0）参数。
  - `donkeycar/launcher/donkeydrifter-launcher.service`：systemd 用户服务模板，使用 conda 环境 Python，`WorkingDirectory=/home/dkc/projects/mycar`，`Restart=always`。
  - 前端页面 JS：键盘 1-9/10 选择菜单项（与终端一致），输入 6 触发 `/api/launch/drive` POST 并重定向；URL 中 `localhost` 替换为 `window.location.hostname` 以支持远程设备访问。
  - 安装方式：`cp donkeydrifter-launcher.service ~/.config/systemd/user/ && systemctl --user enable --now donkeydrifter-launcher`，`loginctl enable-linger dkc` 开机自启。
  - 验证：服务启动正常，`GET /` 返回菜单 HTML，`GET /api/status` 返回正确 JSON；systemd 用户服务 active (running)。

## 2026-08-10

- fix(cli): `donkey web`/`donkey drive` 自动打开浏览器前等待前端端口就绪，修复 TUI 选项 6/7 启动后浏览器打开"无法连接"页面的问题
  - 根因：`_launch_web_ui()` 拉起 Vite 前端进程后立刻 `webbrowser.open()`，Vite 需数秒才开始监听，浏览器在端口未监听时打开即显示无法连接且不会自动恢复（VS Code "View in Browser" 弹窗在端口监听后才出现，故点击总能正常打开）。
  - `donkeycar/management/base.py`：`Web` 新增 `_wait_for_port_ready()`（TCP 轮询本机端口直至可连接，默认 30s 超时）与 `_open_browser_when_frontend_ready()`（先等前端端口就绪再开浏览器；超时仍打开并打印警告，退化为旧行为由用户自行刷新）；`Web.run()` 与 `Drive.run()` 的 `--open` 路径统一改走该等待；`Drive._wait_for_backend_ready()` 复用 `_wait_for_port_ready()` 实现。
  - 测试同步：`donkeycar/tests/test_web_command.py` 的 `test_web_command_opens_requested_route` 补 `_wait_for_port_ready` monkeypatch（避免真实 socket 等待），新增 3 项用例（`_wait_for_port_ready` 对监听/关闭端口的探测、等待前端端口后再开浏览器、等待超时仍打开浏览器兜底）；`donkeycar/tests/test_drive_command.py` 新增 `test_drive_run_waits_for_frontend_port_before_opening_browser`。
  - 验证：相关 30 项测试全部通过；真实拉起 `donkey web --open` 端到端验证——浏览器打开回调在 Vite 就绪后才触发，打开瞬间该 URL 已返回 HTTP 200，退出时子进程清理正常。

## 2026-08-08

- fix(test): 修复配网循环韧性回归测试在 macOS CI 上的时序抖动（main 分支 run #198 失败）
  - 背景：main 分支 CI（macos-latest 任务）报 `donkeycar/tests/test_provisioning.py::TestProvisioningPartUpdateResilience::test_loop_continues_after_unexpected_exception` 失败（`assert 3 > 3`）——用例固定 `sleep(0.5)` 后断言循环调用超过 3 次，macOS runner 线程启动慢时 0.5s 内只跑了 3 次循环（ubuntu 与本地正常）。
  - `donkeycar/tests/test_provisioning.py`：改为轮询等待（`monotonic()` 5s 超时、20ms 间隔），循环跑过前 3 次异常调用后再 shutdown，不再依赖固定时长 sleep；测试意图（循环兜住异常继续运行）与断言不变。
  - 验证：该用例本地连跑 5 遍通过；`pytest donkeycar/tests/test_provisioning.py` 94 项全部通过。
- feat(web_ui): Web UI 全站中英文国际化（i18n）：默认中文（逐字保留现有中英混排界面），可一键切换为全英文界面，语言选择持久化、关机重启后保留
  - 新增 `web_ui/frontend/src/i18n/`：`index.tsx` 提供 `LanguageProvider`、`useTranslation()` hook 与供普通模块（services/stores）使用的独立 `t()`；支持 `{var}` 插值，回退链为 当前语言 → zh → key 本身；语言选择写入 localStorage `donkeydrifter.ui.lang`，首次访问默认 `zh`。`messages/` 下按 10 个命名空间组织字典（common/fab/tubnav/tubeditor/trainer/arena/connector/drive/driveviz/drivehooks），共 427 对 zh/en 词条，zh 侧逐字镜像现有界面，en 侧为完整英文翻译。
  - `web_ui/frontend/src/main.tsx` 挂载 `LanguageProvider`；顶栏 `LanguageSwitcher.tsx` 由占位改为真实切换；右下角 `FabActions.tsx` 语言菜单改接 i18n 上下文（两处切换等效），帮助弹窗全部文案走 `fab.*` 字典。
  - 全站 40+ 源文件（pages/components/hooks/services）的用户可见字符串——含标题、按钮、label、placeholder、aria-label、title、alt、canvas fillText、图表 legend、alert/confirm/toast/setError 及状态枚举→显示映射——全部改走 `t()`；品牌名、后端数据值（模型名/tub 名/路径/错误 message）、协议枚举值、`<kbd>` 键名、单位按约定不译。
  - 顺带修复（工作中发现）：`pages/PilotArenaPage.tsx` 模型类型加载失败分支改用 `getApiErrorMessage`（原直接渲染英文 `error.message`，与全页其他 5 处不一致）；`components/drive/VideoStream.tsx` 删除被重复注册一遍的 MJPEG 淡出 `useEffect`；`tubEditor.restoreTitle` 快捷键提示由双反斜杠 `(\\)` 修正为单 `\`；`SimulatorConfig` toast 与 `FileBrowserModal` 的关闭按钮补 `aria-label`（新增 `common.close` 词条）。
  - 测试同步：`components/LanguageSwitcher.test.tsx` 重写为 3 项用例（默认中文激活、点击切换并持久化、重新挂载恢复选择）；新增 `components/FabActions.test.tsx` 2 项用例（默认中文渲染、持久化 en 时英文渲染）；其余测试因 zh 逐字镜像原界面无需改动。验证：`tsc -b --noEmit` 零错误、`vitest` 54/54 通过、`npm run build` 通过；脚本核对 427 对词条 zh/en 完全对等、代码引用 key 无一缺失、无残留硬编码界面文案（注释与 console 除外）。

- feat(web_ui): MUS4 皮肤固化为永久主题并新增顶栏 GitHub 链接与语言切换组件（此前未提交界面统一改动，随本次一并入库）
  - `web_ui/frontend/index.html`：`<html>` 硬设 `class="theme-mus4"`；`web_ui/frontend/src/main.tsx` 无条件引入 `themes/theme-mus4.css`（不再存在运行时主题切换器）。
  - `web_ui/frontend/src/themes/theme-mus4.css`：文档头重写为"永久主题"约定，并补齐 ESP32 Drifter Console 的填充/线框视觉语言说明与对应规则（选中态实心 `#5cc8ff` + 近黑文字、状态色绿/黄/红/灰线框等）。
  - 新增 `web_ui/frontend/src/components/GitHubLink.tsx`（+ `GitHubLink.test.tsx`）：顶栏 GitHub 仓库链接图标；新增 `web_ui/frontend/src/components/LanguageSwitcher.tsx`（初版为占位组件，本次已接通真实切换，见上条）。
  - 测试同步：`GitHubLink.test.tsx` 2 项用例通过。

- feat(web_ui): 右下角帮助入口改为复刻 ESP32 Drifter Console 的 FAB 组合（发光圆点开关 + 语言球 + 帮助球 + 语言菜单 + 帮助弹窗），并移除底部页脚
  - 新增 `web_ui/frontend/src/components/FabActions.tsx`（替代 `web_ui/frontend/src/components/HelpModal.tsx`）：1:1 复刻 ESP32 `WebConsoleAssets.h` 的 `.fabToggle`（18px 发光青点、双层辉光阴影、hover 放大 1.18 倍）、`.fabActions` 展开动画（语言球上飞 56px、帮助球左飞 56px、.18s 过渡）、`.langFab`（46px 蓝球 🌐）/ `.helpFab`（46px 青球深色粗体 ?）、`.langMenu`（中文/English 菜单、选中高亮、选择持久化到 localStorage `donkeydrifter.ui.lang`）与 `.helpModal`（右下角锚定、`#5cc8ff` 边框渐变面板）；document 级点击收起行为与 ESP 一致。帮助弹窗中的快捷键列表内容保持 DonkeyDrifter 独有（播放控制 / 时间轴导航 / 选择与图表）。
  - 弹窗关闭按钮 × 与 Drifter Console「功能说明」弹窗统一为幽灵样式（28px 透明底 + `#a1a1aa`，hover `#27272a` 底白字）。
  - `web_ui/frontend/src/components/Layout.tsx`：移除底部页脚行（`<footer>` 品牌文字行）；`HelpModal` 引用替换为 `FabActions`。
  - `web_ui/frontend/src/themes/theme-mus4.css`：移除旧的 help 按钮颜色覆盖段（组件已内置 ESP 样式，覆盖段会破坏一致外观）。
  - 验证：`npm run check`（tsc）与 `npm run test`（vitest）通过；Playwright 截图核对收起 / 展开 / 语言菜单 / 帮助弹窗四态外观。

## 2026-08-07

- fix(provisioning): 配网后台线程异常防护与上位机 IP 停报诊断日志
  - 背景（实车排查）：ESP32 经 HTTP OTA 重启后，manage.py 进程的 HOSTIP 周期上报曾长时间静默停止（线程存活、串口 fd 正常、日志无任何记录），只能等进程自愈或重启；为根因定位与兜底防护做两处加固。
  - `donkeycar/parts/provisioning.py`：`update()` 两个后台循环（独立串口模式 / Arduino 共享模式）循环体加 `try/except Exception`，异常经 `logger.exception` 记录后继续运行，线程不再因未捕获异常静默死亡；`_maybe_report_host_ip()` 新增 `_host_ip_skip_count` 计数——`detect_lan_ip()` 连续探测失败时按「首次 + 每 30 次」限频输出 WARNING 告警，恢复时输出 INFO 日志（含此前连续跳过次数）。
  - 测试同步：`donkeycar/tests/test_provisioning.py` 新增 `test_no_ip_detected_warns_rate_limited_and_recovers`（限频告警与恢复日志）与 `TestProvisioningPartUpdateResilience::test_loop_continues_after_unexpected_exception`（循环连续抛异常后线程仍存活、上报仍执行）。
  - 验证：`pytest donkeycar/tests/test_provisioning.py` 94 项全部通过。

- refactor(web_ui): UI 品牌名从 `DonkeyDrifter Web UI` 统一简化为 `DonkeyDrifter`
  - 前端：`web_ui/frontend/index.html` 浏览器标签页标题改为 `DonkeyDrifter`；`web_ui/frontend/src/components/Layout.tsx` 页脚品牌文字同步修改（顶部导航本来即为 `DonkeyDrifter`，无需改动）。
  - 后端：`web_ui/backend/main.py` FastAPI `title` 改为 `DonkeyDrifter`，根路径两条 JSON 提示消息改为 `DonkeyDrifter is running`。
  - CLI：`donkeycar/management/tui.py` TUI 选项 6 的启动提示文案「将启动 DonkeyDrifter 的 Drive 标签页」同步修改。
  - 测试同步：`web_ui/backend/tests/test_branding.py`（标题与根消息断言）、`donkeycar/tests/test_web_ui_branding.py`（index.html 标题断言）更新为新名称；验证两组测试全部通过（2 + 3 passed）。`CHANGELOG.md` 与 `docs/` 中的历史记录保持原样未动。

- feat(web_ui): 移除 Web UI 的 Calibrate 校准功能，舵机/电调 PWM 校准统一在 ESP32 Drifter Console（Web Console）中进行
  - 前端：删除 `web_ui/frontend/src/pages/CalibratePage.tsx`（5 个 PWM 滑杆校准页面）；`web_ui/frontend/src/App.tsx` 移除 `/calibrate` 路由与 `CalibratePage` 懒加载；`web_ui/frontend/src/components/Layout.tsx` 移除顶部导航 Calibrate 入口；`web_ui/frontend/src/services/api.ts` 移除 `sendCalibrate()`。
  - 后端：`web_ui/backend/routers/drive.py` 移除 `CalibrateRequest` 模型与 `POST /api/drive/calibrate` 端点（原实现向车端 WebSocket 下发 `type=calibrate` 消息）。
  - 文档：`docs/guide/web-drive-console-user-guide.md` 移除「校准页面」章节、导航表 Calibrate 行、API 表 `/calibrate` 行及文件结构中的 `CalibratePage.tsx`，新增简短「校准」说明指向 ESP32 Drifter Console 与 `donkey calibrate --channel` CLI。
  - 验证：后端 `python -m pytest tests -q` 70 项全绿；前端 `npm run test` 47 项全绿、`npm run check`（tsc）无错误、`npm run lint` 0 errors（2 个既有 warning 与本次无关）。

- fix(cli): 第二次启动 `donkey drive` 时自动杀掉上一次启动的进程，释放摄像头等硬件资源，避免旧进程占用硬件导致车端离线
  - 新增 PID 记录文件 `~/.donkeycar/drive.pid`：`donkeycar/management/base.py` 与 `donkeycar/management/tui.py` 各提供一组 `_read_drive_pid_file()` / `_write_drive_pid_file()` / `_remove_drive_pid_file()` / `_kill_previous_drive_processes()` 辅助函数；`Drive.run()`（CLI）与 TUI 选项 6 `DriveCommand` 在启动新进程前读取 PID 文件，先 SIGTERM 优雅终止、0.5s 后对仍存活进程 SIGKILL，随后删除 PID 文件。
  - 只精确杀掉 PID 文件中记录的进程（前端 / 后端 / 车端三个子进程），不按端口扫杀，不会误杀其他程序；进程已不存在时静默跳过。本次启动成功后写入新的三个 PID；后端就绪超时或正常 Ctrl+C 退出时清理 PID 文件。
  - 影响范围：CLI `donkey drive` 命令与 TUI 选项 6（DriveCommand）。
  - 测试同步：`donkeycar/tests/test_drive_command.py` 的 `_FakeProcess` 补 `pid` 属性（原用例未随 PID 记录功能更新而失败）；`test_drive_run_spawns_three_processes_and_injects_env` 将 `_DRIVE_PID_FILE` monkeypatch 到临时目录，避免测试读写真实 `~/.donkeycar/drive.pid` 误杀实车进程。验证：`test_drive_command.py` / `test_tui_drive.py` / `test_tui_menu.py` 共 21 项全部通过。

- fix(web_ui): 移除前端右下角的 TRAE SOLO badge
  - `web_ui/frontend/package.json`：移除 devDependency `vite-plugin-trae-solo-badge`；`web_ui/frontend/vite.config.ts`：移除 `traeBadgePlugin` 的 import 与插件配置（dark / bottom-right / prodOnly / 点击跳转 trae.ai）。

- fix(ci): 修复 "Python package and test DonkeyDrifter" 工作流持续失败——裸 pytest 收集范围、mamba 弃用、可选依赖缺失与过时断言四类问题，CI 恢复可用（PR #11，已合并 main）
  - 新增根级 `pytest.ini`（仅 `testpaths = donkeycar/tests tests`）：裸 `pytest` 不再收集 `web_ui/`，与后端契约测试的独立依赖隔离，也避免误收集 `web_ui/` 根目录的临时调试脚本。
  - `.github/workflows/python-package-conda.yml`：删除 `mamba-version: "*"`（mamba 在 macOS runner 上触发 codesign 错误导致建环境失败，默认 conda 已足够）；新增 "Run backend contract tests" 步骤（`cd web_ui/backend && pip install -r requirements.txt && python -m pytest tests -q`），后端契约测试正式纳入 CI。
  - `web_ui/backend/requirements.txt` 末尾补充 `httpx2`（starlette TestClient 的 HTTP 客户端依赖，此前后端测试环境缺包报错）。
  - 测试适配（均为测试代码落后于既有实现、实现侧无回归，仅改测试）：
    - `tests/test_auth_part.py` 整文件重写，适配 AuthPart 惰性初始化（`setup()` 已在 `8427cf5d` 刻意移除），17 项通过。
    - `donkeycar/tests/test_serial2.py` 适配四态状态机，34 项通过。
    - `donkeycar/tests/test_tui_drive.py` 三处端口断言 8000→8100（`ee5439e1` 的有意变更），10 项通过。
    - 可选依赖缺失时跳过而非报错：`test_dgym_reconnect.py` 增加 `pytest.importorskip("gym_donkeycar")`、`test_torch.py` 模块级 importorskip torch 与 pytorch_lightning、`test_train.py` fastai_linear 用例 importorskip fastai。
    - `web_ui/backend/tests/test_branding.py` 标题断言更新为 'DonkeyDrifter Web UI'、根路径按前端 dist 是否存在分支断言（品牌名当日晚些时候再次简化为 `DonkeyDrifter`，断言随之更新，见上方 refactor 条目）；`test_provisioning.py` monkeypatch 目标改为 `donkeycar.parts.provisioning`、缺 ssid 期望码 400→422；后端契约 70 项全部通过。
  - 验证：本地 donkey 环境全量裸 `pytest`（`donkeycar/tests` + 根级 `tests/`）478 passed, 16 skipped 全绿。
- chore(repo): 解除 `web_ui/frontend/dist/` 编译产物的版本追踪（7 个历史遗留文件 `git rm --cached`，本地文件保留；`dist` 本就在 `web_ui/frontend/.gitignore` 中，此后新产物不再入库）。

## 2026-08-06

- feat(web_ui): Calibrate 页面新增 RC Channels 实时面板，与 ESP32 Drifter Console 双向同步（后端 WiFi 直连 ESP32，不动固件、无需车端 manage.py 在跑）
  - 链路：后端作为 WS 客户端直连 ESP32 遥测端口（`ws://<host>:81/`，~60Hz 二进制帧 'M4'/v2），解析出 RC Channels 字段（ch1..ch6 各通道脉宽、sd/ed 输出 duty、sm/mm 转向/油门中点、tl/tu 油门上下限、mode/park/vol）缓存并节流（200ms，对齐 ESP32 UI 的 RC DOM 刷新）广播给浏览器；浏览器下发的 `SERVO_MID`/`MOTOR_MID`/`THROTTLE_MIN`/`THROTTLE_MAX` 命令经后端 HTTP `POST /api/cmd?target=web` 转发 ESP32（首次自动 `AUTH:`，密码可配，默认为空）。两个 UI 以 ESP32 固件为唯一数据源，任一侧修改经遥测广播同步到另一侧，双向同步天然成立。
  - 后端新增 `web_ui/backend/routers/esp32.py`：`Esp32Link` 单例管理到 ESP32 的 WS 重连循环（3s 退避、配置变更 kick 立即重连）、遥测解析 `parse_telemetry_frame()`（`struct '<4BIIIHhh6fBB6H4h2fBB2f4H2h'` 与固件 `WebTelemetry.cpp::pushWifiWebSocketData()` 逐字段对齐）、命令白名单（仅 4 条校准命令，正则严格校验）、浏览器 WS 通道与空闲释放（浏览器全部断开 30s 后释放 ESP32 连接——固件仅允许 2 个并发 WS 客户端）；路由 `GET /api/esp32/status`、`GET/POST /api/esp32/config`、`POST /api/esp32/command`、`WS /api/esp32/ws`，挂载于 `web_ui/backend/main.py`。连接配置（host/password）持久化到 `esp32_link.json`（目录约定同 `drive_params.json`：DONKEY_CAR_DIR → ~/mycar → backend/data），默认 host `mus4-esp.local`（固件默认 AP SSID `MUS4-ESP` 的 mDNS 名），可用 `ESP32_HOST` 环境变量覆盖。
  - 前端新增 `web_ui/frontend/src/hooks/useEsp32Rc.ts`（连 `/api/esp32/ws`，处理 `esp32_state` 快照与 `esp32_rc` 广播，3s 自动重连，命令 100ms latest-value-wins 节流）与 `web_ui/frontend/src/components/calibrate/RcChannelsPanel.tsx`——1:1 复刻 ESP32 UI 的 RC Channels 面板：6 通道网格（CH4 Mode 黄色高亮边框、窄屏 3 列）、OUT Steering/Throttle 行、Mid S/Mid T（Set 按钮把当前 OUT 值设为中点）、Min T/Max T 滑杆（Min T 上限=Mid T、Max T 下限=Mid T 动态跟随，量程 4915-9830），样式沿用固件 rcCell 配色（#0d1219/#2b3441/#8fa1b5）；滑杆拖动期间用本地值避免遥测回跳。面板头部含连接状态点、主机设置（保存并重连）与手动重连按钮。`web_ui/frontend/src/services/api.ts` 新增 `Esp32RcTelemetry`/`Esp32Status` 类型与 `getEsp32Status`/`getEsp32Config`/`setEsp32Config`/`sendEsp32Command`/`getEsp32WebSocketUrl`。`web_ui/frontend/src/pages/CalibratePage.tsx` 顶部集成该面板；原有 5 个 PWM 滑杆（面向 PCA9685 直驱车型）保留不变。
  - 测试同步：新增 `web_ui/backend/tests/test_esp32.py` 13 个契约用例（路由挂载经 `collect_route_paths`、帧解析含坏 magic/短帧拒绝、配置持久化与非法 host 拒绝、命令白名单/首次 AUTH/ACK/NACK/认证失败 502/不可达 502、WS 快照与遥测广播）；前端新增 `src/hooks/useEsp32Rc.test.tsx` 与 `src/components/calibrate/RcChannelsPanel.test.tsx` 共 7 用例（标签渲染、Set 按钮下发 SERVO_MID/MOTOR_MID 当前 OUT 值、滑杆节流命令、Max T 下限跟随 Mid T、离线禁用控件）。
  - 验证：后端 `python -m pytest tests -q` 83 项全绿；前端 `npm run test` 54 项全绿、`npm run check` 无错误、`npm run lint` 0 errors（2 个既有 warning 与本次无关）、`npm run build` 成功；另用伪 ESP32（websockets + http.server）做实链路冒烟：二进制帧→浏览器广播、AUTH→命令 ACK、空闲自动释放连接全部符合预期。待实车联调（需 ESP32 在线时打开 Calibrate 页验证真实遥测与命令回环）。

- refactor(web_ui): 移除 UI 皮肤切换功能，Web UI 只保留 DonkeyDrifter 自身皮肤
  - 删除 `web_ui/frontend/src/components/SkinSwitcher.tsx`（顶栏 `Drifter Console UI` / `DonkeyDrifter Web UI` 分段切换按钮）及其测试 `SkinSwitcher.test.tsx`、`web_ui/frontend/src/store/useUiPrefsStore.ts`（zustand 持久化皮肤状态）、`web_ui/frontend/src/themes/theme-mus4.css`（MUS4/ESP32 Drifter Console 皮肤样式表）。
  - `web_ui/frontend/src/components/Layout.tsx`：移除 SkinSwitcher 渲染与 `theme-mus4` class 切换副作用；`web_ui/frontend/src/main.tsx`：移除 theme-mus4.css 导入；`web_ui/frontend/src/components/drive/DriveModeSelector.tsx`：清理引用 theme-mus4.css 的过期注释（`data-mode`/`mode-active` 钩子保留，仍被测试使用）。
  - 验证：`npm run test`（vitest 8 文件 47 用例全部通过）、`npm run check`（tsc 无错误）、`npm run lint`（0 errors，2 个既有 warning 与本次无关）。
  - 配套：ESP32 固件仓库（`Firmware/MUS4_FW`）同步移除 Web Console 的 DonkeyDrift 皮肤与切换按钮，两边各自只保留自己的 UI。

- fix(provisioning): 修复 TUN 模式 VPN 运行时 ESP32 Drifter Console HOST 分页显示错误上位机 IP（198.18.0.1，ESP32 不可达）的问题
  - 根因：`donkeycar/parts/provisioning.py` 的 `detect_lan_ip()` 用 UDP socket connect `8.8.8.8` 做路由查询取默认出口 IP；Clash Meta/mihomo 等 TUN 模式 VPN 会劫持默认路由到虚拟接口（本机 `Meta` 接口，198.18.0.1/30，属 198.18.0.0/15 基准测试网段伪装的假 IP），内核应答的源地址即为 VPN 假 IP，经 `HOSTIP|<ipv4>` 帧上报后 ESP32 Web Console Network 卡片 HOST 分页显示 198.18.0.1 而非真实局域网地址 192.168.3.41。
  - 修复：`detect_lan_ip()` 改为分级探测——① UDP 路由查询结果（默认出口 IP）是 RFC1918 私有地址**且不位于虚拟接口上**时直接返回（无 VPN/分流 VPN 的常见路径，行为不变）；② 出口被 VPN 劫持或 UDP 查询失败（离线局域网）时，先经 `_physical_default_iface()` 解析 `ip route show default` 找残留的物理网关默认路由（mihomo auto-route、OpenVPN def1、wg-quick 策略路由均会保留高 metric 的物理默认路由），取其接口上的 RFC1918 地址；③ 物理默认路由被完全移除时，用 `_select_lan_ip()` 从 `_enum_inet_entries()`（解析 `ip -4 -o addr show`）的接口地址表中选择——跳过回环与虚拟接口（docker/br0/br-/lxdbr/veth/tun/tap/wg/Clash Meta 等，见 `_VIRTUAL_IFACE_RE`），优先物理命名接口（wl*/en*/eth*/usb*/bond*）；④ 仍无结果保留旧行为返回默认出口地址（公网直连兼容），最后回退主机名解析。新增 `_is_rfc1918()` 统一判定 10/8、172.16/12、192.168/16，显式排除 198.18/15（VPN 假 IP）、100.64/10（CGNAT/Tailscale）、169.254/16（链路本地）。
  - 关键分支：UDP 查询结果为 RFC1918 时须先确认其接口不在 `_VIRTUAL_IFACE_RE` 之列——全隧道 WireGuard/OpenVPN 会把 10.x 隧道地址分到 wg0/tun0 并劫持默认路由，只看地址段会把隧道 IP 报给 ESP32（与 198.18.0.1 同一故障模式）。
  - 测试同步：`donkeycar/tests/test_provisioning.py` 的 `TestDetectLanIp` 全部改为 hermetic 风格（`_mock_udp`/`_mock_net` 辅助 mock socket 与两个 `ip` 命令解析函数），含 2 个 VPN 劫持回归用例（198.18 假 IP、RFC1918 隧道地址）；新增 `TestIsRfc1918`（11 个参数化地址判定）、`TestSelectLanIp`（物理优先于靠前非虚拟、跳过虚拟接口、lxdbr0/br0 网桥与 bond0 命名、非虚拟兜底、无可用地址 5 用例）、`TestEnumInetEntries`（`-o` 格式解析含 veth `@ifN` 后缀剥离、命令失败 2 用例）、`TestPhysicalDefaultIface`（TUN 劫持下认出残留物理默认路由、跳过虚拟网关路由、仅虚拟默认返回 None、命令失败 4 用例）。
  - 验证：本机复现环境（wlp1s0=192.168.3.41 + Meta=198.18.0.1）下 `detect_lan_ip()` 返回 192.168.3.41，`_physical_default_iface()` 正确认出 wlp1s0；`pytest donkeycar/tests/test_provisioning.py` 92 项全部通过。另经多视角对抗评审（correctness/test-quality/compat 三视角 + 逐条反驳验证）确认并修复了全隧道 VPN 绕过、网桥命名缺口、优先级未被测试锁定等残余问题。


## 2026-08-04

- feat(web_ui): 驾驶页模式选择器按 ESP32 Drifter Console 模式卡片配色，一种颜色代表一种模式（手动=绿 `#39d98a`、半自动=琥珀 `#ffcc66`、全自动=蓝 `#5cc8ff`）
  - `web_ui/frontend/src/components/drive/DriveModeSelector.tsx`：`MODE_OPTIONS` 为每个模式增加 `activeClass`（默认皮肤为对应模式色的 20% 底 + 同色文字，替代原先三模式统一的 cyan 激活态）；按钮新增 `data-mode` 属性与激活时的 `mode-active` 标记类，供主题精确定位每个分段。
  - `web_ui/frontend/src/themes/theme-mus4.css`：原先把所有激活分段统一覆盖为蓝色实心填充的规则，改为按 `button.mode-active[data-mode=...]` 分别填充绿/琥珀/蓝 + 黑色加粗标签（沿用 Drifter Console `.netTabs.active` 的选中态语言），hover 色分别为 `#74e4ad` / `#ffdb94` / `#8bdcff`；配色与既有固件模式徽标 `data-rc-mode` 规则一致。
  - 测试：新增 `web_ui/frontend/src/components/drive/DriveModeSelector.test.tsx` 4 个用例（渲染/点击回调/三模式激活色类/disabled），`npm run check`（tsc）与 vitest 全部通过。


## 2026-08-03

- fix(ci): 修复后端契约测试在 FastAPI 0.141 下的两处失败（`test_main_registers_arena_router`、`test_main_registers_connector_router`，macOS + Ubuntu 双红）
  - 根因：`web_ui/backend/requirements.txt` 未锁定版本，CI 当日拉到 fastapi 0.141.1；该版本 `include_router` 改为惰性挂载，`app.routes` 中存私有 `_IncludedRouter` 条目（无 `.path` 属性）而非展平后的路由，按 `{route.path for route in main.app.routes}` 遍历路由表的两处契约测试抛 `AttributeError`（2 failed / 68 passed）。本地环境仍为 fastapi 0.136.3 旧行为，故本地全绿、CI 独红。
  - 修复：新增 `web_ui/backend/tests/conftest.py::collect_route_paths()`，鸭子类型兼容两代 FastAPI——路由条目有 `.path` 直接收集；无 `.path` 但有 `original_router`（0.141+ 惰性挂载）则携带 `include_context.prefix` 递归展开嵌套路由。两处测试改用该辅助函数，不断言 FastAPI 内部结构。
  - 验证：venv 复现 CI 依赖（fastapi 0.141.1 + starlette 1.3.1）——未修复时两测试复现 CI 同款 `AttributeError`，修复后 70 passed；本地 fastapi 0.136.3 下亦 70 passed。


- fix(ci): 修复 "Python package and test DonkeyDrifter" 两处测试失败（PR #14 合并后 CI 变红）
  - 删除 `test_project_metadata.py::test_agent_docs_describe_donkeydrifter_migration_contract`：该用例读取仓库根的 `AGENTS.md`/`CLAUDE.md`，而 agent 说明文件已按约定移出版本控制（本地保留、`.gitignore` 排除），CI 环境不存在这两文件必然 FileNotFoundError（macOS + Ubuntu 双红）；迁移契约已由 `test_docs_include_compatibility_and_attribution_guides`（`docs/guide/donkeycar-compatibility.md`）覆盖。
  - 修复 `test_tui_restore.py::test_get_data_cache_dir`（仅 macOS 红）：`/var` 是 `/private/var` 的符号链接，`Path.cwd()` 返回解析后物理路径，期望值比较前对 `mkdtemp()` 结果补 `os.path.realpath()`。


- feat(provisioning): `ProvisioningPart` 周期向 ESP32 上报本机局域网 IP（`HOSTIP|<ipv4>` 帧）——配套 MUS4 固件 v1.7.39，Drifter Console Network 卡片 HOST 分页显示上位机 IP
  - `donkeycar/parts/provisioning.py` 新增 `detect_lan_ip()`：UDP socket connect 外部地址做路由查询（不实际发包）取默认出口 IPv4，过滤 127.x，失败回退主机名解析，均失败返回 None。
  - `ProvisioningProtocol` 新增 `build_host_ip(ip)` 构建 `HOSTIP|<ipv4>` 上行帧（Linux → ESP32，与既有 `STATUS|`/`OK|`/`FAIL|` 同通道）。
  - `ProvisioningPart` 新增 `host_ip_report`（默认 True）与 `host_ip_report_interval`（默认 10 秒）参数及 `_maybe_report_host_ip()` 节流上报：首次循环立即上报，之后每周期重新探测 IP（DHCP 换地址自愈），独立串口模式与 Arduino 共享串口模式的 `update()` 循环均已接入；ESP32 重启丢失运行时状态后 10 秒内自动恢复显示。
- fix(provisioning): 修复 `ProvisioningPart.run_threaded()` 签名不接收 inputs 传参导致整车崩溃的潜伏 bug
  - 场景：`Vehicle.update_parts()` 以 `p.run_threaded(*inputs)` 调用线程 Part，而 manage.py 注册该 Part 时带 `inputs=['provisioning/trigger']`；旧签名 `run_threaded(self)` 拒收位置参数抛 `TypeError`，Vehicle 主循环首次迭代即退出（此前 `PROVISIONING_ENABLED` 默认为 False，从未实车触发）。
  - 修复：`run_threaded(self, trigger=None)` 与 `run()` 对齐，接受可选 trigger dict 并支持手动触发配网；非 dict / None 输入安全忽略。
- 同步更新 `donkeycar/tests/test_provisioning.py`：新增 13 个用例（`detect_lan_ip` 四条路径、`build_host_ip` 帧构建、上报节流/禁用/无 IP 行为、`run_threaded` trigger 回归三条），全文件 64 项测试全部通过。
- 实车验证：mycar 启用 `PROVISIONING_ENABLED=True` 后重启 manage.py，ESP32（v1.7.39）`/api/status` 显示 `host_ip=192.168.3.41` 且 `host_ip_age_s` 每 ~10 秒刷新。


## 2026-08-02

- feat(tui): TUI `open` 命令在仅有一个有效项目时自动打开（PR #5，已合并 main）
  - `OpenProjectCommand.execute()`（`donkeycar/management/tui.py`）新增单项目分支：扫描 `~/projects` 后若恰好只有 1 个有效项目（含 `manage.py` + `myconfig.py`），打印提示并直接调用 `_change_to_project()` 切换进入，显示成功面板后按回车返回菜单，不再要求输入编号。
  - 0 个项目时保留"未找到有效项目"提示；多个项目时保留原有编号手动选择流程，行为均不变。
  - 启动前的 `_auto_open_project()` 原有单项目自动打开逻辑不变。
- 同步更新 `donkeycar/tests/test_tui_project_selection.py`：新增 2 个用例（单项目自动打开且不要求输入编号、多项目仍手动选择编号），全文件 11 项测试全部通过。
- feat(tui): `drive` 命令未进入项目时不再拦截，仅有一个项目时自动进入后再打开 Web Console
  - `DriveCommand.execute()`（`donkeycar/management/tui.py`）移除非 mycar 目录的红色拦截：扫描 `~/projects` 后若恰好只有 1 个有效项目，打印提示并自动调用 `_change_to_project()` 切换进入，再照常进入命令预览与确认流程。
  - 0 个或多个项目时显示黄色提示"仍将打开 Web Console 驾驶控制台，但不会启动车辆进程（manage.py）"，流程继续而不再直接退出；已在有效项目内时行为不变。
- 同步更新 `donkeycar/tests/test_tui_project_selection.py`：新增 3 个用例（单项目自动进入并记录 last_project、无项目时不拦截且不切目录、多项目时不自动进入），全文件 14 项测试全部通过。
- feat(tui): `web` 命令启动 Web UI 后自动打开浏览器
  - `WebUICommand.get_command_line()`（`donkeycar/management/tui.py`）追加 `--open`（含无 bundled 路径分支）：启动前后端后自动打开浏览器直达 Web UI 首页，不再需手动输入地址。`drive` 命令此前已带 `--open --route /drive`，`donkey_ui` 为 Kivy 桌面窗口不涉及。
- 同步更新 `donkeycar/tests/test_tui_web_command.py`：原有用例增加 `--open` 断言，新增无 bundled 路径分支用例；连同项目选择测试共 16 项全部通过。
- feat(web_ui): 顶栏新增"切换 UI 风格"分段选择条——点选分段即可切换 MUS4 Web Console（ESP32 页面）皮肤或 Donkey 默认皮肤，仅换视觉风格，功能与布局位置完全不变
  - 新增 `web_ui/frontend/src/themes/theme-mus4.css`：全部规则以 `html.theme-mus4` 前缀覆写高频 Tailwind 编译类（背景 `#101318`、面板 `#171c24`、边框 `#2b3441`、强调 `#5cc8ff`、胶囊按钮、system-ui 字体），不含任何布局属性，tsx 组件零改动；末尾另有一条仅针对 SkinSwitcher 激活段的加深规则（`#05070a`，纯颜色）。
  - 新增 `web_ui/frontend/src/store/useUiPrefsStore.ts`：zustand + persist（`donkey-ui-prefs`）持久化 `skin: 'donkey' | 'mus4'`，默认 donkey 原风格，刷新保持，对外提供 `setSkin(skin)`。
  - `Layout.tsx` 顶栏右端渲染分段选择条 `SkinSwitcher`（`web_ui/frontend/src/components/SkinSwitcher.tsx`）：pill 容器内并排 "ESP32 UI" 与 "Donkey UI" 两个分段，点击分段直接切到对应皮肤，当前生效分段背景明显加深（active 态，`aria-pressed`），一眼可辨当前 UI，六个标签页均可见；`main.tsx` 引入主题 CSS，`theme-mus4` class 切换逻辑保留在 `Layout.tsx`。
  - 新增 `web_ui/frontend/src/components/SkinSwitcher.test.tsx`（4 项用例：双分段渲染、默认激活 Donkey UI、点击切至 mus4 且 active 跟随、切回 donkey）；另新增 `src/setupTests.ts` 提供内存版 localStorage（Node ≥22 的实验性 localStorage 遮蔽 jsdom 实现，导致 zustand persist 在测试环境无存储可用），并在 `vite.config.ts` 注册 `setupFiles`。
  - chart.js 图表线条颜色由 JS 传入，不随皮肤切换。
- 验证：`npm run check` / `lint` / `vitest run`（45 项）/ `build` 全部通过。
- feat(web_ui): ESP32 皮肤向 Drifter Console 进一步对齐——补齐面板外框与红/绿/蓝三色视觉
  - `web_ui/frontend/src/themes/theme-mus4.css`（仍为纯视觉覆写，tsx 组件零改动）：
    - 面板外框：`.bg-zinc-900` 面板叠加 ESP32 `.stateCard` 同款对角渐变 `linear-gradient(135deg,#1c2430,#121821)`；并用 `outline + outline-offset:-1px` 为全部面板与内层信息块（`.bg-zinc-900*`、`.bg-zinc-800*`）绘制 1px 内嵌细框——不动布局、不覆盖 Tailwind 投影（Donkey 大量信息块本不带 border 类，此前切到 ESP32 皮肤后看不到框）。
    - 三色状态框：绿 `#39d98a`（emerald 系，正常/开启）、红 `#ef4444`（red 系，关闭/异常）、蓝 `#5cc8ff`（cyan 系，信息）分别给对应语义表面加同色系内嵌框，对应 Drifter Console 的 parkUnlocked/parkLocked/信息态边框；警告黄统一为 ESP32 的 `#ffcc66`（原 `#f59e0b`），amber 文字/表面/边框同步替换。
    - 原有边框更可见：`border-zinc-700` 提为 `#344154`（同 ESP32 `.stateCard` 边框），`border-white/10` 由半透明白改为灰蓝实色。
    - SkinSwitcher 激活段在 ESP32 皮肤下叠加青色描边，当前分段更醒目。
  - 文件头部注释的允许属性清单新增 `background-image` 与 `outline/outline-offset`，仍禁止一切布局属性。
- 验证：`npm run check` / `lint`（仅 2 条既有 warning）/ `vitest run`（45 项）/ `build` 全部通过。
- feat(web_ui): ESP32 皮肤第二轮回访——驾驶页模式按钮三着色与录制键红框（本机 Firefox headless 截图逐项验证）
  - 驾驶模式选择器按 Drifter Console 模式卡（.mode0/.mode1/.mode2）着色：仅激活分段变色——手动=绿 `#39d98a`、半自动=黄 `#ffcc66`、全自动=蓝 `#5cc8ff`，各带同色内嵌框；选择器锚定 `DriveModeSelector` 独有容器签名（`inline-flex rounded-lg overflow-hidden`），全仓库无第二处匹配。
  - 录制键常态叠加红色内嵌框（record = red 语义），选择器 `button.inline-flex.rounded-lg.bg-zinc-800:not(.border)` 全仓库仅匹配驾驶页录制键；红色状态框组补 `bg-red-400/10`（视频降级徽章）。
  - 验证方式：本机 snap Firefox 151 headless + selenium（/tmp venv，未动系统环境）分别截取 Donkey/ESP32 两种皮肤的 Tub Manager 与 Drive 页面对比图，并用 JS 强制切换 active 态逐一确认三个模式按钮的绿/黄/蓝渲染；`npm run build` 通过。
- fix(web_ui): Drive 遥测曲线捕捉不到 RC 手柄输入、陀螺仪 xyz 不显示——断点均在车上位机侧：RC 值解析后只缓存不发布、`HAVE_IMU` 关闭致 ArdImu 未注册、IMU 量纲超出图表固定量程
  - 新增 `ArdRc` 部件（`donkeycar/parts/actuator.py`）：把 `Arduino.Arduino_readline()` 解析 `T<t>S<s>` 帧时无条件更新的 `controller.steering/throttle`（-1..1）发布到 Memory 键 `rc/steering`、`rc/throttle`；刻意不接 `user/angle`，避免重蹈串口 RC 怠速值覆盖导致录制数据间歇跳 0 的历史问题。
  - `DriveApiBridge`（`donkeycar/parts/drive_api_bridge.py`）遥测协议扩展 `rc_steering`/`rc_throttle` 字段：`run_threaded`/`run` 签名末尾追加默认 None 参数（向后兼容，模板无需改），`field_name_map` 同步映射；后端 `routers/drive.py` 原样广播，无需改动。
  - 前端：`useDriveWebsocket.ts` `Telemetry` 接口加 `rc_steering?`/`rc_throttle?`；`TelemetryChart.tsx` 新增 RC Steering/RC Throttle 两条默认开启曲线，`CurveConfig` 新增 `scale` 显示缩放——gyro(rad/s)×0.2（对齐固件 Drifter Console 的 ÷5）、accel(m/s²)×(1/9.8)（1g 满量程），解决 y 轴固定 [-1,1] 下 IMU 曲线被裁剪成贴边直线的问题。
  - 车端接线（mycar 本机车辆目录，不随库分发）：注册 `ArdRc` 输出 `rc/steering`/`rc/throttle`、遥测桥 inputs 末尾追加两键、开启 `HAVE_IMU = True`（ArdImu 从 ESP32 `$IMU` 帧读取——此前固件 100Hz 上行一直被解析但零消费者）；ARDUINO_CONTROLLER 模式下 IMU 不写入 tub，避免新增 imu 键与既有 tub manifest schema 冲突触发 `datastore_v2` 断言、drive 启动即崩溃（本次排障实车复现并修复）。
  - 测试同步：`donkeycar/tests/test_drive_api_bridge_telemetry.py` 补 rc 字段入消息与 None 跳过断言；`web_ui/backend/tests/test_drive_telemetry_forward.py` 转发样例补 rc 字段；`TelemetryChart.test.tsx` 更新为默认 5 条曲线，新增 RC 写入与 scale 缩放用例（mock 数据集改渲染 JSON 数据，NaN 序列化为 null）。
- 验证：车端相关 `pytest` 85 项通过、后端契约 70 项通过、前端 `npm run check` + `vitest run` 47 项通过；实车实链验证：telemetry ~60Hz 含全部 rc/imu 字段（静止 az≈1g、RC 中位抖动合理），WebRTC 视频 60fps 发送、浏览器 53fps 接收。
- feat(web_ui): Drive 遥测接入固件 `M<m>:P<p>` 帧——Drive 页直接显示固件模式与 Park 手刹锁定徽标；实车探针借此定案 RC Throttle 恒精确 0 的根因是固件 Park 手刹锁定（rc_park=1 时 ESP32 SafetyState 持续钳油门、转向不钳），并非遥测链路故障
  - `donkeycar/parts/actuator.py`：`Arduino.__init__` 新增 `mode_data` 缓存，`Arduino_readline()` M 分支解析后无条件写入（此前 M 帧 1Hz 到达上位机但只解析不发布）；`ArdRc.run_threaded()` 扩展为四元输出 `(steering, throttle, mode, park)`，mode/park 未收到 M 帧时为 None，仅注册两键的旧调用方不受影响。
  - `DriveApiBridge`（`donkeycar/parts/drive_api_bridge.py`）：`run_threaded`/`run` 签名在 `rc_throttle` 后插入 `rc_mode`/`rc_park`（默认 None，None 字段跳过不发；插入点位于无任何位置调用方的 drift 参数之前，实车模板位置解包已对齐核对）。
  - 前端：`useDriveWebsocket.ts` `Telemetry` 接口加 `rc_mode?`/`rc_park?`；`DrivePage.tsx` 摄像头画面下方新增徽标行——`rc_park===1` 显示红色"Park 锁定 · 油门被钳 0"，并常显"固件模式：手动/半自动/全自动"。
  - 车端接线（mycar 本机车辆目录，不随库分发）：`ArdRc` 注册四输出 `rc/steering`/`rc/throttle`/`rc/mode`/`rc/park`，遥测桥 inputs 末尾同步追加 `rc/mode`、`rc/park` 两键（位置 17-18 与桥签名一致）。
  - 测试同步：`donkeycar/tests/test_drive_api_bridge_telemetry.py` 补 rc_mode/rc_park 入消息与 None 跳过断言；`web_ui/backend/tests/test_drive_telemetry_forward.py` 转发样例补两字段。
- 验证：库遥测测试 6 项、后端契约 2 项、`test_actuator.py` 25 项、前端 `npm run check` + `vitest run`（47 项）+ `build` 全部通过；实车实链探针 15s 收 897 条遥测（~60Hz）确认 rc_mode/rc_park 正常流动，rc_park=1 与 RC Throttle 精确 0 的因果关系成立。

## [0.1.2] — 2026-06-30

### 驾驶页面 (Drive UI)
- 新增 WebRTC 低延迟视频传输支持，含 MJPEG 自动回退机制
- 添加垂直油门指示器并重构控制栏布局
- 实现侧边面板多抽屉切换，菜单项支持图标与悬停交互效果
- 浮动触发按钮跟随侧边抽屉动画
- 新增实时视频延迟显示、FPS 统计与 WebRTC 连接状态追踪
- 输入源选择器重构并补充单元测试

### 后端 (Backend)
- 新增 WebRTC 信令服务（offer/answer/ICE 候选），含 TURN/ICE 服务器配置
- 实现模拟器自动恢复机制（检测、重连、状态同步）
- 新增局域网车辆扫描与连接优化
- 配置热重载与模拟器扫描优化
- WebSocket 连接异常处理与失效连接清理
- 新增 Drive API Bridge 远程驾驶桥接（含 WebRTC 视频流）
- 驾驶统计详情与录制条数即时同步

### CLI / TUI
- TUI 新增项目管理功能
- Web 命令自动打开浏览器、自动选择可用端口
- 新增调试模式支持并屏蔽冗余第三方日志
- 进程管理重构并补充测试

### 核心库 (Donkeycar)
- Arduino 控制器新增 IMU 数据支持
- 新增 ESP32 串口认证组件与单元测试
- 新增 Serial2 双向连通测试部件及端口扫描功能
- 修复 DGym 连接崩溃问题，调整默认端口并添加重连测试
- 修复 myconfig 模板中 DONKEY_GYM 默认值

### 文档 (Docs)
- 新增基于 Git Worktree 的并行开发指南
- 新增 Drive 60FPS WebRTC 设计规格
- 新增 WebRTC TURN 配置设计与视频加载优化方案
- AGENTS.md 中文本地化并持续更新

### 构建与配置
- 添加 gymnasium 和 pygame 模拟器依赖
- 环境变量配置支持（前端 API 地址、调试模式等）
- 忽略 worktree 目录

---

## [0.1.1] — 初始发布

- 基于 Donkeycar 派生的模块化自驾与漂移机器人平台
- Vehicle + Memory + Part 核心运行时架构
- Tub v2 数据录制格式
- Keras / TensorFlow / PyTorch 训练管道
- 统一 Web UI（FastAPI 后端 + React/Vite 前端）
- ESP32 串口协议与 Arduino 控制器
- CLI 工具链（createcar、calibrate、web、train 等）
- 模拟器集成（DonkeyGym）

