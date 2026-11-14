# WebRTC 真实端到端时延：诚实测量体系与 <50ms 实测

## 经验与教训（2026-10-13 全天战役存档）

**成果线**:20fps / 44ms → **60fps / e2e p50 2.9ms(p95 4.55ms)**。三级跳跃:
BepInEx 运行时补丁(过渡)→ sdsandbox 源码方案(原生 arm64 + `cam_config` fps 键)
→ 异步采集管线(AsyncGPUReadback + 工作线程 JPEG,sim 主线程采包 6-12ms→0.5ms,
~58.3Hz ceiling 消除)。过程产物:事件驱动直推、gym fork 客户端加固、
全链路观测体系、二分命令行开关。

### 方法论(可复用)

1. **先修测量,再修性能**。每一环都有独立计数器(gym 客户端分段 / 帧缓冲 push
   分段 / 发送循环 await-vs-本体),否则死在"感觉像 CPU 问题"的猜测上。最后一击
   是 `sink_pushes=0` 一眼看穿"直推接线根本没生效"。
2. **分段夹逼**:源端独立客户端测速(58.8)→ 独立 dgym(59.9)→ 全栈(52),两
   边一夹,范围立刻收窄到"全栈共置"而非"模拟器不行"。
3. **轮询喂帧是隐形采样器**:消费者节拍跟不上生产者时,高帧率源被静默欠采样。
   事件驱动直推(事件源→缓冲直连)消灭整类问题,顺带把轮询等待从时延里消掉。
4. **共享状态的赋值顺序即并发正确性**:"先换帧对象、再记到达时刻",否则去重逻辑
   被「旧帧+新时刻」竞态骗过、静默吞帧——这类 bug 无日志无异常,只能靠计数器
   对账(appended≠received 时逐段钉桩)。
5. **跨仓库改动核对真实运行入口**:`donkeycar/templates/simulator.py` 只是新建车
   模板;已有 mycar 的 `manage.py` 内联 `drive()` 是另一份代码——改模板≠改实车。
6. **UI 状态恢复挂在常驻层**:自动加载逻辑放抽屉组件里,刷新后直达其他标签页的
   用户永远等不到恢复(连接器"保存后未配置"案)。

### 教训(踩过的坑)

1. **门禁盲区**:像素印章叠加在黑帧上照样可读——e2e/印章门禁无法发现"内容全黑"。
   内容验证必须独立于叠加标记:抓原始帧看 mean/直方图,或存图目检。
2. **"显而易见的冗余"先验证再删**:`sensorCam.Render()` 看着是重复渲染,实为
   prefab 里 component-disabled 相机的**唯一**出图路径;删掉即全黑。
3. **AsyncGPUReadback 两个暗坑**:原始数据 bottom-up(逐行翻转,否则颠倒);
   2022.3 中类型在 `UnityEngine.Rendering` 命名空间(根命名空间无别名)。
4. **运行时注入在 Apple Silicon 的坑**:BepInEx 5 的 MonoMod ILHook 在 arm64 Mono
   崩预载器(被迫 Rosetta);doorstop 3.4/4.5 在该 Unity 2020.3 构建上或崩或静默。
   源码重编是正解,且 2022.3 编辑器原生 arm64。
5. **`git add -A` 前务必 `git status`**:把用户并行的 WIP(steering_smoother)与
   根级 node_modules 缓存扫进了提交;仓库根 .gitignore 曾漏 `node_modules/`。
6. **myconfig 在独立命名空间执行**:只能整体重定义 GYM_CONF,读改父配置会
   NameError。
7. **小心脆弱的字符串契约**:store 的 setError 用英文子串('Failed'/'not found')
   决定是否联动关抽屉——自定义错误文案踩了关键字,抽屉行为翻转。

## 2026-10-13(晚,续):异步采集管线——主线程采包 0.5ms,58.3Hz ceiling 消除

`sdsandbox` 分支 `feature/telemetry-fps-60` 追加:AsyncGPUReadback(2022.3 里
在 `UnityEngine.Rendering` 命名空间)替 ReadPixels、去掉每发送一次的冗余
`sensorCam.Render()`、stb_image_write 工作线程 JPEG、sim 自检仪表
(`[telemetry-stats] send_fps/render_fps/capture_ms`,每 5s)、`--quality/--vsync/
--telemetry_fps` 命令行开关。M4 原生 arm64 实测:

