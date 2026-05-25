# Web 驾驶控制台移植方案

## 背景
Donkeycar 原有 `donkey drive` 启动的 Web 控制台基于 Tornado 实现，与现有基于 FastAPI + React 的 Web UI 互相独立，用户需要分别打开两个页面，体验割裂。本方案将驾驶控制、摄像头回传、状态遥测完整移植到现有 Web UI 中，实现「数据编辑 → 模型训练 → 实车驾驶」全流程闭环。

---

## 一、原有 Web Controller 功能清单（源系统）
> 位于 `donkeycar/parts/web_controller/web.py`，基于 Tornado

### 1. 控制输入层（四种输入互斥）
| 控制方式 | 实现依赖 | 关键行为 |
|---------|---------|---------|
| 虚拟摇杆 | nipple.js | 点击/拖拽输出 `angle [-1, 1]`、`throttle [-1, 1]` |
| 键盘 (IKJL) | 键盘事件 | I 加速、K 刹车/倒车、J/L 转向，松开自动回中，带 PID 平滑 |
| 物理 Gamepad | HTML5 Gamepad API | 摇杆直接映射，优先级高于 Web 控制 |
| 设备陀螺仪 | DeviceOrientation API | 手机横屏握持，前后俯仰控油门、左右倾斜控转向 |

### 2. 驾驶模式
- **User 模式**：纯人工控制
- **Local Angle 模式**：AI 控转向，人工控油门
- **Local 模式**：全自动驾驶

### 3. 录制与按钮
- 录制开关（R 键快捷键），实时显示已录制条数
- 5 个可编程按钮（w1-w5），用于触发自定义逻辑（如切换模型、重置位置等）

### 4. 摄像头回传
- `/video` 接口：MJPEG 流媒体，帧率 ~20fps，由车端 `img_arr` 推送

### 5. 控制参数面板（客户端平滑算法参数）
> 所有参数在前端 JS 中生效，不涉及车端
| 参数 | 范围 | 作用 |
|-----|------|------|
| Kp / Ki / Kd | 0-3 / 0-1 / 0-0.1 | 键盘输入的 PID 平滑，消除抖动 |
| 回中速度 | 0-2 | 松开按键后方向自动回正的角速度 |
| 转向角速度 | 0-3 | 按住转向键时每帧增长的角度量 |
| 加速度变化率 | 0-3 | 油门上升斜率 |
| 刹车变化率 | 0-3 | 油门下降斜率 |

### 6. 参数持久化
- 前端 localStorage 自动保存
- 服务器端 `~/mycar/drive_params.json` 保存，通过 `/api/get_params` / `/api/save_params` 读写

### 7. 校准工具
- `/calibrate` 页面：可视化调节 PWM 舵机左右极限、电调前/后/零位 PWM 值

### 8. 通信协议
- **控制上行**：WebSocket `/wsDrive`，消息包含 `angle`、`throttle`、`drive_mode`、`recording`、`buttons`
- **状态下行**：同一 WebSocket 主动推送，包含 `driveMode`、`recording`、`num_records`
- 降级通道：HTTP POST `/drive` 也接受控制消息

---

## 二、现有 Web UI 架构（目标系统）
> 位于 `web_ui/` 目录

### 后端
- 框架：FastAPI + Uvicorn
- 现有挂载点：
  - `/api/config/*`：配置加载/保存
  - `/api/tub/*`：Tub 数据编辑
  - `/api/trainer/*`：训练任务管理、模型列表
- 缺失能力：**WebSocket 支持**、**MJPEG 流输出**、**车端状态缓存**

### 前端
- 框架：React 18 + TypeScript + TailwindCSS
- 状态管理：Zustand（`store/useStore.ts`），已带 persist 中间件
- 路由：HashRouter，现有页面：`/` (Tub 管理)、`/trainer` (训练)
- 布局：`SidePanel` 左侧抽屉 + 主内容区 + 底部 `StatusBar`
- UI 风格：深色主题（zinc 色系），cyan 作为强调色

