# Car Connector 功能分析、程序架构与移植优化方案

## 背景

当前 `Car Connector` 仍停留在旧版 Kivy 管理界面中，入口位于 `donkeycar/management/ui/ui.kv`，页面结构位于 `donkeycar/management/ui/car_screen.kv`，核心控制逻辑位于 `donkeycar/management/ui/car_screen.py`。新版 `web_ui` 已完成 Tub Manager、Trainer、Drive、Calibrate、Pilot Arena 等页面迁移，但 `web_ui/frontend/src/components/Layout.tsx` 中的 Car Connector 仍是禁用占位项。

因此，Car Connector 的下一步目标应当是迁移到 FastAPI + React 的统一 Web UI，并复用现有 Drive API Bridge、Trainer 在线训练 SSH 能力和前端暗色 UI 组件体系。

## 现有功能边界

旧版 Car Connector 提供四类能力：

1. **连接状态检查**
   - 依赖配置项：`PI_USERNAME`、`PI_HOSTNAME`。
   - 每 3 秒执行一次 `ssh -o ConnectTimeout=3 PI_USERNAME@PI_HOSTNAME date`。
   - 成功则显示已连接，失败则显示断开。

2. **远程目录与 Tub 拉取**
   - 通过 `ssh user@host "ls <car_dir>"` 列出远程车端目录。
   - 用户输入车端 Donkeycar 目录，默认来自 rc 文件中的 `robot_car_dir`，默认值 `~/mycar`。
   - 选择远端 Tub 目录后执行：
     - `rsync -rv --progress --partial user@host:<car_dir>/<tub_dir>/ <DATA_PATH>`
     - 如果用户勾选创建新目录，则去掉末尾 `/`，让 rsync 将整个 tub 目录复制到本地数据目录下。
   - 拉取结束后刷新旧版 Tub 管理器，并尽量合并原先已删除记录索引。

3. **Pilot 推送**
   - 本地来源为 `MODELS_PATH`。
   - 远端目标为 `<car_dir>/models`。
   - 支持按格式过滤：`h5`、`savedmodel`、`tflite`、`trt`。
   - 始终包含 `database.json`，未选择格式时同步全部模型。
   - 通过 `rsync -rv --progress --partial --include=... --exclude=*` 实现增量同步。

4. **远程启动/停止驾驶**
   - 可选模型类型，旧页面默认 `tflite_linear`。
   - 可选远端 pilot；未选择时直接远程执行 `./manage.py drive`。
   - 选择模型时远程执行：`./manage.py drive --type <model_type> --model <car_dir>/models/<pilot>`。
   - 依赖命令输出中的 `PID: <pid>` 捕获远端进程 PID。
   - 停止时执行 `ssh user@host kill -SIGINT <pid>`。

## 现有程序架构

### 旧版 Kivy 架构

```text
ui.kv
└── ScreenManager
    └── CarScreen
        ├── car_screen.kv      # 视觉结构和按钮绑定
        └── car_screen.py      # SSH、rsync、进程控制、进度解析
```

`CarScreen` 将 UI 状态、远端连接、命令拼接、进度解析和跨页面刷新混在同一个类中：

- `connected()` 负责轮询 SSH 连通性。
- `list_remote_dir()` 负责远端目录枚举。
- `pull()` 负责拉取 tub。
- `send_pilot()` 负责推送模型。
- `show_progress()` 解析 rsync 输出并驱动 Kivy 进度条。
- `drive()` 远程启动 `manage.py drive`。
- `stop()` 远程发送 `SIGINT`。

### 新版 Web UI 相关架构

```text
web_ui/backend/main.py
├── /api/config
├── /api/tub
├── /api/trainer
├── /api/drive
└── /api/arena

web_ui/frontend/src/App.tsx
├── /
├── /trainer
├── /drive
├── /calibrate
└── /pilot
```

当前可复用能力：

- `web_ui/backend/routers/trainer.py` 已有配置读取、任务启动、SSE 日志流模式。
- `web_ui/backend/trainer_engine.py` 已有后台 Job、日志队列、停止事件模式。
- `web_ui/backend/web_online_trainer.py` 已基于 `OnlineTrainer` 封装 Paramiko SSH 连接并向 Web UI 发送进度。
- `web_ui/backend/routers/drive.py` 已提供车端 WebSocket 接入、模型加载、校准命令、MJPEG 视频流与客户端广播。
- `web_ui/frontend/src/services/api.ts` 已统一封装 axios API。
- `web_ui/frontend/src/pages/DrivePage.tsx` 已完成车端实时驾驶控制，与 Car Connector 的“启动驾驶”能力存在职责重叠。

## 核心问题

1. **旧实现存在命令拼接风险**
   - `list_remote_dir()`、`drive()`、`stop()` 中存在字符串拼接 shell 命令。
   - 车端目录、模型名等值来自 UI 或远端列表，迁移时必须避免 shell 注入。

