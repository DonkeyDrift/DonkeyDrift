# Web 驾驶控制台 - 用户使用文档

## 概述

Web 驾驶控制台是 Donkeycar 新一代统一 Web UI 的核心模块，将原有的 Tornado 独立驾驶页面整合到 FastAPI + React 架构中。你可以在同一个网页上完成**数据录制 → 模型训练 → 实车驾驶 → 参数校准**全流程操作，不再需要切换端口和页面。

## 快速开始

### 1. 启动服务端

在电脑上启动 FastAPI 后端和前端开发服务器：

```bash
# 后端
cd web_ui/backend
pip install -r requirements.txt   # 首次运行
python main.py                    # 默认监听 0.0.0.0:8000

# 前端（新终端）
cd web_ui/frontend
npm install                       # 首次运行
npm run dev                       # 默认监听 localhost:5173
```

### 2. 车端接入（方式 A：推荐）

修改 `manage.py`，将 `LocalWebController` 替换为 `DriveApiBridge`：

```python
# 原来的导入
# from donkeycar.parts.controller import (JoystickController, LocalWebController, WebFpv)

# 替换为
from donkeycar.parts.controller import (JoystickController, WebFpv)
from donkeycar.parts.drive_api_bridge import DriveApiBridge
```

```python
# 原来的实例化
# ctr = LocalWebController(port=cfg.WEB_CONTROL_PORT, mode=cfg.WEB_INIT_MODE)

# 替换为
ctr = DriveApiBridge(server_url=cfg.DRIVE_API_SERVER_URL)
V.add(ctr,
      inputs=['cam/image_array', 'tub/num_records', 'user/mode', 'recording'],
      outputs=['user/angle', 'user/throttle', 'user/mode', 'recording', 'buttons'],
      threaded=True)
```

在 `myconfig.py` 中添加配置：

```python
# 电脑 IP 地址，车端通过此地址连接
DRIVE_API_SERVER_URL = "ws://192.168.1.100:8000/api/drive/ws"
```

然后正常启动车端：

```bash
python manage.py drive
```

> 详细的迁移步骤和兼容性说明见 [车端接入指南](drive-api-bridge-migration.md)

### 3. 打开驾驶控制台

浏览器访问 `http://localhost:5173/#/drive`，看到驾驶控制台页面。

---

## 页面导航

顶部导航栏包含四个入口：

| 入口 | 功能 |
|------|------|
| **Tub Manager** | Tub 数据浏览、编辑、删除 |
| **Trainer** | 模型训练（本地/在线）、模型管理 |
| **Drive** | 实车驾驶控制台 |
| **Calibrate** | 舵机与电调 PWM 校准 |

---

## 驾驶控制台功能详解

### 页面布局

```
┌────────────────────────────────────────────────────────────────┐
│  输入源切换 │ 驾驶模式 │ 录制按钮 │ WebSocket 连接状态        │
├──────────────────────────┬─────────────────────────────────────┤
│                          │  虚拟摇杆                           │
│  摄像头实时画面           │  转向/油门指示条                    │
│  (MJPEG 流，~20fps)      │  可编程按钮 (W1-W5)                 │
│                          │  控制参数折叠面板                    │
├──────────────────────────┴─────────────────────────────────────┤
│  车端连接 │ 驾驶模式 │ 录制状态 │ 已录制条数 │ 当前模型 │ 延迟  │
└────────────────────────────────────────────────────────────────┘
```

### 四种控制方式

通过顶部「输入源切换」按钮选择，同一时刻只有一种输入源生效：

#### 虚拟摇杆（默认）
- 点击/拖拽蓝色圆球控制转向和油门
- 横向：左负右正 → 转向
- 纵向：上正下负 → 油门（向前推加速）
- 松手自动回中归零

#### 键盘（IKJL）
- `I` 加速前进（按住加速，松开自动减速）
- `K` 刹车/倒车（按住减速/倒车，松开自动归零）
- `J` 左转（按住左转，松开自动回中）
- `L` 右转（按住右转，松开自动回中）

