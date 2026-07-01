# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

DonkeyDrifter 是一个基于 Donkeycar 派生的模块化 Python 自驾与漂移机器人平台，面向真实硬件、模拟器和教学实验场景。核心运行模型仍是把摄像头、控制器、执行器、训练/推理、数据记录等能力拆成可组合的 Part，并由 Vehicle 主循环串联。

- 当前版本：`0.1.2`，定义在 `donkeycar/_version.py`
- Python 版本：`>=3.11.0,<3.12`
- 主发行包：`donkeydrifter`，包元数据在 `setup.cfg`
- 推荐导入：`import donkeydrifter as dk`
- 兼容导入：`import donkeycar as dk`
- Python 实现包：当前仍在 `donkeycar/`，`donkeydrifter/` 提供公开兼容入口和子模块别名
- CLI 入口：`donkey = donkeycar.management.base:execute_from_command_line`
- 旧版车辆模板：`donkeycar/templates/`，新模板应优先使用 `donkeydrifter` 导入
- 统一 Web UI：`web_ui/`，后端 FastAPI，前端 React/Vite
- 许可证：DonkeyDrifter 新增/修改部分采用 Apache License 2.0；源自上游 Donkeycar 的部分继续保留 MIT License，详见 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 与 `LICENSES/MIT-donkeycar.txt`
- 上游来源：https://github.com/autorope/donkeycar

DonkeyDrifter 是独立派生项目，不代表 Donkeycar 官方维护团队，也不构成官方背书。

## CI/CD

GitHub Actions 工作流（`.github/workflows/`）：

- **`python-package-conda.yml`**：push/PR 触发，conda Python 3.11 环境，macOS + Linux 矩阵，安装 `.[pc,dev]` 后验证 `donkeydrifter`/`donkeycar` 双 import，构建包，运行 `pytest`。`fail-fast: false`。
- **`superlinter.yml`**：push/PR 触发，`github/super-linter@v4`，排除 `.css`/`.js`，`DISABLE_ERRORS: true`（非阻塞）。有 `.github/linters/.python-black` 配置。
- **`publish-pypi.yml`**：`v*` tag push 触发，build job 构建 sdist+wheel 并用 twine 校验，publish job 通过 trusted publishing 发布到 PyPI。

## 迁移兼容约定

1. 新代码和新模板优先使用 `donkeydrifter`。
2. 旧代码中的 `donkeycar` import 必须继续兼容。
3. `donkeydrifter/__init__.py` 通过 `sys.meta_path` 把 `donkeydrifter.<submodule>` 映射到 `donkeycar.<submodule>`；迁移时不要破坏这个别名层。
4. CLI 命令继续沿用 `donkey`。
5. 第一阶段不重命名旧 `DONKEY_*` 配置键。
6. 第一阶段不重命名 Web UI 的 `/api/*` 路径和驾驶 WebSocket 协议。
7. 不要盲目全局替换 Donkeycar 字样；上游来源、兼容说明和许可证文本中的 Donkeycar 名称应保留。

## 常用命令

### Python 包

```bash
pip install -e ".[dev]"
pip install -e ".[pc,dev]"
pip install -e ".[torch]"
pip install -e ".[pi]"
pip install -e ".[nano]"

pytest
make tests
pytest donkeycar/tests/test_vehicle.py -q
pytest donkeycar/tests/test_vehicle.py::test_name -v
pytest tests/test_restore_logic.py -q
pytest tests/test_restore_logic.py::test_name -v

mypy donkeycar/
python -m build --sdist --wheel
make package
```

仓库根目录没有 `setup.py`，打包应使用 `python -m build --sdist --wheel` 或 `make package`。

### 测试位置

- `donkeycar/tests/`：核心包单元测试。
- `tests/`：仓库根目录的迁移、恢复逻辑、模型命名和在线训练工作区测试。
- `web_ui/backend/tests/`：FastAPI 后端路由/服务契约测试。
- 前端目前主要依赖类型检查、ESLint、构建和手工运行页面验证。

### Web UI 后端

```bash
cd web_ui/backend
pip install -r requirements.txt
python main.py
python -m pytest tests -q
python -m pytest tests/test_connector.py -q
python -m pytest tests/test_arena.py::test_predict_returns_user_and_pilot_values -q
```

FastAPI 应用定义在 `web_ui/backend/main.py`，默认端口为 `8000`。

### Web UI 前端

