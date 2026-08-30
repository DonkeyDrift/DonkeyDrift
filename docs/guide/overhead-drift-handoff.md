# 俯拍漂移项目：状态交接与后续工作（供后续 AI/开发者继续开展）

> 更新：2026-08-30 深夜（运动丢检测排障闭环，相机链路复验通过；overlay 加粗加长+速度着色轨迹+深蓝 β 航迹箭；当日成果/经验/教训总结见 §8）｜分支 `feat/overhead-drift-control`（未合并 main）｜测试基线 **254 passed**（`cd web_ui/backend && python -m pytest tests/ -q`；TestCameraLoopSmoke 在重负载机器上偶发调度超时为既有抖动，deselect 新测试后仍复现）

## 0. 文档地图

| 文档                                                   | 用途                        |
| ---------------------------------------------------- | ------------------------- |
| `docs/Rfc/overhead-drift-control.md`                 | 总体设计（方案 C：状态估计+反馈控制，13 节） |
| `docs/plan/overhead-drift-control-implementation.md` | M0\~M5 里程碑实施计划            |
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
- [ ] 分支未合并 main
- [ ] `BetaEstimator.course_deg`（控制链路）仍是逐帧差分+半步外推，低速段被位姿噪声主导（§4.4 同款根因）；M4 闭环前评估换 0.2s 割线基线（显示链路已换 `trail_course_deg`）

## 7. 代码地图

| 模块                                                   | 职责                                                                        | 测试                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------- |
| `web_ui/backend/drift_vision.py`                     | 单应性/位姿解算(heading\_offset)/PoseSolver(跳变拒绝+恢复)/USBCamera(手动曝光)/FrameSource 泵/检测(降采样+锐化+全分辨率重试)/叠加绘制(加粗框箭+轨迹滑窗着色+β 深蓝航迹箭/trail\_course\_deg 割线方向) | test\_drift\_vision.py       |
| `web_ui/backend/state_estimator.py`                  | β 估计（heading 域互补滤波+静止衰减）                                                  | test\_state\_estimator.py    |
| `web_ui/backend/drift_controller.py`                 | 级联 PID+油门脉冲发生器+看门狗                                                        | test\_drift\_controller.py   |
| `web_ui/backend/drift_session.py`                    | 会话状态机（观察→β 稳定→接管）                                                         | test\_drift\_session.py      |
| `web_ui/backend/sync_recorder.py`                    | 遥测插值对齐+tub v2 录制                                                          | test\_sync\_recorder.py      |
| `web_ui/backend/drift_engine.py`                     | 编排：相机循环/FpsMeter/分段计时/display\_frame（逐帧透传+轨迹滑窗叠加）/命中率计数                                      | test\_drift\_engine.py       |
| `web_ui/backend/routers/drive.py`                    | 驾驶 ws/控制转发（AUTO 期间浏览器控制门禁，回发 control\_rejected）                                          | test\_drive.py + test\_drift\_control\_arbitration.py |
| `web_ui/backend/drift_webrtc.py`                     | aiortc 60fps 推流（DisplayFrameTrack 360p）                                   | test\_drift\_router.py       |
| `web_ui/backend/routers/drift.py`                    | API：state/session/camera/config/frame.jpg/frame.mjpg/webrtc/offer         | test\_drift\_router.py       |
| `web_ui/frontend/src/components/drive/DriftCard.tsx` | 前端卡片（WebRTC 预览+MJPEG 兜底+参数面板+localStorage）                                | —（build 验证）                  |
| `scripts/generate_apriltag.py`                       | tag36h11 打印件生成（螺旋位序！）                                                     | test\_apriltag\_generator.py |
| `scripts/simulate_drift_controller.py`               | 离线闭环仿真（β=25.00°/极差 0.01°）                                                 | —                            |

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
3. **假硬件泵要节流**：`FakeCamera` 自由空转吃满单核，重负载机器上全量测试偶发调度超时（`TestCameraLoopSmoke`）。处置：宽限 3s→10s + 对照实验（deselect 全部新测试仍挂 → 证明非回归）才放行；后续可把 FakeCamera 加上节拍 sleep 彻底根治。
4. **DSHOW 曝光语义是 log2 秒，不是微秒**：旧 `exposure_us` 参数语义错误且从未接线——删掉重构比保留兼容更安全。
5. **叠加绘制参数（线宽/箭头长度）须在真实 720p 预览上目测验收**：像素数阈值测试只能防回退，"太细太短"这种问题只有眼睛能发现。

**协作纪律**（用户强调）：不臆测、不懂就问、对齐后动手；TDD 红-绿-重构；诚实区分物理保证与实验结论；改行为先写失败测试；所有回复/注释/提交信息简体中文。
