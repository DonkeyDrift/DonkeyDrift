# 俯拍漂移项目：状态交接与后续工作（供后续 AI/开发者继续开展）

> 更新：2026-09-01 深夜（**全量夜间审计与加固**：5 领域并行审计 40+ 发现，看门狗三链路/线程安全/NaN 防线/WebRTC 协议/脚本可靠性修复，详见 §9）｜2026-09-01（分支已合并 main 核实；course_deg 换 0.2s 割线基线+陀螺半程外推；FakeCamera 加节拍根治空转）｜2026-08-30 深夜（运动丢检测排障闭环，相机链路复验通过；overlay 加粗加长+速度着色轨迹+深蓝 β 航迹箭；当日成果/经验/教训总结见 §8）｜分支 `feat/overhead-drift-control`（**已合并 main**，tip 3bbc3d03 同为两分支头）｜测试基线 **345 passed**（`cd web_ui/backend && python -m pytest tests/ -q`；前端 vitest 156 全绿；TestCameraLoopSmoke 重载抖动已由 FakeCamera 节拍根治）

## 0. 文档地图

| 文档                                                   | 用途                        |
| ---------------------------------------------------- | ------------------------- |
| `docs/Rfc/overhead-drift-control.md`                 | 总体设计（方案 C：状态估计+反馈控制，13 节） |
| `docs/plan/overhead-drift-control-implementation.md` | M0\~M5 里程碑实施计划            |
| `docs/plan/overhead-drift-test-plan.md`              | **实车测试执行清单（2026-09-02 用）**   |
| `docs/guide/overhead-drift-first-run.md`             | 实操手册（7 步操作清单）             |
| **本文档**                                              | 当前状态 + 下一步工作 + 踩坑记录       |

工作语言约定：全部沟通/注释/提交信息用简体中文，conventional commits 格式。

## 1. 系统架构一句话

笔记本（本仓库 web\_ui 后端 FastAPI :8000 + 前端）⇄ ws ⇄ 车端 SBC（跑 donkeycar manage.py，主动回连笔记本）⇄ 串口 ⇄ ESP32（MUS4 固件）。笔记本端 USB 俯拍相机（index **1**）检测车顶 AprilTag（tag36h11 ID **0**）→ 位姿 → β 估计 → 级联 PID + 油门脉冲发生器 → ws 下发控制。**人工控制始终走 RC 遥控器（ESP32 本地），笔记本只接管**。

## 2. 当前状态（截至 2026-08-30 晚）

### 2.1 已完成并实测验收 ✅

| 项            | 结果                                                                                                              |
| ------------ | --------------------------------------------------------------------------------------------------------------- |
| tag36h11 打印件 | `docs/assets/apriltags/tag36h11_print_80mm.pdf`，官方检测器解码验证（hamming=0）                                            |
| 打印缩放         | 实测 95%（标尺 100mm→95mm），**确认无影响**：位姿尺度来自场地单应性，`tag_size_m` 未进入解算链路，无需重打                                           |
| 场地单应性        | 1.0×1.0 m 四点点击完成，`C:\Dev\DDC\DonkeyDrift\field_homography.npz`（注意：在**仓库根**，后端 cwd 在 web\_ui/backend，前端表单须填绝对路径） |
| 位置精度         | pose 验收通过（用户确认）                                                                                                 |
| 朝向           | 贴标 180° 已用 `heading_offset_deg=180` 补偿；朝东=0°，**逆时针旋转数值递增**（与 gz 配套正确，无需取反）                                      |
| β 静止语义       | 静止 0.3s 衰减到 0（修复了斜推后冻结 -73.5° 的残影，同时消除 AUTO 误触发风险）                                                              |
| 处理循环         | **60fps 稳定**（推车实测 58.4\~60.5；read≈16.7ms，detect≈8ms@半分辨率）                                                       |
| 预览显示         | WebRTC 60fps 推流（含绿框+车头红箭头叠加），运动画面推流降 360p 编码；MJPEG 自动兜底                                                         |
| 数值刷新         | 10Hz；state 含 `camera_fps/read_ms/detect_ms` 分段诊断                                                                |
| 前端表单         | 相机 index/TagID/朝向偏移/标定文件启动成功后存 localStorage 自动回填                                                                |