| 配置 | client 遥测 fps | sim send_fps | sim render_fps | capture_ms |
|---|---|---|---|---|
| baseline(Ultra,vsync on,fps60) | **60.62** | 60.0 | 60.0 | **0.5** |
| --quality 0 | 59.98 | 60.0 | 60.0 | 0.5 |
| --vsync 0 | 60.74 | 59.9 | 59.9 | 0.5 |
| --telemetry_fps 30 | 30.53 | 30.0 | 60.0 | 0.0 |

全链路 live 门禁:**stamp_fps 59.77 / e2e p50 2.9 / p95 4.55ms PASS**。M4 上画质/
同步开关已不再影响帧率(成为弱机余量旋钮);旧实现 ~6-12ms 主线程采包是 58.3Hz
ceiling 的根因,现已消除。附带修复 Car.cs 加速度遥测 `fixedDeltaTime` bug。

## 2026-10-13(晚):方案 B 落地——源码重编原生 arm64,BepInEx 退役

sdsandbox 源码补丁(`feature/telemetry-fps-60` 分支,DonkeyDrift/sdsandbox)构建的
原生 arm64 donkey_sim.app 替换 BepInEx 补丁版。实测 live 门禁:**stamp_fps 59.0、
e2e p50 3.25 / p95 3.71ms**(门禁 58/30ms 全 PASS)——比 BepInEx 版(60.05 /
4.62ms)时延再降 ~1ms,Rosetta 偶发 SIGSEGV 随之消灭。协议方式:GYM_CONF 加
`"fps": 60`(cam_config fps 键,旧模拟器忽略);不再需要任何运行时注入。
Windows 部署包打同样源码补丁后同理(原生 x64,无 Rosetta 税)。

## 2026-10-13：60fps 真实采集 + 全链路 60fps（BepInEx 补丁 + 事件驱动直推）

**模拟器源 20fps 硬上限已被打破**。sdsandbox 源码里 `TcpCarHandler.limitFPS=20`
（遥测/JPEG 推流每 50ms 一发；游戏渲染本就有 60fps），每次发送都是现拍现编
（`CameraSensor.Render()`+`ReadPixels`+`EncodeToJPG`），把发送节流提上去即
真实 60fps 内容帧、无插帧。两项改动叠加后的实测（live 门禁,真实模拟器源）:

| 指标 | 此前(20fps 源+轮询) | 现在 |
|---|---|---|
| 源帧率 | 20.00 硬上限 | **60.05**(stamp_fps,0 丢帧) |
| e2e p50 / p95 | 15.15 / 25.29ms | **3.95 / 4.62ms** |
| 车端段逐段 | 轮询拾取 9.8ms+编码+发包≈12ms | 直推零等待,合计 <5ms |

改动清单:

1. **BepInEx 5.4.23.5 + SimTelemetryFps 插件**（Mac 已装进
   `~/Dev/DKC/DonkeySimMac/donkey_sim.app`,Windows 部署包
   `~/Dev/DKC/bepinex_work/DonkeySim_Windows_60fps_BepInEx.zip`）:
   运行时把 `TcpCarHandler.limitFPS` 提 60、`Time.fixedDeltaTime` 提 1/60
   (发送在 FixedUpdate,不改只能 50Hz)、画质档 0 + 关 vsync 给编码让预算。
   注意:BepInEx 5 的 MonoMod 在 **arm64 Mono 上崩预载器**,Mac 被迫 x86_64
   Rosetta 运行(模拟器偶发 SIGSEGV,~15-30min 一次);doorstop 原生 arm64
   在本 Unity 2020.3 构建上不可用(3.4 崩、4.5 静默不加载)。Windows 无此问题。
2. **事件驱动直推**(donkeycar/parts/dgym.py `set_frame_sink` +
   mycar/manage.py 接线):模拟器帧在 `_set_frame` 里直接推
   `frame_buffer.update`,不再等车辆主循环轮询。车辆循环负载高时轮询节拍
   跌破源帧率,60Hz 源被欠采样到 ~52Hz;直推后吃满源帧率,轮询等待归零。
   顺序约束:先换 `preview_frame` 再记到达时刻(`_arrive_and_push`),否则
   车辆循环会读到「旧帧+新时刻」,去重竞态吞掉真实新帧。
   注意:**donkeycar/templates/simulator.py 是新建车的模板**;已有 mycar 的
   `manage.py` 内联 `drive()` 需各自接线(本次已接 mycar)。
3. **gym_donkeycar fork** 客户端:`SO_RCVBUF` 提到 8MB(默认缓冲只够几条
   60KB 消息,消费抖动直接反压模拟器发送线程)、JPEG 解码 PIL→cv2
   (GIL 释放、实测逐字节一致)。
