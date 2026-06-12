# 模拟器自动恢复机制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当前端页面刷新后，由后端启动周期性恢复任务，通知车端强制重建模拟器连接，实现整套系统自动恢复。

**Architecture:** 后端 `DriveState` 维护一个 `asyncio` 后台任务；前端通过 WebSocket 发送 `activate_sim_recovery`/`deactivate_sim_recovery` 控制任务启停；任务按固定周期向车端发送 `reconnect_simulator`；车端 `DriveApiBridge` 收到后通过 Memory 总线通知 `DonkeyGymEnv` 强制关闭当前 env 并重连。

**Tech Stack:** Python 3.11, FastAPI, asyncio, React/TypeScript, WebSocket, pytest, vitest

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `web_ui/backend/routers/drive.py` | 后端恢复任务生命周期、消息处理 |
| `web_ui/backend/tests/test_drive.py` | 后端恢复任务测试 |
| `donkeycar/parts/drive_api_bridge.py` | 车端接收 `reconnect_simulator` 并暴露重连标志 |
| `donkeycar/parts/dgym.py` | `DonkeyGymEnv` 响应重连请求并强制重建 env |
| `donkeycar/templates/simulator.py` | 将 `DriveApiBridge` 重连标志接入 `DonkeyGymEnv` |
| `donkeycar/tests/test_dgym_reconnect.py` | 车端重连逻辑测试 |
| `web_ui/frontend/src/hooks/useDriveWebsocket.ts` | 前端刷新激活/关闭恢复任务 |

---

### Task 1: 后端 DriveState 恢复任务基础设施

**Files:**
- Modify: `web_ui/backend/routers/drive.py:27-119` (`DriveState.__init__` 附近)
- Modify: `web_ui/backend/routers/drive.py:79-89` (`broadcast_to_clients` 附近)
- Test: `web_ui/backend/tests/test_drive.py`

- [ ] **Step 1: 编写恢复任务启动/停止的测试**

在 `web_ui/backend/tests/test_drive.py` 末尾追加：

```python
@pytest.mark.anyio
async def test_sim_recovery_starts_and_stops():
    client, drive = make_client()
    assert drive.drive_state.sim_recovery_task is None

    drive.drive_state.start_sim_recovery()
    assert drive.drive_state.sim_recovery_task is not None
    assert not drive.drive_state.sim_recovery_task.done()

    drive.drive_state.stop_sim_recovery()
    # Give the event loop a chance to process cancellation
    await asyncio.sleep(0.1)
    assert drive.drive_state.sim_recovery_task is None or drive.drive_state.sim_recovery_task.done()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd web_ui/backend && python -m pytest tests/test_drive.py::test_sim_recovery_starts_and_stops -v
```

Expected: FAIL (`AttributeError: 'DriveState' object has no attribute 'sim_recovery_task'`)

- [ ] **Step 3: 在 DriveState 中添加恢复任务基础设施**

修改 `web_ui/backend/routers/drive.py` 的 `DriveState.__init__`：

```python
        # 连接管理
        self.car_ws: Optional[WebSocket] = None
        self.client_ws: Dict[str, WebSocket] = {}

        # 模拟器自动恢复任务
        self.sim_recovery_task: Optional[asyncio.Task] = None
        self.sim_recovery_interval: float = float(
            os.environ.get("SIM_RECOVERY_INTERVAL", "5.0")
        )
```

在 `DriveState` 类中追加方法（放在 `broadcast_to_clients` 之后即可）：