### 2.2 复验结果（2026-08-30 深夜，清僵尸进程后）✅

- 预览出画面、干净帧 60fps、慢推/快推不掉帧不卡——通过
- 快推丢检测根因是相机自动曝光拖影；曝光压到 **1/400s** 后甩动车壳全程锁定（完整排障链见 §4.3）

### 2.3 关键运行参数（实测确定，勿改）

| 参数                   | 值                          | 说明                               |
| -------------------- | -------------------------- | -------------------------------- |
| 相机 index             | **1**                      | 笔记本内置相机占用 0                      |
| 标签                   | tag36h11 ID **0**（备用 ID 1） | 车顶黑框中心对准回正中心                     |
| heading\_offset\_deg | **180**                    | 贴标方向与角序约定差 180°                  |
| 场地                   | 1.0×1.0 m                  | 西南原点                             |
| 分辨率/帧率               | 1280×720\@60 MJPG          | 检测 downscale=2（360p 检测、角点还原全分辨率） |
| 曝光                   | **1/400s（≈2.5ms）**         | 运动模糊根治参数：驱动/厂商工具设置，或卡片"曝光"框填 **-8/-9**（DSHOW log2 秒，后端已接线）；自动曝光下快推必丢检测 |

## 3. 坐标与符号约定（重要，别搞反）

- 场地系：**X 向东、Y 向北**（西南原点，数学右手系 z 朝上）——`calibrate_field_homography.py` 的 field\_pts（NW=(0,H)…SW=(0,0)）即此约定
- 视觉 heading：**逆时针为正**；前端显示为指南针式 0\~360°（东=0 北=90 西=180）
- 陀螺 gz 直接积分进 heading（`state_estimator.py`，无翻转位）；实测逆时针递增=配套正确
- β = wrap(heading\_est − course)，(-180,180]；静止时按 0.3s 时间常数衰减到 0
- AprilTag 数据位是**螺旋序**（官方 bit\_x/bit\_y），码字 bit=1 对应**白**模块（`scripts/generate_apriltag.py`，已固化测试）

## 4. 运维纪律（Windows 实测踩坑，必须遵守）

### 4.1 重启后端必须清场（黑屏事故根因）

Git Bash 的 TaskStop **杀不干净 python 子进程**→ 残骸持有 DirectShow 相机句柄 → 新进程以残缺状态打开（read\_ms 从 16.7 恶化到 145ms/帧 ≈ 7fps，预览全黑）。重启后端流程：

```powershell
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"
# 确认 8000 释放后再启动：
cd C:\Dev\DDC\DonkeyDrift\web_ui\backend && python main.py
```

相机异常时先 `tasklist | grep -i python` 查残留，再怀疑代码。另：Git Bash 的 `taskkill /PID` 会被 MSYS 路径转义破坏，须走 PowerShell。

### 4.2 其他

- **热重载不可靠**：相机后台线程会阻塞 uvicorn reload 的优雅退出（reload 卡一半、旧进程继续服务）——改后端代码后必须整体重启，不要相信 reload
- 前端改动后 `cd web_ui/frontend && npm run build`（dist 在 .gitignore，不入库）；用户浏览器需 Ctrl+F5
- 帧率问题**分五条链路定位**：采集(read\_ms)→处理(camera\_fps+detect\_ms)→推流编码→浏览器显示→数值轮询。`/api/drift/state` 已暴露前两者；预览卡≠处理掉帧，先看数据再动手
- H.264 软编码运动画面 20\~35ms/帧超 60fps 预算——推流必须 360p（检测不受影响，仍在 720p 全分辨率帧上做）
- 相机循环冒烟测试 `test_loop_runs_and_reports_stage_timing` 对 CPU 调度敏感：机器重负载（如视频会议）下 3s 宽限必挂，已调至 10s（验证内容不变）；全量测试尽量在空闲机器上跑