4. 观测性(默认零开销):`/api/drive/webrtc/stats` 新增到达间隔 p50/p95、
   发送循环分段(编码 await/本体/节拍);`DRIVE_DGYM_TIMING=1` 打采集分段。

复现门禁:

```bash
env -u http_proxy -u https_proxy .venv/bin/python scripts/e2e_video_test.py \
  --scenarios live --backend http://127.0.0.1:8123 --duration 30 \
  --gate-fps 58 --gate-latency-ms 30
# 期望全 PASS:stamp_fps≥58、e2e p95≤30ms
```

剩余限制:Mac 模拟器 Rosetta 运行有偶发崩溃(原生 arm64 需方案 B 源码重编);
真实浏览器徽标数值在窗口被遮挡时 Chromium 暂停合成会停更(见下文已知陷阱)。

## 背景：徽标曾经是假的

Drive 页 WebRTC 徽标长期显示「33ms」，但用户实际体感约 100ms。排查结论：

- 徽标的 33ms 是 `browser_p95_frame_interval_ms`——**帧到达节奏**（相邻帧间隔的 p95），不是时延；
- 真实 E2E 样本数 `e2e_samples = 0`，因为浏览器的 `requestVideoFrameCallback` metadata **没有 `captureTime` 字段**（Chrome 145 实测：只有 presentationTime/mediaTime/rtpTimestamp 等），rVFC 通路拿不到捕获时刻，徽标静默降级显示帧间隔；
- 于是「延迟目标 < 50ms」根本没有可测量的口径。

本任务先打通诚实测量，再按测量结果削减时延。

## 测量体系

三层结构：车端把时间烧进像素 → 两段时钟对齐 → 浏览器解码求差。

### 1. 车端像素印章（`donkeycar/parts/video_timestamp.py`）

- 二进制单元条（cell bar）格式 v1：2 行 × 28 个 payload cell，行首各 1 个同步 cell（行0 白 ≥160、行1 黑 ≤96，兼作存在性与行序校验）；cell 6px + 2px 间距（pitch 8），起点 (4,4)，外扩 2px 黑色衬底；payload = 微秒时间戳 `>>4`（48bit，64µs 分辨率）+ 8bit 校验和。
- 解码失败（无印章/校验不过）返回 null，**不猜值**；参考实现是 Python 版，TS 版逐字节对齐，fixture（`__fixtures__/frameStamp.json`）由 `draw_timestamp` 生成防两端同错。
- 默认关闭：`DRIVE_WEBRTC_FRAME_STAMP` 默认 `0`（画面纯净优先，徽标降级回帧间隔；显式探针 `latency_probe` 恒开；`=1` 开启烧入，真 E2E 徽标与回环探针像素通路依赖它）。印章画在帧副本上，不污染自动驾驶管线输入。
- 时间源：模拟器模式 = **帧到达时刻**（`donkeycar/parts/frame_freshness.py` 侧信道），实车 = 入缓冲时刻。

### 2. 双段时钟对齐

| 段 | 方法 | 精度（实测） |
|---|---|---|
| 浏览器 ↔ 后端 | NTP 式 3 次取样 `GET /api/drive/time`，取 min-RTT 样本的中点法 | rtt 5.8ms / 偏移 0.48ms |
| 车 ↔ 后端 | `/api/drive/webrtc/stats` 的 `clock_offset_ms` 字段 | — |

e2e 计算（像素通路）：`e2eMs = (浏览器当前时刻 + 浏览器钟偏 − 印章时刻 − 车钟偏移) × 1000`，样本范围校验 `[0, 1000ms]`，越界丢弃。浏览器时钟同步每 30s 重跑一次（`DRIVE_CLOCK_SYNC_INTERVAL_MS`）。

### 3. 浏览器采样（`useDriveWebRtcVideo.ts`）

- **rVFC `captureTime` 通路优先**（浏览器原生、零成本）；缺失时走像素兜底。
- 像素兜底：rVFC 回调里 canvas `drawImage` 采样呈现帧的 240×24 印章区域 → `readFrameTimestamp()` 解码 → 入 `e2eSamplesRef`（窗口 240）。canvas 遇 `SecurityError`/`DOMException` 判定为永久失效（`stampBrokenRef`），其他异常只跳过当帧。
- 徽标降级链（`VideoStream.tsx`）：真 E2E（rVFC 或像素样本非空）→ 显示「XXms **E2E**」；否则降级显示帧间隔（仅作参考，非时延）。

## 时延削减改动

