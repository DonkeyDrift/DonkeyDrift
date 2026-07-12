# 自动漂移回放（Auto Drift Replay）技术方案 RFC

> 状态：草案，待审批
> 宿主项目：DonkeyDrift（`/home/dkc/projects/DonkeyDrift`）
> 固件侧：不改动（`/home/dkc/projects/Firmware/MUS4_FW`）
> 创建：2026-07-12

## 0. 摘要

把人工手动录制的漂移操作（Donkeycar Tub v2 格式，`user/angle`/`user/throttle` 时间序列）以**回放**形式，通过上位机串口向 ESP32 主控发送转向/油门数据，复现漂移动作。

核心思路：在 DonkeyDrift 里新增一个 **`DriftReplayPart`**，它实现与现有 `KerasPilot` **完全相同的 Part 接口**（输出 `pilot/angle`/`pilot/throttle`，`run_condition='run_pilot'`），用"录制数据按 `_timestamp_ms` 时戳重放"替代"模型推理"。所有值域转换、串口下发、安全门控都复用既有链路，**不改固件、不改 `actuator.py`**。

## 1. 背景与目标

### 目标
- 多段拼接 + 后处理：从多个 Tub 片段挑选成功漂移段，拼接、裁剪、归一化、调速率后回放。
- 按原始 `_timestamp_ms` 时戳调度回放（可整体调速率 0.5~2.0x）。
- 循环回放 N 次、段间静置过渡、首尾安全包络。
- 工具层标准限幅（thr≤60、str≤100，-100~100 域）+ delta 限幅。
- 整合到 drift console（DonkeyDrift Web UI）。

### 非目标
- 不做漂移动作生成/优化（只回放录制数据）。
- 不改 ESP32 固件（已有 FULL_AUTO 接收 + Park/mode 安全接管）。
- 不改 `actuator.py` 的 Arduino/ArdPWM 下发链路。

## 2. 可行性结论：✅ 可行

证据链完整（均经亲自核验，见 §3）：

| 层 | 结论 | 关键证据 |
|---|---|---|
| 数据层 | Tub v2 已含录制时序 + 时戳 | `_timestamp_ms` 毫秒时戳、`user/angle`/`user/throttle`（-1~1） |
| 通道层 | 上位机->串口->ESP32 路径已存在并工作 | `actuator.py:1472-1473` 下发 `"%d:%d\n"` |
| 接口层 | Pilot Part 接口标准化，可无缝替换 | `complete.py:426` `outputs=['pilot/angle','pilot/throttle']` |
| 安全层 | 固件双重门控 + 工具层门控 | `CommandParser.cpp:75` ±100 限幅、`SafetyState.cpp:26-75` Park 制动 |
| 复用层 | 现有 KerasPilot 链路完整 | `DriveMode`(461) -> `ArdPWMSteering/Throttle`(1196) |

固件**不需要改**；DonkeyDrift 侧新增 Part + 数据准备 + Web UI 入口。

## 3. 现状与证据

### 3.1 固件端（不改动）

**命令接收与限幅**（`MUS4_FW/libraries/mus4_command/src/CommandParser.cpp`）：
- `parsePilotCommandLine()` 支持 `T:S`、`T:S:Seq`、`T:S*CRC` 三种格式。
- `parseAndValidateCommand()` 第 75 行硬限幅：`if (t < -100 || t > 100 || s < -100 || s > 100) return false;` —— 超范围命令直接拒绝。
- 解析成功写入 `pilot_data`（`CommandDispatcher.cpp:224-227`）。

**模式融合**（`MUS4_FW/libraries/mus4_control/src/ControlMixer.cpp`）：
- `mode_change()` 第 32 行：`car_output.mode` 来自 RC CH4 PWM，`<=1250` MANUAL、`>=1750` FULL_AUTO。**mode 只能由 RC CH4 切换，串口命令无法切**。
- `updateControlOutput()` FULL_AUTO 分支（第 57-82 行）：
  - 第 75 行 `car_output.throttle = pilot_data.throttle;`（仅 park==0 时）
  - 第 77 行 `car_output.steering = apply_drift_assist(pilot_data.steering);`（**在 if-else 之外，park==1 时仍执行**）
  - 即 FULL_AUTO 下油门/转向完全来自 `pilot_data`，RC 油门/转向被忽略。

