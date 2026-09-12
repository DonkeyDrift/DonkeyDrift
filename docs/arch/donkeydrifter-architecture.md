# DonkeyDrifter 架构分析

- 版本基线：`donkeydrifter 0.1.2`（派生自 Donkeycar 5.2.0）
- 分析日期：2026-09-11
- 分析范围：核心框架（`donkeycar/`）、Web UI（`web_ui/`）、启动器（launcher）、漂移子系统、脚本工具与测试体系
- 语言：Python 3.11（`>=3.11,<3.12`）、TypeScript / React

---

## 1. 项目概述

### 1.1 定位与来源

DonkeyDrifter 是一个开源的小型自动驾驶 / **漂移（Drifting）遥控车**软件平台，由 Donkeycar 派生而来（独立分支，非官方）。它在保留 Donkeycar 的核心范式——**Vehicle + Part 模块化车体架构、Tub 数据工作流、神经网络 pilot 训练、模拟器支持**——的基础上，新增/强化了四块能力：

1. **统一 Web UI**：FastAPI 后端 + React/Vite 前端，覆盖驾驶、Tub 管理、训练、模型竞技场、车连接器等全部工作流；
2. **Launcher 启动服务**（默认端口 8090）：浏览器端 TUI 菜单与进程拉起，内置 WebSocket↔PTY 终端；
3. **第三视角俯拍漂移控制系统**：AprilTag 视觉位姿 + 侧滑角 β 估计 + 级联 PID，是当前迭代的重心；
4. **MUS4 ESP32 固件一等集成**：串口 Pilot 控制、遥测配对、车端 Drifter Console 发现与代理。

### 1.2 品牌与包结构

| 场景 | 名称 |
|---|---|
| 品牌 / PyPI 包名 | `donkeydrifter` |
| 实际源码包 | `donkeycar/`（历史兼容，被 `donkeydrifter` 别名） |
| 新推荐 import | `import donkeydrifter as dk` |
| 兼容 import | `import donkeycar as dk` |
| CLI 命令 | `donkey`（入口：`donkeycar.management.base:execute_from_command_line`） |

`donkeydrifter/__init__.py` 通过自定义 `MetaPathFinder`（`_DonkeyDrifterAliasFinder`）把 `donkeydrifter.*` 子模块透明映射到 `donkeycar.*`，并在导入时检测 PyPI 上游 `donkeycar` 包是否覆盖本地兼容包（给出卸载/修复指引）。许可证为 Apache-2.0（新增部分）+ 上游 MIT（Donkeycar 源出部分）。

### 1.3 规模

- Python：约 327 个文件、2.7 MB 源码（不含前端与测试）
- 前端：78 个 TSX + 37 个 TS 文件
- 测试：75 个 `test_*.py`（单元 + 集成），约 764 KB

---

## 2. 总体架构（分层视图）

```
┌─────────────────────────────────────────────────────────────────────┐
│  浏览器  DonkeyDrifter Web UI (React SPA, Vite)                      │
│  FlowPage: Drive → Tub → Trainer → PilotArena (+ Connector/Console) │
│  输入: 虚拟摇杆/键盘/手柄/陀螺仪   输出: 视频/遥测/图表/进度          │
└───────────────┬─────────────────────────────────────────────────────┘
                │ REST (/api/*)   WebSocket (/api/drive/ws)   SSE   WebRTC
┌───────────────▼─────────────────────────────────────────────────────┐
│  Web 服务层  FastAPI 后端 (web_ui/backend)   Launcher (:8090)        │
│  routers: config/tub/trainer/drive/arena/connector/launch/           │
│           console/simcollect/drift                                   │
│  引擎: drift_engine / connector_engine / trainer_engine /            │
│        simcollect_engine / sync_recorder / web_online_trainer        │
│  任务模型: JobManager 单例 + asyncio.Queue + SSE 日志流               │
└───────────────┬─────────────────────────────────────────────────────┘
                │ WebSocket (role=car) / 串口 (HOSTIP) / SSH / rsync
┌───────────────▼─────────────────────────────────────────────────────┐
│  车端 Python 运行时  manage.py drive (模板生成)                       │
│  Vehicle 驱动循环 + Parts: 相机/控制器/Pilot/执行器/TubWriter/...     │
│  DriveApiBridge: 遥测上行 + 控制下行 + WebRTC 视频上行                │
└───────────────┬─────────────────────────────────────────────────────┘
                │ 串口 (t:s 控制帧 / $IMU / T 帧) / GPIO / I2C / PWM
┌───────────────▼─────────────────────────────────────────────────────┐
│  硬件层  MUS4 ESP32 固件 (RC接收机→舵机/电调, MODE 0/1/2)             │
│          SBC 上位机 / 相机 / IMU / 编码器 / 里程计 / 舵机 / 电调       │
└─────────────────────────────────────────────────────────────────────┘

  ── 旁路子系统 ──
  俯拍漂移: USB 相机 → AprilTag 检测 → 单应性 → 位姿/β → 级联PID → ws→车
  训练:     本地 (donkey train) / 远程 GPU (SSH) / 我的电脑 (mypc) / 模拟器采集
  模拟器:   gym_donkeycar / DonkeySim (Mac SSH 采集) / DonkeyGymEnv
```

