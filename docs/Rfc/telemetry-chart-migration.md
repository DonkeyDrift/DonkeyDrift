# Drifter Console 曲线图移植至 Drive 页面 — 技术方案（RFC）

> 状态：待评审
> 日期：2026-07-06
> 范围：跨项目（DonkeyDrift 软件端 + mycar 车实例 + 可选固件扩展）
> 路径：A（扩展 drive WS 通道）+ 全量透传

## 1. 背景与目标

将固件端 `MUS4_FW` 的 Drifter Console 实时遥测曲线图，移植到软件端 DonkeyDrifter 的 Drive 页面，置于实时画面（VideoStream）下方，供用户调试。

固件端曲线图本体（`libraries/mus4_web/src/WebConsoleAssets.h`）：
- 原生 Canvas 2D 绘制，无外部库，自包含
- 3 条曲线：Throttle(绿 `#39d98a`)、Steering(蓝 `#5cc8ff`)、GyroZ(红 `#ff6b6b`)，归一化到 -1~1
- 256 点环形缓冲，约 4 秒窗口，~62.5Hz
- 工具栏：暂停、清空、录制 Tub JSON、下载、全屏

## 2. 可行性结论：整体可行，但遥测通道当前完全缺失

### 2.1 数据流现状（基于证据）

```
固件 ESP32 ──Serial1 上行帧──► 车端 donkey 进程（mycar/manage.py）
   $IMU,seq,ts_ms,ax,ay,az,gx,gy,gz  (100Hz)        │
   T<throttle>S<steering>            (MANUAL 模式)    │  已通
   M<mode>:P<park>                                    │
                                                      ├─ Arduino.Arduino_readline() 解析
                                                      │   actuator.py:1248-1331
                                                      │   → imu/acl_x..z, imu/gyr_x..z 通道 ✅
                                                      │   → steering, throttle, mode, park ✅
                                                      ├─ DriveMode → steering/throttle (manage.py:464) ✅
                                                      └─ DriveApiBridge.run_threaded(img, num_records, mode, recording)
                                                            ⚠️ 签名无遥测输入  drive_api_bridge.py:690
                                                            ⚠️ 只发 frame/car_state  drive_api_bridge.py:661-685
                                                            ▼
   软件端后端 routers/drive.py (car_ws↔client_ws)
       ⚠️ 只解析 frame/car_state  drive.py:541-568
            ▼
   前端 useDriveWebsocket.ts
       ⚠️ 只收 car_state + webrtc_signal  useDriveWebsocket.ts:85-98
            ▼
   DrivePage.tsx 实时画面 VideoStream ✅，下方无曲线图  DrivePage.tsx:269-303
```

### 2.2 四处断点

| # | 位置 | 证据 | 现状 |
|---|---|---|---|
| 1 | 车端 DriveApiBridge 不收遥测 | `donkeycar/parts/drive_api_bridge.py:690` `run_threaded(img_arr, num_records, mode, recording)` | 签名无 IMU/throttle/steering |
| 2 | 车端 DriveApiBridge 不发遥测 | `drive_api_bridge.py:661-685` | 仅 heartbeat/webrtc_stats/car_state/frame |
| 3 | 后端不转发遥测 | `web_ui/backend/routers/drive.py:541-568` | car_ws 仅识别 num_records/drive_mode/recording/frame |
| 4 | 前端不收不画遥测 | `useDriveWebsocket.ts:85-98` | onmessage 仅 3 类消息 |

### 2.3 已就绪的基础设施（无需新建）

- 前端已装 `chart.js@4.5.1` + `react-chartjs-2@5.3.1` —— `web_ui/frontend/package.json:16,20`
- 后端已有 car_ws→client_ws 广播框架 —— `drive.py:518,572,658`（`broadcast_to_clients`）
- 车端 pipeline 已有 `imu/gyr_z`、`imu/acl_*`、`steering`、`throttle`、`pilot/angle`、`pilot/throttle` 通道 —— `mycar/manage.py:393-394,464,514-515`
- DriveApiBridge 接线点清晰 —— `mycar/manage.py:732-735`
- 固件→车端串口遥测源已通 —— `MUS4_FW.ino:765-770`（$IMU 100Hz）

