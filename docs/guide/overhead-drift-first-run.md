# 第三视角漂移系统：首次实操手册（明早按此操作）

- 对应 RFC：`docs/Rfc/overhead-drift-control.md`；实施计划：`docs/plan/overhead-drift-control-implementation.md`
- 代码分支：`feat/overhead-drift-control`（后端模块 + 脚本 + 前端卡片均已提交，测试 193 项通过）

## 今晚已完成的软件框架

| 模块 | 文件 | 测试 |
|---|---|---|
| 会话状态机（分阶段控制流） | `web_ui/backend/drift_session.py` | 17 项 |
| 俯拍视觉（单应性/位姿/平滑/相机抽象） | `web_ui/backend/drift_vision.py` | 12 项 |
| β 估计器（heading 域互补滤波） | `web_ui/backend/state_estimator.py` | 8 项 |
| 同步录制（插值对齐/点动特征/tub） | `web_ui/backend/sync_recorder.py` | 12 项 |
| 漂移控制器（级联 PID+脉冲发生器+看门狗） | `web_ui/backend/drift_controller.py` | 13 项 |
| 点动机理分析 | `web_ui/backend/throttle_analysis.py` | 4 项 |
| 编排引擎 + API | `web_ui/backend/drift_engine.py`、`routers/drift.py` | 10 项 |
| 离线闭环仿真 | `scripts/simulate_drift_controller.py` | ✅ β 收敛 25.00°/极差 0.01° |

## 准备清单（硬件/物料）

- [ ] USB 俯拍相机 + 三脚架（约 2m 高，画面覆盖约 2m×2m 场地）
- [ ] 打印棋盘格（9×6 内角点，格距实测）
- [ ] 打印车顶 AprilTag：`docs/assets/apriltags/tag36h11_print_80mm.pdf`（ID 0 主用 + ID 1 备用，A4 600dpi，页面含 100mm 自检标尺，已用官方检测器验证可解码）。打印时选“100% 实际大小”；打印后先实测标尺=100mm、黑框本体=80mm 再贴车顶（黑框中心对准车顶回正中心）
- [ ] 地面四角标记 + 定圆标记（卷尺量场地宽高，西南角为原点）

## 第 1 步：装依赖 + 冒烟

```powershell
pip install pupil-apriltags    # Windows 编译失败时：WSL 下装，或换 pyapriltags
cd web_ui\backend && python -m pytest tests/ -q    # 期望 193 passed（trainer_tubs 1 项存量失败与本工作无关）
python scripts\simulate_drift_controller.py        # 期望 ✅ β 收敛 25.00°
```

## 第 2 步：M0 标定（每项做完在操作时立即验证）

```powershell
# 2.1 内参（可选但建议；跳过时单应性仍可用，只是畸变略大）
python scripts\calibrate_overhead_camera.py --camera 0 --square 0.025

# 2.2 场地单应性（必须）：按提示依次点击 西北→东北→东南→西南 四角
python scripts\calibrate_field_homography.py --camera 0 --field-width 2.0 --field-height 2.0 --out field_homography.npz
# 验证：把车放在已知坐标（如 (1.0, 0.5)），Drive 页卡片 pose 读数误差应 <2cm
```

## 第 3 步：M0 延迟实测（第一验收项）

```powershell
# 车端 manage.py drive 已连上笔记本后端后：
python scripts\measure_loop_latency.py --camera 0 --server ws://127.0.0.1:8000
```

- 判定：端到端 P95 估计 <100ms ✅；超标 → 记录数字，加超前补偿/降档后再评估（RFC 第 10 节）
- 同时观察：`tag_hits` 应接近 `frames`（丢帧率 <5%），否则查曝光/光照/标签尺寸

## 第 4 步：M1 录制（人 RC 漂移 ≥2 分钟）

1. Web UI Drive 页 →「第三视角漂移」卡片：填相机 index / Tag ID / 标定文件路径 → **启动相机**（预览应出画面，pose 随车移动）
2. 点**录制** → 用 RC 遥控器正常漂移（MANUAL 模式，尽量定圆多圈）→ 点**停止**
3. 验证：`data/drift_tubs/overhead_*` 生成；卡片"已录帧">0；β 读数在漂移段应落在 15°~40°
   - β 异常时先查：标签角序约定（`drift_vision.py` 文件头）是否与实际打印方向一致——必要时旋转标签 90°重贴

## 第 5 步：M2 点动机理验证（不成立则停下修模型）

```powershell
python scripts\analyze_throttle_pulses.py data\drift_tubs\overhead_<时间戳> --center 1.0,1.0
```

- 期望输出 `✅ 机理成立：频率高→半径小`，并得到低/中/高三档参数表
- 把参数表的频率/占空比/幅值/β 填入卡片参数面板（作为外环初值）

## 第 6 步：M4 低速闭环（先非漂移！）

1. 卡片参数：β* 暂设 0（等价定圆普通行驶）、脉冲频率设 0（连续油门）、基础油门 0.2
2. 点**自动漂移** → 状态进入"自动·观察"
3. 低速遥控车进圆 → 让 β 维持接近 0（普通行驶即满足 |β|<15° 不触发接管——低速验证请把β*逻辑改为直接接管测试或临时将阈值调低）→ 验证转向闭环方向正确、车能跟圆
4. **安全联锁演练（必须逐项做）**：拔相机 USB（看门狗 → MODE 0）；断笔记本-车网络（CH4 夺回）；CH4 拨杆物理夺回
   - 静止实测 MODE 0→2 跳变：观察 ESP32 是否接受（RFC 风险表核对项）

## 第 7 步：M5 最终验收（定圆漂 30 秒）

1. 卡片参数恢复：β*=25（或 M2 参数表建议值）、点动频率/占空比/幅值按参数表
2. **关闭固件 yaw-rate 转向修正**（MUS4 现有配置开关，FULL_AUTO 下关闭）
3. RC 起漂 → 稳定侧滑后控制器自动接管（状态变"自动·已接管"）
4. 验收：定圆连续漂移 ≥30 秒不甩尾；全程录制供复盘与后续蒸馏

## 已知遗留（不阻塞，注意即可）

- `test_trainer_tubs.py::test_list_tubs_finds_data_dir_and_subtubs` 为存量失败（干净 main 上同样失败，与本次无关）
- AprilTag 角序（pupil_apriltags corners 顺序 ↔ 车体系[前左,前右,后右,后左]）需在标定时用已知朝向验证一次
- 服务端多 client 仲裁：AUTO 期间请勿在浏览器手动开车（卡片已禁用冲突按钮，但其他标签页 ws 仍可能发控制——明天如出现状态互踩再做服务端互斥）
- `dsc` 遥测字段语义核对（第二阶段前）