---

## 三、移植方案设计

### 整体原则
1. **零侵入车端**：不修改原有 `LocalWebController` 的 Part 接口，通过适配器层对接，保持与现有 `manage.py drive` 兼容
2. **渐进式迁移**：先完成核心驾驶链路（摄像头 + 摇杆/键盘 + 模式切换），再追加参数面板、校准页面等高级功能
3. **状态隔离**：驾驶相关状态单独放一个 Zustand store，不与 Tub/训练 状态耦合

---

### Phase 1：后端架构改造
> 新增文件：`web_ui/backend/routers/drive.py`，挂载到 `/api/drive`

#### 1.1 新增 WebSocket 通道
```
WS  /api/drive/ws
```
- 角色：作为车端 ↔ 浏览器的双向代理，服务端维护一个连接池
- 连接身份标识：query 参数 `role=car|client`，区分车端连接和浏览器连接
- 消息协议与原有 `wsDrive` 完全兼容，不改变 JSON 结构

#### 1.2 新增 MJPEG 流代理
```
GET /api/drive/video
```
- 接收车端推送的帧（通过 WebSocket 或共享内存），复用原有 `VideoAPI` 的 multipart 分片输出逻辑
- 无连接时自动停止发送，空转时输出占位图

#### 1.3 状态缓存层
- 维护全局 `DriveState` 单例：最近一次的 angle、throttle、drive_mode、recording、num_records、last_frame
- 新客户端连接时主动推送一次当前状态，避免画面/模式不同步

#### 1.4 参数读写接口（复用原有逻辑）
```
GET  /api/drive/params   -> 返回已保存的 drive_params.json
POST /api/drive/params   -> 写入 drive_params.json，校验范围与原逻辑一致
```

#### 1.5 车端接入方式（两种可选）
- **方式 A（推荐）**：用户在 `manage.py` 中将 `LocalWebController` 替换为新的 `DriveApiBridge` Part，直接连到现有 Web UI 的 WebSocket 端点，不再启动独立 Tornado 服务
- **方式 B（兼容）**：原有 Tornado 服务保持不变，后端通过 HTTP 轮询 + `/video` 反向代理原有服务，不要求用户改代码（性能略差）

---

### Phase 2：前端新增页面

#### 2.1 新增路由 `/drive`
- 顶部导航栏新增「Drive」入口，与「Tub」「Trainer」平级
- 页面结构（响应式，优先适配平板/手机横屏）：
```
┌──────────────────────────────────────────────────────────┐
│  TopBar: 模式切换下拉 │ 录制按钮 │ 已录制条数 │ 连接状态  │
├──────────────────┬───────────────────────────────────────┤
│                  │                                       │
│  摄像头画面区     │  虚拟摇杆区 (nipple.js)               │
│  (占左侧 2/3)    │  (占右侧 1/3，横屏时底部 1/3)          │
│                  │                                       │
│                  │  油门/转向指示条 + 控制参数折叠面板     │
│                  │                                       │
└──────────────────┴───────────────────────────────────────┘
```

#### 2.2 新增组件拆分（`web_ui/frontend/src/components/drive/`）
| 组件 | 职责 |
|-----|------|
| `DrivePage.tsx` | 页面容器，负责 WebSocket 连接生命周期 |
| `VideoStream.tsx` | MJPEG 流渲染，断连重试、占位图 |
| `VirtualJoystick.tsx` | 封装 nipple.js，输出归一化 angle/throttle |
| `ControlBars.tsx` | 转向/油门实时可视化指示条 |
| `DriveModeSelector.tsx` | 三种驾驶模式下拉 + 快捷键 |
| `ParameterPanel.tsx` | PID/速率参数滑杆，自动同步到服务器和 localStorage |
| `GamepadInput.ts` | 独立 Hook，监听 Gamepad 事件并输出控制量 |
| `KeyboardInput.ts` | 独立 Hook，IKJL + 平滑算法，输出控制量 |
| `GyroInput.ts` | 独立 Hook，处理设备陀螺仪输入 |