数据面按频率分工：**WebRTC/WS 高频控制与视频、SSE 后台任务日志、REST 命令与查询**。

---

## 3. 核心框架：Vehicle + Part + Memory

这是整个车端软件的骨架，源自 Donkeycar 的"机器人即数据流"设计：

### 3.1 Memory —— 通道内存总线

`donkeycar/memory.py` 的 `Memory` 本质是带批量读写语义的 `dict`：

- `put(keys, outputs)` / `get(keys)` 按**通道名**（如 `cam/image_array`、`user/angle`、`pilot/throttle`）读写；
- 支持多键批量；`__setitem__` 支持 list/tuple 键自动展开。

所有 Parts 之间**不直接引用**，只通过通道名松耦合，这是模板可组合性的基础。

### 3.2 Part —— 部件契约

`donkeycar/vehicle.py` 定义部件接口（鸭子类型，无强制基类）：

| 方法 | 语义 |
|---|---|
| `run(*inputs)` | 同步执行（主线程，顺序调用） |
| `run_threaded(*inputs)` | 线程化部件从线程读取最新输入并执行 |
| `update()` | 线程体（被 daemon 线程反复调用，通常内部无限循环） |
| `shutdown()` | 可选清理，`Vehicle.stop()` 时调用（容忍缺失） |

### 3.3 Vehicle —— 驱动循环

`Vehicle.add(part, inputs, outputs, threaded, run_condition)` 注册部件；`start(rate_hz)` 启动主循环（默认频率由模板 `DRIVE_LOOP_HZ` 决定）：

1. 为所有 `threaded` 部件创建 daemon 线程并启动；
2. 固定频率循环 `update_parts()`：按 `run_condition`（从 Memory 读布尔值）决定部件是否运行 → 从 Memory 取 inputs → 调 `run`/`run_threaded` → 输出写回 outputs 通道；
3. 循环用 `1/rate_hz` 补睡眠，超时打 jitter 警告；
4. `stop()` 遍历调用 `shutdown()`。

`PartProfiler` 记录每个部件每次运行的耗时，输出 max/min/avg 与 50/90/99/99.9 百分位表（`verbose` 时每 200 帧打印），用于定位瓶颈部件。

### 3.4 配置系统

`donkeycar/config.py`：

- `Config` 只认**全大写**属性（`from_pyfile` 用 `exec` 执行配置文件模块）；
- `load_config()` 加载链：cwd 下 `config.py` → 同目录 `myconfig.py` 个人覆盖（第二个 Config 覆盖第一个）；
- `createcar` 生成车项目时，`cfg_<template>.py` → `config.py`，`myconfig.py` 模板附**全部注释掉的默认项**供用户按需打开。

---

## 4. Parts 部件库（`donkeycar/parts/`）

按职责分类：

