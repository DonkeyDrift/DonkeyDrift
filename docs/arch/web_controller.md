## 模块概览
- **位置**: `donkeycar/parts/web_controller`。基于 Tornado 的轻量级 Web/WS 服务，为车辆提供远程驾驶界面、校准面板与实时视频。
- **端口**: 本地控制器默认 `8887`；仅 FPV 的 WebFpv 服务器默认 `8890`。
- **静态资源**: 来自 `templates/static/`，包含 jQuery、Bootstrap、nipple.js 虚拟摇杆、主样式与 JS。

## Python 端组成（web.py）
- **RemoteWebServer**: 作为客户端轮询远端控制接口，POST 当前传感数据并解析返回的角度、油门、模式、录制标记，可在独立线程中持续更新。
- **LocalWebController (tornado.web.Application)**:
  - 持有共享状态：`angle`、`throttle`、`mode`、`recording`、按钮锁存、图像帧与记录计数。
  - 路由:
    - `/` → 重定向 `/drive`
    - `/drive` → `DriveAPI`（表单式控制）
    - `/wsDrive` → `WebSocketDriveAPI`（实时控制通道）
    - `/wsCalibrate` → `WebSocketCalibrateAPI`（校准通道）
    - `/calibrate` → `CalibrateHandler`（校准页）
    - `/video` → `VideoAPI`（MJPEG 流）
    - `/wsTest` → `WsTest`（压力/连通测试页）
    - `/static/*` → 静态资源
  - 启动：`update()` 新事件循环、监听端口并启动 IOLoop；构造时尝试自动打开浏览器。
  - `run_threaded(...)` 将驾驶循环的传入状态对齐到内部状态，处理按钮锁存，并通过 `update_wsclients` 将变更推送到所有 WS 客户端。
- **DriveAPI**: GET 渲染 `vehicle.html`；POST 将 JSON 中的 `angle/throttle/drive_mode/recording/buttons` 写入应用状态（按钮经 `latch_buttons` 锁存一次性消费）。
- **WebSocketDriveAPI**: 处理 `ws://.../wsDrive` 实时指令，更新角度/油门/模式/录制/按钮，并记录模式与录制的锁存值以便下个循环应用。
- **WebSocketCalibrateAPI**: 接收校准页面发送的 throttle/angle 或驱动配置（针对 PWM_STEERING_THROTTLE、I2C_SERVO、MM1 等），直接修改 `application.drive_train` 或相关脉宽字段。
- **VideoAPI**: 以 multipart MJPEG 方式推流 `application.img_arr`，无图像时发送占位图 `img_placeholder.jpg`。
- **WebFpv & BaseHandler**: 精简的 FPV 只读服务器（根路径显示 `base_fpv.html`，`/video` 共享同一 MJPEG 推流）。

## 前端模板与页面
- **`base.html`**: 公共框架，加载 jQuery、jQuery UI、Bootstrap、`nipple.js`、`main.js` 与样式；`{% block content %}` 插槽。
- **`vehicle.html` (/drive)**: 主驾驶界面。含模式切换与录制按钮、5 个自定义按钮、视频缩略图实时画面 `/video`、转向/油门进度条、虚拟摇杆与键盘/游戏手柄/设备倾斜控制模式切换、油门限制选择、底部启动/刹车按钮；就绪时调用 `driveHandler.load()`（定义于 `static/main.js`）。
- **`base_fpv.html`**: 简洁 FPV 视图，头部展示 logo，主体全屏 `<img src="/video">`。
- **`calibrate.html` (/calibrate)**: WebSocket 连接 `/wsCalibrate`，提供 PWM 与 MM1 参数编辑，方向键触发测试油门/转向并实时写入配置。
- **数据浏览模板**: `session_list.html` 列出会话目录；`session.html` 展示单次会话的图像缩略图、翻页、批量选择/删除与下载；`vehicle_list.html`、`vehicle.html`、`pilots_list.html` 提供车辆/模型枚举入口；`home.html` 介绍功能；`wsTest.html` 连接 `/wsDrive` 发送随机控制指令用于压力测试。

## 关键交互与数据流
- **控制流**: 浏览器 → (`/drive` JS 或 `/wsDrive` WebSocket) → Tornado 状态 → 车辆主循环（经 `run_threaded` 返回最新指令）。
- **录制/按钮锁存**: 录制与模式可通过 WS 设置并在下一次循环生效；按钮采用锁存字典，在一次驱动迭代中消费后清零，避免丢按压。
- **视频流**: 驾驶与 FPV 页面均通过 `/video` 订阅 MJPEG；服务器以 5ms 间隔尝试推送帧，断开时捕获并忽略异常。

## 使用提示
- 车辆侧循环应周期性调用 `run_threaded(img_arr, num_records, mode, recording)`，以便同步 UI 控制与推送状态（含记录计数）。
- 若需仅观看画面且不控制，使用 `WebFpv` 可减少路由与前端负载。
- 校准完成后需手动将新参数写回 `myconfig.py`，否则重启后丢失。