```python
    async def _sim_recovery_worker(self):
        """周期性向车端发送重连模拟器请求。"""
        while True:
            try:
                await asyncio.sleep(self.sim_recovery_interval)
            except asyncio.CancelledError:
                break

            if self.car_ws is None:
                logger.debug("恢复任务：车端不在线，跳过本次重连")
                continue

            try:
                await self.car_ws.send_text(
                    json.dumps({"type": "reconnect_simulator"})
                )
                logger.debug("恢复任务：已发送 reconnect_simulator 到车端")
            except Exception as e:
                logger.warning(f"恢复任务：发送重连命令失败: {e}")
                self.car_ws = None

    def start_sim_recovery(self):
        """启动模拟器自动恢复任务。"""
        if self.sim_recovery_task is None or self.sim_recovery_task.done():
            self.sim_recovery_task = asyncio.create_task(self._sim_recovery_worker())
            logger.info("模拟器自动恢复任务已启动")

    def stop_sim_recovery(self):
        """停止模拟器自动恢复任务。"""
        if self.sim_recovery_task and not self.sim_recovery_task.done():
            self.sim_recovery_task.cancel()
            self.sim_recovery_task = None
            logger.info("模拟器自动恢复任务已停止")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd web_ui/backend && python -m pytest tests/test_drive.py::test_sim_recovery_starts_and_stops -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web_ui/backend/routers/drive.py web_ui/backend/tests/test_drive.py
git commit -m "feat(backend): add simulator recovery task infrastructure"
```

---

### Task 2: 后端 drive_ws 处理激活/停止消息

**Files:**
- Modify: `web_ui/backend/routers/drive.py:554-593` (客户端 while 循环内)
- Test: `web_ui/backend/tests/test_drive.py`

- [ ] **Step 1: 编写消息处理测试**

在 `web_ui/backend/tests/test_drive.py` 末尾追加：

```python
@pytest.mark.anyio
async def test_activate_sim_recovery_starts_worker(monkeypatch):
    client, drive = make_client()
    started = []

    def fake_start():
        started.append(True)

    monkeypatch.setattr(drive.drive_state, "start_sim_recovery", fake_start)

    # Simulate a client websocket that sends activate then disconnects
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        ws.send_json({"type": "activate_sim_recovery"})
        time.sleep(0.1)

    assert len(started) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd web_ui/backend && python -m pytest tests/test_drive.py::test_activate_sim_recovery_starts_worker -v
```

Expected: FAIL (激活消息未被处理，但测试可能通过 if WebSocket 连接正常；主要验证 fake_start 未被调用)

- [ ] **Step 3: 在 drive_ws 客户端分支中处理恢复消息**

修改 `web_ui/backend/routers/drive.py` 客户端 while 循环中的消息处理逻辑，在 JSON 解析之后、控制指令处理之前插入：

```python
                # 模拟器自动恢复控制
                if msg.get("type") == "activate_sim_recovery":
                    drive_state.start_sim_recovery()
                    continue
                if msg.get("type") == "deactivate_sim_recovery":
                    drive_state.stop_sim_recovery()
                    continue
```

同时在客户端断开处理处（`except (WebSocketDisconnect, RuntimeError)` 块）增加停止恢复任务的逻辑：

```python
        except (WebSocketDisconnect, RuntimeError):
            if drive_state.client_ws.get(client_id) is websocket:
                drive_state.client_ws.pop(client_id, None)
            logger.info(f"客户端断开，当前在线: {len(drive_state.client_ws)}")
            # 没有前端在线时停止恢复任务
            if not drive_state.client_ws:
                drive_state.stop_sim_recovery()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd web_ui/backend && python -m pytest tests/test_drive.py::test_activate_sim_recovery_starts_worker -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web_ui/backend/routers/drive.py web_ui/backend/tests/test_drive.py
git commit -m "feat(backend): handle activate/deactivate sim recovery messages"
```

---

### Task 3: 车端 DriveApiBridge 处理 reconnect_simulator

**Files:**
- Modify: `donkeycar/parts/drive_api_bridge.py:400-414` (`_handle_message`)
- Modify: `donkeycar/parts/drive_api_bridge.py:665-705` (`run_threaded`)
- Test: `donkeycar/tests/test_drive_api_bridge.py`

- [ ] **Step 1: 编写 DriveApiBridge 重连消息测试**

在 `donkeycar/tests/test_drive_api_bridge.py` 末尾追加（需要先确认该文件导入结构）：

