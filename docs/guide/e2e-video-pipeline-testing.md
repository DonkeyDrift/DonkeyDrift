# 端到端图传闭环测试方法（e2e_video_test）

目标：让图传（Drive 页 WebRTC 视频）的效果优化**可测量、可对比、可回归**——
改任何一个图传参数，一条命令重跑同一场景，与历史对比指标增减，门禁守住下限。

工具：`scripts/e2e_video_test.py`（编排器）+ `scripts/synthetic_car_video.py`
（合成图传源）+ `scripts/webrtc_loop_probe.py`（回环探针，含 marker 释放口径修正）+
`/api/drive/webrtc/stats`（浏览器支路聚合上报）。

## 指标模型：分段预算

端到端时延 = 各段之和，优化先看哪段超预算：

| 段 | 典型值（本机实测） | 测量手段 |
|---|---|---|
| 源出帧→到达（模拟器内部） | ~30-50ms（20fps 节拍，闭源端固有） | 印章不含此段；只能靠缩小渲染分辨率间接压 |
| 到达→被消费（车辆循环轮询） | ~9.8ms@60Hz（0@源帧率>循环率时反超） | 车端插桩 / `DRIVE_LOOP_HZ` |
| 缓冲→取帧→编码→发包 | ~2ms（VP8 cpu-used=15） | 车端插桩（见 CHANGELOG 270） |
| 网络→解码（探针/浏览器） | ~1-4ms 回环 | 回环探针 |
| 浏览器抖动缓冲 + 呈现 | ~8-14ms | 页面上报 `jitter_buffer_delay_ms` |

帧率上限由**源**决定：模拟器固定 20fps（闭源端硬上限，与渲染分辨率无关）；
真车相机与合成源 60fps。管线能力用合成源单独测（pipeline-* 场景）。

## 场景矩阵与门禁

| 场景 | 源 | 门禁 | 守护什么 |
|---|---|---|---|
| `pipeline-320p60` | 合成 320×240@60 | fps≥58、p95≤50ms | 管线能力/回归（真车相机口径） |
| `pipeline-480p60` | 合成 640×480@60 | 同上 | 预览编码上限分辨率下的能力 |
| `simcadence-320p20` | 合成 320×240@20 | fps≥19、p95≤50ms | 模拟器节拍仿真 |
| `simcadence-480p20` | 合成 640×480@20 | 同上 | 模拟器节拍 + 上限分辨率 |
| `live` | 在跑车端（须 `--backend`） | fps≥19、p95≤50ms | 真实链路（含模拟器/真车） |

每个场景可选加浏览器支路（`--browser`）：headless Chromium 打开 Drive 页，
页面自己接入 WebRTC、解码、像素印章采样并 POST 回后端，编排器取
`e2e_latency_p50/p95`、`inbound_fps`、`jitter_buffer_delay_ms`——
这是**含浏览器抖动缓冲与呈现的真实用户口径**。探针支路（aiortc 接收端）
与浏览器支路在同一场景内串行跑，互不抢会话。

门禁细则：印章覆盖必须 100%（无印章帧=0，防口径静默失效）；浏览器支路要求
`e2e_samples ≥ 60` 才认定有效。

## 快速上手

```bash
# 前置：剥掉 shell 代理 env（回环会被代理机劫持）
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY .venv/bin/python scripts/e2e_video_test.py

# 常用变体
... scripts/e2e_video_test.py --list-scenarios          # 看场景与门限
... scripts/e2e_video_test.py --browser                 # 加浏览器支路（约多 1 分钟/场景）
... scripts/e2e_video_test.py --scenarios live \
    --backend http://127.0.0.1:8000                     # 打在跑的真实链路
... scripts/e2e_video_test.py --duration 25             # 加长采样更稳

# 退出码：任一门禁失败 → 1，可直接挂 CI / pre-push
```

默认自动起**隔离后端**（随机空闲端口），与在跑的正式实例互不干扰；
`live` 场景例外——它必须 `--backend` 指向真实实例。

## 优化闭环工作流

```
跑基线 → 改一个旋钮 → 重跑同场景 --compare-last → 看指标增减 → 保留/回退
```

```bash
# 例：把码率降到 750kbps，看时延/帧率是否受益
... scripts/e2e_video_test.py --scenarios pipeline-320p60,simcadence-320p20 \
    --set DRIVE_WEBRTC_VIDEO_BITRATE=750000 --compare-last
# [对比] pipeline-320p60（vs 上一次同场景）:
#     stamp_fps  60.07 → 60.10（+0.03）
#     e2e p50    3.99 → 4.12（+0.13）
```

历史落 `~/.donkeycar/video_pipeline_history.jsonl`（JSONL，每场景一行，
含参数快照与逐项门禁结果），可用 jq 自由分析趋势。

### 可 A/B 的旋钮（`--set` 传给合成源进程的 env）

| 旋钮 | 作用 |
|---|---|
| `DRIVE_WEBRTC_VIDEO_BITRATE` | VP8 初始码率（aiortc 上限 1.5M） |
| `DRIVE_WEBRTC_ENCODER_TUNE` | 0=回退上游 VP8 默认参数（对照实验） |
| `DRIVE_WEBRTC_PREVIEW_MAX_WIDTH/HEIGHT` | 预览编码分辨率上限（0=不设限） |
| `DRIVE_WEBRTC_FRAME_STAMP` | 印章开关（合成源用 `--probe` 已恒开） |

源侧参数直接用场景定义（fps/分辨率），或改 `SCENARIOS` 字典加自定义场景。
非 env 类改动（编码器参数、轨道逻辑）直接改代码后重跑对比。

### 判读规则

- 探针 p95 涨、浏览器 p95 同步涨 → 管线真退化；只有浏览器涨 → 浏览器侧
  （抖动缓冲/呈现）退化，查 `jitter_buffer_delay_ms` 与前端 hints。
- 帧间隔 p95 显著大于 1000/fps → 源侧节拍抖动或消费侧丢拍。
- 印章覆盖 <100% → 印章/缩放链路被动过，先修口径再谈指标。

## 已知陷阱（详见 docs/arch/webrtc-e2e-latency.md）

- **不要与修正前的探针读数对比**：旧探针接收端押帧一帧周期（20fps 源 +50ms），
  历史门禁数字（p50 31.96 等）含虚高。
- **模拟器源 20fps 硬上限**：`simcadence-*` 场景即为此口径的仿真；`live` 打
  模拟器时帧率门限应为 19 而非 58。
- **代理 env**：全部子进程已被编排器剥离代理；手动跑单件时仍需自己剥。
- **浏览器支路**：headless（`--headless=new`）不存在遮挡停摆问题；有窗浏览
  器被遮挡时 Chromium 暂停合成、rVFC 停摆，样本会枯竭——数值要在窗口
  真实可见时读。
- **前端改动后**需 `cd web_ui/frontend && npm run build`，浏览器支路测的是
  `dist/` 构建产物。