```bash
cd web_ui/frontend
npm install
npm run dev
npm run build
npm run lint
npm run check
npm run preview
```

前端开发服务器默认端口为 `5188`。开发时 `/api` 由 Vite 代理到后端；也可通过 `VITE_API_BASE_URL` 覆盖 API base URL。

### 一键安装前后端依赖

```bash
pip install -e ".[pc,dev]"
donkey installweb --path ./web_ui
# 或者：
make installweb

donkey web --path ./web_ui
# 一体化启动并自动安装缺失依赖：
donkey web --path ./web_ui --install-deps
```

`donkey` 是 DonkeyDrifter 继续沿用的 CLI 命令，用于兼容 Donkeycar 生态和已有脚本。

### 运行时 CLI

```bash
donkey createcar --path ~/mycar --template complete
cd ~/mycar
donkey drive --path /home/dkc/projects/DonkeyDrift/web_ui --car ~/mycar   # 一键拉起 Web UI + 本机 Vehicle
python manage.py train --tub ./data/* --model ./models/mypilot.h5
donkey calibrate --channel 0
```

驾驶控制已统一迁移到新 Web UI（`http://localhost:5188/#/drive`，dev 模式由 Vite 提供）。`donkey drive` 一条命令同时拉起 web_ui 前后端与本机 `manage.py drive`，自动注入 `DRIVE_API_SERVER_URL`，车端 `DriveApiBridge` 以 `role=car` 连回 `ws://127.0.0.1:8000/api/drive/ws`。单独 `python manage.py drive` 也会默认连本机 8000 端口（需 `donkey web` 已在 8000 运行）。旧版 `LocalWebController`（端口 8887）已移除。这些命令通常在用户通过模板生成的车目录中执行。

## 核心架构

### Vehicle + Memory + Part

`donkeycar/vehicle.py` 的 `Vehicle` 是运行时主循环容器。`Vehicle.add(part, inputs, outputs, threaded, run_condition)` 将 Part 注册进循环；主循环按顺序从 `Memory` 读取 inputs，调用 Part 的 `run()`，再把结果写回 outputs。

`donkeycar/memory.py` 的 `Memory` 是简单键值存储。Part 之间不直接互相依赖，而是通过字符串 key 交换数据。新增数据通道时，要在模板或车辆组装代码中显式声明对应 inputs/outputs。

Part 不需要继承基类；通常只要实现 `run()`，线程型 Part 还会实现 `update()`，可选实现 `shutdown()`。

**Vehicle 生命周期：**
- `Vehicle.start(rate_hz=10, max_loop_count=None, verbose=False)`：启动所有 threaded Part 的 `update()` 线程（daemon），进入主循环调用 `update_parts()`。循环速率由 `rate_hz` 调控（`sleep_time = 1.0/rate_hz - elapsed`）。`finally` 块保证 KeyboardInterrupt 和异常时都会调用 `self.stop()`。
- `Vehicle.update_parts()`：遍历 parts 列表，对每个 part 检查 `run_condition`（从 Memory 读取的布尔条件），threaded part 调用 `run_threaded()`（通过 queue 与 `update()` 线程通信），普通 part 直接调用 `run()`。返回值非 None 时写入 Memory。
- `Vehicle.stop()`：依次调用所有 part 的 `shutdown()`，然后输出 `PartProfiler` 的性能报告（prettytable，包含各 part 的百分位耗时）。
- `Vehicle.remove(part)`：从 parts 列表中移除一个 part。`Vehicle.add(..., threaded=True)` 会调用 Part 的 `update()` 后台线程；并发写 Memory 时要避免多个 Part 写同一 key。

### 训练管道与 Tub v2 数据格式

**训练管道**（`donkeycar/pipeline/`）：

- `training.py` 的 `train()` 是训练入口：加载 tub → 划分 train/val → 构建 `BatchSequence`（TensorFlow）或 `TorchTubDataset`（PyTorch） → `model.train()` → 保存 loss 元数据 JSON → TFLite/TensorRT 转换 → 写入 `PilotDatabase`。
- `types.py`：`TubDataset` 加载 tub 为 `TubRecord` 列表；`TubRecord` 包装单条记录，支持三种 lazy 图像加载缓存策略（NOCACHE/BINARY/ARRAY）；`Collator` 构建 RNN 模型的序列记录。
- `database.py`：`PilotDatabase` 管理 `database.json`，方法包括 `generate_model_name()`、`delete_entry()`、`get_entry()`、`to_df()`、`to_df_tubgrouped()`。
- `augmentations.py`：`ImageAugmentation` 包装 albumentations，支持 BRIGHTNESS 和 BLUR 类型。
- `sequence.py`：`TubSequence`、`TfmIterator` 等构建 tf.data pipeline 的迭代器类型。