| 类别 | 部件 | 说明 |
|---|---|---|
| 相机/视觉 | `camera.py`：PiCamera/Webcam/CSICamera/V4LCamera/MockCamera/ImageListCamera；`cv.py`、`image.py`、`image_transformations.py`、`object_detector/`（StopSignDetector）、`oak_d.py`（OAK-D）、`realsense*`、`leopard_imaging.py` | 多后端相机抽象，模板按 `CAMERA_TYPE` 选择 |
| 惯性/位姿 | `imu.py`、`gps.py`（NMEA）、`odometer.py`、`encoder.py`、`tachometer.py`、`pigpio_enc.py`、`pose.py`（BicyclePose/UnicyclePose 融合里程计+运动学）、`kinematics.py`（Bicycle/Unicycle/Inverse* 运动学模型与归一化） | 状态估计基础；kinematics 被漂移控制复用 |
| 测距/激光 | `lidar.py`（RPLidar/YDLidar + BreezySLAM 建图）、`tfmini.py` | 可选 |
| 执行器 | `actuator.py`：PWMSteering/PWMThrottle + PCA9685/PiGPIO/ServoBlaster/VESC/Maestro/L298N 后端；Arduino 系 ArdPWMSteering/ArdPWMThrottle/ArdImu/ArdRc/ArdModeCmd/RcRecordMerge；`pins.py`（Pin 抽象与 `pwm_pin_by_id` 解析）、`sombrero.py`、`robohat.py`、`teensy.py` | ESP32/Arduino 串口执行链路 |
| 控制器 | `controller.py`（PS3/PS4/Xbox/Logitech/Nimbus/WiiU/RC3Chan 摇杆家族 + `get_js_controller` 工厂）、`serial_controller.py`、`telemetry.py`（MQTT 遥测） | 人工输入 |
| AI 推理 | `keras.py`（KerasPilot 家族：Categorical/Linear/Memory/IMU/Behavioral/Localizer/LSTM/3D_CNN/Latent + CNN 构建函数）、`interpreter.py`（Keras/TFLite/TensorRT/FastAI 推理后端解耦）、`fastai.py`、`coral.py`、`pytorch/`（ResNet18 + Lightning 训练） | `utils.get_model_by_type` 按类型名分发 |
| 数据存储 | `datastore.py`（旧 Tub，归档）、`datastore_v2.py`（Seekable 行偏移索引 + Catalog/Manifest，mmap 只读）、`tub_v2.py`（Tub/TubWriter/TubWiper，PNG 图像） | 录制与回放 |
| 通信 | `network.py`（ZMQ/UDP/TCP/MQTT Pub/Sub）、`drive_api_bridge.py`（**DriveApiBridge**：车端↔Web UI 的 WS 桥 + WebRTC 视频上行） | 车联网关 |
| 漂移/控制扩展 | `drift_replay.py`（DriftReplayPart：按录制时间戳回放 (angle,throttle)）、`transform.py`（Lambda/TriggeredCallback/DelayedTrigger/PIDController/twiddle）、`launch.py`（AiLaunch）、`behavior.py`、`path.py`（CsvPath/CTE/PID_Pilot）、`throttle_filter.py`、`explode.py`、`fps.py`、`perfmon.py`、`logger.py`、`file_watcher.py`、`provisioning.py`、`auth_part.py` | 模板组装用的"胶水"部件 |
| 仿真 | `dgym.py`（DonkeyGymEnv：gymnasium 包装、断线重连、myconfig 热加载）、`simulation.py` | 无硬件训练 |

---

## 5. 车项目模板与 manage.py（`donkeycar/templates/`）

`donkey createcar --template X` 把 `<template>.py` 复制为用户车目录的 `manage.py`，`cfg_<template>.py` 复制为 `config.py`。模板即**用 Vehicle.add 组装 Parts 的蓝图**：

| 模板 | 组成要点 |
|---|---|
| `basic` | 相机 → Web 控制器(DriveApiBridge) → KerasPilot → DriveMode → PCA9685 → TubWriter（`run_condition='recording'`） |
| `complete`（旗舰） | 仿真/相机分派、里程计（Bicycle/UnicyclePose）、LIDAR、FPS、web+摇杆双控制器、Pipe、ThrottleFilter、UserPilotCondition（user/pilot 模式切换）、LED、RecordTracker、模型热重载（FileWatcher+DelayedTrigger）、BehaviorPart、IMU、StopSignDetector、AiLaunch、DriveMode、TubWriter、MQTT 遥测、TCP 推流、ProvisioningPart；**漂移链路**：`ScaleToArdPwm`（-1~1→-100~100）→ ArdPWMSteering/Throttle（threaded，串口→ESP32）+ ArdRc/ArdModeCmd/ArdImu + DriftReplayPart + RcRecordMerge（MANUAL 模式录制合并 rc 实值） |
| `just_drive` | 常量控制最小示例 |
| `arduino_drive` | 摇杆 + ArduinoFirmata |
| `simulator` | DonkeyGymEnv 全仿真 |
| `cv_control` | 视觉巡线 |
| `path_follow` | CTE + PID 路径跟踪 |
| `square` | 定时跑方块 |
| `train` | 训练入口脚本 |

最终 `V.start(rate_hz=cfg.DRIVE_LOOP_HZ)` 启动。

---

## 6. 数据管道：Tub 与训练

### 6.1 Tub 存储

- **Tub v1**（`datastore.py`）：JSON 记录 + 图像文件，已被 v2 取代（归档）。
- **Tub v2**（`parts/tub_v2.py` + `parts/datastore_v2.py`）：可寻址（Seekable 行偏移索引）、Catalog/Manifest 元数据、mmap 只读，`image_array` 存 PNG（gray16 存 16bit PNG）。**Web UI 的 Tub 管理、漂移同步录制（SyncRecorder）都写 v2**。