1. **`DRIVE_LOOP_HZ` 20 → 60**（`cfg_simulator.py`）：车辆循环 20Hz 轮询意味着「帧到达→被消费」平均等待 25ms，直接计入 E2E；提到 60Hz 与帧率对齐后该段≈0。
2. **同源去重 + 到达时刻作时间戳**（`frame_freshness.py` + `DriveVideoFrameBuffer.update`）：模拟器帧被循环重复轮询时，同一到达帧只编码一次（`source_fps` 反映真实新帧率，旧帧不再反复进编码器）；帧时间戳取到达时刻，把「出帧→轮询」等待纳入时延口径（此前取 update 时刻，会少算这一段）。实车侧信道恒为 `None`，行为不变。
3. 此前已落地的基线优化（见记忆 donkeydrift-webrtc-performance）：媒体线程绑大核 4-7、VP8 调参（cpu-used=15 等）、接收端 `playoutDelayHint=0` / `jitterBufferTarget=0`。

## 实测结果（2026-10-12，模拟器真实链路 + 探针口径修正）

**先修测量，再谈时延**：本轮发现回环探针（aiortc 接收端）的测量存在**系统性虚高一整个帧周期**——

- 上游 `aiortc.jitterbuffer.JitterBuffer._remove_frame` 靠「下一帧首包的时间戳变化」判帧边界，**完全忽略 marker 位**：每个已收齐的帧被押到下一帧首包到达才交给解码。20fps 源 = +50ms、60fps 源 = +16.7ms，**恰好等于此前实测与真实链路的全部差值**（20fps 模拟器流探针报 p50 63.4ms，逐段插桩证明车端实际仅 ~12ms；60fps 合成源报 p50 31.96ms，其中 16.7ms 是这段押帧）。
- 浏览器不走这段逻辑（Chrome `jitterBufferTarget=0` 立即出帧），所以**用户真实时延没有被虚增**，虚增的只是探针口径。
- 修复：`scripts/webrtc_loop_probe.py` 进程内替换为 `MarkerReleaseJitterBuffer`——车端 VP8 打包器（aiortc `Vp8Encoder._packetize`）在每个帧最后一个包置 marker=1，据此立即出帧，与浏览器行为对齐。

**模拟器源帧率天花板 = 20fps（硬上限，非本仓库可修）**：

- 实测同一台模拟器在 1920×1080 / 640×480 / 320×240 三种渲染分辨率下，gym `step()` 均稳定 20.00fps（p50 49-50ms/步）——遥测/出图节拍是闭源 Unity 端固定值，`cam_config` 协议无帧率键，客户端 `observe()` 仅 1ms 自旋不限速。
- 结论：**模拟器预览的帧率上限是 20fps**；「60FPS」目标对 WebRTC 管线本身成立（下表合成源门禁），对模拟器源不成立。真车相机路径（320×240@60）不受此限。

**配置修正（本机 mycar）**：`DRIVE_LOOP_HZ` 20→60（消费侧不再丢帧、轮询等待归零）；`GYM_CONF render_img_w/h` 缺省 1920×1080→640×480（模板与 dgym 默认同步）——实测渲染分辨率不影响模拟器帧率，更高渲染只多烧模拟器 CPU（实测 71%）并放大每帧编解码与传输耗时，而预览编码上限本就是 640×480。

| 口径 | 条件 | 结果 |
|---|---|---|
| **回环探针·模拟器真实流** | `--gate-fps 19 --gate-latency-ms 50`，25s | **stamp_fps 20.04（源满速率、0 丢帧）、e2e p50 15.15 / p95 25.29ms → PASS** |
| **回环探针·合成源** | `--gate-fps 58 --gate-latency-ms 50`，25s | **stamp_fps 60.04、e2e p50 4.11 / p95 4.64ms → PASS**（管线余量巨大） |
| **真实浏览器** | Drive 页徽标（像素印章通路） | **「WebRTC 44ms E2E」< 50ms**；inbound 20fps、Chrome 抖动缓冲 13.9ms、transport 丢帧 0 |

逐段实测（真实 drive 进程，20fps 源）：帧到达→被取走 p50 9.8ms（60Hz 轮询均值）+ 编码 1.4ms + 编码→发包 0.3ms——车端段合计 ~12ms，与探针修正后读数吻合。

## 实测结果（2026-10-10，历史基线——探针含押帧虚高，仅作对照）