**Park 紧急制动**（`MUS4_FW/libraries/mus4_safety/src/SafetyState.cpp:26-75`）：
- 三级状态机：`EST_IDLE`(throttle>0 时设 15) -> `EST_READY`(500ms 后设 -100) -> `EST_BRAKING`(1500ms) -> `EST_DONE`(设 0)。
- **Park 后油门经 15 -> -100 -> 0 三级制动，总耗时约 2 秒，不是瞬停**。
- RC Park（CH3 长按 1s，第 124-130 行）和 RC mode 切换（CH4）**无条件立即接管**。

**PWM 硬限幅**（`MUS4_FW/libraries/mus4_safety/src/ActuatorOutput.cpp:49`）：
- `pwm_steering = min(max(pwm_steering, 4915), 9830);` 全局硬边界。
- 油门受 `joystick_cal.throttle_min/max_duty` 限幅（第 50 行）。
- **无 slew rate（变化率）限制**——上位机必须自带 delta 限幅。

### 3.2 DonkeyDrift 上位机端（改动落点）

**实际下发代码**（`donkeycar/parts/actuator.py`）：
- `Arduino` 类（第 1166 行）：管理串口，`Arduino_readline()`（第 1248 行）解析上行 `T..S..`/`M:P`/`$IMU` 帧；上行 -100~100 映射回 -1~1（第 1288-1291 行）。
- `ArdPWMSteering`（第 1334 行）：`LEFT_ANGLE=-100, RIGHT_ANGLE=100`；`run_threaded(self, mode, angle)` 第 1381 行 `if(self.mode != 'user')` 才走 set_cmd——**上位机只在 donkeycar `user/mode != 'user'` 时才下发**，与固件 FULL_AUTO 门控双重一致。
- `ArdPWMThrottle`（第 1410 行）：`MAX_THROTTLE=100`；`run_threaded(self, mode, throttle, throttleUser)` 第 1472-1473 行**实际下发**：
  ```python
  with Arduino.ard_lock:
      Arduino.ard_device.write(("%d:%d\n" % (self.controller.throttleCmd, self.controller.steeringCmd)).encode('ascii'))
  ```
- `Arduino.set_cmd()`（第 1199-1210 行）下发代码已被注释，下发逻辑已移到 `ArdPWMThrottle.run_threaded`。

**Vehicle 装配**（`donkeycar/templates/complete.py`）：
- Pilot Part 注册（第 426 行）：`V.add(kl, inputs=['cam/image_array'], outputs=['pilot/angle','pilot/throttle'], run_condition='run_pilot')`。
- `run_pilot` 条件由 `UserPilotCondition`（第 174-176 行）维护，`user/mode != 'user'` 时为 True。
- `DriveMode` Part（第 461-464 行）：按 `user/mode` 选 `user/*` 或 `pilot/*` 输出到 `steering`/`throttle`。
- ARDUINO_CONTROLLER 装配（第 1196-1197 行）：
  ```python
  V.add(steering, inputs=['user/mode','steering'], outputs=['user/mode','user/angle','user/throttle'], threaded=True)
  V.add(throttle, inputs=['user/mode','throttle','user/throttle'], outputs=['user/throttle'])
  ```
- `donkeydrifter.parts.actuator` 通过 meta_path 转发到 `donkeycar.parts.actuator`（`donkeydrifter/__init__.py:50-57`，已确认）。

