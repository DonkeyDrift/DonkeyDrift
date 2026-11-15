# DonkeyDrift 长期记忆：模拟器驾驶链路排障复盘

日期：2026-10-30
范围：TUI Drive 启动、8000/8001 后端、WebSocket 控制、WebRTC 视频、模拟器连接、虚拟摇杆、8GB macOS 测试环境。

## 一句话结论

今天最终完成了一个真实的 TUI 端口占用修复，并用独立浏览器证明：在模拟器 TCP 正常连接、只有一个 DD 页面且没有重型后台测试时，视频和虚拟摇杆端到端链路均可正常工作。排障过程中没有修改前端摇杆实现。

## 最终已验证成果

- TUI 在 8000 被占用时，能让新后端和车端统一使用 8001，不再出现浏览器与车端连接到不同后端的问题。
- 健康会话中，DD 页面显示车端在线，WebRTC 画面恢复到约 58 FPS、约 18ms 页面指示延迟。
- 独立 Playwright 浏览器真实拖动虚拟摇杆：
  - 浏览器发出 98 帧非零控制消息；
  - 车端实际遥测达到 `angle≈0.488`、`throttle≈0.549`；
  - `sim_connected:true`；
  - 没有 `control_rejected`；
  - 松开后控制值回到 0。
- Python 启动相关测试在隔离 HOME 下 42 项通过。
- 虚拟摇杆、60Hz 控制循环、输入新鲜度共 11 项 JavaScript 测试通过。
- 生产 `DrivePage` bundle 的 source map 与当时前端源码一致，排除了“浏览器加载旧包”的假设。

## 实际代码变更

### 1. 修复 macOS 端口占用误判

文件：`donkeycar/management/tui.py:1479`

`DriveCommand.choose_available_backend_port()` 不再给端口预检 socket 设置 `SO_REUSEADDR`。

原问题：在 macOS 上，当 `127.0.0.1:8000` 已被监听时，使用 `0.0.0.0 + SO_REUSEADDR` 预检仍可能误判 8000 可用。随后出现：

1. TUI 给车端注入 `ws://localhost:8000/api/drive/ws`；
2. `donkey web` 再次检测后发现 8000 被占用，改开 8001；
3. 浏览器打开 8001，车端却连接 8000；
4. 页面显示车端离线，视频与摇杆都无法工作。

实测证据：当时 8000 返回 `online:true`，8001 返回 `online:false`；去掉 `SO_REUSEADDR` 后，同一个占用端口会被正确识别为 `occupied(48)`。

### 2. 添加真实 socket 回归测试

文件：`donkeycar/tests/test_tui_drive.py:62`

`test_choose_available_backend_port_skips_loopback_listener` 在 `127.0.0.1` 上建立真实监听，再断言端口选择器不会返回该端口。

- 旧实现上按预期失败：`55167 != 55167`；
- 修复后通过；
- 不是源码文本断言，而是验证真实端口选择行为。

### 3. 没有修改的文件

- 没有修改 `VirtualJoystick.tsx`、`useDriveControlLoop.ts`、`useDriveWebsocket.ts` 或 `inputFreshness.ts`。
- 没有修改 `package.json` 或 `package-lock.json`。
- `npm install` 仅修复了本地缺失的 Rollup 平台可选依赖。
- 本次没有创建 git commit。

## 另外确认的三个独立问题

### 重复 DD 标签页导致视频互相影响

后端是单客户端 WebRTC 会话。两个 DD 标签页同时指向 8001 时，后建立的会话可能使前一个页面失去画面或降级。关闭重复标签页后，保留页面恢复 WebRTC 视频。

经验：视频黑屏时先检查是否开了多个 DD 页面，不要先改编码器。

### 车端在线不等于模拟器在线

后续摇杆排障中曾出现：

- 浏览器 Pointer 事件正常；
- 页面角度/油门数值正常；
- 浏览器 WebSocket 以 60Hz 发出非零值；
- 但车端实际输出仍为 0。

最后确认当时遥测为 `sim_connected:false`，车端日志正在反复重连 9091。重新启动模拟器并恢复 TCP 后，同一套前端和生产包立即通过端到端测试。

经验：必须分别检查 `car_ws_connected`、`sim_connected`、视频源帧率、帧时间戳新鲜度，不能只看“车端在线”。

### 8GB 机器上的资源争用

完整单进程 pytest 在运行约 2 分半后被 SIGKILL，退出码 137。后台测试、模拟器、Chrome 和 Drive 同时运行时还出现过帧率降至约 1 FPS、帧时间戳停滞和会话失稳。停止重型测试并干净重启后，健康会话恢复到约 58 FPS。