### 6.2 训练管线（`donkeycar/pipeline/`）

- `types.py`：`TubRecord`（缓存策略 NOCACHE/BINARY/ARRAY）、`TubDataset`、`Collator`（RNN 连续序列）；
- `sequence.py`：`TubSequence` + 变换管线（build_pipeline/map_pipeline）；
- `database.py`：`PilotDatabase` 维护 `models/database.json`（模型编号命名、增删、分组统计）；
- `training.py`：`BatchSequence` 把序列经 x_transform（归一化 + TRANSFORMATIONS + 训练期 AUGMENTATIONS）/ y_transform 生成 `tf.data`；`train()` 流程：数据库登记 → 建模型 → 数据集切分 → 训练（EarlyStopping + ModelCheckpoint）→ 写 `*_meta.json` 损失元数据 → 转 tflite/trt → 入库；
- `augmentations.py`：albumentations 数据增强；
- PyTorch 路线：`parts/pytorch/torch_train.py`（Lightning + TorchTubDataModule），CLI `train --framework` 分发。

### 6.3 远程训练

- `management/train_online.py`：`OnlineTrainer` SSH 打包上传数据到远程 GPU 训练并回传模型；
- Web 后端 `web_online_trainer.py`：把 Rich 输出改为队列 emit，SSH PTY 流式读远端输出、解析进度（1h 超时）；
- `mypc_probe.py`：paramiko 无副作用预检远端环境（平台/Python 路径/donkey CLI），返回可操作建议。

---

## 7. CLI、TUI 与 Launcher

### 7.1 CLI 命令表（`donkeycar/management/base.py`）

| 命令 | 功能 |
|---|---|
| `createcar` | 生成车项目目录（模板 + config + train.py） |
| `findcar` | nmap 局域网找车 IP |
| `calibrate` | PWM/PCA9685/Arduino 舵机油门校准 |
| `tubplot` / `tubhist` | 数据可视化（预测对比图 / 直方图） |
| `evaluate` | **分支新增**：模型在 tub 上的 corr/MAE/RMSE 量化评估 + 数据健康度告警（左右失衡/直行占比过高会提示"模型退化为预测均值"） |
| `makemovie` | tub → 视频（可叠加 salient 激活图） |
| `createjs` | 交互生成 `my_joystick.py` |
| `cnnactivations` | 卷积层激活可视化 |
| `train` | tensorflow/pytorch 训练 |
| `models` | PilotDatabase 查询 |
| `ui` | Kivy 桌面 GUI（`management/ui/`，历史） |
| `tui` | **rich/prompt_toolkit 交互终端**（无参数默认进入）：建车/开项目/清数据(回收站)/备份/恢复/本地训练/在线训练/驾驶/Drifter Console/Web UI |
| `web` | 拉起 FastAPI 后端 + Vite 前端；生产模式构建 dist 由后端托管 SPA（同端口），dev 模式 Vite HMR + `/api` 代理 |
| `drive` | `web` 基础上再启动 `manage.py drive`，注入 `DRIVE_API_SERVER_URL=ws://127.0.0.1:<backend>/api/drive/ws` 让车端以 `role=car` 回连 |
| `installweb` | 安装/修复 Web UI 依赖（pip fastapi 栈 + npm install） |

### 7.2 Launcher 服务（`donkeycar/launcher/server.py`，:8090）

纯标准库 `ThreadingHTTPServer` 实现，**零第三方依赖**：

- 内嵌 `MENU_HTML` 复刻 TUI 菜单（项目选择、备份/恢复、启动 web/drive、Drifter Console、Kimi/DSH AI 编码工具）；
- `/terminal` + `/terminal/ws`：**手写 RFC6455 帧解析**的 WebSocket↔PTY 桥（xterm.js 前端），会话与连接解耦（`?session=` 重连、1MiB 回放缓冲补发、15 分钟宽限期回收）；
- `/api/launch/drive`：`kill_previous_car_processes` → 复用/新起 `donkey web`（等登记文件 + HTTP 探测回读真实端口）→ 起 `manage.py drive`；
- `/api/data/clear|backup|restore`、`/api/createcar`、`/api/projects/open` 等，均带安全校验（目录白名单、防路径穿越、回收站+回滚）；
- `dsh_web.py` / `kimi_web.py`：启动/复用 AI 编码工具 Web（实例登记 + 特征探测 + 幂等自愈补丁）。