#### 2.3 状态管理（新增 `store/useDriveStore.ts`）
```typescript
interface DriveState {
  // 连接状态
  connected: boolean;
  latencyMs: number;

  // 实时控制量
  angle: number;
  throttle: number;

  // 车端状态
  driveMode: 'user' | 'local_angle' | 'local';
  recording: boolean;
  numRecords: number;

  // 参数
  params: {
    pid: { kp: number; ki: number; kd: number };
    recenterRate: number;
    steerRate: number;
    accelRate: number;
    brakeRate: number;
  };

  // 配置项
  maxThrottle: number;
  throttleMode: 'user' | 'constant';
  activeInput: 'joystick' | 'keyboard' | 'gamepad' | 'gyro';
}
```
- 开启 persist 中间件，参数和配置项自动持久化到 localStorage
- 控制量节流：WebSocket 发送频率限制在 50Hz，避免车端过载

#### 2.4 样式规范
- 严格沿用现有深色主题：背景 `bg-zinc-900`、边框 `border-zinc-800`、强调色 `text-cyan-500`
- 控制按钮尺寸：最小 44px，满足触屏点击
- 摄像头区：保持原始比例，最大高度 70vh，黑边等宽填充

---

### Phase 3：与现有系统的衔接点

#### 3.1 SidePanel 扩展
- 现有「Data Management」分组下新增「Car Connection」卡片
- 配置项：车端 WebSocket 地址（默认 `ws://<host>:8000/api/drive/ws`）、自动重连开关

#### 3.2 StatusBar 扩展
- 新增驾驶连接状态指示灯（绿/红）、当前模式、录制状态指示
- 全局可见，切换页面时不丢失

#### 3.3 模型列表联动
- Trainer 页面的 Trained Models 列表新增「Load to Car」按钮
- 点击后通过 WebSocket 下发到车端，自动切换自动驾驶模型

---

## 四、里程碑与交付顺序

| 阶段 | 交付物 | 状态 |
|-----|--------|------|
| M1 骨架 | 后端 drive 路由空实现 + 前端空页面 + 路由注册 | ✅ 已完成 |
| M2 通信通路 | WebSocket 双向打通 + MJPEG 流代理正常显示 | ✅ 已完成 |
| M3 基础控制 | 虚拟摇杆 + 键盘控制 + 模式切换 + 指示条 | ✅ 已完成 |
| M4 数据闭环 | 录制控制 + 记录数同步 + 模型下发联动 + 可编程按钮 | ✅ 已完成 |
| M5 参数系统 | 参数面板 + 本地/服务器双端持久化 + 导入导出 | ✅ 已完成 |
| M6 高级控制 | Gamepad API + 陀螺仪输入 + 输入源切换 | ✅ 已完成 |
| M7 校准工具 | 舵机/电调可视化 PWM 校准 + 实时测试 | ✅ 已完成 |
| M8 文档 | 用户使用文档 + 迁移指南 | ✅ 已完成 |

---

## 五、风险与规避

1. **实时性风险**：WebSocket 代理引入额外延迟 → 缓解：直连模式下车端直接连 FastAPI，不经过代理
2. **兼容性风险**：旧用户仍在使用 Tornado → 缓解：提供反向代理模式，无需改配置即可无缝接入新页面
3. **多客户端冲突**：多个浏览器同时连接控制同一台车 → 缓解：服务端加「主控」锁，只有第一个连接的客户端能发控制指令，其余为只读模式
4. **断连失控风险**：WebSocket 断开时车可能继续按最后指令行驶 → 缓解：客户端 500ms 心跳，服务端 1s 无心跳自动将油门归零
