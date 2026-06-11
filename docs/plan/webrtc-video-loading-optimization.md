# WebRTC 视频加载优化方案

## 背景

Web Console Drive 页面在采用 WebRTC 传输摄像头画面时，用户经常反馈「黑屏时间长」、「首次加载慢」、「偶发卡死」。本方案对现有前后端信令链路进行逐层拆解，定位瓶颈并给出可落地的优化路径与标准操作流程。

> **涉及范围**
> - 前端：`web_ui/frontend/src/components/drive/VideoStream.tsx`、`useDriveWebRtcVideo.ts`、`useDriveWebsocket.ts`
> - 后端：`web_ui/backend/routers/drive.py`
> - 车端：`donkeycar/parts/drive_api_bridge.py`

---

## 一、当前运行逻辑

WebRTC 视频链路涉及 **浏览器 → FastAPI 后端 → DriveApiBridge（车端）** 三方协同：

```
浏览器（React）
  ├─ WebSocket /drive/ws?role=client  ←────────────→  后端 drive.py  ←──── WebSocket ────→  DriveApiBridge（车端）
  ├─ HTTP POST /webrtc/session         创建会话
  ├─ HTTP POST /webrtc/offer           发送 Offer
  ├─ WebSocket 接收 answer/ice         信令回传
  └─ RTCPeerConnection ontrack         接收视频

车端（DriveApiBridge）
  ├─ WebSocket 接收 offer
  ├─ aiortc RTCPeerConnection 创建 Answer
  ├─ HTTP POST /webrtc/answer  ─────────────────────→ 后端 drive.py
  ├─ HTTP POST /webrtc/ice     ─────────────────────→ 后端 drive.py
  └─ aiortc VideoTrack 推送帧
```

### 1.1 前端时序

1. 页面挂载 → `useDriveWebRtcVideo.start()` 自动执行。
2. `POST /webrtc/session` 创建会话（后端要求车端必须在线）。
3. 创建 `RTCPeerConnection`，添加 `recvonly` video transceiver。
4. 创建 offer → `setLocalDescription` → `POST /webrtc/offer`。
5. 通过 WebSocket 监听 answer 与 ICE candidates。
6. `ontrack` 触发后设置 `video.srcObject`，状态变为 `connected`。
7. 若 12 秒内未收到 track，状态变为 `degraded`，5 秒后重试。

### 1.2 车端时序

1. WebSocket 收到 offer → `_accept_webrtc_offer`。
2. 创建 `RTCPeerConnection`，添加 `DriveAiortcVideoTrack`。
3. `setRemoteDescription(offer)` → `createAnswer()`。
4. **同步 HTTP POST** answer 到后端 `/webrtc/answer`。
5. `setLocalDescription(answer)`（timeout 8 秒）。
6. 从 local SDP 批量提取 ICE candidates 并 HTTP POST 到后端。
7. 收到远程 ICE candidate → `addIceCandidate`。

### 1.3 后端时序

- `POST /webrtc/session`：检查车端在线，生成 session_id。
- `POST /webrtc/offer`：验证 session，通过 WebSocket 转发给车端。
- `POST /webrtc/answer`：从车端接收，通过 WebSocket 转发给浏览器。
- `POST /webrtc/ice`：按来源双向转发。

---

## 二、瓶颈根因分析（按严重程度排序）

### 🔴 P0 — 车端用同步 requests 阻塞 asyncio 事件循环

**位置**：`donkeycar/parts/drive_api_bridge.py:559-563`

```python
def _post_json(self, path: str, payload: dict):
    url = f"{self.http_api_base}{path}"
    response = requests.post(url, json=payload, timeout=3)
    ...
```

**问题**：
- `_accept_webrtc_offer` 是 async 函数，运行在 asyncio 事件循环中。
- 创建 answer 后调用 `_post_webrtc_answer` → `_post_json` → **同步阻塞的 `requests.post`**。
- 发送 answer 期间，整个车端事件循环被冻结：WebSocket 收消息暂停、ICE 处理暂停、心跳暂停。
- 若网络抖动，`timeout=3` 会直接卡满 3 秒。
- ICE candidate 的回传同样走 `_post_json`，每次都会重复阻塞。