2. **UI 与业务逻辑强耦合**
   - Kivy `CarScreen` 同时负责状态、命令、进度和页面刷新，不适合直接搬到 Web UI。

3. **远程驾驶职责需要重新划分**
   - 旧 Car Connector 的 Drive Car 是通过 SSH 启动远端 `manage.py drive`。
   - 新 Drive 页面则依赖车端主动运行 `DriveApiBridge` 连接 `/api/drive/ws?role=car`。
   - 迁移后 Car Connector 更适合作为“车端进程管理与文件同步”页面，而实时操控继续留在 Drive 页面。

4. **连接配置来源不统一**
   - 旧版使用 `PI_USERNAME`、`PI_HOSTNAME`。
   - 在线训练使用 `train_online.conf` 的 `[Remote] host/user/password/remote_dir_base/python_path`。
   - 新 Web UI 需要统一远端连接配置，避免用户在多个地方重复填写。

5. **rsync 进度解析不适合 HTTP 请求阻塞返回**
   - 拉取 Tub、推送 Pilot 都可能耗时较长。
   - 应采用后台 Job + SSE 日志/进度流，避免单个 HTTP 请求长时间占用。

## 推荐目标架构

### 后端模块划分

新增：

```text
web_ui/backend/
├── routers/
│   └── connector.py
├── connector_engine.py
└── remote_car_client.py
```

职责建议：

| 模块 | 职责 |
|------|------|
| `routers/connector.py` | HTTP API、请求校验、Job 创建、SSE 暴露 |
| `connector_engine.py` | 拉取 Tub、推送 Pilot、启动/停止远程驾驶等长任务编排 |
| `remote_car_client.py` | SSH/SFTP/rsync/远程命令的安全封装 |

`main.py` 中注册：

```python
from routers import config, tub, trainer, drive, arena, connector

app.include_router(connector.router, prefix="/api/connector", tags=["connector"])
```

### 前端模块划分

新增：

```text
web_ui/frontend/src/
├── pages/
│   └── CarConnectorPage.tsx
├── components/connector/
│   ├── ConnectionCard.tsx
│   ├── RemoteDirectoryCard.tsx
│   ├── PullTubCard.tsx
│   ├── PushPilotsCard.tsx
│   ├── RemoteDriveCard.tsx
│   └── ConnectorLogPanel.tsx
└── hooks/
    └── useConnectorJob.ts
```

并在 `App.tsx` 增加 `/connector` 路由，在 `Layout.tsx` 中将 Car Connector 从禁用占位改成可点击导航。

### 数据流

```text
React 页面
  ↓ HTTP
/api/connector/config
/api/connector/status
/api/connector/remote/list
/api/connector/tub/pull
/api/connector/pilots/push
/api/connector/drive/start
/api/connector/drive/stop
  ↓
ConnectorJobManager
  ↓
RemoteCarClient
  ↓
SSH / rsync / Paramiko / 远端 manage.py
```

长任务统一返回 `job_id`，前端通过 SSE 订阅：

```text
GET /api/connector/jobs/{job_id}/events
```

## API 设计建议

### 配置与连接

```http
GET /api/connector/config
POST /api/connector/config
POST /api/connector/status
```

建议配置模型：

```json
{
  "host": "donkeycar.local",
  "user": "pi",
  "port": 22,
  "car_dir": "~/mycar",
  "auth_mode": "agent_or_key",
  "key_path": "~/.ssh/id_rsa"
}
```

说明：

- 优先支持 SSH agent/key，不建议在 Web UI 中长期保存明文密码。
- 若必须兼容密码，应只写入本机配置文件，并在 UI 中明确提示风险。
- 可从 `PI_USERNAME`、`PI_HOSTNAME` 初始化默认值，但 Web UI 自身应使用独立 connector 配置。

### 远端目录与模型列表

```http
GET /api/connector/remote/list?path=~/mycar
GET /api/connector/remote/models?car_dir=~/mycar
GET /api/connector/remote/tubs?car_dir=~/mycar
```

返回示例：

```json
{
  "items": [
    { "name": "data", "type": "directory", "path": "~/mycar/data" },
    { "name": "models", "type": "directory", "path": "~/mycar/models" }
  ]
}
```

### Tub 拉取

```http
POST /api/connector/tub/pull
```

请求：

```json
{
  "car_dir": "~/mycar",
  "remote_tub": "data",
  "local_data_path": "./data",
  "create_new_dir": false
}
```

响应：

```json
{ "job_id": "...", "status": "running" }
```

### Pilot 推送

```http
POST /api/connector/pilots/push
```

请求：

```json
{
  "car_dir": "~/mycar",
  "local_models_path": "./models",
  "formats": ["tflite"]
}
```

