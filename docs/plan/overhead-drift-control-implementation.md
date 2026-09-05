# 实施计划：第三视角俯拍漂移控制系统

- 日期：2026-08-30
- 关联 RFC：`docs/Rfc/overhead-drift-control.md`（已评审通过）
- 分支：`docs/rfc-overhead-drift-control`（RFC 提交）→ 实施分支 `feat/overhead-drift-control`

## 总体原则

1. **TDD 红-绿-重构**：每个模块先写失败测试再写实现（用户工作流强制）。
2. **里程碑门禁**：每个里程碑有明确验收标准，通过才进下一个（对应 RFC 第 10 节分步验收）。
3. **模块边界**：`drift_vision.py`（视觉）/ `drift_controller.py`（控制）/ `sync_recorder.py`（录制）/ `routers/drift.py`（API）各单一职责，单文件目标 <300 行；新增依赖进 `web_ui/backend/requirements.txt`。
4. **车端与固件零代码改动**（RFC 第 13 节），仅配置操作。

## 里程碑

### M0：链路与标定基座（RFC 验收第 1 步）

**目标**：俯拍相机接入、标定能力、延迟实测——回答"链路够不够格"。

| 任务 | 文件 | 说明 |
|---|---|---|
| 相机采集 Part | `web_ui/backend/drift_vision.py` | UVC 相机（MJPG，帧率/曝光可配），帧带单调笔记本时钟戳 |
| AprilTag 检测 | `drift_vision.py` | 选型 `pupil-apriltags`（预装验证，不可用则备选 `pyapriltags`），检出车顶标签 ID 与四角 |
| 相机内参标定 | `scripts/calibrate_overhead_camera.py` | 棋盘格流程，输出内参文件 |
| 单应性标定 | `scripts/calibrate_field_homography.py` | 地面四角已知点 → 图像坐标映射（米制），输出标定文件 |
| 会话状态机 | `web_ui/backend/drift_session.py` | `IDLE/CALIBRATE/RECORD/AUTO` 转换与守卫 |
| API 骨架 | `web_ui/backend/routers/drift.py` + `main.py` 注册 | 状态查询、标定文件加载 |
| 延迟实测工具 | `scripts/measure_loop_latency.py` | 分段测量：相机采集→检测耗时；ws 下发→车端回显往返 |

**测试（先红后绿）**：状态机非法转换拒绝；单应性映射（合成四点往返一致性，误差 <1e-9）；时间戳单调性。

**验收**：①端到端延迟 P95 实测值记录在案（预算 ~100ms，超标按 RFC 加超前补偿再评估）；②场地上车顶 AprilTag 在漂移速度下稳定检出（丢帧率 <5%）；③核对 `routers/drive.py` 多 client 并发行为，记录仲裁结论。

### M1：状态估计 + 三路同步录制（RECORD 模式）

**目标**：人工 RC 漂移全程可录，产出带 β 和点动特征的 tub。

| 任务 | 文件 | 说明 |
|---|---|---|
| 位姿解算 | `drift_vision.py` | AprilTag → (x, y, heading)，经单应性映射场地坐标 |
| β 估计器 | `web_ui/backend/state_estimator.py` | 航迹角=位姿差分低通；与 `gyr_z` 互补滤波；起漂前直行 β≈0 锚定 |
| 遥测对齐 | `web_ui/backend/sync_recorder.py` | 以相机帧时戳为基准对 ws 遥测流线性插值（rc 60Hz / imu 100Hz） |
| 点动特征在线提取 | `sync_recorder.py` | 滑动窗（~1s）过零/峰检测：频率、占空比、峰值幅值 |
| tub 写入 | `sync_recorder.py` | tub v2 格式，字段按 RFC 第 6 节，笔记本本地目录 |
| RECORD 模式串通 | `drift_session.py` + `routers/drift.py` | 订阅现有遥测流（复用 `routers/drive.py` 遥测转发通路，不新开链路） |

**测试**：合成遥测流插值对齐误差 <10ms；合成方波点动特征（已知频率/占空比/幅值恢复误差 <10%）；互补滤波对合成 β 阶跃的收敛；tub 字段清单与 manifest 一致。