**影响**：
- answer 回传延迟不可控（几十毫秒到 3 秒）。
- 浏览器在 `setRemoteDescription` 之前无法开始 ICE 连通性检查。
- 偶发的「信令卡住」现象根源在此。

---

### 🟠 P1 — WebRTC 与 MJPEG 串行而非并行

**位置**：`web_ui/frontend/src/components/drive/VideoStream.tsx:64-80`

```typescript
if (webRtcConnected) {
  resetFallbackTimer();
  return;
}
// WebRTC 没连上时，15 秒后才允许 MJPEG fallback
fallbackTimerRef.current = setTimeout(() => {
  setMjpegFallbackAllowed(true);
}, DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS); // 15000ms
```

**问题**：
- 页面打开后，WebRTC 未连接前只显示 `<video>` 黑屏。
- 必须等 **15 秒** 才会降级到 MJPEG。
- 即使后端 `/drive/video` 本来就有帧，前端也**拒绝渲染**。
- 加上 `negotiationTimeoutMs = 12000`（12 秒），最坏情况下用户要等 **12~15 秒** 才能看到画面。

---

### 🟠 P1 — 前端盲目创建会话，不判断车端在线状态

**位置**：`web_ui/frontend/src/hooks/useDriveWebRtcVideo.ts:310-316`

```typescript
useEffect(() => {
  mountedRef.current = true;
  start();  // 页面一挂载立刻创建 WebRTC 会话
  ...
}, [closePeer, start]);
```

**问题**：
- `start()` 立即 `POST /webrtc/session`。
- 后端检查车端未在线时返回 **400**，前端 catch 后进入 5 秒重试。
- 车端后于浏览器上线时，会白白浪费多个 5 秒周期。

---

### 🟡 P2 — ICE 候选收集方式偏慢

**位置**：`donkeycar/parts/drive_api_bridge.py:471-478`

```python
await asyncio.wait_for(peer.setLocalDescription(answer), timeout=8.0)
self._post_local_ice_candidates_from_sdp(...)
```

**问题**：
- 车端依赖 `setLocalDescription` 完成后，**批量从 SDP 提取** candidates 发送。
- 而非通过 `on_icecandidate` 事件**实时 trickle** 发送。
- 浏览器必须等 SDP 中所有 candidates 到齐才能开始连通性检查，延迟增加。

---

### 🟡 P2 — 信令通道混合导致额外 RTT

**问题**：
- 浏览器 → 后端 → 车端的 offer 走 **WebSocket**，延迟低。
- 车端 → 后端的 answer/ICE 走 **HTTP POST**，多了一个 TCP/TLS 建连 RTT。
- 跨网环境下每次 HTTP 往返都会累加。

---

## 三、优化方案

| 优先级 | 优化项 | 修改文件 | 预期收益 |
|:---:|---|---|---|
| **P0** | 车端 `_post_json` 改为异步 HTTP（`aiohttp`）或在线程池中执行 `requests` | `donkeycar/parts/drive_api_bridge.py` | **消除事件循环阻塞**，信令延迟从数百毫秒降至数十毫秒 |
| **P0** | MJPEG 与 WebRTC **并行预加载**：页面打开即同时尝试 MJPEG，WebRTC 连上后无缝切换 | `VideoStream.tsx` | **用户 1 秒内即可见画面**，而非黑屏 15 秒 |
| **P1** | 前端监听车端在线状态后再发起 WebRTC | `useDriveWebRtcVideo.ts` + `useDriveWebsocket.ts` | 避免 400 错误与 5 秒空等 |
| **P1** | 缩短 fallback 延迟，或根据网络质量动态调整 | `VideoStream.tsx` | 更快降级到可用视频 |
| **P1** | 车端 `on_icecandidate` 实时发送 candidates，SDP 提取作为 fallback | `drive_api_bridge.py` | 加快 ICE 连通性检查 |
| **P2** | 车端 answer/ICE 统一走 WebSocket 回传 | `drive.py` + `drive_api_bridge.py` | 减少 HTTP 建连开销 |
| **P2** | 前端实现指数退避重连，替代固定 5 秒 | `useDriveWebRtcVideo.ts` | 减少无效重试压力 |