### 7.3 实例登记与复用（`donkeycar/webui_instance.py`）

`donkey web` / `donkey drive` / Launcher / TUI 四条启动链路统一走 **"先找存活实例→复用；没有才新起并登记"**：

- 登记文件 `~/.donkeycar/webui.json`（pid/backend_port/frontend_port/started_at，原子替换）；
- `find_live_instance`：pid 存活 + 后端 `/docs` 与前端 `/` 探测均通，否则视为陈旧登记清除；
- `drive.pid` 记录车进程，重启时**只杀 `manage.py drive` 进程**（按 /proc cmdline 精确匹配），Web 前后端保留复用——解决摄像头等硬件占用只需重启车进程的问题。

---

## 8. Web UI

### 8.1 FastAPI 后端（`web_ui/backend/main.py`）

- `FastAPI(title="DonkeyDrifter")`，CORS 全开；`cache_control_middleware` 给 `/assets/` 加 immutable 缓存、HTML 加 no-cache；
- **10 个路由组**：`/api/config`、`/api/tub`、`/api/trainer`、`/api/drive`、`/api/arena`、`/api/connector`、`/api/launch`、`/api/console`、`/api/simcollect`、`/api/drift`；
- 生产模式静态托管 SPA：`/assets` 挂 StaticFiles，`/{full_path:path}` 回退 index.html（`api/*` 保持 404）；
- startup 钩子 `drift.install_drive_hooks()` 完成漂移引擎与 drive WS 的进程内接线。

**统一任务模型**：`TrainingJobManager` / `ConnectorJobManager` / `SimCollectJobManager` 三个单例——Job 持有 `asyncio.Queue log_queue` + 进程句柄；路由 `asyncio.create_task` 后台执行；SSE 端点消费队列推送 `log/progress/status`（keep-alive 心跳）。本地训练用 `create_subprocess_exec` 逐行读流，正则解析 `Epoch/steps/loss` 计算 `globalPercent` 与 `loss_history`。

### 8.2 驾驶链路（`routers/drive.py` + `parts/drive_api_bridge.py`）

WebSocket `/api/drive/ws` 是**双角色桥**：

- `role=car`（车端）：心跳、`telemetry` 原样广播、base64 `frame`、`webrtc_stats`、状态提取（num_records/drive_mode/recording）；
- `role=client`（浏览器）：控制字段转发车端（60Hz angle/throttle/drive_mode）、`car_connection`/`car_state` 推送、WebRTC 信令中继、模拟器恢复开关。

车端 `DriveApiBridge` 是模板里"Web 控制器"部件：连上 WS 后把遥测上行、把 `send_to_car` 下行命令写入 `user/angle`、`user/throttle` 等通道；并内置 aiortc `VideoStreamTrack` 把相机帧 WebRTC 上行（低延迟），MJPEG (`/api/drive/video`) 作兜底。遥测广播前同步调用 `telemetry_hooks`——漂移引擎的订阅点。

### 8.3 前端（`web_ui/frontend/`）

**技术栈**：Vite 6 + React 18.3 + TypeScript 5.8、react-router（HashRouter）、zustand 5、chart.js、Tailwind 3.4（`theme-mus4` 深色 / `theme-light` 浅色双皮肤）、i18n（12 命名空间 × zh/en）。

**路由与页面**：

- `App.tsx`：HashRouter + ErrorBoundary + `useIdlePrefetch`（空闲预取懒加载 chunk）；
- **FlowPage 单页流程**（核心设计）：Drive → Tub → Trainer → Pilot 四个 section 纵向堆叠，IntersectionObserver scroll-spy + rAF 平滑滚动 + `content-visibility:auto`；滚出视口的 section 会停掉视频/WS/快捷键；
- `DrivePage`：实时驾驶（详见下）；`TubManagerPage` = TubLibrary（会话播放器，60fps 墙钟调度 + LRU 图像缓存 + canvas 直绘）+ TubEditor（chart.js 图表、框选删除/恢复、undo/redo）；`TrainerPage`：local/online/mypc 三模式；`PilotArenaPage`：回放 tub 并排多模型推理对比；`CarConnectorPage`/`DrifterConsolePage`/`DonkeyMenuPage`：iframe 嵌入车端 ESP32 设置页 / Drifter Console / launcher 菜单。

**DrivePage 细节**：

