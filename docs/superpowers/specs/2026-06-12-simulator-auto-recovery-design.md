# 模拟器自动恢复机制设计文档

## 1. 背景与目标

当前 DonkeyDrifter Web UI 驾驶链路为：

```
前端 Drive 页面  <--WebSocket/HTTP-->  后端 FastAPI  <--WebSocket-->  车端 manage.py drive  <--TCP-->  DonkeySim 模拟器
```

当模拟器端重启或网络抖动时，车端的 `DonkeyGymEnv` 可能失去与模拟器的 TCP 连接。虽然 `DonkeyGymEnv` 已经具备 step() 异常捕获与自动重连能力，但在某些边界情况下（例如 gym-donkeycar 的 proc_msg 线程死锁、`observe()` 卡住）车端无法自行恢复。

本设计目标：当前端页面刷新后，由后端启动一个周期性的恢复任务，主动通知车端检查/重建模拟器连接，从而实现整套系统的自动恢复。

## 2. 设计约束

- 后端本身不直接连接模拟器；后端只能通过 WebSocket 通知车端去重连。
- 车端 `DonkeyGymEnv` 与 `DriveApiBridge` 是两个独立的 Vehicle part，没有直接引用，需要通过约定接口或共享状态通信。
- 恢复任务不应在无人驾驶/无前端在线时持续运行，避免资源浪费。

## 3. 方案概述

采用**后端恢复任务**方案：

1. 前端刷新并连接 WebSocket 后，发送一次 `activate_sim_recovery` 消息。
2. 后端收到后启动一个 `asyncio` 后台任务，以固定频率（默认 5 秒，可配置）执行恢复动作。
3. 每次恢复动作：
   - 若车端在线，向后端 WebSocket 发送 `{"type": "reconnect_simulator"}`。
   - 若车端不在线，仅记录日志，等待车端自动重连后端。
4. 车端 `DriveApiBridge` 收到 `reconnect_simulator` 后，触发 `DonkeyGymEnv` 强制重建模拟器连接。
5. 当所有前端客户端都断开时，后端自动停止恢复任务。
6. 前端也可发送 `deactivate_sim_recovery` 显式停止任务。

## 4. 消息协议

### 4.1 前端 -> 后端

```json
{"type": "activate_sim_recovery"}
{"type": "deactivate_sim_recovery"}
```

### 4.2 后端 -> 车端

```json
{"type": "reconnect_simulator"}
```

## 5. 后端实现

### 5.1 DriveState 扩展

在 `web_ui/backend/routers/drive.py` 的 `DriveState` 中新增：

```python
self.sim_recovery_task: Optional[asyncio.Task] = None
self.sim_recovery_interval: float = 5.0
```

### 5.2 恢复任务

```python
async def _sim_recovery_worker(self):
    while True:
        await asyncio.sleep(self.sim_recovery_interval)
        if self.car_ws is not None:
            try:
                await self.car_ws.send_text(json.dumps({"type": "reconnect_simulator"}))
            except Exception:
                self.car_ws = None
```

### 5.3 启动/停止

```python
def start_sim_recovery(self):
    if self.sim_recovery_task is None or self.sim_recovery_task.done():
        self.sim_recovery_task = asyncio.create_task(self._sim_recovery_worker())

def stop_sim_recovery(self):
    if self.sim_recovery_task and not self.sim_recovery_task.done():
        self.sim_recovery_task.cancel()
        self.sim_recovery_task = None
```

### 5.4 客户端消息处理

在 `drive_ws` 的客户端分支中：

```python
if msg.get("type") == "activate_sim_recovery":
    drive_state.start_sim_recovery()
    continue
if msg.get("type") == "deactivate_sim_recovery":
    drive_state.stop_sim_recovery()
    continue
```

### 5.5 生命周期

- 启动：收到 `activate_sim_recovery` 时。
- 停止：收到 `deactivate_sim_recovery` 时，或 `client_ws` 为空时。