**验收**：实车人工漂移录制 ≥2 分钟，回放检查：对齐达标、漂移段 β 落在物理合理区间（约 15°~40°）、点动特征与肉眼观察的节奏一致。

### M2：点动机理离线验证（RFC 验收第 3 步）

| 任务 | 文件 |
|---|---|
| 点动分析工具 | `scripts/analyze_throttle_pulses.py`：滑动窗输出"频率↔半径""占空比↔β"关系曲线与拟合参数表 |
| 控制器参数表输出 | 同上，产出外环整定初值（f/D/A/T_base 范围） |

**测试**：合成 tub（构造已知频率-半径关系）分析结果正确。

**验收**：真实数据上"频率高→半径小"单调性成立。**不成立则停下回 RFC 修正机理模型，不带病进 M3。**

### M3：控制器 + 离线仿真（TDD 核心）

| 任务 | 文件 | 说明 |
|---|---|---|
| 级联 PID | `web_ui/backend/drift_controller.py` | β* 外环（慢 5~10Hz）、yaw-rate 内环（快）、半径保持环 |
| 油门脉冲发生器 | `drift_controller.py` | 参数 (f, D, A, T_base)，60Hz tick，参数变更相位平滑过渡 |
| 限幅与看门狗 | `drift_controller.py` | 输出限幅、delta 限幅（转向变化率）、丢帧 >200ms/ws 断线 → Park + MODE 0 |
| AUTO 编排 | `drift_session.py` | MANUAL 观察 → β 稳定判定（\|β\|>15° 持续 500ms）→ 下发 MODE 2 → 60Hz 控制循环（经现有 ws 控制通道） |
| 离线仿真 | `scripts/simulate_drift_controller.py` | M1 tub 的位姿/IMU 序列驱动控制器闭环 |

**测试（先红后绿，全部合成数据）**：PID 输出限幅边界；脉冲发生器波形周期/占空比/参数平滑（无半周期突变）；看门狗触发路径；接管判定逻辑（含抖动抑制）；MODE 0→2 命令序列正确。

**验收**：离线仿真中 β 收敛到 β* 并保持；模拟丢帧/断线时安全路径 100% 触发。**先静止实测 MODE 0→2 跳变的固件接受性（RFC 风险表），再进实车。**

### M4：实车低速闭环（RFC 验收第 5 步）

**目标**：非漂移低速定圆验证控制链路与安全联锁。

任务：低速定圆闭环实测；安全联锁演练（拔相机→看门狗、断 ws→看门狗、CH4 物理夺回）。

**验收**：低速定圆稳定 ≥1 分钟；三项安全联锁全部按预期触发。

### M5：漂移验收 + 前端卡片（RFC 验收第 6 步·最终）

| 任务 | 文件 | 说明 |
|---|---|---|
| 前端卡片 | `web_ui/frontend/src/components/drift/` | 俯拍预览+位姿/β 叠加、模式按钮（标定/录制/自动）、参数面板（PID、β*、f/D/A/T_base、限幅） |
| 固件配置操作 | （无代码） | FULL_AUTO 下关闭 yaw-rate 转向修正（现有开关），操作步骤写入卡片帮助文案 |
| 最终验收 | — | RC 起漂 → 接管 → 定圆连续漂移 ≥30 秒 |

**验收**：定圆 30 秒达成；录制 AUTO 全程数据（后续调参与蒸馏复用）。

## 依赖与顺序

```
M0 ──→ M1 ──→ M2 ──→ M3 ──→ M4 ──→ M5
（硬件：俯拍相机+三脚架在 M0 前到位；标定场地标记同）
```

M2 与 M3 的部分纯软件任务可并行（控制器 TDD 不依赖真实数据），但 M3 的参数整定必须等 M2 的参数表。

## 新增依赖（M0 时加入 `web_ui/backend/requirements.txt`）

`pupil-apriltags`（AprilTag 检测；不可用备选 `pyapriltags`）；`scipy`（滤波/插值，若环境中缺）。

## 遗留核对项（散布在对应里程碑内执行）

- 多 client 仲裁行为（M0）；固件 MODE 0→2 跳变接受性（M3 前静止实测）；`dsc` 遥测字段语义（第二阶段前核对，不阻塞本计划）。
