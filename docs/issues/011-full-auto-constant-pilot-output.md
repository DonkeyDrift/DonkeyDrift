# 011 drive 全自动 pilot 恒定输出、小车冲出赛道（排查档案）

> 状态：**已解决/闭环**。两模型实车恢复正常跑圈；根因归为**旧车端进程的运行时性态**
> （最大嫌疑：帧输送停滞，旧进程日志走 DEVNULL 无直接取证），已落地可观测性
> 基建盯防复发。本文档保留完整排查链路与经验教训，供同类问题（"离线正常、
> 实车异常"）直接复用方法。

## 现象

- `test-md-1.tflite`（本地训练）与 `deployed.tflite`（云端训练）在 Pilot Arena
  推理结果与验证集标签偏差很小（angle MAE≈0.055 / throttle MAE≈0.017）。
- 同批模型在 drive 页面切「全自动」后，TelemetryChart 的 `pilot_angle`/
  `pilot_throttle` 基本恒定（≈数据集均值：angle≈-0.08 / throttle≈0.22），
  小车匀速直行冲出赛道。
- 手动模式一切正常（视频流、转向、油门、录制）。

## 静态排查（全部排除项）

逐项对拍 arena 与车端两条推理链，证明代码层面**完全对称**：

| 排查项 | 结论 | 证据 |
|---|---|---|
| 模型输入形状 | 均为 `[1,120,160,3]`（签名 `img_in`→`n_outputs0/1`） | `od` 直读 tflite FlatBuffer 张量表（无 TF 环境可用的手法），两模型同形 |
| resize 口径 | 训练 `pipeline/training.py` 与车端 `PilotHolder` 同用 `fit_image_array`；320x240→160x120 同比例纯缩放，arena 的 cv2 拉伸等价 | 代码比对 + Test A/B 输出对拍 |
| 解释器环境 | 车端进程与后端 uvicorn 实测都在 `.venv`（TF 2.19.1），`get_model_by_type` 走同一 `KerasLinear+TfLite` 分支 | `ps`/`/proc/<pid>/cmdline` 现场取证 |
| 标签退化 | tub 标签 angle 覆盖 -1.0~+0.99（单会话 11413 帧） | catalog 全量直方图 |
| 模型坍缩 | 扰动探针（平移/亮度/镜像）输出极差 0.384，模型对输入敏感 | `tools/diagnose_pilot.py` Test C2 |
| 执行链 | mode 门控/DriveMode/平滑器/ArdPWM 写回环均标准；part 抛异常会停车（车在跑=无异常） | 逐段代码审读 |
| 相机（离线） | pygame Webcam 22fps、100% 唯一内容帧 | diagnose Test C |

## 定论

新进程里两模型实车均正常，`logs/drive.log` 观测数据健康：

- **帧新鲜**：`新帧 250~286/5s`（50~57fps，满负载含推理+WebRTC）；
- **输出随弯道摆动**：test-md-1 行驶段 angle -0.69~+0.10，deployed -0.54~+0.10；
- **零帧冻结告警**。

原始故障进程（长时运行、当时加载 test-md-1）的 stdout 为 DEVNULL，无法直接
取证；结合 009（WebRTC 中途冻结）的历史，最大嫌疑是**该进程帧输送停滞**
（pilot 收到定格画面→输出恒定≈数据集均值→匀速直行出轨）。现已由帧冻结
检测器盯防：复发即打 `疑似相机/管道冻结` 告警且日志永久留档。

## 落地的修复与基建

1. **`parts/pilot_holder.py` 推理可观测性**：全自动运行时每 5s 记
   `pilot 观测: 输入 shape/dtype/mean 输出[..] 新帧 n/5s`；输入帧 >2s 不变
   打告警（对象 id 每帧比较 + 1Hz 内容哈希兜底）；`DK_PILOT_DEBUG=1` 逐帧打印。
2. **车端日志永久落盘**：`manage.py`（及模板 `complete.py`）加 RotatingFileHandler
   → `logs/drive.log`（2MB×2），launcher 起（stdout=DEVNULL）与终端起都留档。
3. **`tools/diagnose_pilot.py` 诊断脚本**：Test A 对照（tub+arena 预处理+MAE）/
   Test B（PilotHolder letterbox 路径对拍）/ Test C（实时相机帧新鲜度+输出）/
   Test C2（扰动敏感性探针）。**模型上车前先跑 Test A 看 MAE**。
4. **arena 预处理口径统一**：`fit_model_input_shape` 改 `fit_image_array`
   （与训练/车端一致，仍严格输出模型尺寸，不影响 XNNPack 约束）。
5. **车速偏快修正（车端目录，不在本仓库）**：`myconfig.py` `AI_THROTTLE_MULT`
   1.1→1.0。全自动油门=模型油门×该系数，模型预测（≈0.22）本已接近手动
   记录值（≈0.21），×1.1 即偏快、弯道刹不住跑偏。
6. 弯道跑偏的调参序（车端）：`AI_THROTTLE_MULT=0.9` → `STEERING_SMOOTHER_ALPHA`
   0.35→0.5 → 补录过弯数据重训（单会话数据回归模型在弯道天然打角偏浅）。

## 经验与教训

1. **先让日志落盘，再谈运行时排查**。launcher 拉起的车端 stdout=DEVNULL，
   第一现场证据全部丢失；`RotatingFileHandler` 一劳永逸。
2. **"离线正常、实车异常"用对称性二分**：把两条链拆成
   模型文件/解释器/预处理/标签/执行链/输入图像 逐项对拍，排除到最后
   剩下的就是答案（本例收敛到"输入图像"）。
3. **无 TF 环境也能验模型**：`od` 直读 tflite FlatBuffer 可确认输入形状、
   张量名、签名；`tools/diagnose_pilot.py` 已把常用检验固化。
4. **"输出恒定"≠模型坏**：回归模型对 OOD 视角会输出≈数据集均值
   （本例对着工位画面 angle≈-0.08/throttle≈0.22 正是均值）。先跑扰动探针
   （Test C2）区分"模型不敏感"与"输入没变化"。
5. **离线健康≠运行时健康**：帧冻结/线程饥饿只在真实负载（推理+编码+60Hz
   循环并发）下出现，静态审查与离线复现都可能正常——周期观测（输入统计+
   新帧计数+冻结告警）才是长期答案。
6. **Arena 验证有盲区**：验证帧全部来自训练分布（同一会话），模型过拟合
   路线视角时 arena 依然"偏差很小"；实车视角才是最终考官。
7. **运维细节**：停车端用 SIGINT（SIGTERM 可能挂在串口优雅退出上）；
   myconfig 改动需重启车端生效；诊断占用相机前确认车端进程已停（V4L2 独占）。
8. **换模型热加载 vs 默认模型**：selected_model.json 才是重启后的默认，
   UI 里最后一次选择会持久化——长期用的模型记得在 UI 选定一次。