**遗留问题（需在实施时关注，不在本 RFC 范围内修）**：
- `complete.py:1178` 注释自相矛盾："This driver is DEPRECATED in favor of 'DRIVE_TRAIN_TYPE == \"ARDUINO_CONTROLLER\"'"。
- `ArdPWMSteering.LEFT_ANGLE=-100` 与 `DriveMode` 输出的 -1~1 衔接存在值域疑点，是既有代码既有行为；回放 Part 复用 KerasPilot 接口即与之同构，**实施时用 dry-run + 串口抓包验证最终下发值**。

### 3.3 数据格式

用户确认录制数据为 **Donkeycar Tub v2 原生**（`manifest.json` + `catalog_*.catalog`）：
- 读取 API：`donkeycar/parts/tub_v2.py` `Tub(base_path, read_only=True)`，`for record in tub:` 迭代（代理到 `ManifestIterator`）。
- 单条记录是 dict，字段名带 `/`：`user/angle`（-1~1）、`user/throttle`（-1~1）、`user/mode`、`cam/image_array`。
- **每条含 `_timestamp_ms`（毫秒 Unix 时戳）+ `_index`（序号）+ `_session_id`**（`tub_v2.py:78-82`）——支持"按原始 t 时戳回放"。
- 固件仓库 `data/ref/` 下有样本（manifest inputs `["cam/image_array","user/angle","user/throttle","user/mode"]`）。

## 4. 方案设计

### 4.1 总体架构

```
[Tub v2 录制数据]
      │  (DriftClipBuilder 离线编辑: 选段/拼接/归一化/调速率)
      ▼
[replay clip JSON]  ← 标准化中间格式 mus4.drift_replay_clip.v1
      │
      ▼
[DriftReplayPart]   ← Vehicle Part, run_condition='run_pilot'
      │  run() 按 _timestamp_ms 返回 (angle, throttle) ∈ [-1,1]
      │  内部: 限幅 + delta + 循环 + 段间过渡 + 首尾包络
      ▼
  Memory: pilot/angle, pilot/throttle
      │  (DriveMode 按 user/mode='local' 选取)
      ▼
  Memory: steering, throttle
      │  (ArdPWMSteering/ArdPWMThrottle 消费)
      ▼
  串口下发 "throttleCmd:steeringCmd\n"  (actuator.py:1473)
      ▼
  ESP32 CommandParser(±100限幅) -> FULL_AUTO 融合 -> PWM 输出
```

回放 Part 是"假 Pilot"：接口与 `KerasPilot` 完全同构，只是数据源从"模型推理"换成"录制序列重放"。

### 4.2 DriftReplayPart（核心）

**文件**：`donkeycar/parts/drift_replay.py`（新）

**职责**：读 replay clip，按 `_timestamp_ms` 调度，输出 `pilot/angle`/`pilot/throttle`（-1~1）。

**接口**（与 KerasPilot 对齐）：
```python
class DriftReplayPart:
    def __init__(self, clip_path, speed=1.0, loop=1,
                 max_throttle=0.6, max_steering=1.0,
                 max_delta_throttle=0.2, max_delta_steering=0.3,
                 transition_ms=300, warmup_frames=10, ...): ...
    def run(self): -> (angle, throttle)  # 写入 pilot/angle, pilot/throttle
    def shutdown(self): ...
```

**调度**（按原始 t 时戳，用户已选）：
- 起始时记录 `_start_mono = time.monotonic()`、`_start_ts = clip[0]._timestamp_ms`。
- 每帧目标时刻 `t_target = _start_mono + (clip[i]._timestamp_ms - _start_ts) * speed / 1000.0`。
- 若当前时刻已超过 `t_target` 且落后多帧，跳帧追赶（不阻塞主循环）；若超前，返回上一帧值。
- 循环：到末尾后，若 `loop>1`，重置起点继续；段间插入静置帧（`transition_ms` 内 angle=throttle=0）。

**安全机制**（Part 内部，-1~1 域）：
- 限幅：`max_throttle=0.6`（对应 -100~100 域 60）、`max_steering=1.0`（对应 100）。
- delta 限幅：`max_delta_throttle=0.2`、`max_delta_steering=0.3`（固件无 slew rate，**这是上位机必须承担的安全责任**）。
- 首尾包络：开头发 `warmup_frames` 帧 (0,0)；结尾发 (0,0) 收尾。
- 失效安全：异常或 shutdown 时输出 (0,0)。