---

## 四、标准操作流程（SOP）

### 4.1 实施步骤

#### 步骤 1：消除车端事件循环阻塞（P0）

**方案 A（推荐）**：引入 `aiohttp` 作为车端异步 HTTP 客户端。

```python
# donkeycar/parts/drive_api_bridge.py
import aiohttp

class DriveApiBridge:
    def __init__(...):
        ...
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def _ensure_http_session(self):
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
        return self._http_session

    async def _post_json_async(self, path: str, payload: dict):
        session = await self._ensure_http_session()
        url = f"{self.http_api_base}{path}"
        async with session.post(url, json=payload) as response:
            response.raise_for_status()
            return await response.json()

    # 原 _post_webrtc_answer / _post_webrtc_ice 改为 await self._post_json_async(...)
```

> **依赖说明**：`aiohttp` 已存在于 `web_ui/backend/requirements.txt`，车端如需独立运行，建议在 `setup.cfg` 的 `[options.extras_require]` 中增加 `pc` / `pi` 等平台的 optional 依赖，或复用现有 `requests` 但在线程池中执行（`loop.run_in_executor`）。

**方案 B（无新增依赖）**：在线程池中执行同步 `requests`。

```python
async def _post_json_async(self, path: str, payload: dict):
    url = f"{self.http_api_base}{path}"
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None, lambda: requests.post(url, json=payload, timeout=3)
    )
    response.raise_for_status()
    return response
```

**改造点清单**：
- `_accept_webrtc_offer` 中 `_post_webrtc_answer` 改为 `await`。
- `_handle_webrtc_ice` 中如涉及 `_post_json`，同样改为 `await`。
- `shutdown()` 中关闭 `aiohttp.ClientSession`（若采用方案 A）。

#### 步骤 2：MJPEG 与 WebRTC 并行渲染（P0）

修改 `VideoStream.tsx`，不再串行等待 15 秒：

```typescript
// 伪代码：并行渲染策略
const [preferredTransport, setPreferredTransport] = useState<'webrtc' | 'mjpeg'>('mjpeg');

// WebRTC 连接成功后立即提升为主画面
useEffect(() => {
  if (webRtcConnected) {
    setPreferredTransport('webrtc');
  }
}, [webRtcConnected]);

// 组件始终渲染 MJPEG（底层），WebRTC 覆盖其上
// 或采用双标签同时加载，CSS z-index / visibility 控制切换
```

具体实现约束：
- 保留 `degraded` 状态语义（用于统计和标签展示）。
- MJPEG `<img>` 与 WebRTC `<video>` 同时存在于 DOM，通过 `visibility` 或 `z-index` 切换，避免 `<img>` 反复卸载导致重连。
- `DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS` 可保留但缩短至 **3000ms**，仅作为「确认无法降级」的兜底，而非首次显示门槛。

#### 步骤 3：前端监听车端在线后再发起 WebRTC（P1）

在 `useDriveWebRtcVideo` 中增加 `carOnline` 依赖：

```typescript
interface UseDriveWebRtcVideoOptions {
  ...
  carOnline?: boolean;
}

useEffect(() => {
  if (!carOnline) return;
  mountedRef.current = true;
  start();
  return () => { ... };
}, [carOnline, start, closePeer]);
```

`VideoStream.tsx` 中将 `useDriveWebsocket` 返回的 `carState.online` 传入 `useDriveWebRtcVideo`。

#### 步骤 4：优化 ICE 候选发送策略（P1）

在 `drive_api_bridge.py` 中确保 `on_icecandidate` 实时发送：

```python
@peer.on("icecandidate")
def on_icecandidate(candidate):
    self._handle_local_ice_candidate(candidate)
```

现有代码已注册该回调，但 `_accept_webrtc_offer` 在 `setLocalDescription` 后仍批量发送 SDP candidates。**保留批量发送作为 fallback**，但主路径改为依赖回调。无需删除现有逻辑，只需确保回调不遗漏。