## 3. 全量透传范围界定（关键，基于证据）

固件 WebConsole 显示的十几个字段，**并非全部经由串口上传给车端**。固件 Serial1 上行帧协议（`wireless_console_policy.py:190-224`、`MUS4_FW.ino:23`）仅有 3 类帧。因此"全量透传"实际可得的范围如下：

### 3.1 ✅ 车端可得（路径 A 全量范围）

| 来源 | 字段 | 车端通道 |
|---|---|---|
| 固件串口 $IMU | ax, ay, az, gx, gy, gz, seq, ts_ms | `imu/acl_x..z`、`imu/gyr_x..z`（`ArdImu` Part，`actuator.py:1500-1575`；源数据由 `Arduino.Arduino_readline` 解析 `$IMU` 并缓存于 `self.imu_data`，`actuator.py:1248-1327`） |
| 车端 donkey 自算 | steering, throttle（最终执行值） | `steering`、`throttle`（DriveMode，`manage.py:464`） |
| 车端 donkey 自算 | pilot/angle, pilot/throttle | `pilot/angle`、`pilot/throttle` |
| 车端 donkey 自算 | user/angle, user/throttle | `user/angle`、`user/throttle` |

### 3.2 ⚠️ 固件 WebConsole 有、但车端不可得（需扩固件串口协议）

固件 ESP32 内部采集、仅通过其 WiFi WebConsole 暴露，**未走串口上传**：

- 电压 `voltage`、电流 `currentMa`（INA219）
- RC 通道 `rcChannels[6]`、`rcThrottle`、`rcSteering`
- `driftEnabled`/`driftActive`/`driftCompensation`、`gyroZFiltered`、`pseudoSpeed`
- `actuatorSteeringDuty`/`actuatorThrottleDuty`、`servo_mid_v`、`motor_mid_v`、`throttle_min/max_duty`
- 固件端 `pilotThrottle`/`pilotSteering`

> **决策点**：若用户调试需要这些字段（尤其电压/电流），需扩固件 Serial1 协议新增帧 + 车端 Arduino Part 增解析。列为第 7 节"可选扩展"，**默认不在本期实施**，避免改动固件引入回归风险。

## 4. 实施方案（打通 4 处断点）

### 4.1 改动 1 — 车端 DriveApiBridge 采集并发送遥测

文件：`DonkeyDrift/donkeycar/parts/drive_api_bridge.py`

- `run_threaded` / `run` 签名增加遥测入参（全部默认 `None`，保持向后兼容）：
  ```python
  def run_threaded(self, img_arr=None, num_records=0, mode=None, recording=None,
                  imu_gz=None, imu_gx=None, imu_gy=None,
                  imu_ax=None, imu_ay=None, imu_az=None,
                  steering=None, throttle=None,
                  pilot_angle=None, pilot_throttle=None):
  ```
- 新增 `_send_telemetry(...)`，按节流频率（**100Hz / 10ms**，与固件 `$IMU` 100Hz 上行对齐）发送：
  ```python
  {"type":"telemetry","t":<epoch_ms>,"gz":..,"gx":..,"gy":..,"ax":..,"ay":..,"az":..,
   "steering":..,"throttle":..,"pilot_angle":..,"pilot_throttle":..}
  ```
- run_threaded 内调用：`if now - self.last_telemetry >= 0.01: self._send_telemetry(...)`
- **向后兼容**：新参数均默认 None，旧模板（basic.py/complete.py 等）不传亦不报错；None 字段不写入消息
- **流量**：单帧 ~190 字节 JSON，100Hz 单客户端 ~18.6 KB/s，3 客户端 ~55.7 KB/s（可接受）

### 4.2 改动 2 — 车端接线（注入遥测通道）

文件：`mycar/manage.py:732-735`