**装配**（`complete.py` 新增 `add_drift_replay(V, cfg)`，在 `add_pilot` 旁）：
```python
if cfg.DRIFT_REPLAY_ENABLED:
    from donkeydrifter.parts.drift_replay import DriftReplayPart
    replay = DriftReplayPart(clip_path=cfg.DRIFT_REPLAY_CLIP, ...)
    V.add(replay, outputs=['pilot/angle', 'pilot/throttle'], run_condition='run_pilot')
```
与 KerasPilot 互斥（回放时关闭模型推理，或用配置开关二选一）。

### 4.3 数据准备（clip 编辑）

**文件**：`scripts/build_drift_clip.py`（新，独立脚本，非 Vehicle 运行时）

**职责**：从 Tub v2 读取 -> 选段/裁剪/拼接/归一化/调速率 -> 输出标准化 replay clip JSON。

**功能**：
- 加载一个或多个 Tub（`Tub(base_path, read_only=True)` 迭代）。
- 选段：按 `_index` 区间 / `_timestamp_ms` 区间 / `user/mode` 过滤裁剪。
- 拼接：多段首尾相接，段间插入静置帧（`thr=0,str=0`，时长 `transition_ms`）。
- 归一化：可选 `--scale`、`--offset`、`--clip`（缩放/偏移/限幅 thr/str）。
- 调速率：`--speed` 对时间轴重采样（0.5~2.0x），生成新 `_t_rel` 序列。
- 输出：`mus4.drift_replay_clip.v1` JSON，含 `samples:[{t_rel, throttle, angle}]` + 元信息（来源 tub、缩放、速率、段数）。

**纯数据处理，不连串口，无安全风险**。可独立 TDD。

### 4.4 Web UI（drift console）集成

**后端**（`web_ui/backend/routers/replay.py`，新）：
- FastAPI `APIRouter`，挂载到 `main.py` 的 `app.include_router(replay.router, prefix="/api/replay", ...)`。
- 端点：`GET /api/replay/clips`（列出可用 clip）、`POST /api/replay/load`（加载 clip 到运行时）、`POST /api/replay/start`、`POST /api/replay/stop`、`GET /api/replay/status`。
- 状态管理参考 `provisioning.py` 的模块级状态模式（Vehicle 未运行时也能列 clip）。

**前端**（`web_ui/frontend/src/pages/ReplayPage.tsx`，新）：
- `App.tsx` 用 `React.lazy` 导入 + `<Route path="/replay">` 注册。
- API 客户端函数加到 `services/api.ts`（复用现有 axios 实例，不手写 base URL）。
- 页面：clip 列表选择、参数调节（speed/loop/限幅）、启动/停止按钮、实时状态显示。

**安全约束**：启动回放前，前端校验 `user/mode` 已切到非 user（提示用户拨 RC CH4 到 FULL_AUTO + 解 Park），否则拒绝启动并提示。

## 5. 安全设计

### 双重门控（固件 + 工具）
1. **固件层**（已有，不改）：RC Park 三级制动 + RC mode 立即接管 + ±100 硬限幅 + PWM 硬限幅。
2. **工具层**（新）：Part 内限幅 + delta 限幅 + 首尾包络 + 失效安全。

### 紧急停止路径
- **首要**：驾驶员按 RC Park 或拨 CH4 回 MANUAL —— 固件立即接管，**这是最可靠的，任何时候都有效**。
- **次要**：Web UI 点"停止" / Ctrl-C / 异常 —— Part 输出 (0,0)，但**注意 Park 制动需约 2 秒**（三级状态机），高速漂移时需预留制动距离。