#### 步骤 5：统一信令通道（P2，可选）

将 answer/ICE 的车端回传从 HTTP POST 改为 WebSocket：

- 后端 `drive.py`：新增 WebSocket 消息类型处理逻辑，车端可直接通过 `ws` 发送 answer/ice。
- 车端 `drive_api_bridge.py`：`_post_webrtc_answer` / `_post_webrtc_ice` 改为 `_send_json`（WebSocket）。
- 优势：零额外建连开销，与 offer 路径对称。
- 风险：需修改信令协议，建议放在独立 PR 中实施。

---

### 4.2 验证方法

1. **本地启动后端**：
   ```bash
   cd web_ui/backend
   python main.py
   ```

2. **启动前端**：
   ```bash
   cd web_ui/frontend
   npm run dev
   ```

3. **模拟车端上线**：
   ```bash
   python -c "
   from donkeycar.parts.drive_api_bridge import DriveApiBridge
   bridge = DriveApiBridge(server_url='ws://localhost:8000/api/drive/ws')
   import time; time.sleep(60)
   "
   ```

4. **观察指标**：
   - 浏览器 DevTools → Network → WS 中 `/drive/ws` 连接时间。
   - 浏览器控制台 `offer_to_answer_elapsed_ms` 统计值应 **< 500ms**（优化前常 > 1000ms）。
   - 页面打开后 **< 1 秒** 应出现 MJPEG 画面，WebRTC 连接成功后标签变为 `WebRTC`。
   - 车端日志无 `"设置 WebRTC local description 失败"` 或阻塞警告。

5. **自动化测试回归**：
   ```bash
   cd web_ui/backend && python -m pytest tests/test_drive.py -q
   cd donkeycar && python -m pytest tests/test_drive_api_bridge.py -q
   cd web_ui/frontend && npm run test
   ```

---

### 4.3 回退方案

| 场景 | 回退操作 |
|---|---|
| aiohttp 引入导致车端依赖冲突 | 改用方案 B（`run_in_executor` + `requests`），无需新增依赖 |
| 并行 MJPEG 导致带宽翻倍 | 增加 `VITE_DRIVE_VIDEO_TRANSPORT=mjpeg` 强制降级环境变量，一键切回旧行为 |
| WebRTC 完全不可用 | 前端 `transport='mjpeg'` 强制走 MJPEG 流，功能无损 |
| 车端 aiortc 未安装 | 现有逻辑已自动降级为 MJPEG（`drive_api_bridge.py:632-633`），无需操作 |

---

## 五、相关文件清单

| 文件路径 | 职责 |
|---|---|
| `web_ui/frontend/src/hooks/useDriveWebRtcVideo.ts` | 前端 WebRTC 连接、重试、状态管理 |
| `web_ui/frontend/src/hooks/useDriveWebsocket.ts` | 前端 WebSocket 信令通道 |
| `web_ui/frontend/src/components/drive/VideoStream.tsx` | 视频渲染、MJPEG fallback 策略 |
| `web_ui/frontend/src/services/api.ts` | HTTP API 封装（session/offer/ice/stats） |
| `web_ui/backend/routers/drive.py` | 后端信令转发、WebSocket 管理、MJPEG 流输出 |
| `donkeycar/parts/drive_api_bridge.py` | 车端 WebSocket 桥接、aiortc PeerConnection、帧缓冲 |

---

## 六、关键指标（优化前后对比）

| 指标 | 优化前 | 优化后目标 |
|---|---|---|
| 首次画面出现时间 | 12~15 秒 | **< 1 秒**（MJPEG 预加载） |
| Offer → Answer 延迟 | 500ms ~ 3s（requests 阻塞） | **< 200ms** |
| WebRTC 连接成功率 | 受网络抖动影响大 | **显著提升**（事件循环不阻塞） |
| 降级感知时间 | 15 秒固定 | **3 秒内动态感知** |
| 车端 CPU 阻塞 | 有（同步 IO） | **无**（全异步） |