## 6. 车端实现

### 6.1 DriveApiBridge 消息处理

在 `donkeycar/parts/drive_api_bridge.py` 的 `_handle_message` 中：

```python
if msg.get("type") == "reconnect_simulator":
    self.reconnect_simulator = True
    return
```

### 6.2 DriveApiBridge 暴露状态

`run_threaded()` 返回新增字段 `reconnect_simulator`（或写入 Memory）：

```python
return self.angle, self.throttle, self.mode, self.recording, self.buttons, self.reconnect_simulator
```

### 6.3 DonkeyGymEnv 响应

在 `simulator.py` 模板中，将 `DriveApiBridge` 的 `reconnect_simulator` 输出连接到 `DonkeyGymEnv` 的输入：

```python
V.add(cam, inputs=['angle', 'throttle', 'brake', 'reconnect_simulator'], threaded=True)
```

在 `DonkeyGymEnv.run_threaded()` 中接收该标志：

```python
def run_threaded(self, steering, throttle, brake=None, reconnect=False):
    if reconnect:
        self._request_reconnect()
    ...
```

在 `DonkeyGymEnv` 中新增：

```python
def _request_reconnect(self):
    if self.env is not None:
        print("[DonkeyGymEnv] 收到强制重连请求")
        self._close_env()
```

`update()` 循环在 env 为 None 时会自动调用 `_try_connect()` 重连。

## 7. 前端实现

### 7.1 刷新后激活

在 `useDriveWebsocket` 的 `ws.onopen` 中：

```typescript
ws.send(JSON.stringify({ type: 'activate_sim_recovery' }));
```

### 7.2 页面关闭前停止

在 `useEffect` 的 cleanup 中：

```typescript
closingRef.current = true;
if (wsRef.current?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'deactivate_sim_recovery' }));
}
```

## 8. 配置项

- `SIM_RECOVERY_INTERVAL`：后端恢复任务周期，默认 5 秒。
- 可在 `web_ui/backend/routers/drive.py` 中作为环境变量读取，例如 `os.environ.get("SIM_RECOVERY_INTERVAL", "5.0")`。

## 9. 错误处理

- 后端发送 `reconnect_simulator` 失败时，将车端 `car_ws` 置为 None，等待车端自动重连。
- 恢复任务本身抛异常时，记录日志并自动重启任务（或停止，视策略而定）。
- 车端收到 `reconnect_simulator` 时，即使当前连接正常，也强制关闭并重建连接，确保模拟器重启后能够恢复。

## 10. 测试策略

### 10.1 后端测试

- 模拟前端发送 `activate_sim_recovery`，验证后端启动恢复任务。
- 验证恢复任务按周期向车端发送 `reconnect_simulator`。
- 验证所有客户端断开后任务停止。
- 模拟前端发送 `deactivate_sim_recovery`，验证任务停止。

### 10.2 车端测试

- 验证 `DriveApiBridge` 收到 `reconnect_simulator` 后设置标志。
- 验证 `DonkeyGymEnv` 收到标志后关闭 env 并触发重连。

### 10.3 集成测试

- 通过 TestClient 模拟前端连接 -> 激活恢复 -> 车端收到重连命令的完整链路。

## 11. 风险与回退

- 如果恢复任务频率过高，可能增加车端负担。默认 5 秒并可通过环境变量调整。
- 如果车端不在线，恢复任务不会发送命令，仅等待车端重连后端。
- 可通过 `deactivate_sim_recovery` 随时关闭恢复任务。

## 12. 相关文件

- `web_ui/backend/routers/drive.py`
- `web_ui/frontend/src/hooks/useDriveWebsocket.ts`
- `donkeycar/parts/drive_api_bridge.py`
- `donkeycar/parts/dgym.py`
- `donkeycar/templates/simulator.py`
- `web_ui/backend/tests/test_drive.py`
- `donkeycar/tests/test_dgym_reconnect.py`