### 必须遵守的安全约束（来自证据）
| 约束 | 证据 | 对策 |
|---|---|---|
| Park 不瞬停（~2s） | `SafetyState.cpp:26-75` | 高速回放预留制动空间 |
| Park 时转向仍跟随上位机 | `ControlMixer.cpp:77` 在 if-else 外 | Part 检测 park 后停发或发 str=0 |
| 固件无 slew rate | `ActuatorOutput.cpp` map 后直写 | Part 内 delta 限幅（必须） |
| mode 只能 RC 切 | `ControlMixer.cpp:32` | 启动前校验 + 提示用户拨 CH4 |
| 录制 thr/str 是人工语义 | Tub `user/*` | 回放复现人当时操作，非优化轨迹 |

## 6. 关键约束与已知坑

1. **值域衔接**：Tub 录制 -1~1，ArdPWM 内部 -100~100。回放 Part 输出 -1~1（与 KerasPilot 同构），既有 `DriveMode -> ArdPWM` 链路负责转换。**实施时必须用 dry-run + 串口抓包验证最终下发值落在预期范围**（固件 `CommandParser:75` 会拒绝超 ±100 的值）。
2. **时间基准**：`_timestamp_ms` 是录制时的绝对 Unix 时戳；回放按相对时差调度，不依赖绝对值。若某些旧 Tub 无 `_timestamp_ms`，回退到按 `_index` 等间隔（用 `--rate-hz` 指定）。
3. **回放与 RC 的关系**：FULL_AUTO 下 RC 油门/转向被完全忽略（`ControlMixer.cpp:75,77`），但 RC Park/mode 仍有效。即回放中驾驶员无法用 RC 油门微调，只能 Park 或切模式接管。
4. **Drift Assist 叠加**：`ControlMixer.cpp:77` `apply_drift_assist(pilot_data.steering)` 会在回放转向上叠加 IMU 补偿。回放漂移时这可能是利好（辅助维持姿态）或干扰（偏离录制轨迹），**实测决定是否需要在固件层临时关闭 Drift Assist**（若需关，则触及固件，需另起 RFC）。
5. **录制节奏复现**：按原始 t 时戳回放依赖录制时戳质量；若录制时 Vehicle 主循环有抖动，回放会复现同样的抖动。`--speed` 整体调速可缓解。

## 7. 值域与限幅（标准档，用户已选）

| 参数 | 默认值 | -100~100 域等价 | 说明 |
|---|---|---|---|
| max_throttle | 0.6 | 60 | 油门上限 |
| max_steering | 1.0 | 100 | 转向上限（漂移需大转向） |
| max_delta_throttle | 0.2 | 20/帧 | 油门变化率 |
| max_delta_steering | 0.3 | 30/帧 | 转向变化率 |
| speed | 1.0 | — | 回放速率 |
| loop | 1 | — | 循环次数 |
| transition_ms | 300 | — | 段间静置 |
| warmup_frames | 10 | — | 首部 (0,0) 预热帧 |

全部可配，硬上限受固件 ±100 兜底。

## 8. TDD 计划（红-绿-重构）

按用户全局 CLAUDE.md 的 PCT 工作流，测试先行。

### DriftReplayPart 单测（`donkeycar/tests/test_drift_replay.py`）
- 🔴 `test_run_returns_zero_before_clip_loaded` —— 未加载 clip 返回 (0,0)
- 🔴 `test_first_frame_after_warmup_is_zero` —— 首部预热帧为 (0,0)
- 🔴 `test_frame_scheduled_by_timestamp` —— 按 `_timestamp_ms` 调度正确帧
- 🔴 `test_throttle_clamped_to_max` —— 油门超限被钳到 0.6
- 🔴 `test_steering_delta_limited` —— 转向瞬变被 delta 限制
- 🔴 `test_loop_restarts_clip` —— 循环到末尾后重置
- 🔴 `test_transition_frame_between_segments` —— 段间插入静置帧
- 🔴 `test_shutdown_emits_zero` —— shutdown 输出 (0,0)
- 🔴 `test_speed_scales_timeline` —— speed=2.0 时间轴压缩一半
- 🔴 `test_park_signal_stops_steering` —— 检测 park 时转向归零（对应 `ControlMixer.cpp:77` 约束）