### 4.3 运动丢检测排障链（2026-08-30 深夜，已闭环）

按 §4.2 五链路法逐层取证，四层症状各有独立根因，逐层修复（全程 TDD，每层先写失败测试）：

1. **"静止流畅、运动卡顿"** → 数据显示采集/处理/编码全程健康（60fps、detect≈8ms、360p 编码实测 2\~5ms），根因在显示帧更新逻辑：`_display_frame` 只在检测成功时更新，运动模糊的检测缺口期间推流持续发旧帧。**修复**：显示帧逐帧透传原始帧、检测成功才叠加（drift\_engine.py；测试 TestDisplayFrameFreshness）。
2. **"绿框在、红箭头跟不上"** → `PoseSolver` 跳变拒绝（>0.5m）无恢复机制：检测缺口期间车真实移过 0.5m 后，新位姿被当中值离群**永久拒绝**（绿框走原始角点故正常）。**修复**：连续 window(5) 帧一致被拒即判定真实位移、采信并重置窗（drift\_vision.py；测试 test\_sustained\_jump\_recovers）。
3. **"快推丢检测"（软件层兜底）** → `decode_sharpening` 0.25→**0.6** + 半分辨率未检出时**全分辨率自适应重试**（好帧 8ms\@360p 保 60fps，难帧 +\~30ms\@720p；测试 TestAdaptiveDetection）。评估过 `quad_decimate=1.0` 并**弃用**：720p 下单帧 210ms 会压垮管线。修复后慢推紧贴，但快推命中率仍只有 0\~50%。
4. **根因（物理层）**：USB 相机自动曝光在 60fps 下实测默认只有 \~1/100s（10ms），1m/s 快推把 78px\@720p 标签拖出 20\~40% 涂抹，**任何分辨率/锐化都无解**。**最终参数：曝光 1/400s（≈2.5ms），甩动车壳全程锁定**。设置途径：驱动/厂商工具设 1/400s；或卡片"曝光"框填 **-8/-9**（DirectShow log2 秒；后端链路已接线：USBCamera 先关自动曝光再设值 / API 字段 `exposure` / 前端表单 localStorage 回填；旧 `exposure_us` 参数语义对 DSHOW 是错的且从未接线，已重构）。

副产品：引擎状态新增 `frames_total`/`tag_hits` 命中率计数（M0 丢帧率验收的直接数据源）。

**当前特性（勿误判为回退）**：短曝光下 360p 快路径命中率低（标签 39px 本就在分辨率下限，quadrilateral 阶段经 quad\_decimate=2 仅 \~19px），难帧几乎全靠 720p 重试兜底——快推段表现为 detect≈40ms、处理 fps≈20、累计命中率 ≈86%（含车出画面的时段）。跟踪质量已过目测验收；若第 1 步延迟实测超标，候选优化：直接 720p 检测（\~36ms 恒定）或 360p+quad\_decimate=1（\~34ms，四边像素翻倍），二选一实测后再动。

### 4.4 可视化增强（2026-08-30 晚，TDD 20 例）

- **加粗加长**：绿框线宽 2→4；车头红箭线宽 2→5、长度 6cm→**15cm**（720p 预览上原尺寸太细太短）。
- **中心轨迹**：`TrajectoryTrail` 2s 滑窗记录位姿中心点，逐段按线速度着色——0=绿、1m/s=黄、≥2m/s=红（`speed_to_bgr` 线性插值），最新点画实心圆点。不动时轨迹始终是一个点；超窗旧点动态消失；**检测丢失帧轨迹仍叠加**（不再纯透传），检测缺口期间轨迹不闪断。
- **β 朝向箭头**：深蓝色航迹箭（BGR 139,0,0），先画蓝后画红——两箭对齐即 β≈0，张开的夹角即 β。箭头方向取**轨迹割线**（`trail_course_deg`：末点与 0.2s 基线前点），与屏幕上的轨迹线天然相切；位移 <2cm（静止/噪声级）时不画。
- **β 箭头曾乱指（甚至垂直于运动方向）的根因**：初版直接画 `BetaEstimator.course_deg`——逐帧差分+2cm 位移阈值，低速时每帧真实位移卡在阈值附近，能超阈的帧对被 ±1\~2cm 位姿噪声主导，方向随机。换 0.2s 割线基线后噪声摊薄一个量级。**注意**：控制链路（session/控制器）的 `BetaEstimator.course_deg` 未改动，M4 前需评估（见 §6）。
- 逐点速度同样用 0.2s 差分基线平滑（`trail_speeds`），抑制颜色闪烁；轨迹/箭头随 display\_frame 走 WebRTC 与 MJPEG 双通道，前端零改动。

