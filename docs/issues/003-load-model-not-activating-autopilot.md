# Issue 003: 先切换全自动/半自动模式再选择模型时，自动驾驶不激活

- 状态: open
- 记录日期: 2026-09-04
- 页面: Drive（驾驶）页面
- 类型: bug（功能缺失导致）

## 现象

在驾驶页面先切换到「全自动」模式、再从模型下拉框选择模型（如 DKG-1.tflite）后，全自动驾驶没有激活（车不动、不推理）；「半自动」模式同样如此。UI 上看似已加载模型，但实际未生效。

## 根因分析

**「选模型」链路是断头路：后端把 `load_model` 消息推进车端 WebSocket，但车端没有任何代码消费它，模型从未真正加载。** 这不是模式与模型的顺序问题，而是接收端缺失。

消息流：

- 切模式（链路正常）：前端 `DrivePage.tsx:276-279` 发 WS `{ drive_mode, car_mode }` → 后端 `web_ui/backend/routers/drive.py:634-660` 转发 → 车端 `donkeycar/parts/drive_api_bridge.py:430-438` 置 mode_latch → `run_pilot`=True。60Hz 控制循环（`DrivePage.tsx:220-228`）持续携带 `drive_mode`，模式本身不会丢。
- 选模型（断头）：前端 `DrivePage.tsx:281-289` HTTP `POST /drive/load_model` → 后端 `drive.py:311-323` 向车端 WS 发 `{"type":"load_model","model_path":...}` → **车端 `drive_api_bridge.py:415-444` 的 `_handle_message` 没有 `load_model` 分支，消息被静默丢弃**。全仓库 grep 证实该消息只有一处生产、零处消费。后端只校验「车端在线」即返回 success，无 ACK，前端无法感知失败。

结构性缺口：

- 车端模型只在启动时按 `--model` 加载（`donkeycar/templates/complete.py:317-365`）；运行时重载仅靠 FileWatcher 监视**启动时那个文件**的磁盘改动，没有接收新模型路径的通道。
- 无 `--model` 启动时 `KerasPilot` part 根本未注册（`complete.py:426`），切全自动后 `pilot/*` 恒为 None，`DriveMode` 输出 0——车不动。

## 修复建议

1. 车端 bridge 增加 `load_model` 分支：`_handle_message` 中置 latch，`run_threaded` 输出新增 `model/reload_path`。
2. 模板侧接线：`complete.py` 的 `TriggeredCallback` 换用动态路径输入；无 `--model` 启动时 `kl` part 未注册的问题需决策——强制带模型启动并在 UI 提示，或始终创建 `kl` 延迟加载权重。
3. 闭环反馈：车端加载后回发 `{"type":"model_loaded","success":...}`，后端广播，前端显示加载状态/错误。
4. 路径安全：后端 `/drive/load_model` 校验 `model_path` 限制在车端 models 目录内。

## 待确认

- 目标形态是「运行时热切换模型」还是「选模型即重启/要求带模型启动」？两者改动量差异大。