### clip builder 单测（`tests/test_build_drift_clip.py`）
- 🔴 `test_load_tub_v2_records` —— 正确迭代 Tub v2 取 `user/angle`/`user/throttle`
- 🔴 `test_clip_segment_by_index_range` —— 按 _index 区间裁剪
- 🔴 `test_concat_segments_inserts_transition` —— 拼接插入静置帧
- 🔴 `test_scale_applies_to_throttle` —— 缩放生效
- 🔴 `test_speed_resample_timeline` —— 调速率重采样
- 🔴 `test_output_schema_v1` —— 输出符合 `mus4.drift_replay_clip.v1`

### Web UI（若纳入第一版）
- 后端 `web_ui/backend/tests/test_replay.py`：路由契约、状态机。
- 前端 `ReplayPage.test.tsx`：clip 列表渲染、启动前校验。

## 9. 任务清单

### 阶段一：数据层（无硬件风险）
- [ ] `scripts/build_drift_clip.py` + 单测
- [ ] replay clip JSON schema `mus4.drift_replay_clip.v1` 定义
- [ ] 用固件仓库 `data/ref/` 样本验证 clip 生成

### 阶段二：回放 Part（dry-run 验证）
- [ ] `donkeycar/parts/drift_replay.py` `DriftReplayPart` + 单测
- [ ] `complete.py` `add_drift_replay()` 装配 + `cfg_complete.py` 配置键
- [ ] dry-run：不连车，验证 Part 输出序列与录制一致

### 阶段三：实车验证（需用户在场）
- [ ] 串口抓包验证最终下发值（值域衔接确认）
- [ ] 低速 + 小限幅实车回放
- [ ] 验证 RC Park/mode 紧急接管有效
- [ ] 逐步放宽到标准限幅

### 阶段四：Web UI 集成
- [ ] 后端 `routers/replay.py` + 测试
- [ ] 前端 `ReplayPage.tsx` + `services/api.ts` + 路由注册
- [ ] 启动前安全校验（mode/park 状态）

## 10. 不在本次范围

- 不改 ESP32 固件（含 Drift Assist 开关——若实测需关，另起固件 RFC）。
- 不改 `actuator.py` 下发链路（含值域衔接遗留问题）。
- 不做漂移动作生成/优化/路径规划。
- 不支持 ESP32 导出 JSON 格式（用户确认只用 Tub v2）。

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 值域衔接导致下发值异常 | dry-run + 串口抓包，阶段三才上实车 |
| 回放中失控 | RC Park/mode 随时接管（固件保底） |
| delta 不足损坏电调/舵机 | Part 内 delta 限幅 + 标准限幅默认值 |
| Drift Assist 干扰回放 | 实测决定，必要时另起固件 RFC 临时关闭 |
| 时间戳缺失 | 回退按 `_index` 等间隔 + `--rate-hz` |

**回滚**：所有改动在 DonkeyDrift 侧新增文件 + `complete.py` 受 `cfg.DRIFT_REPLAY_ENABLED` 开关控制，关闭开关即完全回退到现有 Pilot 链路，无残留影响。

## 12. 范围决策（已与用户确认）

1. **Web UI**：不纳入第一版，作为阶段四后续。第一版 = 阶段一（数据层）+ 阶段二（Part + dry-run），无实车、无 Web UI、不改固件。
2. **Drift Assist**：不关，实测后定；若回放时干扰，另起固件 RFC 临时关闭（触及安全关键固件）。
3. **clip 存放**：mycar 车目录 `data/clips/`（与 tub 录制数据同级），builder 输出路径参数化、默认此处。
4. **配置开关**：`DRIFT_REPLAY_ENABLED` 等键加到 `cfg_complete.py` 默认 `False`（不影响现有行为），用户在 `myconfig.py` 覆盖开启。