## 5. 下一步工作（按序执行，含命令与验收标准）

### 第 0 步：复验相机链路（清僵尸进程后）✅ 已通过（2026-08-30 深夜，含曝光修复，见 §4.3）

浏览器刷新 → 启动相机。验收：预览出画面、相机 fps≈60、来回推车不掉帧。过了即 **M0 正式收官**。

### 第 1 步：M0 延迟实测（第一个硬指标）

车端 SBC 跑 `manage.py drive` 连上笔记本 :8000 后：

```powershell
python scripts\measure_loop_latency.py --camera 1 --server ws://127.0.0.1:8000
```

验收：端到端 P95 < 100ms ✅；超标则记录数字，按 RFC 第 10 节加超前补偿/降档。同时看 tag\_hits/frames 丢帧率 <5%。

### 第 2 步：M1 录制（人 RC 漂移 ≥2 分钟）

卡片点**录制** → RC 遥控器 MANUAL 模式定圆漂移多圈 → 停止。验收：`data/drift_tubs/overhead_*` 生成、已录帧>0、漂移段 β 落在 15°\~40°。β 异常先查标签角序（必要时旋转标签重贴/调 heading\_offset）。

### 第 3 步：M2 点动机理验证（不成立则停下修模型）

```powershell
python scripts\analyze_throttle_pulses.py data\drift_tubs\overhead_<时间戳> --center 0.5,0.5
```

（注意 `--center` 用**本场地中心 0.5,0.5**，手册示例 1.0,1.0 是 2×2 场地的。）验收：输出 `✅ 机理成立：频率高→半径小` + 低/中/高三档参数表 → 填入卡片参数面板作外环初值。

### 第 4 步：M4 低速闭环（先非漂移！安全第一）

1. 参数：β\*=0、脉冲频率 0（连续油门）、基础油门 0.2
2. 自动漂移 → 状态"自动·观察" → 低速遥控进圆，验证转向闭环方向、车能跟圆
3. 安全联锁核对：RC 遥控器随时可夺回（MODE 0）、看门狗触发时 car\_mode=0+零油门、浏览器其他标签页不得发控制（服务端门禁已实现，待实车核对生效）

### 第 5 步：M5 定圆漂移验收

β\* 设 25° 左右、按 M2 参数表给脉冲参数 → RC 起漂 → 接管 → 验收：定圆保持 30s，β 均值误差 <5°，半径波动可接受。

## 6. 遗留与风险清单