**Tub v2 数据格式**（`donkeycar/parts/tub_v2.py`、`donkeycar/parts/datastore_v2.py`）：

- `Tub` 类包装 `Manifest` 并管理 `images/` 子目录。支持多种数据类型：float、str、int、boolean、nparray、list/vector、image_array、gray16_array。
- `Manifest` 管理 `manifest.json`（inputs、types、metadata、catalog_metadata 等区段）。支持 session ID 追踪和 `delete_records()` 软删除（`deleted_indexes` 集合标记）、`restore_records()` 恢复。大 tub 通过 `_add_catalog()` 自动分割为 `catalog_0.catalog`、`catalog_1.catalog` 等多文件。
- `Catalog` 是新行分隔 JSON 文件（`.catalog`），配合 `Seekable` 类实现 O(1) 行定位（基于 `line_lengths` 索引，支持 mmap 只读模式）。
- `ManifestIterator` 提供惰性迭代并自动跳过 `deleted_indexes`。
- `TubWriter` 和 `TubWiper` 是对应的 Donkey Part，通过 Vehicle 循环写入/删除记录。

### Parts 系统

`donkeycar/parts/` 包含约 60 个 Part 模块，按功能分为：

- **执行器**：`actuator.py`、`pins.py`（PCA9685、PWMSteering、PWMThrottle、Arduino 串口控制器、ArdPWMSteering、ArdPWMThrottle、ArdImu 等）
- **摄像头**：`camera.py`（PiCamera、Webcam、CSICamera、V4LCamera、MockCamera、ImageListCamera 等）
- **控制器**：`controller.py`（JoystickController、RCReceiver）、`drive_api_bridge.py`（DriveApiBridge，车端 WebSocket client，连新 Web UI 后端 `/api/drive/ws`，替代已移除的 LocalWebController）
- **数据存储**：`tub_v2.py`、`datastore_v2.py`、`datastore.py`（TubHandler、TubManager）
- **模型推理**：`keras.py`（KerasPilot 基类及各模型架构）、`interpreter.py`（KerasInterpreter、TFLiteInterpreter、TensorRTInterpreter）、`fastai.py`、`pytorch/`
- **传感器**：`imu.py`、`lidar.py`、`gps.py`、`encoder.py`、`velocity.py`
- **运动学/路径**：`kinematics.py`、`path.py`
- **模拟器**：`simulation.py`、`dgym.py`
- **图像处理**：`image.py`、`image_transformations.py`、`cv.py`
- **桥接**：`drive_api_bridge.py`（连接 Web UI 后端，上报车辆状态）
- **其他**：`serial_port.py`、`network.py`、`ros.py`、`file_watcher.py`、`led_status.py`、`perfmon.py`、`text_writer.py`、`coral.py`（TPU）、`provisioning.py`（ESP32 WiFi 配网，见下文专节）等

所有 Part 遵循 duck-type 协议：`run()`（必须）、`update()`（threaded）、`shutdown()`（清理，可选）。模型推理 Part 继承 `KerasPilot` 基类，通过 `Interpreter` 子类封装不同推理后端。



### ESP32 串口协议与 Arduino Parts

`DRIVE_TRAIN_TYPE = "ARDUINO_CONTROLLER"` 时，系统通过串口连接 ESP32 固件（位于独立仓库 `/home/dkc/projects/Firmware/MUS4_FW/`）。

**串口上行协议（ESP32 → 上位机）：**

| 帧格式 | 频率 | 说明 |
|--------|------|------|
| `T{throttle}S{steering}\n` | ~60Hz | 人工油门/转向，仅 MANUAL 模式 |
| `M{mode}:P{park}\n` | 状态变化 + 1Hz 心跳 | 模式/手刹状态 |
| `$IMU,seq,ts_ms,ax,ay,az,gx,gy,gz\n` | ~100Hz | 加速度 m/s² + 陀螺仪 rad/s |

**串口下行协议（上位机 → ESP32）：**
`<thr>:<str>[:seq][*CRC]\n` — Pilot 控制指令

**actuator.py 中的 Arduino 相关类：**