完整 pytest 没有跑完，不能记为通过。

## 测试记录与边界

已完成：

- 端口回归测试先红后绿；
- Python 相关启动测试 42 项通过；
- JavaScript 相关测试 11 项通过；
- 直接 WebSocket 控制测试曾准确输出 `angle=0.15`、`throttle=0.20`；
- 独立浏览器完成真实摇杆到车端遥测的闭环验证。

未完成或需注意：

- 完整 pytest 因内存压力被 kill，后续分组尝试也因影响模拟器而主动停止；全套状态未知。
- 默认 HOME 下有两个旧测试会读取本机 Drive token，导致未预料 `?token=...` 的断言失败；使用临时隔离 HOME 后相关 42 项全部通过。不能把这两个环境相关失败记成端口修复回归。
- `make tests` 因已有 `tests` 路径且目标未声明 `.PHONY`，只报告 `tests is up to date`，没有真正执行 pytest。需要真实测试时应直接调用 pytest。
- `npm install` 报告 23 个依赖漏洞（1 low、6 moderate、16 high）；今天没有处理，不能用 `npm audit fix` 盲目扩大变更。
- 如果旧 DD 标签页仍保留已经关闭的 WebRTC peer，需要刷新页面重新建会话。

## 经验和教训

### 1. 按组件边界收集证据，不从症状直接猜代码

端口、浏览器 WS、车端 WS、模拟器 TCP、WebRTC 会话是不同边界。`online:true` 只说明其中一层正常，不能推出整个链路正常。

### 2. 同时观察“浏览器发了什么”和“车端实际输出什么”

只看摇杆 UI 或浏览器发送帧，会漏掉后端、仲裁、车端和模拟器离线问题。有效闭环是：

`Pointer 事件 → 浏览器 WS 非零帧 → 后端无 control_rejected → 车端 telemetry 非零 → sim_connected:true`。

### 3. 时间戳和连接状态必须新鲜

旧 WebRTC stats 中的高 FPS 不能证明当前仍有视频。应检查 `ts_tail_age_ms`、最近帧间隔、`peer_connection_state` 和 `sim_connected`，而不是只看历史累计值。

### 4. 不在实时驾驶环境上并行跑重型测试

在这台 8GB Mac 上，模拟器运行期间不再启动完整 pytest。先做轻量、定向测试；全套测试应等模拟器关闭或资源充足时再运行。

### 5. 少操作用户正在使用的浏览器

反复切换标签页会打断用户，也容易让自动化结果混入真实鼠标输入。端到端验证优先使用独立、临时的 Playwright 浏览器，并在结束后关闭。

测试浏览器还应阻止 `/api/drive/webrtc/**`，避免它抢占用户现有单客户端视频会话；本次摇杆测试不需要测试浏览器自己的 WebRTC 视频。

### 6. 先证明生产包和运行环境，再决定改哪层

本次 source map 证明生产包与前端源码一致，因此没有摇杆代码修复空间需求。依赖缺失、虚拟环境 PATH、测试 HOME 也应先排查，避免把环境问题误当产品 bug。

### 7. 不把未完成的验证写成成功

完整 pytest 被 kill 不是“测试通过”，断言失败和被 SIGKILL/OOM 要分开记录。功能点的真实端到端通过，也不能外推成整个项目全部测试通过。

## 下次启动与验证清单

1. 关闭多余 DD 标签页，只保留一个。
2. 模拟器运行期间不启动完整 pytest 或其他重型任务。
3. 先启动模拟器并确认 9091 监听，再启动 Drive。
4. 确认浏览器与车端使用同一个后端端口。
5. 检查 `/api/drive/stats`：`online:true`、`car_ws_connected:true`。
6. 检查遥测：`sim_connected:true`，并确认帧时间戳持续更新。
7. 用小幅摇杆输入验证车端实际 telemetry，最后归零。
8. 旧页面黑屏时先刷新重建 WebRTC，仍异常再分层排查，不直接修改摇杆或编码器。

## 安全记录

本文不保存 Drive token、API Key、凭据或包含这些信息的 URL。排障截图和日志若进入其他文档，也应先脱敏。

## 长期协作约定：任务完成后合并到 Tony

- 每个任务完成并验证后，直接创建 commit、提交 PR 并合并到 `Tony` 分支，不停留在未提交的本地工作区。
- 每次提交只包含当前任务相关文件，排除无关修改；继续遵守 `AGENTS.md` 中已有的 Linux 验证、同步和冲突保护约定。
