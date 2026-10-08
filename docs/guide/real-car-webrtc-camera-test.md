# 真车相机链路 WebRTC 时延测试操作说明

适用：真车（AidLux 车端 + UVC 相机 + 浏览器遥控）验证 P0（编码调优）/ P1a（媒体绑核）
效果，并采集是否需要 P1b（推流进程隔离）的决策数据。工具链全部复用本仓库：
时延印章（`video_timestamp`）+ 回环探针（`scripts/webrtc_loop_probe.py`）+
浏览器探针（`web_ui/frontend/e2e/webrtc-browser-probe.mjs`）。

代码基线要求：车端仓库 ≥ `8e1d6007`（P0+P1a 均默认生效，`~/projects/mycar/` 无需改动）。

```bash
cd ~/projects/DonkeyDrift && git pull
```

## 0. 安全与前置

- **架空车轮**（驱动轮离地）后再启动驾驶进程；测试期间无人遥控时不给油。
- 车端与浏览器 PC 处于同一局域网（当前信令/媒体都是局域网直连，无 TURN）。
- 记录测试环境：车端 IP、浏览器 PC、Wi-Fi RSSI（`iwconfig wlan0 | grep -i qual`，可选）。

## 1. 相机能力确认（一次性，5 分钟）

真车配置为 `CAMERA_TYPE = "WEBCAM"`（UVC 相机）。先确认相机硬件档位：

```bash
v4l2-ctl -d /dev/video2 --list-formats-ext | head -30
```

要点：MJPG 模式下 640×480 / 352×288 均支持 60fps；YUYV 模式 640×480 只有 30fps。
若后续 `source_fps` 只有 ~30，说明相机协商到了 YUYV（见第 7 节排查）。

**注意**：`source_fps`（车端实际出帧率）永远以 stats 为准，不以相机标称为准——
车辆循环、相机驱动、pygame 采集任何一环不足都会在 `source_fps` 上如实暴露，
这正是设计文档「不补帧、暴露瓶颈」的原则。

## 2. 启动驾驶链路（探针印章开启）

### 方式 A：一键启动（推荐）

```bash
cd ~/projects/mycar
DRIVE_WEBRTC_LATENCY_PROBE=1 donkey drive \
    --path ~/projects/DonkeyDrift/web_ui --car ~/projects/mycar
```

一条命令拉起：后端+前端（生产模式同源，默认 :8000）+ 车端 `manage.py drive`
（探针 env 随进程继承，`DRIVE_API_SERVER_URL` 自动注入指向本机后端）。
**浏览器访问 `http://<车端IP>:8000/#/drive`**（生产模式前端由后端端口托管，
与 API 同源）；加 `--dev` 才是 Vite 的 5188。Ctrl+C 同时停三层。

### 方式 A'：TUI 入口（`donkey tui` 或直接 `donkey`）

菜单选 `6 · Drive`，确认页会询问「开启 WebRTC 时延探针？」，选 `y` 等价于
方式 A 带 `DRIVE_WEBRTC_LATENCY_PROBE=1`（选择显式覆盖 shell 残留 env），
启动后直接给出针对本次端口的探针命令；正常驾驶选 `n`（默认）。

### 方式 B：分开启动（调试用）

```bash
# 终端 1：Web UI（生产模式：前端+API 同源在 8000）
donkey web --path ~/projects/DonkeyDrift/web_ui
# 终端 2：车端（探针开；显式用 venv 解释器，避免 PATH 上的 python 不是项目环境）
cd ~/projects/mycar
DRIVE_WEBRTC_LATENCY_PROBE=1 ~/projects/DonkeyDrift/.venv310/bin/python manage.py drive
```

### 启动后核对（三个信号）

```bash
curl -s http://127.0.0.1:8000/api/drive/stats          # online:true, car_ws_connected:true
curl -s http://127.0.0.1:8000/api/drive/webrtc/stats   # source_fps 应≈60
```

车端日志必须出现两行（P0/P1a 生效标志）：