- 视频：**WebRTC 优先**（`useDriveWebRtcVideo`：REST+WS 信令协商、`requestVideoFrameCallback` 算 FPS/p95 延迟回传、指数退避重试降级）+ **常驻预载 MJPEG 兜底**；
- 输入：虚拟摇杆（Pointer Events）/ 键盘（I/K/J/L，60fps rAF 平滑）/ 手柄（Gamepad API）/ 陀螺仪（DeviceOrientation）；
- 控制：`useDriveControlLoop` 60Hz setInterval 经 WS 下发完整控制状态；UI 50ms 同步一次；
- 遥测：100Hz 进 **useTelemetryStore 旁路**（不触发 React 渲染），图表 `subscribe` + 128 点环形缓冲 + `chart.update('none')` 5fps 重绘；
- 模式：DriveModeSelector（user/local_angle/local ⇄ ESP32 rc_mode 0/1/2）；录制、模型选择、参数面板（PID，防抖持久化）、热键；
- 漂移卡：DriftCard（`/api/drift/*` 100ms 轮询 + 独立 WebRTC 俯拍预览）；SimCollectCard（SSE 任务）。

**状态与 Hooks**：四个 zustand store（全局/驱动参数/遥测旁路/Flow 活跃区）；hooks 分输入类、链路类（WS 心跳重连）、任务类（SSE 优先 + 轮询兜底）三组。

### 8.4 通信模式汇总

| 通道 | 用途 | 频率/特点 |
|---|---|---|
| REST `/api/*` | 命令、配置、查询 | 任务启动即返回 `job_id` |
| WS `/api/drive/ws` | 控制上行、状态/遥测下行、WebRTC 信令 | 控制 60Hz、遥测 100Hz |
| SSE | trainer/connector/simcollect 任务日志与进度 | keep-alive 心跳 |
| WebRTC | 车端视频（浏览器↔车端 P2P 中继信令）、俯拍预览 | 低延迟 60fps，QoS 统计回传 |
| MJPEG | WebRTC 不可用时的兜底视频 | 轮询 |

---

## 9. 第三视角俯拍漂移控制系统（项目特色）

背景：车载视角行为克隆训练无法让车进入/保持漂移（β 侧滑角在车载画面中不可观测）。方案 C："**状态估计 + 经典反馈控制先行，学习留门**"（RFC：`docs/Rfc/overhead-drift-control.md`）。

```
人 RC 起漂(MODE 0) ──> |β|≥15° 持续500ms ──> 自动接管(MODE 2 FULL_AUTO)
                                            │
    USB 相机 ──> AprilTag 检测(tag36h11) ──> 单应性 → 车位姿(x,y,heading)
                                            │
    陀螺仪遥测(100Hz) + 位姿差分 ──互补滤波──> β 估计
                                            │
    外环(慢): β*/半径误差 → 转向偏置 + 油门脉冲参数(f,D,A,T_base)
    内环(60Hz): yaw-rate 跟踪 → 转向 P+I + delta 限幅
    油门脉冲发生器: 相位连续脉冲, 参数平滑过渡
                                            │
    ws ──> SBC ──> 串口 t:s 帧 ──> ESP32 执行
                                            │
    看门狗(丢帧>200ms/ws断线/失稳) ──> Park + MODE 0 交还人工
    RC CH4 拨杆物理夺回(固件最高优先级)
```

模块（`web_ui/backend/`）：

| 模块 | 职责 |
|---|---|
| `drift_vision.py` | `FieldHomography`（cv2.findHomography，npz 持久化）；`solve_tag_pose` 标签四角解位姿（`heading_offset_deg` 贴标补偿）；`PoseSolver` 滑动窗中值+跳变拒绝；`FrameSource` 泵线程只留最新帧；AprilTagDetector（pupil-apriltags，downscale=2）/ USBCamera / Fake 可注入 |
| `state_estimator.py` | `BetaEstimator` 互补滤波：陀螺积分预测 + 视觉 α=0.3 校正；`β = wrap(heading − course)`；静止时按时间常数衰减、`anchor()` 抑漂移 |
| `drift_controller.py` | 级联控制：外环前馈 `v/R` + `k_beta·(β*−β)` → `r_des`（限幅 300°/s），半径误差修正脉冲频率；内环 yaw-rate 误差→转向 P+I（抗饱和）+ 每 tick 0.05 转向 delta 限幅；`PulseGenerator` 相位连续油门脉冲（freq/duty/amp/base）；`Watchdog` 200ms |
| `drift_session.py` | `DriftSession` 状态机 `IDLE → CALIBRATE/RECORD/AUTO_OBSERVE → AUTO_ENGAGED`；接管判定、看门狗回 IDLE、`SessionEvent` 事件时间线 |
| `drift_engine.py` | 编排（模块级单例）：`send_sink` 注入为 `drive_state.send_to_car`；遥测经 `telemetry_hooks → ingest_telemetry_msg`（gz rad/s→deg/s）；`start_camera_loop` 后台线程 读帧→检测→位姿→β→控制；泵线程死亡触发看门狗（car_mode=0 + 零油门交还人工）；`auto_active()` 使 drive WS 丢弃浏览器控制 |
| `drift_webrtc.py` | aiortc 服务端推流叠加帧（标签绿框 + 车头红箭头），60fps 节拍 |
| `sync_recorder.py` | `SyncRecorder` 以相机帧时戳为基准，`TelemetryBuffer`（bisect + 线性插值，<10ms 误差）对齐车端遥测（rc 60Hz / imu 100Hz），`ThrottlePulseAnalyzer` 边沿检测提取点动 freq/duty/amp，写入 tub v2（`overhead/image_array`、`pose/*`、`state/beta|yaw_rate|throttle_pulse_*`、`rc/*`、`imu/gyr_z`）——Web UI Tub 页直接可见 |
| `throttle_analysis.py` | 离线分析录制 tub：Pearson 相关（r<−0.6 判单调）+ 三档分桶参数表，供外环整定初值 |

