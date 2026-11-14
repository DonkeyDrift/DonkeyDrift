# Issue 009: Drive 页 WebRTC 画面中途卡死后永不恢复

- 状态: fixed（2026-10-07）
- 记录日期: 2026-10-07
- 页面: Drive（WebRTC 预览链路）
- 类型: bug

## 现象

页面刚打开时 WebRTC 画面正常刷新，运行一段时间后画面冻结，一直停留在最后一帧；
左上角仍显示「WebRTC 已连接」、FPS 徽标停止，MJPEG 兜底层被冻结的 WebRTC 层压住不可见，
只能刷新页面恢复。

后端统计在冻结期间的表现（真实复现现场，19:10 采样）：
车端 `source_fps≈58 / sent_fps≈57`、`peer_connection_state=connected`、
`ice_connection_state=completed`，而 `browser_fps=0`——自会话创建起浏览器侧
`requestVideoFrameCallback` 一次都没触发过（rVFC 只在真实出画时回调），
即传输层健康、媒体从未呈现。

## 调研结论

- **前端对「中途故障」没有任何恢复路径**（根因）：`useDriveWebRtcVideo` 只处理了
  建连阶段（协商超时 / 首帧超时，issue #221），建连成功后不再监听
  `connectionStatechange`、不监听 `track.mute`、不监测渲染停滞。
  `videoReady` 一旦置 true 只在 `closePeer` 复位——任何一次环境瞬断
  （Wi-Fi 抖动/丢包后解码器等关键帧、笔记本锁屏、Wi-Fi 漫游、NAT 重绑定、
  会话被其他页签/设备抢占）都会让画面**永久**冻结。
- `VideoStream` 的 `webRtcVisible = webRtcConnected && videoReady` 在卡死后恒为 true，
  冻结的 WebRTC 层（`z-10` + `opacity-100`）盖住 MJPEG 兜底，用户看到的是定格画面。
- 车端视角无法暴露该故障：aioice 有 consent 检测（CONSENT_INTERVAL=5s × 6 次），
  浏览器页面只要还开着，ICE 就保持 connected；车端每秒上报的 stats 全部来自
  自己的 peer 对象，永远「健康」。
- 次要发现：车端 `DriveAiortcVideoTrack` 的 pts 按「每帧 +1」以声明 fps（60）的
  时基推进，而实际发送速率 48~57fps（编码波动），RTP 媒体时钟长期慢于墙钟
  （约 80~95%），属于 RTP 规范违例，接收端缓冲时序随运行时长失真。
- 单会话槽位 + 无接管通知是叠加因素：`webrtc_session` 是单槽位，新车端 offer 会
  直接关掉旧 peer，旧页签收不到任何通知。
- localhost 链路（无丢包）30 分钟探针不复现，复现依赖环境瞬断，符合上述结论。

## 实现要点（已落地，2026-10-07）

1. **连接状态监控**（`useDriveWebRtcVideo.ts`）：`peer.onconnectionstatechange`——
   `failed`/`closed` 立即恢复；`disconnected` 给 3s 自愈宽限（`DRIVE_WEBRTC_DISCONNECT_GRACE_MS`），
   宽限内回到 `connected` 不打断。以 `peerRef.current === peer` 守卫，自己 close 的
   peer 不触发恢复。
2. **track 静音监控**：`track.onmute/onunmute` 记录静音起点，静音超过 6s
   （`DRIVE_WEBRTC_MUTE_RECOVERY_MS`）判定对端媒体断流，恢复。
3. **渲染停滞看门狗**：页面可见（`visibilityState === 'visible'`）且已出画后，
   rVFC 停止超过 6s（`DRIVE_WEBRTC_STALL_RECOVERY_MS`）判定卡死（覆盖「传输正常但
   解码卡住等关键帧」的场景，此时 connectionState 仍是 connected）。回前台时重置
   时钟，避免后台标签 rVFC 暂停被误判。
4. **恢复动作与接管判定**：恢复 = `closePeer` + 指数退避重连（上限 8s）；
   恢复前用 stats 轮询判定「活跃会话是否已被其他客户端接管」（`session_id` 不一致
   → superseded）：被接管则回 `idle` 交给 MJPEG 兜底，**不重连**——否则两个存活
   页签会互相抢会话形成拉锯战。`state='reconnecting'`/'idle' 期间 `webRtcVisible`
   为 false，MJPEG 层自动浮上来，用户始终有活画面。
5. **start() 重入先关旧 peer**：carOnline 抖动等路径带旧连接再次 start() 时，
   旧 peer 会在后台维持 ICE/DTLS 泄漏。
6. **pts 对齐墙钟**（`drive_api_bridge.py`）：pts 按帧真实采集时刻
   （`DriveVideoFrame.timestamp`）以锚点方式换算，单调保护兜底墙钟回拨
   （NTP 校时退化为每帧 +1）。恢复时间戳语义：RTP 时钟 = 墙钟。
7. 现场诊断口：恢复动作在浏览器控制台输出 `[drive-webrtc] recover: <原因>`。

## 验证

- 前端 `tsc -b --noEmit` 通过；eslint 0 error 0 warning；
  `vitest run` 全套 390/390 通过（含 5 个新增恢复路径用例：
  failed 重连 / disconnected 宽限自愈 / 渲染停滞恢复 / mute 恢复 / 接管不重连）。
- 后端新增 `tests/test_drive_webrtc_track.py` 3 用例：pts 跟随墙钟、墙钟回拨单调、
  time_base 语义。
- Playwright 双浏览器上下文端到端复现接管死亡：页签 A 播放中，页签 B 抢占会话
  （车端关闭 A 的 peer），A 在 **10s** 内检测到媒体死亡并回退 MJPEG（修复前永久
  冻结），B 全程零卡顿（38/38 采样帧数单调递增），会话槽位稳定无拉锯。
- 修复后前端 dist 已构建并经 :8001 真机服务（`index-kuJis5wm.js`）。