`formats` 为空数组时代表同步全部格式。

### 远程驾驶进程管理

```http
POST /api/connector/drive/start
POST /api/connector/drive/stop
GET /api/connector/drive/status
```

请求：

```json
{
  "car_dir": "~/mycar",
  "model_type": "tflite_linear",
  "pilot": "mypilot.tflite",
  "bridge_server_url": "ws://<pc-ip>:8000/api/drive/ws"
}
```

建议远程启动命令从旧版：

```bash
source env/bin/activate; cd ~/mycar; ./manage.py drive --type ... --model ...
```

逐步升级为显式支持 DriveApiBridge 的启动方式：

```bash
DRIVE_API_SERVER_URL=ws://<pc-ip>:8000/api/drive/ws python manage.py drive --type ... --model ...
```

远程停止不建议仅依赖旧输出中的 `PID: <pid>`。建议补充：

- 后端保存 start job 捕获到的 PID。
- 远端写入 pidfile，例如 `<car_dir>/.donkeycar/drive.pid`。
- 停止时优先读取 pidfile 并验证命令行匹配 `manage.py drive` 后再发送 `SIGINT`。

## 迁移方案

### 阶段 1：后端能力抽取

1. 新增 `remote_car_client.py`。
2. 将连接检查、目录列表、模型列表封装为可单测的纯后端服务。
3. 优先使用 Paramiko 执行远端命令；文件同步可保留 rsync 子进程，但参数必须数组化，不使用 shell。
4. 对远端路径做边界校验：禁止空路径、控制字符、换行、命令分隔符。
5. 引入 Job 模型，参考 `trainer_engine.py` 的队列日志和停止事件。

验收：

- 可通过后端 API 检查连接。
- 可列出远端 `car_dir`、`models` 和 Tub 目录。
- 单元测试覆盖路径校验、格式过滤、rsync 参数生成。

### 阶段 2：Tub 拉取与 Pilot 推送

1. 实现 `/api/connector/tub/pull` 和 `/api/connector/pilots/push`。
2. 后端解析 rsync `to-chk` / `to-check` 输出并转成结构化进度事件。
3. 前端展示进度条、日志、成功/失败状态。
4. Tub 拉取成功后，触发前端提示用户重新加载 Tub，或自动调用现有 `loadTub()` 重新加载目标目录。

验收：

- 可从车端拉取 Tub 到本地 `DATA_PATH`。
- 可按模型格式推送到车端 `models` 目录。
- 中断、失败、认证错误有明确错误展示。

### 阶段 3：远程驾驶启动/停止

1. 实现远程 `manage.py drive` 启动任务。
2. 将 `DRIVE_API_SERVER_URL` 注入远端进程，确保车端启动后主动连接当前 Web UI 后端。
3. 启动后前端引导用户跳转到 `/drive` 页面查看车端在线状态和视频流。
4. 实现停止按钮，优先优雅发送 `SIGINT`。

验收：

- 在 Car Connector 启动车端后，Drive 页面显示车端在线。
- 远端进程停止后，Drive 页面连接状态变为离线。
- 不选择 pilot 时可启动手动驾驶；选择 pilot 时可启动自动驾驶模型。

### 阶段 4：前端完整迁移

1. 新增 `CarConnectorPage.tsx`。
2. 新增导航 `/connector`。
3. 页面分为：连接配置、远端目录、拉取 Tub、推送 Pilots、远程驾驶进程、日志/进度。
4. 复用现有 `Button`、`Card`、`Input`、`StatusBar` 风格。
5. 所有长任务统一使用 `useConnectorJob` 管理状态和 SSE。

验收：

- 旧 Kivy 页面所有核心操作在 Web UI 可完成。
- 用户无需打开旧 UI 即可完成“同步数据 → 同步模型 → 启动车端 → 进入 Drive 控制”。

## 优化方案

### 安全性优化

1. **禁止 shell=True 和拼接命令字符串**
   - 本地执行统一使用参数数组。
   - 远端执行命令应进行参数引用或通过 SFTP 上传小脚本再执行固定入口。

2. **远端路径白名单与规范化**
   - `car_dir` 默认为用户 home 下目录。
   - 禁止 `;`、`&&`、`|`、反引号、换行等控制字符。
   - 模型名只能来自远端 `models` 列表，不接受任意前端输入路径。

3. **认证方式优化**
   - 推荐 SSH key/agent。
   - 不默认保存密码。
   - 配置文件权限应尽量限制为当前用户可读写。

4. **进程停止安全校验**
   - kill 前检查 PID 对应命令是否为目标 `manage.py drive`。
   - 避免误杀远端其他进程。

### 可用性优化

1. **连接诊断**
   - 将“无法连接”拆分为：DNS/主机不可达、认证失败、car_dir 不存在、models/data 不存在。

