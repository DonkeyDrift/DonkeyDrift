# 010 源码重编 DonkeySim 偶发启动/运行期崩溃（交接排查档案）

> 状态：待排查。本文档汇总全部已知证据与线索，供接手方（人或 AI）直接开工。
> 建档：2026-10-13 晚。最后更新：同。

## 问题摘要

`sdsandbox` 源码重编的 macOS DonkeySim（Unity 2022.3.49f1，原生 arm64）
**偶发 SIGSEGV 崩溃**：集中在启动阶段（menu 场景，概率约 1/4~1/3，重试 1-3 次必成功），
另有至少 1 次运行约 15 分钟后的运行期崩溃（pid 83039，22:02，此前已正常出图/推流）。
崩溃不影响功能正确性，但影响无人值守启动与用户体验。

## 环境

- 机器：Mac16,8（Apple M4 Pro），macOS 27.0.1 (26A434) —— 极新系统
- 构建：Unity 2022.3.49f1（项目自 2020.3.49f1 迁移，分支 `feature/telemetry-fps-60`，
  DonkeyDrift/sdsandbox），Universal 二进制（x86_64+arm64），运行 arm64 原生
- 产物：`~/Dev/DKC/DonkeySimMac/donkey_sim.app`
  （旧 2020.3 预编译包备份：`donkey_sim.app.bepinex-backup`，**它在本机 Rosetta 下
  也有同类崩溃史**——`~/Library/Logs/DiagnosticReports/donkey_sim.orig-2026-10-13-080*.ips`，
  说明问题可能不随引擎版本消灭，需考虑机器/系统因素）
- 构建日志：`/tmp/unity_build6.log` ~ `unity_build8.log`（均 result=Succeeded errors=0）

## 复现

```bash
# 启动并检测 9091 监听；约 1/4 概率在 ~12s 内崩溃（无监听、无窗口）
open ~/Dev/DKC/DonkeySimMac/donkey_sim.app
lsof -nP -iTCP:9091 -sTCP:LISTEN
# 兜底重试循环（当前缓解手段）：崩溃后 sleep 2 重开，1-3 次内必成功
```

直接启动二进制（不经 `open`）+ 带命令行参数（`--quality 0`）时观测到 1/1 崩溃
（单次样本，未排除参数/启动方式因素）。

## 证据清单

- **系统崩溃报告**：`~/Library/Logs/DiagnosticReports/donkey_sim-2026-10-13-*.ips`
  （新版 7 份：18:03×3、21:09、21:10×2、22:02；旧 Rosetta 版 3 份在 `donkey_sim.orig-*`）
- **Unity player 日志**：`~/Library/Logs/DonkeyCar/donkey_sim/Player.log`
  （崩溃时尾部有 managed/native 混合栈，如 `operator delete[] ← PlayerMain ← __NSFireTimer`）
- 应用自身日志：`~/Dev/DKC/DonkeySimMac/unitylog.txt`（历史遗留文件，非每轮更新）

### 崩溃签名汇总（新版 arm64，按 .ips 解析）

| 报告 | 异常 | 崩溃线程栈顶 | 解读 |
|---|---|---|---|
| 210921 | EXC_BAD_ACCESS SIGSEGV | 符号缺失 | 待符号化 |
| 211017 | **EXC_BREAKPOINT SIGKILL** | `_os_semaphore_dispose.cold.1 ← _os_semaphore_dispose ← _dispatch_dispose` | **dispatch semaphore 被 dispose（最后一个引用释放）** |
| 211017.000 | EXC_CRASH SIGSEGV | `semaphore_wait_trap ← _dispatch_semaphore_wait_slow` | 配对样本：另一个线程正阻塞在该 semaphore 上等待 |
| 220256 | EXC_BAD_ACCESS SIGSEGV | `_os_log_preferences_refresh ← os_log_type_enabled ← _xpc_connection_activate` | XPC/日志子系统路径的访存错误（可能是另一独立 flake 或栈破坏表现） |
| 220257 | EXC_CRASH SIGSEGV | `semaphore_wait_trap ← _dispatch_semaphore_wait_slow ← UnityPlayer×4 ← pthread_start` | UnityPlayer 工作线程等信号量时崩溃 |