配套脚本：`scripts/generate_apriltag.py`（打印标签）、`calibrate_field_homography.py` / `calibrate_overhead_camera.py`（棋盘格标定）、`simulate_drift_controller.py`（离线闭环仿真）、`analyze_throttle_pulses.py`（点动机理分析）、`build_drift_clip.py`（漂移段导出回放 clip）、`measure_loop_latency.py`（端到端延迟分段实测）。

---

## 10. 远程连接与分布式能力

### 10.1 Connector（`connector_engine.py` + `remote_car_client.py` + `routers/connector.py`）

- 纯命令构造（SSH/rsync），**路径正则防注入**；`check_connection / list_tubs / list_models / pull_tub / push_pilots / remote drive 启停`；
- 远端 drive 停止带**多重身份核对**（pid 文件匹配 + `ps` 参数含 manage.py drive + `/proc/<pid>/cwd` 等于 car_dir 才 `kill -SIGINT`）；
- rsync 进度从 `to-check=x/y` 解析进 SSE；
- `discover_console`：`network_utils.discover_hosts`（并发 TCP 探测端口 80，候选来自网关 /24、WSL nameserver、RFC1918 子网）匹配 Drifter Console HTML 特征；
- 配置持久化 `~/.donkeycar_web_connector.json`。

### 10.2 SimCollect（`simcollect_engine.py`）

通过 SSH 在 Mac 上跑 DonkeySim 自动采集（`DONKEY_SIM_STEPS/KP/KD/THROTTLE/...` 环境变量注入），正则解析 `[collect] step/cte/speed` 与 `RESULT`，SSE 推流；停止用 `start_new_session` + `killpg`。

### 10.3 在线/异地训练

`trainer_engine.py` 的 `TrainingJob.mode ∈ local/mypc/online`；mypc 模式先 `probe_mypc_environment` 预检（paramiko），SSH 凭据仅会话内传递、不落盘。

---

## 11. MUS4 ESP32 固件集成

- **执行**：模板 `ScaleToArdPwm`（-1~1 → -100~100）+ ArdPWMSteering/Throttle 经串口下发；`ArdModeCmd` 切换固件 MODE 0/1/2（MANUAL/SEMI/FULL_AUTO），`ArdRc` 读 RC 值，`ArdImu` 读 IMU；
- **遥测**：固件 `$IMU` 100Hz 全模式、T 帧（RC 实际值）60Hz 仅 MANUAL 模式；经 SBC → ws 到达后端广播；
- **HOSTIP 上报**：launcher 后台线程每 30s 向串口写 `HOSTIP|<ip>\n`（115200 8N1，发送前重设 termios 自愈），让车端知道笔记本 IP；
- **Drifter Console 发现**：`dc_discovery.py` 探测 `http://<ip>/api/status` 的 `version=`/`ap_ip=` 特征（先 AP 固定地址 192.168.4.1 再扫 /24，60s 缓存）；
- **代理**：`routers/console.py` `/api/console/proxy/<ip>/<path>` 同源反向代理 ESP32 HTTP API（仅 IPv4 防 SSRF，`/update` OTA 放宽 300s）；
- **安全闭环**：RC CH4 拨杆物理夺回（固件最高优先级，不依赖软件）；漂移看门狗自动交还人工。

---

## 12. 模拟器与 Gym