- [ ] 棋盘格标定板未到货：2.1 内参标定**用户明确说自己下次做**（跳过不影响单应性/标签位姿）
- [x] 检测降采样余量：360p 检测下标签约 39px 接近 AprilTag 下限——**已实锤并由 §4.3 链路解决**（锐化 0.6 + 720p 自适应重试 + 曝光 1/400s）；残余优化候选见 §4.3 末段
- [ ] `dsc` 遥测字段语义核对（第二阶段蒸馏前）
- [x] 服务端多 client 仲裁（AUTO 期间其他浏览器标签页仍可能发控制）——已实现服务端门禁：AUTO（观察/接管）期间浏览器控制字段在 drive ws 一律丢弃并回发 `control_rejected`（routers/drive.py + `drift_engine.auto_active()`，测试 tests/test\_drift\_control\_arbitration.py），待实车核对
- [ ] MODE 0→2 固件跳变实车核对
- [ ] **看门狗三链路实车核对**（2026-09-01 夜补齐代码，待实车）：ENGAGED 期检测丢失>0.2s/遥测停滞>0.5s/控制下发连续失败≥3 → car_mode 0+零油门；非 AUTO 触发只记事件不动车
- [ ] **半径环符号实证**（M2）：`radius_freq_sign` 默认 −1（按 RFC §7.3 机理负反馈：偏内→降频）；若 M2 实测"频率高→半径大"则置 +1（/config 可热改）
- [ ] **低速 β 噪声 vs 接管判据**（M4 前评估）：0.2s 割线基线下低速段 β 抖动水位 ≈6.5~8°，接管判据要求 500ms 零次跌破阈值，低速段可能接管困难——必要时判据改滑窗均值/超阈占比（当前仅做了缺口不计入计时）
- [x] 分支未合并 main——**已合并**（2026-09-01 核实：tip 3bbc3d03 同时是 `feat/overhead-drift-control` 与 `main` 分支头）
- [x] `BetaEstimator.course_deg`（控制链路）逐帧差分低速被位姿噪声主导（§4.4 同款根因）——**已换 0.2s 割线基线+陀螺半程外推**（2026-09-01，TDD：低速噪声直行/爬行两用例先红后绿；全量 256 项通过；离线仿真 β=24.72°/极差 0.47° 仍收敛）；M4 前遗留项清零

## 7. 代码地图

| 模块                                                   | 职责                                                                        | 测试                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------- |
| `web_ui/backend/drift_vision.py`                     | 单应性(校验 shape/有限性/行列式)/位姿解算(heading\_offset)/PoseSolver(跳变拒绝+恢复+非有限拒收可返回 None)/USBCamera(手动曝光)/FrameSource 泵(EMA 冷启动直赋+异常日志)/检测(降采样+锐化+全分辨率重试)/叠加绘制 | test\_drift\_vision.py       |
| `web_ui/backend/state_estimator.py`                  | β 估计（heading 域互补滤波+静止衰减+course 0.2s 割线基线[取最新满足点]陀螺半程外推+NaN 入口拦截计数） | test\_state\_estimator.py    |
| `web_ui/backend/drift_controller.py`                 | 级联 PID+油门脉冲发生器(四参数热更新)+看门狗+摆速限幅 dt 化(max\_steering\_rate\_per\_s)+半径环符号配置(radius\_freq\_sign)+NaN 抛错 | test\_drift\_controller.py   |
| `web_ui/backend/drift_session.py`                    | 会话状态机（观察→β 稳定→接管；迁移加锁/检测缺口清锚点/events 有界 500）                          | test\_drift\_session.py      |
| `web_ui/backend/sync_recorder.py`                    | 遥测插值对齐(线程锁+30s 前缀裁剪)+点动特征(施密特触发+时间加权 duty)+tub v2 录制                | test\_sync\_recorder.py      |
| `web_ui/backend/drift_engine.py`                     | 编排：相机循环(整体异常护栏)/看门狗三链路(丢检测/遥测停滞/下发失败)/重入守卫/解算失败按丢帧/FpsMeter/分段计时/display\_frame/命中率计数 | test\_drift\_engine.py + test\_drift\_engine\_watchdog.py + test\_drift\_engine\_integration.py |
| `web_ui/backend/routers/drive.py`                    | 驾驶 ws/控制转发（AUTO 期间浏览器控制门禁，回发 control\_rejected）                                          | test\_drive.py + test\_drift\_control\_arbitration.py |
| `web_ui/backend/drift_webrtc.py`                     | aiortc 60fps 推流（DisplayFrameTrack 360p；协商失败清理 pc/monotonic 节拍/黑帧缓存）           | test\_drift\_router.py       |
| `web_ui/backend/routers/drift.py`                    | API：state/session/camera/config(有限性+范围校验 422)/frame.jpg/frame.mjpg/webrtc/offer；阻塞调用 to\_thread | test\_drift\_router.py       |
| `web_ui/frontend/src/components/drive/DriftCard.tsx` | 前端卡片（WebRTC[等 ICE gathering 完成]预览+MJPEG 兜底+参数面板+i18n 全量+串行轮询+离线徽标）      | DriftCard.test.tsx（16 例）    |
| `scripts/generate_apriltag.py`                       | tag36h11 打印件生成（螺旋位序！）                                                     | test\_apriltag\_generator.py |
| `scripts/simulate_drift_controller.py`               | 离线闭环仿真（β=24.72°/极差 0.47°）                                                 | test\_simulate\_drift\_controller.py |