- `Arduino` — 串口连接管理，`Arduino_readline()` 解析上行帧。`$IMU` 帧解析后存入 `self.imu_data` 并返回 `None`（不干扰控制流）。`T...S...` 和 `M:P` 帧解析后返回控制 dict。
- `ArdPWMSteering` / `ArdPWMThrottle` — 将 Vehicle 循环的 steering/throttle 映射为 PWM 指令下发。`ArdPWMSteering.update()` 作为唯一串口读取线程（threaded=True），调用 `Arduino_readline()` 消费所有帧。
- `ArdImu` — 从 `Arduino.imu_data` 读取缓存的 IMU 数据，以标准 Part 接口输出到 Memory 键 `imu/acl_x`、`imu/acl_y`、`imu/acl_z`、`imu/gyr_x`、`imu/gyr_y`、`imu/gyr_z`。`update()` 以 ~100Hz 轮询。

**模板集成逻辑：**
- `add_imu()` 在 `DRIVE_TRAIN_TYPE == "ARDUINO_CONTROLLER"` 时跳过本地 I2C IMU（返回 None）
- `add_drivetrain()` 在 ARDUINO_CONTROLLER 分支中，若 `cfg.HAVE_IMU` 则创建 `ArdImu` 并注册到 Vehicle
- IMU Memory key 与 I2C IMU 完全一致，Tub 录制和 KerasIMU 模型无需改动

**Arduino 配置键**（在 `myconfig.py` 中）：
`ARDUINO_SERIAL_PORT`、`ARDUINO_BAUDRATE`、`ARDUINO_TIMEOUT`、`ARDUINO_WRITE_TIMEOUT`、`ARDUINO_LOCK_TIMEOUT`、`ARDUINO_MAX_RETRIES`

### ESP32 WiFi 配网系统（Provisioning）

`donkeycar/parts/provisioning.py` 的 `ProvisioningPart` 通过 Linux 串口与 ESP32 配网固件通信，接收 WiFi 凭据后调用 `nmcli` 连接目标网络。这是与上面的 ARDUINO_CONTROLLER 控制串口**相互独立**的另一条串口链路，专用于初次上电配网。

**两种运行模式：**
1. **Donkeycar Part 模式**：`V.add(ProvisioningPart(...), threaded=True)`，通过 `provisioning/trigger` 触发，输出 `provisioning/status`、`provisioning/ssid`、`provisioning/ip`、`provisioning/error`。
2. **独立守护进程模式**：`python -m donkeycar.parts.provisioning`，无需 Vehicle 即可运行。

**配网串口协议（与控制串口协议不同）：**
- 下行（ESP32 → Linux）：`WIFI|<ssid>|<password>\n`
- 上行（Linux → ESP32）：`STATUS|CONNECTING\n` / `OK|<ip>\n` / `FAIL|<reason>\n`

**`WifiManager`** 封装 nmcli：断开当前热点、连接目标 WiFi、查询 DHCP 分配的 IPv4、扫描附近网络。ESP32 端固件保持不变，独立运行。

**Web UI 集成**：`web_ui/backend/routers/provisioning.py` 提供 WiFi 配网状态查询、手动触发连接、WiFi 扫描和串口扫描。Vehicle 未运行时，后端通过模块级 `_provisioning_state`（参考 `tub.py` 的 `current_tub` 模式）独立维护配网状态。

**模板集成**：`complete.py` 在 `cfg.PROVISIONING_ENABLED` 为真时创建 `ProvisioningPart` 并注册到 Vehicle。

**Provisioning 配置键**（在 `myconfig.py` 中，默认见 `cfg_complete.py`）：
`PROVISIONING_ENABLED`、`PROVISIONING_SERIAL_PORT`、`PROVISIONING_BAUDRATE`、`PROVISIONING_WIFI_INTERFACE`、`PROVISIONING_SERIAL_TIMEOUT`

### Python 包与 CLI

