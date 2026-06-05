# DriveApiBridge 车端接入指南

## 背景
`DriveApiBridge` 是原有 `LocalWebController`（基于 Tornado，监听 8887 端口）的替代方案。它不再启动独立的 Web 服务器，而是作为标准 Donkeycar Part，通过 WebSocket 连接到统一的 FastAPI 服务端（端口 8000），实现摄像头回传、控制指令、状态同步全链路接入新的 Web 驾驶控制台。

## 接入步骤（manage.py 修改）

### 步骤 1：导入
在 `manage.py` 的导入区，把原来的：
```python
from donkeycar.parts.controller import (JoystickController, LocalWebController,
                                        WebFpv)
```
替换为：
```python
from donkeycar.parts.controller import (JoystickController, WebFpv)
from donkeycar.parts.drive_api_bridge import DriveApiBridge
```

### 步骤 2：替换部件实例化
找到原有的 LocalWebController 实例化代码（约 711 行）：
```python
ctr = LocalWebController(port=cfg.WEB_CONTROL_PORT, mode=cfg.WEB_INIT_MODE)
V.add(ctr,
      inputs=['cam/image_array', 'tub/num_records', 'user/mode', 'recording'],
      outputs=['user/angle', 'user/throttle', 'user/mode', 'recording', 'buttons'],
      threaded=True)
```
**整体替换**为：
```python
ctr = DriveApiBridge(
    server_url=cfg.DRIVE_API_SERVER_URL,  # 可选，默认 ws://localhost:8000/api/drive/ws
    reconnect_interval=3.0,                # 可选，断连重连间隔
)
V.add(ctr,
      inputs=['cam/image_array', 'tub/num_records', 'user/mode', 'recording'],
      outputs=['user/angle', 'user/throttle', 'user/mode', 'recording', 'buttons'],
      threaded=True)
```

### 步骤 3：配置项
在 `myconfig.py` 中增加以下配置（默认值可省略）：
```python
# DriveApiBridge 服务端地址
# 车端在树莓派运行时，改为你电脑的 IP，例如 ws://192.168.1.100:8000/api/drive/ws
DRIVE_API_SERVER_URL = "ws://localhost:8000/api/drive/ws"
```

## 兼容性说明

| 特性 | LocalWebController | DriveApiBridge |
|------|-------------------|----------------|
| 输入 outputs 接口 | 完全一致 | ✅ 完全一致，无缝替换 |
| 按钮事件 (buttons) | w1-w5 格式 | ✅ 一致 |
| 驾驶模式切换 | user / local_angle / local | ✅ 一致 |
| 录制控制 | 支持 | ✅ 一致 |
| 摄像头回传 | MJPEG 20fps | ✅ 一致，20fps 节流 |
| 键盘快捷键 (IKJL / R / M) | 支持 | ✅ 新 Web UI 已实现 |
| 游戏手柄 | 支持 | ✅ HTML5 Gamepad API |
| 设备陀螺仪 | 支持 | ✅ DeviceOrientation API |
| 参数面板（PID / 速率） | 支持 | ✅ 折叠面板 + 导入导出 |
| 校准页面 | 支持 | ✅ 可视化 PWM 滑杆 + 实时测试 |
| 独立端口 | 8887 | ❌ 不再需要，统一走 8000 端口 |

## 验证方法

1. 先启动 FastAPI 服务端：
```bash
cd web_ui/backend
python main.py
```
2. 浏览器打开 `http://localhost:5173/#/drive`，进入驾驶控制台
3. 启动车端：
```bash
python manage.py drive
```
4. 观察页面右上角「车端连接」状态变为「在线」，摄像头画面正常显示
5. 拖动虚拟摇杆或按 I / K / J / L 键，车端控制正常响应

## 回退方案
如果遇到问题，只需要把步骤 1 和 2 中的代码改回原来的 `LocalWebController` 即可，无任何破坏性。