## 8. 当日成果、经验与教训（2026-08-30）

### 8.1 成果（一天闭环）

1. **M0 相机链路正式收官**：复验通过（§2.2），60fps 稳定，甩动车壳全程锁定；§5 第 0 步 ✅。
2. **运动丢检测排障链闭环**（§4.3）：四层症状四个独立根因，逐层修复——显示帧逐帧透传 / PoseSolver 跳变恢复 / 锐化 0.6+720p 自适应重试 / 相机曝光 1/400s（物理根因）。
3. **可视化增强上线**（§4.4）：框箭加粗加长、2s 速度着色轨迹（绿→黄→红）、深蓝 β 航迹箭（轨迹割线方向）。
4. **服务端多 client 仲裁门禁**：AUTO 期间浏览器控制字段一律丢弃并回发 `control_rejected`（§6 已勾，待实车核对）。
5. **测试基线 217 → 254**（+37 例，全部 TDD 先红后绿）；新增 `frames_total`/`tag_hits` 命中率计数，M0 丢帧率验收有了直接数据源。

### 8.2 经验（可复用方法论）

1. **分链路定位，逐层取证**（§4.2 五链路法）："预览卡"与"处理掉帧"是两回事，采集/处理/编码/推流/显示各有独立指标，先看数据再动手。本次四个症状四个根因——不要指望一个修复解决全部。
2. **物理层优先于算法层**：运动模糊的根因是相机曝光（1/100s 在 1m/s 下拖影 20\~40%），锐化/降采样/重试只能兜底。遇到"算法怎么调都差点意思"时，回头查物理参数（曝光/对焦/光照）。
3. **数据显示健康而观感异常 → 查显示/传输边界**：采集处理编码全程健康时的"卡顿"，根因在 `_display_frame` 只在检测成功时更新。
4. **任何"离群拒绝"逻辑都必须配"持续离群即采信"的逃逸通道**，否则滤波器永久冻结（PoseSolver 教训）。
5. **差分类估计要拉长基线**：逐帧差分+阈值门限在信号贴近阈值时被噪声主导（β 箭头垂直于运动方向的根因）；0.2s 割线基线把噪声摊薄一个量级。宁要稳定的滞后，不要噪声的"领先"。
6. **观测先行**：`camera_fps`/`read_ms`/`detect_ms`/`tag_hits` 这些计数器把"感觉卡"变成可量化验收（<5% 丢帧率），排障全程靠它们定位层位。

### 8.3 教训（踩坑清单）

1. **重启后端必须清场**（§4.1）：Git Bash 杀不干净 python 子进程，残骸持有相机句柄 → 黑屏。相机异常先查 `tasklist | grep -i python` 再怀疑代码。
2. **热重载不可信**：相机后台线程阻塞 uvicorn reload 优雅退出，改后端代码必须整体重启。
3. **假硬件泵要节流**：`FakeCamera` 自由空转吃满单核，重负载机器上全量测试偶发调度超时（`TestCameraLoopSmoke`）。处置：宽限 3s→10s + 对照实验（deselect 全部新测试仍挂 → 证明非回归）才放行；~~后续可把 FakeCamera 加上节拍 sleep 彻底根治~~ **2026-09-01 已根治**：`FakeCamera.read` 加 60fps 节拍 sleep（`test_fake_camera_read_is_paced` 固化）。
4. **DSHOW 曝光语义是 log2 秒，不是微秒**：旧 `exposure_us` 参数语义错误且从未接线——删掉重构比保留兼容更安全。
5. **叠加绘制参数（线宽/箭头长度）须在真实 720p 预览上目测验收**：像素数阈值测试只能防回退，"太细太短"这种问题只有眼睛能发现。