#### 游戏手柄
- 连接 USB/蓝牙手柄后自动检测，输入源按钮显示绿色小点
- 左摇杆横向 → 转向，纵向 → 油门
- 内置死区过滤，消除摇杆漂移

#### 设备陀螺仪
- 适用于带陀螺仪的手机/平板
- 横屏握持，左右倾斜控转向，前后俯仰控油门
- iOS 设备首次使用需授权运动权限

### 快捷键

| 按键 | 功能 |
|------|------|
| `I` | 加速前进 |
| `K` | 刹车/倒车 |
| `J` | 左转 |
| `L` | 右转 |
| `R` | 切换录制 |
| `M` | 循环切换驾驶模式 |
| `U` | 切换到人工模式 |
| `S` | 切换到 AI 转向模式 |
| `A` | 切换到全自动模式 |

### 驾驶模式

| 模式 | 说明 |
|------|------|
| **人工驾驶** | 完全由用户控制转向和油门 |
| **AI 转向** | AI 控制转向，用户控制油门 |
| **全自动** | AI 同时控制转向和油门 |

### 录制功能

- 点击顶部「开始录制」按钮或按 `R` 键切换录制状态
- 录制中按钮变红并显示实时时长（分:秒）
- 底部状态卡片实时显示已录制条数

### 可编程按钮

5 个按钮（W1-W5），点击后通过 WebSocket 下发 `buttons` 事件到车端。你可以在 `manage.py` 中自定义每个按钮的行为，例如切换模型、重置位置等。

### 控制参数面板

点击右侧「控制参数」折叠面板展开，包含两组参数：

**PID 平滑参数**（影响键盘输入手感）

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| 比例系数 Kp | 0 - 3 | 0.8 | 响应强度 |
| 积分系数 Ki | 0 - 1 | 0.0 | 累积误差修正 |
| 微分系数 Kd | 0 - 0.1 | 0.05 | 抑制振荡 |

**响应速率参数**

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| 回中速度 | 0 - 2 | 0.35 | 松开按键后自动回正的速度 |
| 转向角速度 | 0 - 3 | 1.2 | 按住转向键时每秒增长的角度量 |
| 加速度变化率 | 0 - 3 | 1.0 | 油门上升斜率 |
| 刹车变化率 | 0 - 3 | 1.2 | 油门下降斜率 |

**参数管理**
- 参数变更后 500ms 自动保存到本地和服务器
- 点击「重置默认」恢复出厂值
- 点击「导出」下载为 JSON 文件
- 点击「导入」从 JSON 文件加载参数

---

## 校准页面

访问顶部导航「Calibrate」进入舵机与电调校准页面。

### 使用方法

1. 确保车端已连接（底部状态显示「在线」）
2. 拖动滑杆调整 PWM 值
3. 点击每项右侧的「发送」按钮实时测试当前值
4. 确认无误后点击顶部「保存全部到车端」持久化

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 左转极限 PWM | 460 | 舵机向左打满时的脉冲宽度 |
| 右转极限 PWM | 290 | 舵机向右打满时的脉冲宽度 |
| 全油门前进 PWM | 500 | 电调最大前进脉冲宽度 |
| 油门零点 PWM | 370 | 电机静止时的脉冲宽度 |
| 全油门倒车 PWM | 220 | 电调最大倒车脉冲宽度 |

> **安全提示**：油门相关参数请从小值开始测试，确认车轮转向正确后再逐步增大。

---

## 模型管理联动

在 Trainer 页面的 Trained Models 列表中，每个模型行右侧有以下操作按钮：

| 按钮 | 功能 |
|------|------|
| ⬇ 下载 | 将 .tflite 模型文件下载到本地 |
| ➤ 加载到车 | 通过 WebSocket 下发模型路径到车端，自动加载 |
| 📋 复制路径 | 复制模型文件绝对路径到剪贴板 |
| 🗑 删除 | 删除模型及其关联的预览图和元数据 |