```python
V.add(ctr,
      inputs=[input_image, 'tub/num_records', 'user/mode', 'recording',
              'imu/gyr_z', 'imu/gyr_x', 'imu/gyr_y',
              'imu/acl_x', 'imu/acl_y', 'imu/acl_z',
              'steering', 'throttle', 'pilot/angle', 'pilot/throttle'],
      outputs=['user/steering', 'user/throttle', 'user/mode', 'recording', 'web/buttons'],
      threaded=True)
```

> **降级**：非 `ARDUINO_CONTROLLER` 模式（`manage.py:952`）下 `imu/*` 通道可能不存在。需在接线前判断 `cfg.HAVE_IMU`，缺失通道不接入参，曲线图组件对缺失字段自动隐藏对应曲线。

> **接线时序**：模板中 `ctr`（`complete.py:732`）在 `ArdImu`（`complete.py:1205`）之前注册。Vehicle 主循环按注册顺序每轮从 Memory 读 inputs，故首轮循环 `ctr` 读到的 `imu/gyr_z` 等为 `None`（ArdImu 尚未写入），第二轮起正常。此为 Donkey 既定行为而非缺陷，由"None 字段不写入 telemetry 消息 + 组件隐藏缺失曲线"覆盖，无需特殊处理。

> **docstring 勘误**：`ArdImu` 类 docstring（`actuator.py:1511-1521`）示例使用全称通道 `imu/accel_x`/`imu/gyro_x`，而模板实际接线使用短缩 `imu/acl_x`/`imu/gyr_x`（`complete.py:1205-1206`）。接线须以模板短缩为准；建议顺带修正 docstring 以免误导后续实施者。

### 4.3 改动 3 — 后端转发遥测

文件：`DonkeyDrift/web_ui/backend/routers/drive.py`（car_ws 处理段，541-568 附近）

在 car_ws 消息循环中新增：
```python
if msg.get("type") == "telemetry":
    # 原样广播给所有客户端；后端不节流（车端已节流 100Hz）
    await drive_state.broadcast_to_clients(msg)
    continue
```

> 100Hz 广播对所有在线 client；多客户端时流量线性放大（单帧 ~190 字节，3 客户端 ~55.7 KB/s），可接受。如需进一步降负载，后端可做 10ms 合并或改 50Hz。

### 4.4 改动 4 — 前端接收与绘制

#### 4.4.1 useDriveWebsocket 暴露遥测回调
文件：`web_ui/frontend/src/hooks/useDriveWebsocket.ts:81-98`

```typescript
// onmessage 增加
if (msg.type === 'telemetry') {
  onTelemetry?.(msg);
}
```
`UseDriveWebsocketOptions` 增加 `onTelemetry?: (t: Telemetry) => void`；新增 `Telemetry` 类型。

#### 4.4.2 新建 TelemetryChart 组件
文件：`web_ui/frontend/src/components/drive/TelemetryChart.tsx`

- 用 `react-chartjs-2` 的 `Line` 组件
- 自管 256 长度环形缓冲数组，`requestAnimationFrame` 节流重绘（上限 60fps，避免 100Hz 全量 setState）
- 默认 3 条曲线（对齐固件端）：Throttle(绿 `#39d98a`)、Steering(蓝 `#5cc8ff`)、GyroZ(红 `#ff6b6b`)，归一化 -1~1
- 全量开关：ax/ay/az/gx/gy/pilot_angle/pilot_throttle 通过工具栏 checkbox 切换显隐
- 工具栏：暂停、清空、全屏、曲线开关
- 缺失字段（None）自动隐藏对应曲线

#### 4.4.3 DrivePage 插入曲线图
文件：`web_ui/frontend/src/pages/DrivePage.tsx:269-303`

在摄像头区（`lg:col-span-2`）下方插入：
```tsx
<div className="lg:col-span-2">
  <VideoStream ... />
  <TelemetryChart telemetry={telemetry} className="mt-4" />
</div>
```
DrivePage 通过 `useDriveWebsocket({ onTelemetry })` 持有最新遥测 ref（不进 state，避免重渲染）。

## 5. TDD 计划（红-绿-重构）