```
INFO ... webrtc_encoder: 已安装调优 VP8 编码器: cpu-used=15 noise-sensitivity=0 gop=240 码率=1500000bps
INFO ... drive_api_bridge: bridge 线程已绑核: [4, 5, 6, 7]
```

> 探针印章说明：`DRIVE_WEBRTC_LATENCY_PROBE=1` 会在每帧上烧入捕获时刻（多一次
> 帧拷贝+绘制，测量态开销）。正式跑比赛/录制时可去掉该 env；本文档所有时延
> 数值均需在此模式下测。

## 3. 车端链路实测（回环探针：相机→编码→解码）

在**车上** SSH 执行（回环网络，不含 Wi-Fi 与浏览器呈现段）：

```bash
cd ~/projects/DonkeyDrift
.venv310/bin/python scripts/webrtc_loop_probe.py \
    --backend http://127.0.0.1:8000 --duration 10 \
    --gate-fps 58 --gate-latency-ms 60          # 门禁不达标退出码 1
.venv310/bin/python scripts/webrtc_loop_probe.py \
    --backend http://127.0.0.1:8000 --duration 30 --json > probe_30s.json   # 长测存档
```

行为说明：

- 探针会**接管单客户端视频会话**：此时若有浏览器页面开着 Drive，页面会自动降级
  MJPEG（issue #009 的接管判定机制），**控制通道不受影响**。测量时建议关闭浏览器
  Drive 页，测完刷新即恢复 WebRTC。
- 输出 `e2e_ms`（p50/p95/max）= 帧上印章时刻 → 探针解码出像素时刻，两端已通过
  `/api/drive/time` 做 NTP 式对时，无需人工对表。
- 也可在局域网 PC 上跑（需同一仓库 + venv 依赖：aiortc/av/numpy/requests/websockets），
  探针自动与后端对时；PC 上跑会把真实 Wi-Fi 网络段计入，数值更接近用户体感。

## 4. 浏览器端验收（真实呈现链路）

### 4a. 自动探针（推荐，可做门禁）

在能访问车端的机器上（本机 node v24 + Playwright 已就绪）：

```bash
cd ~/projects/DonkeyDrift/web_ui/frontend
node e2e/webrtc-browser-probe.mjs \
    --url http://<车端IP>:8000/ --duration 12000 \
    --gate-fps 59 --gate-e2e-ms 100        # --headed 可观察画面
```

（`--url` 用后端端口：生产模式前端与 API 同源；`--dev` 启动时才是 5188。）

浏览器探针指标：rVFC 的 `expectedDisplayTime − captureTime`（同处浏览器时钟域，
含解码+呈现，不含跨机对时误差）+ 后端 stats 里浏览器自报 browser FPS / P95 间隔。

### 4b. 人工验收（按设计文档验收清单）

浏览器打开 `http://<车端IP>:8000/#/drive`（生产模式同源端口；`--dev` 启动时为 `5188`）：

1. 左上角确认传输模式为 **WebRTC**（非降级）；
2. **连续运行 2 分钟**，记录徽标：browser FPS（平均）、帧间隔 P95、source/sent FPS；
3. 断流恢复：手动断开浏览器 Wi-Fi 3 秒再恢复（或刷新页面），确认 ≤3s 内画面恢复；
4. 视频运行期间用键盘/手柄持续给 60Hz 控制输入，确认控制跟手、无卡顿毛刺；
5. （可选）`chrome://webrtc-internals` 抓一份 dump：关注 `jitterBufferDelay`、
   `packetsLost`、`pliCount`（PLI 频繁 = 丢包在触发关键帧重传）。

## 5. 验收判读表

