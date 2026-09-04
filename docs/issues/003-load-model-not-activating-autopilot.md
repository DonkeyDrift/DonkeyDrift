# Issue 003: 先切换全自动/半自动模式再选择模型时，自动驾驶不激活

- 状态: fixed（2026-09-04）
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

## 修复建议（已确认方向）

**目标形态已确认（2026-09-04）：「选模型后要求带模型重启」，不做运行时热切换。**

按此方向收敛改动：

1. 后端 `/drive/load_model`（`drive.py:311-323`）改为持久化所选模型路径（写入车端配置/启动参数），并触发或提示重启车端进程（`donkeycar/templates/complete.py --model <路径>` 重启）。
2. 前端 `DrivePage.handleModelChange`（`DrivePage.tsx:281-289`）：选模型后显示「需重启生效」状态/进度，重启完成前禁用模式切换或给出明确提示。
3. 重启后模式需恢复为重启前的全自动/半自动（模式状态持久化或重启后由前端补发），避免「重启后又要手动切模式」的二次坑。
4. 路径安全：后端校验 `model_path` 限制在车端 models 目录内。

不再需要做：bridge 的 `load_model` 消息消费分支、模板侧运行时换模型通道、`model_loaded` ACK 链路（原建议 1-3 作废）。

## 修复实现（2026-09-04）

按上述确认方向落地，「选模型 = 持久化选择 + 车端带模型重启」：

1. **持久化**：`donkeycar/webui_instance.py` 新增 `DRIVE_MODEL_FILE`（`~/.donkeycar/drive_model.json`）与 `read/write/remove_drive_model()`，记录 `{model, model_type, selected_at}`（原子写入）。
2. **后端** `web_ui/backend/routers/drive.py` `/drive/load_model` 重写：校验 `model_path` 必须解析到 `<working_dir>/models` 内的真实文件（防目录逃逸、扩展名白名单、存在性检查，`.tflite→tflite_linear`、`.trt→tensorrt_linear` 推导 `--type`）→ 写入持久化记录（空路径=「无模型」则删除记录）→ 经 `routers/launch.py` 的 `_post_to_launcher` 请 launcher 重启车进程。不再要求车端在线（重启后上线即带模型）；launcher 不可达/报错时选择仍已保存，返回 `restart_required: true` 让前端提示手动重启，不再假成功。
3. **launcher** `donkeycar/launcher/server.py` `_launch_drive()`：起车进程时读取持久化记录，存在则附加 `--model/--type`；记录指向的文件已删除时回退无模型启动并告警（避免 manage.py 反复退出）。选择因此对一切 launch 入口（菜单页/TUI）保持粘性。
4. **前端** `DrivePage.tsx` + 新 hook `hooks/useModelRestart.ts`：后端确认重启后进入 restarting 状态——期间抑制车端→页面的模式回同步（车端重启后默认报 user，不抑制会冲掉全自动/半自动选择）、禁用模式/模型切换控件、显示「正在重启车端加载模型…」；车端掉线再上线时补发当前 `{drive_mode, car_mode}`；车端回报收敛或 3s settle 窗口后结束，120s 整体超时兜底并提示。`ModelsList` 的「加载到车端」提示改用服务端返回消息。

测试：`tests/test_webui_instance.py`（持久化读写 6 项）、`tests/test_launcher_drive_launch.py`（带模型启动 4 项）、`web_ui/backend/tests/test_drive.py`（load_model 校验/重启/降级 9 项）、`web_ui/frontend/src/hooks/useModelRestart.test.tsx`（状态机 7 项）、`tests/test_drive_page_layout.py`（接线 2 项）。