点击「加载到车」后，车端自动加载该模型，你可以在 Drive 页面切换到 AI 转向或全自动模式测试效果。

---

## API 接口一览

所有驾驶相关接口挂载在 `/api/drive` 前缀下：

| 方法 | 路径 | 说明 |
|------|------|------|
| `WS` | `/ws?role=car` | 车端 WebSocket 连接 |
| `WS` | `/ws?role=client` | 浏览器 WebSocket 连接 |
| `GET` | `/video` | MJPEG 视频流 |
| `GET` | `/params` | 加载驾驶参数 |
| `POST` | `/params` | 保存驾驶参数 |
| `POST` | `/load_model` | 下发模型加载指令 |
| `POST` | `/calibrate` | 下发校准参数 |

### WebSocket 消息协议

**浏览器 → 服务端（控制指令）**

```json
{ "angle": 0.5, "throttle": 0.3 }
{ "drive_mode": "local_angle" }
{ "recording": true }
{ "buttons": { "w1": true } }
```

**服务端 → 浏览器（状态推送）**

```json
{ "type": "car_connection", "online": true }
{ "type": "car_state", "drive_mode": "user", "recording": false, "num_records": 0 }
```

**车端 → 服务端（帧推送）**

```json
{ "type": "frame", "data": "<base64 jpeg>" }
```

---

## 常见问题

### Q: 页面显示「车端离线」？
1. 确认 `web_ui/backend/main.py` 正在运行
2. 确认车端 `manage.py` 中 `DRIVE_API_SERVER_URL` 配置正确（IP 和端口）
3. 确认车端和电脑在同一局域网，防火墙未屏蔽 8000 端口

### Q: 摄像头画面不显示？
1. 确认车端 Part 正确传入 `cam/image_array`
2. 确认 `DriveApiBridge` 已替换原有的 `LocalWebController`
3. 检查浏览器控制台是否有 WebSocket 连接错误

### Q: 控制无响应？
1. 检查输入源是否选中了正确的模式（如手柄未连接时选了手柄）
2. 确认车端在线，底部状态卡片显示「在线」
3. 键盘控制只在页面获得焦点时生效，点击页面任意位置获取焦点

### Q: 如何回退到原有 Tornado 控制台？
把 `manage.py` 中的 `DriveApiBridge` 改回 `LocalWebController`，恢复原来的导入即可，无任何破坏性。

---

## 文件结构

```
web_ui/
├── backend/
│   └── routers/
│       └── drive.py          # 驾驶 API（WebSocket/MJPEG/参数/校准）
└── frontend/
    └── src/
        ├── pages/
        │   ├── DrivePage.tsx      # 驾驶控制台页面
        │   └── CalibratePage.tsx  # 校准页面
        ├── components/drive/
        │   ├── VideoStream.tsx      # MJPEG 视频流
        │   ├── VirtualJoystick.tsx  # 虚拟摇杆
        │   ├── ControlBars.tsx      # 转向/油门指示条
        │   ├── DriveModeSelector.tsx # 驾驶模式切换
        │   ├── InputSourceSelector.tsx # 输入源切换
        │   ├── ProgrammableButtons.tsx # 可编程按钮
        │   └── ParameterPanel.tsx    # 控制参数面板
        ├── hooks/
        │   ├── useDriveWebsocket.ts  # WebSocket 连接管理
        │   ├── useKeyboardDrive.ts   # 键盘输入
        │   ├── useGamepadDrive.ts    # 手柄输入
        │   ├── useGyroDrive.ts       # 陀螺仪输入
        │   └── useDriveHotkeys.ts    # 驾驶快捷键
        └── store/
            └── useDriveStore.ts      # 驾驶参数状态管理

donkeycar/parts/
└── drive_api_bridge.py       # 车端 WebSocket 桥接 Part
```