- `setup.cfg` 定义包名、依赖、extras 和 `donkey` console script。
- `donkeycar/management/base.py` 承载 `createcar`、`web`、`installweb` 等 CLI 子命令入口。
- 车辆应用由 `donkey createcar` 从 `donkeycar/templates/` 复制 `manage.py`、`config.py`、`myconfig.py`、`train.py` 等文件生成（`calibrate.py` 模板已随 LocalWebController 一并移除；标定改用 `donkey calibrate --channel` CLI 或 Web UI 标定页）。
- 配置通过 `dk.load_config()` 加载用户车目录中的 `config.py` 和 `myconfig.py`。
- `Config` 类（`donkeycar/config.py`）使用 `exec()` 执行 Python 文件加载配置；**仅 UPPERCASE 属性**被识别为配置键。提供 `from_pyfile()`、`from_object()`、`from_dict()`、`to_pyfile()`、`show()` 方法。
- `load_config()` 先加载 `config.py`，再用同目录的 `myconfig.py` 覆盖（merge 模式）。Web UI 的 `/api/config/save_training` 和 `/api/config/save_simulator` 端点负责往 `myconfig.py` 写入训练/模拟器配置。
- 每种模板类型有对应的 `cfg_*.py`（`cfg_basic.py`、`cfg_complete.py`、`cfg_simulator.py` 等），定义了该类型的默认配置。

### Web UI 架构

- 后端入口是 `web_ui/backend/main.py`，通过 `include_router` 挂载 `/api/config`、`/api/tub`、`/api/trainer`、`/api/drive`、`/api/arena`、`/api/connector`、`/api/provisioning`。
- 后端业务辅助模块包括 `trainer_engine.py`、`connector_engine.py`、`remote_car_client.py` 和 `web_online_trainer.py`。
- `/api/drive/ws` 是核心 WebSocket 端点（`role=car|client` 查询参数区分角色），用于车辆端上报状态+视频帧、客户端下发控制指令。`DriveState` 单例管理所有共享状态。
- `/api/drive` 还提供 MJPEG 视频（`/video`）、WebRTC 信令（`/webrtc/session`、`/webrtc/offer`、`/webrtc/answer`、`/webrtc/ice`）、参数持久化（`/params`）、模型加载（`/load_model`）、校准（`/calibrate`）。
- `/api/trainer` 和 `/api/connector` 均通过 SSE（Server-Sent Events）推送任务日志流（`/train/{job_id}/logs` 模式）。
- `/api/arena` 管理多 Pilot 并行加载/预测，使用 LRU 缓存淘汰预测结果。`/api/connector` 通过 SSH（paramiko）管理远程车辆。
- 前端入口是 `web_ui/frontend/src/main.tsx` 和 `App.tsx`，页面位于 `src/pages/`，复用组件位于 `src/components/`。
- 前端 API 客户端集中在 `web_ui/frontend/src/services/api.ts`；URL 拼接、WebSocket 地址和错误消息应复用这里的工具。
- 驾驶相关状态与输入逻辑分布在 `src/store/useDriveStore.ts`、`src/hooks/useDriveWebsocket.ts`、`src/hooks/useKeyboardDrive.ts`、`src/hooks/useGamepadDrive.ts`、`src/hooks/useGyroDrive.ts`、`src/hooks/useDriveWebRtcVideo.ts`、`src/hooks/useDriveControlLoop.ts`。

### 主要目录职责

- `donkeydrifter/`：DonkeyDrifter 推荐 import 入口，转发到当前实现包。
- `donkeycar/`：当前实现包和旧 import 兼容命名空间。
- `donkeycar/parts/`：可插拔硬件和算法组件。
- `donkeycar/templates/`：`donkey createcar` 使用的车辆应用模板和默认配置。
- `donkeycar/management/`：CLI 子命令入口和管理逻辑。
- `donkeycar/pipeline/`：训练管道、图像增强、序列数据处理和 Tub 数据集管理。
- `web_ui/`：新版统一管理界面。
- `docs/`：项目内设计、计划、验证和用户指南。

## 重要约定

1. 录制数据统一使用 Tub v2 格式，核心类为 `Tub`、`Manifest`、`Catalog`、`Seekable`，删除为软删除（`deleted_indexes` 集合），支持恢复。
2. TensorFlow 固定在 `2.15.*`，PyTorch 固定在 `2.1.*`，依赖大版本升级会影响模型兼容性。
3. `Config` 类通过 `exec()` 执行 Python 文件加载配置，仅 UPPERCASE 属性被视为配置键。`load_config()` 先加载 `config.py` 再用 `myconfig.py` 覆盖。
4. CLI 模板文件既是用户生成车应用的来源，也是配置契约的一部分；修改模板时通常要同步对应 `cfg_*.py` 和相关测试。
5. Web UI 前后端 API 前缀约定为 `/api`；不要绕过 `services/api.ts` 手写重复的 API base URL 逻辑。
6. 涉及硬件、路径、进程或网络行为时要避免只适配当前开发机。
7. 新功能或已有功能变更通常需要同步用户文档。