```python
def test_drive_api_bridge_handles_reconnect_simulator():
    from donkeycar.parts.drive_api_bridge import DriveApiBridge

    bridge = DriveApiBridge(server_url="ws://localhost:8000/api/drive/ws")
    bridge._handle_message({"type": "reconnect_simulator"})

    assert bridge.reconnect_simulator is True

    outputs = bridge.run_threaded(img_arr=None, num_records=0, mode="user", recording=False)
    # outputs order: angle, throttle, mode, recording, buttons, reconnect_simulator
    assert outputs[-1] is False
    assert bridge.reconnect_simulator is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest donkeycar/tests/test_drive_api_bridge.py::test_drive_api_bridge_handles_reconnect_simulator -v
```

Expected: FAIL (`AttributeError: 'DriveApiBridge' object has no attribute 'reconnect_simulator'`)

- [ ] **Step 3: 实现 DriveApiBridge 重连标志**

修改 `donkeycar/parts/drive_api_bridge.py`：

在 `DriveApiBridge.__init__` 中初始化标志（找到 `__init__` 方法，在 `self.buttons = {}` 附近添加）：

```python
        self.reconnect_simulator = False
```

修改 `_handle_message`：

```python
    def _handle_message(self, msg: dict):
        """处理服务端发来的控制消息。"""
        if msg.get("type") == "webrtc_signal":
            self._handle_webrtc_signal(msg)
            return
        if msg.get("type") == "reconnect_simulator":
            self.reconnect_simulator = True
            return
        if "angle" in msg:
            ...
```

修改 `run_threaded` 的返回值：

```python
        buttons = self.buttons
        self.buttons = {}
        reconnect = self.reconnect_simulator
        self.reconnect_simulator = False
        return self.angle, self.throttle, self.mode, self.recording, buttons, reconnect
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest donkeycar/tests/test_drive_api_bridge.py::test_drive_api_bridge_handles_reconnect_simulator -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add donkeycar/parts/drive_api_bridge.py donkeycar/tests/test_drive_api_bridge.py
git commit -m "feat(car): DriveApiBridge handles reconnect_simulator command"
```

---

### Task 4: 车端 DonkeyGymEnv 响应重连请求

**Files:**
- Modify: `donkeycar/parts/dgym.py`
- Test: `donkeycar/tests/test_dgym_reconnect.py`

- [ ] **Step 1: 编写 DonkeyGymEnv 强制重连测试**

在 `donkeycar/tests/test_dgym_reconnect.py` 末尾追加：

```python
def test_run_threaded_reconnect_closes_env(mock_gym_make):
    """验证 run_threaded 收到 reconnect=True 时会关闭当前 env。"""
    fake_env = FakeEnv(fail_after=9999)
    mock_gym_make.return_value = fake_env

    gym_env = DonkeyGymEnv(
        sim_path="remote",
        host="127.0.0.1",
        port=9091,
        env_name="donkey-generated-track-v0",
        conf={"img_h": 120, "img_w": 160},
    )

    # 通过 run_threaded 请求重连
    gym_env.run_threaded(0.0, 0.0, 0.0, reconnect=True)

    # update 线程会在下一次循环中关闭 env 并重连
    thread = threading.Thread(target=gym_env.update, daemon=True)
    thread.start()

    time.sleep(0.3)

    assert fake_env.closed, "收到重连请求后 env 应该被关闭"
    assert gym_env.env is None, "env 应该被设为 None"

    gym_env.shutdown()
    thread.join(timeout=2.0)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest donkeycar/tests/test_dgym_reconnect.py::test_run_threaded_reconnect_closes_env -v
```

Expected: FAIL (`TypeError: run_threaded() got an unexpected keyword argument 'reconnect'`)

- [ ] **Step 3: 实现 DonkeyGymEnv 重连请求响应**

修改 `donkeycar/parts/dgym.py`：

在 `_is_env_connected` 之后、`update` 之前添加：