**关键线索**：211017 + 211017.000 构成教科书式的 **dispatch semaphore 生命周期竞态**——
某线程释放（dispose）了一个 dispatch semaphore，而另一线程仍在 `_dispatch_semaphore_wait_slow`
里等它。崩溃点本身（等待方）不是根因，**找到谁过早 dispose 才是**。该 semaphore 大概率
位于 UnityPlayer 的 macOS 平台引导层（非托管），或经 P/Invoke 桥接的托管代码
（sdsandbox 用 `tk.TcpServer` 自建 C# socket 线程、`UnityMainThreadDispatcher`、
`ClientWebSocket`？——排查时优先怀疑引导期创建的异步原语）。

## 已排除（不必重查）

- ❌ 异步采集代码（CameraSensor AsyncGPUReadback/工作线程 JPEG）：崩溃发生在
  menu 场景/无车状态，该代码路径（Update 且 state==SendTelemetry）未运行；
  build7（无翻转）与 build8（有翻转）崩溃率相同。
- ❌ 编译问题：三次全量构建 0 error；崩溃为非托管段错误。
- ❌ BepInEx/doorstop 注入：新版无任何注入，纯原版 player。
- ❌ 端口绑定冲突本身：`SocketException: Address already in use` 有托管日志路径，
  不会表现为 C++ `delete[]`/semaphore 崩溃（但"上一个实例刚被杀就重开"是
  可疑的时序放大器，见下）。

## 疑点时序（值得优先验证）

崩溃多发于 **`pkill` 强杀后数秒内重启**。旧版日志曾出现双实例绑定竞争。强杀使
托管终结器/非托管析构不完整，若 semaphore 的释放依赖特定 shutdown 顺序，重启竞态
窗口被放大。验证实验：
1. 用 `osascript -e 'quit app "Unity"'` 式优雅退出 vs `pkill -9` 后重启，各统计 20 次崩溃率；
2. 崩溃后在启动前检查 `pgrep donkey_sim` 残留与 9091/9092 端口占用状态，记录与崩溃的相关性。

## 建议排查步骤（按性价比排序）

1. **符号化全部 .ips**：用 `atos -o UnityPlayer.dylib`（app 内
   `Contents/Frameworks/UnityPlayer.dylib` 有 dSYM? 若无则用 Unity 安装目录
   同版本符号）把 210921/220256 的匿名帧符号化，确认是否与 semaphore 线索同源。
2. **优雅退出对照实验**（见上），量化 pkill 与崩溃的相关性。
3. **升级 2022.3 LTS 最新补丁**（如 2022.3.62f1+，经 Unity Hub）：2022.3.49 较旧，
   官方后续 patch 修过若干 macOS player 崩溃；这是成本最低的大概率修复。
4. **最小化工程对照**：新建空 2022.3 工程出包启动 N 次——若空工程也崩，是
   Unity×macOS 27 平台问题（步骤 3 优先）；若不崩，逐层加回 sdsim 的
   Packages/Plugins（SimpleFileBrowser、UnityMainThreadDispatcher、旧
   ProBuilder DLL），二分定位到具体包/插件。
5. **检索 Unity Issue Tracker**：关键词 "macOS player crash startup 2022.3 semaphore"、
   "UnityPlayer macOS 15/26 crash dispatch_semaphore"、"player SIGSEGV boot macOS"。
6. ** Sonoma/新系统兼容性检查**：macOS 27 非常新，确认 Unity 2022.3 官方支持矩阵；
   若不受支持，评估 6000.6（已装）迁移工程的可行性（跨度更大，预留编译修复工作量）。
7. 运行期崩溃（22:02 样本）单独复盘：该实例已正常服务 15 分钟（60Hz 推流中），
   抓其 Player.log 尾部与 .ips 对照，确认与启动崩溃是否同因。

## 临时缓解（已在使用）

启动重试循环（见"复现"节）；车端 dgym 自带看门狗重连，崩溃对用户最终可见的
影响是 Drive 页短暂断流后自动恢复。