| 口径 | 条件 | 结果 |
|---|---|---|
| **回环探针（正式门禁）** | `--gate-fps 58 --gate-latency-ms 50`，25s，本机 8123 后端 | **stamp_fps 59.89、e2e p95 41.86ms → PASS**；p50 31.96 / min 19.59 / max 82.44；1497 帧 0 帧无印章 |
| **真实浏览器** | Chrome 145 headless，Drive 页 45s，板载 load 6.77/8（软解 VP8） | 徽标「57ms E2E」（240 样本，像素通路激活）；**p50 ≈ 45ms 达标**；p95 57~66ms（满载偏高）；前后半程 p95 66.3 → 63.4 无发散；jb_ms ~20、inbound 59-60fps、receiver hints 0/0 确认生效 |

结论对目标「网页 E2E < 50ms」：**p50 达标、回环门禁 p95 达标**；浏览器 p95 在板子满载 + 软件 VP8 解码条件下超 50ms，常规负载下预期落入门禁范围。徽标从此诚实——「E2E」标签出现即真实样本，无标签即降级。

## 复现方法

> 闭环编排器：`scripts/e2e_video_test.py` 一条命令完成「隔离后端→合成源→探针
> 门禁→headless 浏览器实测→历史对比」，场景矩阵与优化工作流见
> **docs/guide/e2e-video-pipeline-testing.md**。以下是单件手动路径。

```bash
# 回环探针（门禁）：必须剥掉 shell 里的 Clash 代理 env，否则连不上本机后端
# 合成源 60fps 门禁（需先起 scripts/synthetic_car_video.py --fps 60 --probe 作车端）：
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
  .venv310/bin/python scripts/webrtc_loop_probe.py \
  --backend http://127.0.0.1:8123 --duration 25 \
  --gate-fps 58 --gate-latency-ms 50
# 期望 EXIT=0

# 模拟器真实流门禁（源上限 20fps，帧率门槛相应放宽到 19）：
#   同上命令改 --gate-fps 19；车端需 DRIVE_WEBRTC_FRAME_STAMP=1 或探针模式启动

# 浏览器：打开 Drive 页（后端 8123 静态服务 dist/），徽标出现「XXms E2E」即像素通路激活
# 前端测试 / 构建
cd web_ui/frontend && npm test && npm run build
# 车端测试
env -u http_proxy -u https_proxy .venv310/bin/python -m pytest donkeycar/tests/ -q
```

## 已知限制与陷阱

- **Chrome 145 无 `captureTime`**：rVFC 通路在真实浏览器中不可用，像素印章是生产路径；未来 Chrome 若补上该字段会自动优先走原生通路（代码已按优先级处理）。
- **损坏 fixture 陷阱**：印章 cell 是 6px，2×2 中心采样——损坏测试只翻转 cell 内 1 个像素时，采样均值可能仍不过阈值、校验照样通过。要作废一个 cell 必须**翻转整个 cell 区域**（Python 参考实现验证返回 None 后再落盘）。
- **`TestFrontendNeedsBuild` 偶发失败**：f2fs 上背靠背写文件 `st_mtime_ns` 相同，是既有环境竞态，与本改动无关（测试文件 git status 干净）。
- **pytest 必须剥代理 env**：shell 常驻 Clash 代理会让 `test_launcher_dsh_web` 等 502（详见 donkeydrift-proxy-env-pitfall 记忆）。
- **口径边界**：e2e = 「浏览器呈现时刻 − 车端出帧时刻」，不含模拟器合成视频源内部的产生延迟；合成源 `synthetic_car_video` 的上游时间不计入。
- 印章默认关闭后，徽标退回帧间隔显示；要报真 E2E（或跑回环探针像素通路）需车端 `DRIVE_WEBRTC_FRAME_STAMP=1`（或以探针模式 `DRIVE_WEBRTC_LATENCY_PROBE=1` 启动，印章恒开）——测时延时开，日常驾驶保持关闭。
- **探针接收端押帧**：aiortc 上游 JitterBuffer 押帧一帧周期的口径问题已由探针内 `MarkerReleaseJitterBuffer` 修正；**不要**把修正前后的探针读数直接对比（旧读数系统性虚高：20fps 源 +50ms / 60fps 源 +16.7ms）。
- **遮挡窗口测量陷阱**：浏览器窗口被遮挡时 Chromium 暂停合成，rVFC 不触发（徽标/FPS 停更、droppedVideoFrames 虚高）——自动化截图会强制单次合成但采样环仍停；浏览器徽标数值要在窗口真实可见时读。
- **模拟器帧率上限**：闭源 Unity 端遥测/出图节拍固定 20fps（与渲染分辨率、客户端步调均无关），模拟器预览帧率勿设高于 20 的预期；真车相机与合成源不受此限。