| 指标 | 读取位置 | 参考线 | 说明 |
|------|---------|--------|------|
| source_fps | `/api/drive/webrtc/stats` | ≥58 | 相机+车辆循环实际出帧；≈30 → 查第 7 节 |
| sent_fps | 同上 | ≈source_fps | 编码器是否跟得上 |
| browser FPS | Drive 页徽标 / 浏览器探针 | 2min 平均 ≥58 | 含解码+呈现 |
| 帧间隔 P95 | Drive 页徽标 / 浏览器探针 | ≤25ms | 抖动 |
| 回环探针 e2e p95 | `webrtc_loop_probe.py` | ≤60ms | 车端管线（不含 Wi-Fi/呈现）；合成源基线 44ms 可作地板参考 |
| 浏览器端 e2e | `webrtc-browser-probe.mjs` | ≤100ms | 含网络+呈现，首次真车实测后固化 |
| 断流恢复 | 人工 | ≤3s | 前端看门狗 |
| 控制 60Hz | 人工体感 + internals | 无阻塞 | 视频/控制隔离 |

## 6. 数据记录模板（每轮一行，便于回归对比）

```
日期 | 车端IP/浏览器PC | Wi-Fi RSSI | 探针JSON存档 | source/sent/browser fps |
探针 p50/p95 | 浏览器 p50/p95 | 备注（异常/降级/PLI）
```

## 7. 故障排查矩阵

| 现象 | 首先查 | 处置 |
|------|--------|------|
| source_fps≈30 | `v4l2-ctl --list-formats-ext` | 相机协商到 YUYV@30：改用 MJPG 显式协商（如 `CAMERA_TYPE="CVCAM"` + OpenCV `CAP_PROP_FOURCC=MJPG`），或接受 30fps 并把门禁改为 `--gate-fps 29` |
| source 正常、sent_fps 低 | 车端日志「bridge 线程已绑核」是否存在 | 确认 `DRIVE_WEBRTC_AFFINITY` 未被关；试 `DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE=1`；推理重时试 `DRIVE_WEBRTC_MEDIA_CPUS=0-3` 反转分配 |
| sent 正常、browser FPS 低/卡顿 | internals `packetsLost`/`pliCount` | Wi-Fi 质量；降码率 `DRIVE_WEBRTC_VIDEO_BITRATE=1000000`；近距离复测排除信号问题 |
| 画面冻结不恢复 | 浏览器控制台 `[drive-webrtc] recover:` | 应 ≤10s 自动回 MJPEG/重连；若真冻结，按 issue #009 流程抓现场 |
| 探针报「采样帧数不足」 | 车端是否带 `DRIVE_WEBRTC_LATENCY_PROBE=1` 启动 | 该 env 必须在车端进程启动前设置 |
| 探针期间页面变 MJPEG | 预期行为 | 单客户端会话被探针接管（issue #009 接管判定），刷新页面恢复 |

## 8. 同机基线对照（可选，推荐做一次）

区分「相机/车辆循环慢」还是「网络/编码慢」：同一台车机、同一 Wi-Fi，换合成源跑一轮——
合成源无相机采集与推理开销，等于链路的性能地板。

```bash
# 终端 1：只起 Web UI（避开 8000，不干扰真车栈）
donkey web --path ~/projects/DonkeyDrift/web_ui --backend-port 8123
# 终端 2：合成 60fps 源 + 探针印章
cd ~/projects/DonkeyDrift
.venv310/bin/python scripts/synthetic_car_video.py \
    --server ws://127.0.0.1:8123/api/drive/ws --fps 60 --probe
# 终端 3：探针（同第 3 节，backend 换 8123）
```

对照口径：合成源基线（P1a 后）fps≈60 / 回环 p50≈33ms / p95≈44ms /
帧间隔 P95≈21ms。真车与它的差距即为相机采集 + 推理引入的额外成本，
差距大才考虑 P1b（推流进程隔离）。

## 9. 测完之后

- 把真车数据与合成源基线（P1a 后：fps 59.94 / 回环 p50 33.9ms / p95 44.5ms /
  帧间隔 P95 21.8ms）对比：
  - **接近** → P1b（推流进程隔离）不需要推进，WebRTC 时延工作收口；
  - **source/sent 显著劣化**（推理负载挤占）→ 带 `probe_30s.json` 数据启动 P1b 设计。
- 正式驾驶/录制时去掉 `DRIVE_WEBRTC_LATENCY_PROBE`（省去每帧印章开销）。
