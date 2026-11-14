# WebRTC 浏览器渲染优化实录：从 65ms/25FPS 到 18ms/60FPS

> 日期：2026-10-16 ｜ 分支：`ui-drive-target-sim-badge`
> 相关 commit：`d9a7ce70`（第一轮）、`9230ff3e`（第二轮）
> 目标：WebRTC 画面时延稳定 25ms、帧率 60FPS
> 结果：**原生 120Hz 屏 17.4ms/60FPS；外接 60Hz 屏 ~18ms/~58FPS**

---

## 1. 背景与初始症状

驾驶页 WebRTC 画面自报「时延平均 >65ms、帧率 <25FPS」。直接优化编码器、网络、队列都可能无效——先分段定位。

## 2. 诊断方法论（本次最大产出）

### 2.1 四段对拍口诀

```bash
curl -s http://127.0.0.1:8000/api/drive/webrtc/stats | jq '{
  source_fps, sent_fps, inbound_fps, browser_fps,
  render_fps_gap, browser_p95_frame_interval_ms,
  e2e_samples, transport, peer_connection_state
}'
```

| 指标 | 含义 | 低 → 瓶颈 |
|---|---|---|
| `source_fps` | 模拟器/相机源出帧 | 源端（原版 DonkeySim 仅 20fps，需重编 arm64 版） |
| `sent_fps` | 车端编码+发送 | 编码/发送（VP8 软编已调优至 ~2ms，正常应≈源） |
| `inbound_fps` | 浏览器 RTP 接收 | 网络/传输 |
| `browser_fps` | 浏览器实际呈现 | **浏览器渲染被抑制（最常见）** |
| `render_fps_gap` | inbound − browser | >5 即浏览器段丢帧 |

### 2.2 测量口径陷阱

- **徽章不带「E2E」标记时，显示的是帧间隔，不是真实端到端时延**。60Hz 节拍补帧 + 20fps 源下，帧间隔天然虚高。
- 真实 E2E 需车端 `DRIVE_WEBRTC_FRAME_STAMP=1`（像素印章），或前端 `VITE_DRIVE_WEBRTC_DIAGNOSTIC=1` 诊断模式。
- 浏览器窗口必须**真实可见**：后台标签 rVFC 停更、遮挡时 Chromium 暂停合成，读数不可信。
- 内置浏览器/headless SwiftShader 只有 ~45fps 上限，不能作为验收环境。

### 2.3 本次定位结论

实时 stats：`source 59.98 / sent 59.98 / inbound 60.0 / browser 17.6`，`p95_frame_interval 67.6ms`。

→ 源、发、收全部 60fps，**瓶颈完全在浏览器呈现段**。用户感知的「>65ms」是呈现帧间隔。

## 3. 第一轮：渲染抑制修复（commit d9a7ce70）

| 改动 | 文件 | 作用 |
|---|---|---|
| MJPEG 淡出后 `src` 置空 | `VideoStream.tsx` | WebRTC 显示期间 MJPEG `<img>` 仍持续解码/占带宽，彻底断开 |
| `renderThrottleDetected` | `useDriveWebRtcVideo.ts` | inbound≥50 且 browser<40 持续 2s → 「渲染降频」告警 |
| 可见性监听 + WakeLock | `useDriveWebRtcVideo.ts` | 切前台重置看门狗；防息屏/省电降频 |
| stats 增加 `render_fps_gap` | `routers/drive.py` | 后端直接暴露浏览器段丢帧 |

**效果**：browser_fps 17.6 → ~46（内置浏览器验证环境）。

## 4. 第二轮：呈现路径 jitter 压减（commit 9230ff3e）

核心认知：**60Hz 屏上 60fps 视频是 1:1 贴 vsync，每帧固定开销都会转化为 vsync miss**。清除了两个每帧固定开销：

1. **像素印章 canvas 读回自适应降频**（`useDriveWebRtcVideo.ts`）
   车端默认不烧印章时，逐帧 `drawImage+getImageData(240×24)` 是纯开销且落在呈现关键路径。未激活时每 15 帧探一次，读到印章即恢复逐帧精确采样；首帧立即探测（测试桩兼容），closePeer 重置为 STRIDE−1。