遵循 CLAUDE.md 的 PCT 工作流，每处断点先写失败测试：

| 测试文件 | 覆盖断点 | 关键用例 |
|---|---|---|
| `donkeycar/tests/test_drive_api_bridge_telemetry.py` | 1 | 输入遥测 → 发出 telemetry 消息；None 输入不报错；100Hz 节流 |
| `web_ui/backend/tests/test_drive_telemetry_forward.py` | 3 | car 发 telemetry → 所有 client 收到原样消息 |
| `web_ui/frontend/src/components/drive/TelemetryChart.test.tsx` | 4 | 收到 telemetry → 曲线数据更新；暂停停止更新；清空归零；缺失字段隐藏 |

车端接线（改动 2）无独立单测，由集成验证：启动 manage.py 确认 DriveApiBridge 收到 imu/gyr_z。

## 6. 风险与降级

| 风险 | 影响 | 缓解 |
|---|---|---|
| DriveApiBridge 属 donkeycar 框架库，改动波及模板（basic/complete 等） | 中 | 新参数全默认 None，向后兼容；模板无需改 |
| 非 ARDUINO_CONTROLLER 模式无 imu/* 通道 | 中 | 接线前判 `cfg.HAVE_IMU`；组件对缺失字段降级 |
| 50Hz 广播多客户端放大流量 | 低 | 单帧~190B；100Hz 单客户端 ~18.6 KB/s，3 客户端 ~55.7 KB/s；必要时后端 10ms 合并或降回 50Hz |
| Chart.js 100Hz 重绘性能 | 中 | requestAnimationFrame 节流至上限 60fps；256 点环形缓冲；非 setState 驱动；低端设备可降回 50Hz |
| 前端曲线归一化范围与固件端不一致 | 低 | 固件 gyroZ 除以 5、thr/str 除以 100；前端统一按字段实际范围配置 yAxis |

## 7. 可选扩展（默认不做，需用户确认）

若需第 3.2 节字段（电压/电流/RC/PID/漂移补偿等）：
- 固件端：`MUS4_FW.ino` 扩 Serial1 新增帧（如 `$PWR,voltage,current\n`、`$DRIFT,...\n`）
- 车端：`actuator.py` Arduino_readline 增解析分支，输出 `pwr/voltage` 等通道
- 车端接线 + DriveApiBridge + 后端 + 前端同步扩展

> 此扩展改动固件，引入回归风险，且与本任务核心（移植曲线图）解耦。建议曲线图先落地，再按调试需求逐字段扩。

## 8. 工作量估算

| 改动 | 文件 | 估算 |
|---|---|---|
| 1 车端 Part | drive_api_bridge.py + 测试 | 中 |
| 2 车端接线 | mycar/manage.py | 小 |
| 3 后端转发 | routers/drive.py + 测试 | 小 |
| 4 前端组件 | useDriveWebsocket.ts + TelemetryChart.tsx + DrivePage.tsx + 测试 | 中 |
| 集成验证 | 启动 manage.py + 软件端 | 小 |

## 9. 决策点（已确认）

1. **第 3.2 节字段（电压/电流/RC 等）是否本期纳入？** → **不纳入**。仅用现有串口 $IMU + 车端自算通道（steering/throttle/pilot）。电压/电流/RC/PID/漂移补偿等需改固件 Serial1 协议，回归风险高且与曲线图核心解耦，留作后续按调试需求逐字段扩。
2. **曲线频率**：→ **车端 100Hz 发送 / 前端 60fps 重绘**。与固件 `$IMU` 100Hz 上行对齐；requestAnimationFrame 节流至上限 60fps，256 点环形缓冲，ref 不进 state。窗口约 256/100≈2.6 秒。
3. **曲线默认显示**：→ **固件原样 3 条**（Throttle 绿 `#39d98a`、Steering 蓝 `#5cc8ff`、GyroZ 红 `#ff6b6b`）+ 其余（ax/ay/az/gx/gy/pilot_angle/pilot_throttle）通过工具栏 checkbox 开关。