**协作纪律**（用户强调）：不臆测、不懂就问、对齐后动手；TDD 红-绿-重构；诚实区分物理保证与实验结论；改行为先写失败测试；所有回复/注释/提交信息简体中文。

## 9. 夜间全量审计与加固报告（2026-09-01，AI 自主执行）

> 方式：5 个并行只读审计代理（视觉/编排、控制链路、录制/API/推流、前端、脚本与测试缺口）逐行精读全系统 → 分级问题清单 → 4 个并行修复代理按文件所有权分区 TDD 修复 → 主会话集成协调与复验。**全部改动未提交 git，工作区待用户 review。**

### 9.1 验证基线

- 后端 `pytest tests/ -q`：**345 passed**（254→345，+91 例，全部先红后绿）
- 前端 `vitest run`：**156 passed**（+16 例 DriftCard）；`tsc -b`、`npm run build` 通过
- 离线仿真：β=24.72°/极差 0.47° 收敛（β\*=25°），退出码 0
- 仓库根 tests/ 的 4 收集错误（launcher 依赖 Unix `fcntl`）+ 3 失败（`SIGKILL`/前端构建判定）为本机 Windows 平台既有问题，与本次无关

### 9.2 关键发现与修复（按严重度，全部本地验证）

**🔴 安全链路（此前失控场景只有 RC CH4 物理夺回一道兜底）**

1. **相机循环异常裸奔**（最 systemic 的发现）：检测/解算/估计/控制/落盘任一抛异常 → 线程静默死亡、看门狗不触发（泵还活着）、DirectShow 句柄泄漏。已修：循环体整体护栏（计数+日志+看门狗+finally 停泵）。
2. **看门狗三链路只落地一条**：RFC 第 9 节要求丢帧>200ms/ws 断线/控制器异常三触发，原仅"泵线程死亡"一项，`Watchdog.expired()` 无人调用（结构僵尸）。已补齐 ENGAGED 期三链路巡检（丢检测>0.2s、遥测停滞>0.5s、下发连续失败≥3），且 `trigger_watchdog` 修正为仅 AUTO 期才碰车。
3. **NaN 无防线且被 min/max 顺序放大**：单帧坏位姿 → 满舵+积分永久钉满幅+估计器永久中毒（`min(0.6,nan)=0.6` 等 Python 语义）。已修：估计器/控制器/位姿解算/单应四层入口拦截。
4. **WebRTC 协商协议级 bug（前端）**：POST 的是 `setLocalDescription` 前的旧 offer.sdp（零 ICE 候选），aiortc 不支持 trickle → 60fps 路径必败、永远回退 MJPEG。已修：等 gathering 完成再 POST `localDescription`，加连接态监控与首轨超时回退。
5. **录制层跨线程竞态**：遥测 push（事件循环线程）与插值/特征提取（相机线程）无锁，两段 insert 非原子 → IndexError/时戳错配污染 tub。已修：加锁+30s 前缀裁剪（原 maxlen 死代码，小时级会话内存无界）。
6. **相机生命周期**：`/camera/start` 重入产生双循环双句柄；检测器构造失败泄漏句柄；进程退出无释放路径。已全部加护栏（重入幂等停旧/失败 close/shutdown 钩子+atexit）。
7. **WebRTC 协商失败泄漏 pc**：垃圾 SDP 每次泄漏一个 RTCPeerConnection。已修（失败 close+discard，含 disconnected 态）。

**🟡 正确性/验收**