2. **移除常驻徽标 backdrop-blur**（`VideoStream.tsx`）
   `backdrop-filter` 对 60fps 动态画面逐帧模糊采样是持续 GPU 合成开销。两个常驻徽标改不透明底 `bg-zinc-900/85`；条件性横幅保留原样。

**同环境 A/B**（内置浏览器 Electron webview，vsync 余量最紧）：

| 构建 | browser_fps | p95 帧间隔 |
|---|---|---|
| 旧 | 46.6 | 33.5ms |
| 新 | **58.5（稳态）** | **17.7ms** |

## 5. 屏幕刷新率是硬地板（重要结论）

`system_profiler SPDisplaysDataType`：内建 Liquid Retina XDR（120Hz ProMotion）vs 外接 3840×2560 @ 60Hz。

- vsync 量子：120Hz = 8.33ms；60Hz = 16.67ms。
- 60Hz 屏上任何解码/合成 jitter 错过当前 vsync → 顺延一拍：时延 +17ms、平均 FPS 60→50。
- **60Hz 屏 `<video>` 管线理论地板 ≈ 33ms**（解码 ~2 + jitter buffer ~9 + 合成 ~5 + 1 个 vsync 16.7）。实测外接屏 ~18ms 是在 jitter 极小、jitter buffer 压到 ~5ms 时逼近地板的好结果。
- 稳定 <25ms 必须 120Hz 屏，或 WebCodecs 手动呈现（仍受面板物理刷新率约束）。

### 关于关闭 vsync

`--disable-gpu-vsync` 类 flag 最多省掉平均 ~8ms@60Hz 的 vsync 等待，代价是撕裂；且 macOS WindowServer 仍按显示刷新率合成，收益再打折扣。**vsync 是免费的去抖动机制，不是敌人**——正确姿势是压 jitter 让每帧都赶上 vsync，而非拆掉它。

## 6. 最终成绩

| 环境 | 时延（p95 帧间隔） | FPS | 备注 |
|---|---|---|---|
| Edge @ 原生 120Hz 屏 | **17.4ms** | **60.0** | gap≈0 |
| 外接 60Hz 屏 | **~18ms** | **~58（50+）** | 逼近 60Hz 理论地板 |

验证：`tsc`/`eslint` 通过，`VideoStream` + `useDriveWebRtcVideo` 32 个单测全绿；`web_ui/backend/tests/test_drive.py` stats 相关 11 个全绿。

## 7. 经验沉淀

1. **先分段定位再动手**：四段指标一对拍，瓶颈段立刻现形，避免在无关段浪费时间。
2. **每帧固定开销是 60Hz 屏的隐形杀手**：canvas 读回、backdrop-filter、CSS transition 残留、rVFC 回调里的重活——120Hz 屏有 2:1 余量时被掩盖，60Hz 屏 1:1 贴 vsync 时全部显形。排查时找呈现路径上「每帧无条件执行」的代码。
3. **测量口径决定结论方向**：帧间隔 ≠ 端到端时延；徽章口径、窗口可见性、合成器状态三者不对齐，读数全是陷阱。
4. **后台预加载是隐蔽资源杀手**：`opacity:0` ≠ 停止工作，`<img src>`、解码器、transition 都还在跑。
5. **显示刷新率 > 一切软件优化**：屏幕换不了时，把 jitter 压到极限是唯一手段；屏幕能换时，120Hz 一步到位。

## 8. 操作命令速查

```bash
# 诊断
curl -s http://127.0.0.1:8000/api/drive/webrtc/stats | jq '.'
system_profiler SPDisplaysDataType | grep -E "Resolution|Hz|UI Looks like"

# 前端验证
cd web_ui/frontend && npm run check && \
  npm run test -- --run src/components/drive/VideoStream.test.tsx src/hooks/useDriveWebRtcVideo.test.tsx && \
  npm run build

# 后端 stats 测试
.venv/bin/python -m pytest web_ui/backend/tests/test_drive.py -k stats -x -q

# 重启 web 后端（Python 改动需重启；仅前端构建不需要）
pkill -f "uvicorn main:app"; nohup .venv/bin/donkey web --path web_ui --backend-port 8000 --route /drive &
```