```python
    def _request_reconnect(self):
        """标记需要在下一次 update 循环中强制重建模拟器连接。"""
        if self.env is not None:
            print("[DonkeyGymEnv] 收到强制重连请求，准备重建模拟器连接")
            self._close_env()
```

修改 `run_threaded` 签名并在开头处理重连：

```python
    def run_threaded(self, steering, throttle, brake=None, reconnect=False):
        if reconnect:
            self._request_reconnect()

        if steering is None or throttle is None:
            ...
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest donkeycar/tests/test_dgym_reconnect.py::test_run_threaded_reconnect_closes_env -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add donkeycar/parts/dgym.py donkeycar/tests/test_dgym_reconnect.py
git commit -m "feat(car): DonkeyGymEnv responds to forced reconnect request"
```

---

### Task 5: simulator.py 模板连接 DriveApiBridge 与 DonkeyGymEnv

**Files:**
- Modify: `donkeycar/templates/simulator.py:66-72` (DonkeyGymEnv 部分)
- Modify: `donkeycar/templates/simulator.py:418-419` (DriveApiBridge 输出部分)
- Test: `donkeycar/tests/test_template.py` 或新建 `donkeycar/tests/test_template_simulator_recovery.py`

- [ ] **Step 1: 编写模板连接测试**

新建 `donkeycar/tests/test_template_simulator_recovery.py`：

```python
"""验证 simulator.py 模板正确连接了重连标志。"""
import ast
from pathlib import Path


def test_simulator_template_wires_reconnect_flag():
    source = Path("donkeycar/templates/simulator.py").read_text()
    tree = ast.parse(source)

    found_bridge_reconnect_output = False
    found_gym_reconnect_input = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "add":
                # V.add(ctr, inputs=..., outputs=[..., 'reconnect_simulator_requested'])
                for kw in node.keywords:
                    if kw.arg == "outputs":
                        if any(
                            isinstance(elt, ast.Constant)
                            and elt.value == "reconnect_simulator_requested"
                            for elt in kw.value.elts
                        ):
                            found_bridge_reconnect_output = True
                    if kw.arg == "inputs":
                        if any(
                            isinstance(elt, ast.Constant)
                            and elt.value == "reconnect_simulator"
                            for elt in kw.value.elts
                        ):
                            found_gym_reconnect_input = True

    assert found_bridge_reconnect_output, "DriveApiBridge 应输出 reconnect_simulator_requested"
    assert found_gym_reconnect_input, "DonkeyGymEnv 应接收 reconnect_simulator 输入"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest donkeycar/tests/test_template_simulator_recovery.py -v
```

Expected: FAIL

- [ ] **Step 3: 修改 simulator.py 模板**

修改 `donkeycar/templates/simulator.py`：

找到 DonkeyGymEnv 添加处：

```python
    cam = DonkeyGymEnv(cfg.DONKEY_SIM_PATH, host=cfg.SIM_HOST, env_name=cfg.DONKEY_GYM_ENV_NAME, conf=cfg.GYM_CONF, delay=cfg.SIM_ARTIFICIAL_LATENCY)
    threaded = True
    inputs = ['angle', 'throttle', 'brake']

    V.add(cam, inputs=inputs, outputs=['cam/image_array'], threaded=threaded)
```

改为：

```python
    cam = DonkeyGymEnv(cfg.DONKEY_SIM_PATH, host=cfg.SIM_HOST, env_name=cfg.DONKEY_GYM_ENV_NAME, conf=cfg.GYM_CONF, delay=cfg.SIM_ARTIFICIAL_LATENCY)
    threaded = True
    inputs = ['angle', 'throttle', 'brake', 'reconnect_simulator']

    V.add(cam, inputs=inputs, outputs=['cam/image_array'], threaded=threaded)
```

找到 DriveApiBridge 添加处（在文件末尾附近）：

```python
    elif isinstance(ctr, DriveApiBridge):
        print("Web Console Drive 已就绪，请打开浏览器访问 http://localhost:5188/")
```

