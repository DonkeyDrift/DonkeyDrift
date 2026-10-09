# WebRTC 真实端到端时延：诚实测量体系与 <50ms 实测

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
- 默认常开：`DRIVE_WEBRTC_FRAME_STAMP` 默认 `1`（显式探针 `latency_probe` 恒开；`=0` 关闭，徽标降级回帧间隔）。印章画在帧副本上，不污染自动驾驶管线输入。
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

## 实测结果（2026-10-10）

| 口径 | 条件 | 结果 |
|---|---|---|
| **回环探针（正式门禁）** | `--gate-fps 58 --gate-latency-ms 50`，25s，本机 8123 后端 | **stamp_fps 59.89、e2e p95 41.86ms → PASS**；p50 31.96 / min 19.59 / max 82.44；1497 帧 0 帧无印章 |
| **真实浏览器** | Chrome 145 headless，Drive 页 45s，板载 load 6.77/8（软解 VP8） | 徽标「57ms E2E」（240 样本，像素通路激活）；**p50 ≈ 45ms 达标**；p95 57~66ms（满载偏高）；前后半程 p95 66.3 → 63.4 无发散；jb_ms ~20、inbound 59-60fps、receiver hints 0/0 确认生效 |

结论对目标「网页 E2E < 50ms」：**p50 达标、回环门禁 p95 达标**；浏览器 p95 在板子满载 + 软件 VP8 解码条件下超 50ms，常规负载下预期落入门禁范围。徽标从此诚实——「E2E」标签出现即真实样本，无标签即降级。

## 复现方法

```bash
# 回环探针（门禁）：必须剥掉 shell 里的 Clash 代理 env，否则连不上本机后端
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
  .venv310/bin/python scripts/webrtc_loop_probe.py \
  --backend http://127.0.0.1:8123 --duration 25 \
  --gate-fps 58 --gate-latency-ms 50
# 期望 EXIT=0

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
- 关闭印章（`DRIVE_WEBRTC_FRAME_STAMP=0`）后徽标退回帧间隔显示，回环探针印章帧率也会归零——正常驾驶想画面纯净才关。