8. **估计器割线基线取错点**（当日新逻辑的打磨）：deque 最旧端取点使 0.5s 窗长成实际基线，`course_baseline_s=0.2` 成死参数。已修（reversed 取最新满足点，与 `trail_course_deg` 语义对齐）。注意：0.2s 基线的固有代价是低速 β 抖动水位 ≈6.5~8°（噪声 σ∝1/基线跨度），若 M2 嫌噪可加大基线参数而非回退还点逻辑。
9. **半径环按 RFC 机理是正反馈**：偏内→增频→（频率高→半径小）→更偏内。已配置化 `radius_freq_sign` 默认 −1（负反馈），M2 实证后确认（§6 遗留）。
10. **delta 限幅量纲错误**：每 tick 固定 0.05，控制节率=相机帧率 20~60fps 可变 → 摆速漂移且剧烈运动时恰好削减转向权限。已 dt 化（`max_steering_rate_per_s`，旧键 ×60 兼容）。
11. **脉冲 duty/amp/base 面板热改不生效**（仅频率每拍回写）。已修：每拍全量回写（相位连续）。
12. **观察期检测缺口计入接管计时**（β 超阈 100ms + 丢 400ms → 恢复即接管）。已修：缺口清锚点。
13. **脚本 GBK 崩溃在写报告之前**：三脚本 ✅ 打印致 UnicodeEncodeError，`latency_report.json` 丢。已修（stdout reconfigure utf-8，且报告先落盘后打印）。
14. **measure_loop_latency 口径**：ws 初始推送不排空（首两个 RTT 样本≈0 是假的）、视觉段与生产配置不一致（全分辨率默认参数 vs 生产 360p+锐化 0.6）、nan 误报超预算、退出码恒 0。已全修——**明早 M0 实测请用新版**：`python scripts\measure_loop_latency.py --camera 1 --server ws://127.0.0.1:8000 --exposure -8`。
15. 前端：cameraOn 前后端脱钩（刷新即破）改后端快照权威；i18n 全量（原全卡硬编码中文）；10Hz 轮询无互斥改串行+超时+离线徽标；「标定」按钮补齐；gating 对齐 `calibration_ready`。
16. `build_drift_clip` 多 tub 拼接时戳可回退为负（单段早退分支形同虚设）。已修（独立段传入）。

**🔵 其余修复**：EMA 冷启动（read/detect 首样本直赋）、`sent_messages` 无界（deque 1000）、session events 有界（500）、dt=0 静止衰减清零笔误、`anchor()` 清 `_last_t`、preview_hz≤0 语义反转、`install_drive_hooks` 幂等、`/config` 422 校验、record 启动失败回滚、tub 路径毫秒防冲突、API 阻塞调用 to_thread、webrtc monotonic 节拍/黑帧缓存、施密特触发+时间加权 duty、泵异常日志、stop 跳过卡死泵的并发 close、两处空洞断言修复（观察期零下发语义化、smoke EMA>0）。

### 9.3 审计确认无问题的部分（反向结论，同样重要）

- 几何/估计数学核心：单应性、位姿解算、轨迹/速度着色、FpsMeter 无 off-by-one/除零/环回错误
- 脉冲发生器相位连续性正确；session 非法转换全拒；三条退出路径消息层面均带 MODE 0+零油门
- 浏览器并发控制门禁完整；时基统一（monotonic）；静止衰减帧率无关
- FrameSource 锁粒度正确，读路径无撕图；前端卸载清理（轮询/PC/MJPEG）无泄漏
- 控制器 NaN 抛错由循环护栏兜底（先红测试验证：解算异常按丢帧、循环异常才看门狗，两路径分离）

### 9.4 遗留（需实车/需决策，勿盲目再改）

- §6 全部实车核对项（看门狗三链路、MODE 0→2、多 client 仲裁、半径环符号 M2 实证）
- 低速 β 噪声 vs 接管判据（§6 第 4 条，M4 前评估）
- 仿真玩具模型无「脉冲频率→半径」耦合——半径环离线验收需先扩展仿真模型（M2 后做）
- JPEG 预览编码挤占处理线程（15Hz 每 4 帧 ~10ms）——若实测 camera_fps 吃紧，挪消费侧/线程池
- 视觉参数（PoseSolver window/max_jump_m 等）未进 /config 白名单——实车整定不便时可加
- drift_vision.py(467 行)/drift_engine.py(532 行) 超计划 <300 行目标——功能稳定后再拆（overlay 绘制可独立成模块）
- DriftCard 的 `camera_running` 依赖后端快照字段（已上线），明早真机冒烟：刷新页面验证按钮态