在此之前或同时，确认 DriveApiBridge 的输出包含 `reconnect_simulator_requested`：

```python
        V.add(ctr,
          inputs=['cam/image_array', 'tub/num_records'],
          outputs=['user/angle', 'user/throttle', 'user/mode', 'recording', 'reconnect_simulator_requested'],
          threaded=True)
```

如果模板中 DriveApiBridge 已经以这种方式添加，只需把 `'reconnect_simulator_requested'` 追加到 outputs 列表。

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest donkeycar/tests/test_template_simulator_recovery.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add donkeycar/templates/simulator.py donkeycar/tests/test_template_simulator_recovery.py
git commit -m "feat(template): wire reconnect_simulator flag in simulator.py"
```

---

### Task 6: 前端 useDriveWebsocket 激活/关闭恢复

**Files:**
- Modify: `web_ui/frontend/src/hooks/useDriveWebsocket.ts`

- [ ] **Step 1: 在 onopen 中发送激活消息**

修改 `web_ui/frontend/src/hooks/useDriveWebsocket.ts` 的 `ws.onopen`：

```typescript
      ws.onopen = () => {
        if (wsRef.current !== ws || !mountedRef.current) return;
        setConnected(true);
        // 页面刷新后激活后端的模拟器自动恢复任务
        try {
          ws.send(JSON.stringify({ type: 'activate_sim_recovery' }));
        } catch {
          // ignore
        }
        // 心跳 5s 一次，更快感知断线与车端上线
        heartbeatTimerRef.current = setInterval(() => {
          if (wsRef.current === ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'heartbeat' }));
          }
        }, 5000);
      };
```

- [ ] **Step 2: 在 cleanup 中发送停止消息**

修改 `useEffect` 的 cleanup：

```typescript
  useEffect(() => {
    mountedRef.current = true;
    closingRef.current = false;
    connect();
    return () => {
      mountedRef.current = false;
      closingRef.current = true;
      clearTimers();
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: 'deactivate_sim_recovery' }));
        } catch {
          // ignore
        }
      }
      wsRef.current = null;
      if (ws) {
        ws.close();
      }
    };
  }, [connect]);
```

注意：发送 `deactivate_sim_recovery` 应该在 `wsRef.current = null` 之前。

- [ ] **Step 3: 运行前端类型检查**

```bash
cd web_ui/frontend && npm run check
```

Expected: 无新增类型错误

- [ ] **Step 4: Commit**

```bash
git add web_ui/frontend/src/hooks/useDriveWebsocket.ts
git commit -m "feat(frontend): activate/deactivate sim recovery on mount/unmount"
```

---

### Task 7: 集成验证

- [ ] **Step 1: 运行后端所有测试**

```bash
cd web_ui/backend && python -m pytest tests/ -q
```

Expected: 全部通过

- [ ] **Step 2: 运行车端相关测试**

```bash
python -m pytest donkeycar/tests/test_dgym_reconnect.py donkeycar/tests/test_drive_api_bridge.py donkeycar/tests/test_template_simulator_recovery.py -q
```

Expected: 全部通过

- [ ] **Step 3: 运行前端 lint/build**

```bash
cd web_ui/frontend && npm run lint && npm run build
```

Expected: 通过

- [ ] **Step 4: Commit 任何测试修复**

```bash
git add -A
git commit -m "test: verify simulator auto recovery integration"
```

---

## 自审检查

| Spec 要求 | 对应任务 |
|-----------|---------|
| 前端刷新发送 `activate_sim_recovery` | Task 6 |
| 后端启动周期性恢复任务 | Task 1 |
| 后端向车端发送 `reconnect_simulator` | Task 1 |
| 车端 DriveApiBridge 处理命令 | Task 3 |
| DonkeyGymEnv 强制重建连接 | Task 4 |
| simulator.py 模板接线 | Task 5 |
| 所有客户端断开后停止任务 | Task 2 |
| 可配置恢复间隔 | Task 1 |

无占位符，所有步骤包含具体代码与命令。