2. **任务可取消**
   - rsync 拉取/推送支持 Stop 按钮。
   - 停止时终止本地 rsync 子进程，并返回 canceled 状态。

3. **结构化日志**
   - 后端输出 `info`、`progress`、`warning`、`error`、`done` 事件。
   - 前端按类型显示，不再只展示原始 stdout。

4. **模型格式默认值**
   - 默认只选择 `tflite`，因为新版 Web UI 和树莓派部署更常用 tflite。
   - 提供“一键全选/同步全部”。

5. **与 Drive 页面联动**
   - 远程启动成功后显示“打开驾驶控制台”按钮。
   - 如果 `/api/drive` 已显示车端在线，Car Connector 中的驾驶启动按钮应提示“车端已在线”。

### 架构优化

1. **复用在线训练远端连接配置**
   - 可将 Trainer RemoteConfig 与 ConnectorConfig 抽象为同一 RemoteConnectionConfig。
   - 避免 `PI_USERNAME/PI_HOSTNAME`、`train_online.conf`、Connector 配置三套并存。

2. **统一 JobManager**
   - Trainer 和 Connector 都需要长任务、日志、停止、状态查询。
   - 可先复制轻量实现，稳定后再抽象通用 `web_ui/backend/job_manager.py`。

3. **Drive 启动职责收敛**
   - Car Connector 只负责远端进程生命周期。
   - Drive 页面只负责实时控制和状态显示。
   - 不在 Car Connector 页面内重复实现摄像头画面和控制杆。

4. **逐步废弃旧 Kivy 入口**
   - Web UI 稳定后，可在旧 Kivy Car Connector 中增加迁移提示。
   - 不建议立即删除旧实现，先保留一个版本周期作为回退。

## 测试策略

### 后端单元测试

建议新增：

```text
web_ui/backend/tests/test_connector.py
```

覆盖：

- 配置读取/保存。
- 路径校验拒绝危险输入。
- rsync 参数生成正确。
- 模型格式过滤规则正确。
- 连接失败返回明确错误。
- start/stop drive 的命令构造不使用 shell 拼接。

### 后端集成测试

- 使用 mock SSH client 模拟远端目录、远端模型、远端命令输出。
- 使用 fake rsync 进程输出 `to-chk=...`，验证进度事件。
- 验证取消任务能终止子进程并更新状态。

### 前端测试与手动验证

- TypeScript 检查：`npm run check`。
- Lint：`npm run lint`。
- 手动验证路径：
  1. 打开 `/connector`。
  2. 保存连接配置。
  3. 检查连接状态。
  4. 列出远端 Tub 和模型。
  5. 拉取 Tub 并观察进度。
  6. 推送 tflite 模型并观察进度。
  7. 启动车端驾驶进程。
  8. 跳转 `/drive` 验证车端在线、视频流和控制指令。
  9. 回到 `/connector` 停止远端进程。

## 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 用户机器没有 rsync | Tub/Pilot 同步不可用 | 启动前检测 rsync，给出安装提示；长期可增加 SFTP fallback |
| Windows 原生环境 rsync 不稳定 | Web UI 同步失败 | WSL/ Git Bash 环境提示；文档注明依赖 |
| SSH 认证方式复杂 | 用户无法连接 | 支持 key/agent，错误信息细化；保留密码选项但不推荐 |
| 远端路径包含空格或特殊字符 | 命令失败或安全风险 | 参数化、引用和路径校验 |
| 远程 `manage.py drive` 不输出 PID | 停止按钮失效 | 增加 pidfile 或 `pgrep -f` 校验策略 |
| DriveApiBridge 未配置服务端 URL | 车端启动后无法连回 Web UI | 启动命令显式注入 `DRIVE_API_SERVER_URL` |
| 拉取 Tub 后本地 Tub 状态过期 | 页面仍显示旧数据 | 成功后自动刷新或提示重新加载 |

## 推荐实施顺序

1. 后端 `RemoteCarClient` + 连接/目录 API。
2. 前端 `/connector` 基础页面和连接状态。
3. Tub 拉取 Job + SSE 进度。
4. Pilot 推送 Job + 格式过滤。
5. 远程 Drive 启停 + 与 `/drive` 联动。
6. 安全加固、测试补齐、旧 Kivy 页面迁移提示。

## 结论

Car Connector 不应简单逐行移植 Kivy 逻辑，而应拆分为“远端连接服务 + 长任务引擎 + Web 页面”。核心文件同步能力可以继续复用 rsync，但必须通过后端 Job 和结构化进度事件暴露给前端；远程驾驶能力应从“在 Car Connector 中控制车辆”转变为“启动车端 DriveApiBridge 进程，然后交给 Drive 页面实时操控”。这样可以最大化复用现有 Web UI 架构，同时降低安全风险和维护成本。
