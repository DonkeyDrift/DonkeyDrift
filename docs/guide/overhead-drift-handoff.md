# 俯拍漂移项目：状态交接与后续工作（供后续 AI/开发者继续开展）

> 更新：2026-08-30 晚（实车调试日结束）｜分支 `feat/overhead-drift-control`（未合并 main）｜测试基线 **222 passed**（`cd web_ui/backend && python -m pytest tests/ -q`）

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

### 2.2 待用户验证（清僵尸进程后未再实测）⚠️

- 启动相机 → 预览出画面、fps≈60、推车不掉帧（黑屏事件后尚未复验，见 §4.1）

### 2.3 关键运行参数（实测确定，勿改）

| 参数                   | 值                          | 说明                               |
| -------------------- | -------------------------- | -------------------------------- |
| 相机 index             | **1**                      | 笔记本内置相机占用 0                      |
| 标签                   | tag36h11 ID **0**（备用 ID 1） | 车顶黑框中心对准回正中心                     |
| heading\_offset\_deg | **180**                    | 贴标方向与角序约定差 180°                  |
| 场地                   | 1.0×1.0 m                  | 西南原点                             |
| 分辨率/帧率               | 1280×720\@60 MJPG          | 检测 downscale=2（360p 检测、角点还原全分辨率） |

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

## 5. 下一步工作（按序执行，含命令与验收标准）

### 第 0 步：复验相机链路（清僵尸进程后）

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
- [x] 检测降采样余量：360p 检测下标签约 39px 接近 AprilTag 下限——若实测丢帧率升高，回退 `AprilTagDetector(downscale=1)`（routers/drift.py camera\_start）
- [ ] `dsc` 遥测字段语义核对（第二阶段蒸馏前）
- [x] 服务端多 client 仲裁（AUTO 期间其他浏览器标签页仍可能发控制）——已实现服务端门禁：AUTO（观察/接管）期间浏览器控制字段在 drive ws 一律丢弃并回发 `control_rejected`（routers/drive.py + `drift_engine.auto_active()`，测试 tests/test\_drift\_control\_arbitration.py），待实车核对
- [ ] MODE 0→2 固件跳变实车核对
- [ ] 分支未合并 main

## 7. 代码地图

| 模块                                                   | 职责                                                                        | 测试                           |
| ---------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------- |
| `web_ui/backend/drift_vision.py`                     | 单应性/位姿解算(heading\_offset)/PoseSolver/USBCamera/FrameSource 泵/检测(降采样)/叠加绘制 | test\_drift\_vision.py       |
| `web_ui/backend/state_estimator.py`                  | β 估计（heading 域互补滤波+静止衰减）                                                  | test\_state\_estimator.py    |
| `web_ui/backend/drift_controller.py`                 | 级联 PID+油门脉冲发生器+看门狗                                                        | test\_drift\_controller.py   |
| `web_ui/backend/drift_session.py`                    | 会话状态机（观察→β 稳定→接管）                                                         | test\_drift\_session.py      |
| `web_ui/backend/sync_recorder.py`                    | 遥测插值对齐+tub v2 录制                                                          | test\_sync\_recorder.py      |
| `web_ui/backend/drift_engine.py`                     | 编排：相机循环/FpsMeter/分段计时/display\_frame                                      | test\_drift\_engine.py       |
| `web_ui/backend/drift_webrtc.py`                     | aiortc 60fps 推流（DisplayFrameTrack 360p）                                   | test\_drift\_router.py       |
| `web_ui/backend/routers/drift.py`                    | API：state/session/camera/config/frame.jpg/frame.mjpg/webrtc/offer         | test\_drift\_router.py       |
| `web_ui/frontend/src/components/drive/DriftCard.tsx` | 前端卡片（WebRTC 预览+MJPEG 兜底+参数面板+localStorage）                                | —（build 验证）                  |
| `scripts/generate_apriltag.py`                       | tag36h11 打印件生成（螺旋位序！）                                                     | test\_apriltag\_generator.py |
| `scripts/simulate_drift_controller.py`               | 离线闭环仿真（β=25.00°/极差 0.01°）                                                 | —                            |

**协作纪律**（用户强调）：不臆测、不懂就问、对齐后动手；TDD 红-绿-重构；诚实区分物理保证与实验结论；改行为先写失败测试；所有回复/注释/提交信息简体中文。
