# Issue 004: 模拟器断连后自动重连不成功

- 状态: fixed（2026-09-04）
- 记录日期: 2026-09-04
- 页面: 连接器（Connector）→ DonkeySim 模拟器配置
- 类型: bug

## 现象

配置 DonkeySim 模拟器（如 172.24.48.1:9091）后，模拟器一旦断连（如 Windows 侧关闭/重启 DonkeySim），自动重连不成功，画面冻结且 UI 无任何状态提示。典型拓扑：车端代码跑在 WSL、模拟器跑在 Windows 宿主机。

## 根因分析（按严重性排序）

**A. 主循环在 `observe()` 里永久自旋，走不到重连代码（最直接根因）**

`gym_donkeycar/envs/donkey_sim.py:437-439`：`observe()` 中 `while self.last_received == self.time_received: time.sleep(0.001)` 无限等待新遥测，无超时。模拟器一关，`update()` 线程永远阻塞在 `env.step()` 内部——既到不了健康检查，也到不了异常重试路径（`donkeycar/parts/dgym.py:215`）。

**B. 断线健康检查失效**

`sim_client.py:50` `is_connected()` 返回 `not self.aborted`，但 `gym_donkeycar/core/client.py` 的收包线程在两种最常见断连路径——对端优雅关闭（`client.py:114-119`）和 `ConnectionResetError`（`client.py:108-112`）——只退出循环，**从不置 `self.aborted=True`**。即使能跑到健康检查也会误判为连接正常。

**C. Web 重连信号链在模板接线处断裂**

前端 Drive 页打开时发 `activate_sim_recovery`（`useDriveWebsocket.ts:97`），后端每 5s 向车端发 `reconnect_simulator`（`web_ui/backend/routers/drive.py:129-161`），车端 bridge 置标志并返回 **7 元组**（`drive_api_bridge.py:804-806`）；但 `donkeycar/templates/simulator.py:110-122` 只声明了 **5 个 outputs**，`memory.py:35-42` 按索引对位写入导致第 6、7 个返回值被静默丢弃，且输出键 `reconnect_simulator_requested` 与 cam 输入键 `reconnect_simulator` 不匹配——重连请求永远到不了 `DonkeyGymEnv`。现有测试 `donkeycar/tests/test_template_simulator_recovery.py` 只做字符串存在性检查，形同虚设。

**D. 附带缺陷**

`client.py:76` `stop()` 调用 `threading.current_thread()` 但只 `from threading import Thread`，会抛 NameError（被 try/except 吞掉）；断连后无遥测上报模拟器状态，前后端 UI 均无法感知离线。

## 修复建议

1. 修模板接线（`simulator.py:121`）：outputs 补到与 7 元组返回值一一对应，键名与 cam 输入对齐；把恢复测试改成真正解析 `V.add` 的 inputs/outputs 配对。
2. 给 `observe()` 加超时（如 2s 无新遥测抛异常或返回 done），让 `dgym.py:215` 的异常路径生效。
3. 修 `is_connected` 语义：优雅关闭与连接重置分支同样置 `aborted=True`；顺手补 `import threading`。
4. 车端兜底看门狗（`dgym.py`）：记录最近一次 `env.step` 返回时间戳，超 N 秒无新帧强制 `_close_env()` 重连，不依赖 gym_donkeycar 内部状态。
5. UI 反馈：遥测附带 `sim_connected` 字段，前后端透传，Connector/Drive 页显示「模拟器离线，重连中…」。

## 备注

根因 A、B 位于 editable 安装的 `gym_donkeycar`（`/home/dkc/projects/gym-donkeycar`，v1.3.1），修复需要改该仓库或在本仓库侧用看门狗（建议 4）规避。

## 修复记录（2026-09-04）

五条修复全部落地：

1. **模板接线**：`donkeycar/templates/simulator.py` ctr outputs 补齐为 7 元组全量键（`... 'web/buttons', 'reconnect_simulator', 'car/mode_cmd'`），与 `DriveApiBridge.run_threaded` 返回值和 cam 输入键对齐；`test_template_simulator_recovery.py` 重写为 AST 级解析 `V.add` inputs/outputs 配对与返回值数量。
2. **observe() 超时**（gym-donkeycar 仓库 `donkey_sim.py`）：连接中止或超过 `observe_timeout_sec`（默认 2s，可经 GYM_CONF 配置）无新遥测时抛 `ConnectionError`，`dgym.py` 异常路径生效。
3. **is_connected 语义**（gym-donkeycar `core/client.py`）：优雅关闭与 ConnectionResetError 分支均置 `aborted=True`；补 `import threading` 消除 `stop()` 的 NameError。
4. **车端看门狗**（`donkeycar/parts/dgym.py`）：记录最近一次 `env.step` 成功返回时间戳，主循环侧 `run_threaded` 检测超过 `watchdog_sec`（默认 5s）无新帧即强制 `_close_env()` 触发重连，不依赖 gym_donkeycar 内部状态。
5. **UI 反馈**：`simulator.py` 新增 `SimConnectionState` 发布 `sim/connected` → bridge 遥测透传 `sim_connected` 字段 → 后端原样广播 → Drive 页显示「模拟器离线，重连中…」琥珀色徽章（`drive.simOfflineReconnecting`，中英双语）。

测试：DonkeyDrifter 新增/重写 7 个用例（模板接线 3、看门狗 2、遥测 2）；gym-donkeycar 新增 `tests/test_sim_disconnect.py` 5 个用例。