- `donkeycar/gym/gym_real.py`：`DonkeyRealEnv`（gym.Env，MQTT 遥控**真车**）+ `remote_controller.py`；
- `parts/dgym.py`：`DonkeyGymEnv` 对接 gym_donkeycar（gymnasium），支持断线重连与 myconfig 热更新；
- `simulator` 模板直接消费（pos/cte/gyro/vel/lidar 记录）；SimCollect 用 DonkeySim 自动采集。

---

## 13. scripts 工具链（`scripts/`）

| 类别 | 脚本 |
|---|---|
| 漂移标定/分析 | `generate_apriltag.py`、`calibrate_field_homography.py`、`calibrate_overhead_camera.py`、`simulate_drift_controller.py`、`analyze_throttle_pulses.py`、`build_drift_clip.py`、`measure_loop_latency.py` |
| 模型转换/优化 | `convert_to_tflite.py`、`tflite_convert.py`、`freeze_model.py`、`tflite_profile.py`、`migrate_model_names.py` |
| 训练辅助 | `multi_train.py`（多配置并行）、`preview_augumentations.py` |
| 性能/调试 | `profile.py`、`profile_coral.py`、`remote_cam_view.py`、`remote_cam_view_tcp.py`、`graph_listener.py`、`salient_vis_listener.py`、`hsv_picker.py`、`pigpio_donkey.py` |
| 数据迁移 | `convert_to_tub_v2.py` |

---

## 14. 测试体系

- `donkeycar/tests/`（单元）：核心（vehicle/memory/kinematics/pipeline/launch）、各 parts（keras/torch/actuator/controller/odometer/lidar/telemetry/tachometer/robohat/serial2）、存储（datastore_v2/catalog_v2/seekable_v2/tub_v2）、漂移专有（drift_replay/drive_api_bridge/rc_record_merge/dgym_reconnect）、CLI（tui 系列/web_command/evaluate/cli_branding）；
- `tests/`（集成）：launcher 系列（menu/terminal/dsh/kimi/drive_launch）、train 模板 fp16、online_trainer_workspace、web_production_mode、migration、upstream_override_warning、tub 图像缓存、自动刷新等；
- `donkeycar/benchmarks/`：旧/新 Tub 写删读计时基准。

---

## 15. 关键启动链路（实例复用）

```
donkey tui ──> 菜单选择
donkey web ──────────┐
donkey drive ────────┤ find_live_instance? ── 是 ──> 复用 (只起车进程)
launcher /api/launch ┘        │ 否
                              ▼
              起 uvicorn 后端 + Vite/静态前端
              ┌─ drive: 注入 DRIVE_API_SERVER_URL, 起 manage.py drive
              └─ 登记 ~/.donkeycar/webui.json (原子替换)
              退出时 remove_instance(only_pid=自身)
```

---

## 16. 安全设计要点

- SSH 路径/命令注入校验（remote car client）；
- 远端 drive 停止多重身份核对（pid + cmdline + cwd）；
- ESP32 代理仅 IPv4（防 SSRF）；
- launcher createcar 目录白名单、restore 防路径穿越、磁盘空间检查、trash + 回滚；
- 漂移看门狗（丢帧/断线/失稳 → Park + MODE 0 交还人工）+ RC 物理夺回；
- 终端无认证（声明为家庭可信网络）；
- 上游 `donkeycar` 包覆盖检测（导入时告警 + 修复指引）。

---

## 17. 架构特点总结

1. **松耦合数据流内核**：Vehicle + Part + Memory 让"车"成为可任意组合的部件流水线，模板即蓝图，硬件差异被 Parts 抽象吸收；
2. **一栈式 Web 工作流**：驾驶/数据/训练/评估全部收敛到浏览器，REST/WS/SSE/WebRTC 四种通道按 频率与语义 分工，遥测旁路 + 单页流程保证 100Hz 数据不卡 UI；
3. **多链路进程编排**：CLI/TUI/Launcher/Web 四条启动路径通过实例登记文件统一"复用优先"，进程级安全清理（只杀车进程）；
4. **经典控制 + 学习留门**：漂移子系统以可解释的 β 估计 + 级联 PID 先实现闭环（数据同时进 tub 为模仿学习留接口），离线仿真/标定工具闭环支撑整定；
5. **车-云-端协同**：SSH/rsync 连接远程车与 GPU 训练机、SimCollect 自动采集、mypc 探测预检，构成从采集到部署的完整链路；
6. **兼容与品牌双轨**：`donkeydrifter` 新名 + `donkeycar` 兼容层 + `donkey` CLI 不变，迁移成本低。
