import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from '@/i18n';
import {
  createDriveClientId,
  createDriveWebRtcSession,
  getDriveWebRtcStats,
  sendDriveWebRtcBrowserStats,
  sendDriveWebRtcIce,
  sendDriveWebRtcOffer,
  type DriveWebRtcStats,
} from '../services/api';
import type { WebRtcSignal } from './useDriveWebsocket';

export type DriveVideoState = 'idle' | 'connecting' | 'connected' | 'unstable' | 'reconnecting' | 'degraded' | 'error';

export const DRIVE_WEBRTC_NEGOTIATION_TIMEOUT_MS = 12000;
export const DRIVE_WEBRTC_VIDEO_READY_TIMEOUT_MS = 8000;
// connectionState=disconnected 的自愈宽限：网络瞬断（Wi-Fi 抖动）可能自行恢复，
// 宽限期内回到 connected 则不打断；超过宽限仍断开才重连。
export const DRIVE_WEBRTC_DISCONNECT_GRACE_MS = 3000;
// 页面可见、track 已就绪后，渲染帧停止超过该时长判定画面卡死
// （解码器等关键帧卡住时 connectionState 仍是 connected，只有渲染能暴露）。
export const DRIVE_WEBRTC_STALL_RECOVERY_MS = 6000;
// track muted（对端媒体包停止到达）超过该时长判定上行链路死亡并重连。
export const DRIVE_WEBRTC_MUTE_RECOVERY_MS = 6000;

interface UseDriveWebRtcVideoOptions {
  incomingSignal?: WebRtcSignal | null;
  peerConnectionFactory?: () => RTCPeerConnection;
  negotiationTimeoutMs?: number;
  retryIntervalMs?: number;
  videoReadyTimeoutMs?: number;
  disabled?: boolean;
  clientId?: string;
  carOnline?: boolean | null;
  /** connectionState=disconnected 的自愈宽限毫秒数 */
  disconnectGraceMs?: number;
  /** 渲染帧停止多久判定卡死并重连（页面可见时才生效） */
  stallRecoveryMs?: number;
  /** track muted 多久判定媒体断流并重连 */
  muteRecoveryMs?: number;
  /** 卡死看门狗轮询间隔（测试用） */
  watchdogIntervalMs?: number;
}

export interface DriveVideoMetrics {
  browserFps: number;
  p95FrameIntervalMs: number;
  /** 真实端到端时延 p50/p95（captureTime→expectedDisplayTime），无采样时为 0 */
  e2eLatencyP50Ms: number;
  e2eLatencyP95Ms: number;
  e2eSamples: number;
}

/** rVFC 采样窗口：240 帧 ≈ 4s@60fps，足够稳定的 p95 */
export const E2E_SAMPLE_WINDOW = 240;

/** 单次 e2e 采样有效性上限：超过视为异常值（时钟毛刺/标签缺失），丢弃 */
export const E2E_SAMPLE_MAX_MS = 1000;

/** p50/p95 计算：排序后取分位点（样本 <2 时返回 0） */
export const calculatePercentile = (samples: number[], ratio: number): number => {
  if (samples.length === 0) return 0;
  const sorted = [...samples].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1));
  return sorted[index] ?? 0;
};

export const getDriveWebRtcIceServers = (): RTCIceServer[] => {
  const raw = import.meta.env.VITE_DRIVE_WEBRTC_ICE_SERVERS?.trim();
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      console.warn('VITE_DRIVE_WEBRTC_ICE_SERVERS 必须是 JSON 数组');
      return [];
    }
    return parsed.filter((item) => item && typeof item === 'object') as RTCIceServer[];
  } catch (exc) {
    console.warn('解析 VITE_DRIVE_WEBRTC_ICE_SERVERS 失败', exc);
    return [];
  }
};

const EMPTY_STATS: DriveWebRtcStats = {
  active: false,
  session_id: null,
  webrtc_available: false,
  source_fps: 0,
  sent_fps: 0,
  browser_fps: 0,
  browser_p95_frame_interval_ms: 0,
  disconnect_count: 0,
  stale_frames: 0,
  peer_connection_state: null,
  ice_connection_state: null,
  ice_gathering_state: null,
  local_description_error: null,
  local_description_elapsed_ms: null,
  answer_sent_elapsed_ms: null,
  local_candidates_sent: 0,
  offer_to_answer_elapsed_ms: null,
  inbound_fps: 0,
  frames_dropped: 0,
  jitter_ms: 0,
  jitter_buffer_delay_ms: 0,
  e2e_latency_p50_ms: 0,
  e2e_latency_p95_ms: 0,
  e2e_samples: 0,
  transport: 'webrtc',
  degraded: false,
};

interface BrowserInboundStats {
  inbound_fps?: number;
  frames_dropped?: number;
  jitter_ms?: number;
  jitter_buffer_delay_ms?: number;
}

export const calculateVideoMetrics = (timestamps: number[]): DriveVideoMetrics => {
  if (timestamps.length < 2) {
    return { browserFps: 0, p95FrameIntervalMs: 0, e2eLatencyP50Ms: 0, e2eLatencyP95Ms: 0, e2eSamples: 0 };
  }
  const intervals = timestamps.slice(1).map((value, index) => value - timestamps[index]);
  const elapsed = timestamps[timestamps.length - 1] - timestamps[0];
  const sorted = [...intervals].sort((a, b) => a - b);
  const p95Index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return {
    browserFps: elapsed <= 0 ? 0 : ((timestamps.length - 1) * 1000) / elapsed,
    p95FrameIntervalMs: sorted[p95Index] ?? 0,
    e2eLatencyP50Ms: 0,
    e2eLatencyP95Ms: 0,
    e2eSamples: 0,
  };
};

const collectBrowserInboundStats = async (peer: RTCPeerConnection | null): Promise<BrowserInboundStats> => {
  if (!peer?.getStats) {
    return {};
  }
  const reports = await peer.getStats();
  for (const report of reports.values()) {
    const value = report as RTCInboundRtpStreamStats & {
      kind?: string;
      framesPerSecond?: number;
      framesDropped?: number;
      jitterBufferDelay?: number;
      jitterBufferEmittedCount?: number;
    };
    if (value.type !== 'inbound-rtp' || value.kind !== 'video') {
      continue;
    }
    const jitterBufferDelayMs = value.jitterBufferDelay !== undefined && value.jitterBufferEmittedCount
      ? (value.jitterBufferDelay / value.jitterBufferEmittedCount) * 1000
      : undefined;
    return {
      inbound_fps: value.framesPerSecond,
      frames_dropped: value.framesDropped,
      jitter_ms: value.jitter !== undefined ? value.jitter * 1000 : undefined,
      jitter_buffer_delay_ms: jitterBufferDelayMs,
    };
  }
  return {};
};

export const useDriveWebRtcVideo = (options: UseDriveWebRtcVideoOptions = {}) => {
  const {
    incomingSignal,
    peerConnectionFactory,
    negotiationTimeoutMs = DRIVE_WEBRTC_NEGOTIATION_TIMEOUT_MS,
    // retryIntervalMs is part of the public API but not yet wired internally
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    retryIntervalMs = 5000,
    videoReadyTimeoutMs = DRIVE_WEBRTC_VIDEO_READY_TIMEOUT_MS,
    disabled = false,
    clientId,
    carOnline,
    disconnectGraceMs = DRIVE_WEBRTC_DISCONNECT_GRACE_MS,
    stallRecoveryMs = DRIVE_WEBRTC_STALL_RECOVERY_MS,
    muteRecoveryMs = DRIVE_WEBRTC_MUTE_RECOVERY_MS,
    watchdogIntervalMs = 1000,
  } = options;
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const clientIdRef = useRef(clientId ?? createDriveClientId());
  const frameTimestampsRef = useRef<number[]>([]);
  const e2eSamplesRef = useRef<number[]>([]);
  const frameCallbackRef = useRef<number | null>(null);
  const lastBrowserStatsSentAtRef = useRef(0);
  const lastMetricsAtRef = useRef(0);
  const trackReceivedRef = useRef(false);
  const negotiationTimerRef = useRef<number | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const videoReadyRef = useRef(false);
  const videoReadyTimerRef = useRef<number | null>(null);
  const retryAttemptRef = useRef(0);
  const mountedRef = useRef(false);
  const attemptIdRef = useRef(0);
  const startInFlightRef = useRef(false);
  const shouldRunRef = useRef(false);
  // 中途故障恢复：最近一次渲染帧的本地时刻（rVFC 才有）、track 静音起点、
  // disconnected 自愈宽限定时器、stats 轮询镜像（被接管判定用）。
  const lastPresentationAtRef = useRef(0);
  const mutedAtRef = useRef(0);
  const disconnectTimerRef = useRef<number | null>(null);
  const statsRef = useRef<DriveWebRtcStats>(EMPTY_STATS);

  const startRef = useRef<() => void>(() => undefined);

  const [state, setState] = useState<DriveVideoState>('idle');
  const [stats, setStats] = useState<DriveWebRtcStats>(EMPTY_STATS);
  const [metrics, setMetrics] = useState<DriveVideoMetrics>(
    { browserFps: 0, p95FrameIntervalMs: 0, e2eLatencyP50Ms: 0, e2eLatencyP95Ms: 0, e2eSamples: 0 });
  const [error, setError] = useState<string | null>(null);
  const [videoReady, setVideoReady] = useState(false);

  const createPeer = useCallback(() => {
    if (peerConnectionFactory) {
      return peerConnectionFactory();
    }
    return new RTCPeerConnection({ iceServers: getDriveWebRtcIceServers() });
  }, [peerConnectionFactory]);

  const closePeer = useCallback(() => {
    if (negotiationTimerRef.current !== null) {
      window.clearTimeout(negotiationTimerRef.current);
      negotiationTimerRef.current = null;
    }
    if (videoReadyTimerRef.current !== null) {
      window.clearTimeout(videoReadyTimerRef.current);
      videoReadyTimerRef.current = null;
    }
    if (disconnectTimerRef.current !== null) {
      window.clearTimeout(disconnectTimerRef.current);
      disconnectTimerRef.current = null;
    }
    lastPresentationAtRef.current = 0;
    mutedAtRef.current = 0;
    videoReadyRef.current = false;
    if (frameCallbackRef.current !== null && videoRef.current?.cancelVideoFrameCallback) {
      videoRef.current.cancelVideoFrameCallback(frameCallbackRef.current);
      frameCallbackRef.current = null;
    }
    e2eSamplesRef.current = [];
    if (videoRef.current) {
      videoRef.current.onloadeddata = null;
    }
    peerRef.current?.close();
    peerRef.current = null;
    setVideoReady(false);
  }, []);

  const scheduleRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
    }
    const attempt = retryAttemptRef.current;
    const delay = Math.min(500 * Math.pow(2, attempt), 8000);
    retryAttemptRef.current = attempt + 1;
    retryTimerRef.current = window.setTimeout(() => {
      retryTimerRef.current = null;
      startRef.current();
    }, delay);
  }, []);

  // 中途故障恢复：WebRTC 在「传输已死/画面卡死」时 connectionState 可能长期
  // 停在 connected（issue #221 修的是首帧黑屏，这里修的是中途卡死不恢复）。
  // 恢复动作 = 关闭当前 peer 并按退避重连；若 stats 轮询发现活跃会话已换成
  // 别的客户端，说明本页签被接管，回退 MJPEG 且不再重连（避免多页签互踢拉锯）。
  const recover = useCallback((reason: string) => {
    if (!mountedRef.current) {
      return;
    }
    // 现场诊断口：卡死/断流恢复原因可在浏览器控制台回溯
    console.info(`[drive-webrtc] recover: ${reason}`);
    const polledSession = statsRef.current.session_id;
    const superseded = Boolean(
      polledSession && sessionIdRef.current && polledSession !== sessionIdRef.current,
    );
    closePeer();
    if (superseded) {
      setState('idle');
      setStats((current) => ({ ...current, degraded: true }));
      return;
    }
    setState('reconnecting');
    scheduleRetry();
  }, [closePeer, scheduleRetry]);

  const scheduleFrameStats = useCallback(() => {
    const video = videoRef.current;
    if (!video?.requestVideoFrameCallback) {
      return;
    }
    const onFrame: VideoFrameRequestCallback = (_now, metadata) => {
      lastPresentationAtRef.current = performance.now();
      frameTimestampsRef.current = [...frameTimestampsRef.current.slice(-119), metadata.presentationTime];
      // 真实端到端时延：expectedDisplayTime(呈现时刻) − captureTime(采集时刻)，
      // 两者同处浏览器时钟域（Chrome 经 RTCP SR 映射），无需跨机时钟同步。
      // captureTime 由 aiortc 的 SR NTP 映射提供，含 ≤半帧周期的 pts 量化误差。
      const captureTime = (metadata as VideoFrameCallbackMetadata & { captureTime?: number }).captureTime;
      if (captureTime !== undefined && metadata.expectedDisplayTime !== undefined) {
        const e2e = metadata.expectedDisplayTime - captureTime;
        if (e2e >= 0 && e2e <= E2E_SAMPLE_MAX_MS) {
          e2eSamplesRef.current = [...e2eSamplesRef.current.slice(-(E2E_SAMPLE_WINDOW - 1)), e2e];
        }
      }
      const nextMetrics: DriveVideoMetrics = {
        ...calculateVideoMetrics(frameTimestampsRef.current),
        e2eLatencyP50Ms: calculatePercentile(e2eSamplesRef.current, 0.5),
        e2eLatencyP95Ms: calculatePercentile(e2eSamplesRef.current, 0.95),
        e2eSamples: e2eSamplesRef.current.length,
      };
      // FPS/延迟徽标无需逐帧刷新：500ms 节流一次，避免 60fps 重渲染 VideoStream（#135）
      const now = performance.now();
      if (now - lastMetricsAtRef.current >= 500) {
        lastMetricsAtRef.current = now;
        setMetrics(nextMetrics);
      }
      const sessionId = sessionIdRef.current;
      if (sessionId && nextMetrics.browserFps > 0 && metadata.presentationTime - lastBrowserStatsSentAtRef.current >= 1000) {
        lastBrowserStatsSentAtRef.current = metadata.presentationTime;
        collectBrowserInboundStats(peerRef.current)
          .then((inboundStats) => sendDriveWebRtcBrowserStats(sessionId, {
            browser_fps: nextMetrics.browserFps,
            browser_p95_frame_interval_ms: nextMetrics.p95FrameIntervalMs,
            e2e_latency_p50_ms: nextMetrics.e2eSamples > 0 ? nextMetrics.e2eLatencyP50Ms : undefined,
            e2e_latency_p95_ms: nextMetrics.e2eSamples > 0 ? nextMetrics.e2eLatencyP95Ms : undefined,
            e2e_samples: nextMetrics.e2eSamples,
            ...inboundStats,
          }))
          .catch(() => undefined);
      }
      frameCallbackRef.current = video.requestVideoFrameCallback(onFrame);
    };
    frameCallbackRef.current = video.requestVideoFrameCallback(onFrame);
  }, []);

  const start = useCallback(async () => {
    if (startInFlightRef.current) {
      return;
    }
    const attemptId = ++attemptIdRef.current;
    startInFlightRef.current = true;
    const isCurrentAttempt = () => mountedRef.current && attemptId === attemptIdRef.current;
    if (disabled) {
      startInFlightRef.current = false;
      setState('degraded');
      setStats((current) => ({ ...current, degraded: true }));
      return;
    }
    if (typeof RTCPeerConnection === 'undefined' && !peerConnectionFactory) {
      startInFlightRef.current = false;
      setState('degraded');
      setStats((current) => ({ ...current, degraded: true }));
      return;
    }

    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    // 重入前先关掉旧 peer：carOnline 抖动等路径会带旧连接再次 start()，
    // 旧 peer 不关会在后台维持 ICE/DTLS（泄漏）并占用视频元素流
    closePeer();
    setState('connecting');
    trackReceivedRef.current = false;
    try {
      const session = await createDriveWebRtcSession(clientIdRef.current);
      if (!isCurrentAttempt()) {
        startInFlightRef.current = false;
        return;
      }
      sessionIdRef.current = session.session_id;
      const peer = createPeer();
      if (!isCurrentAttempt()) {
        peer.close();
        startInFlightRef.current = false;
        return;
      }
      peerRef.current = peer;

      peer.addTransceiver?.('video', { direction: 'recvonly' });
      peer.onicecandidate = (event) => {
        if (!isCurrentAttempt()) return;
        if (event.candidate && sessionIdRef.current) {
          sendDriveWebRtcIce(sessionIdRef.current, event.candidate.toJSON()).catch(() => undefined);
        }
      };
      // 连接状态监控：Wi-Fi 抖动/锁屏/会话被其他页签抢占后，媒体路径死亡
      // 但没有任何信令通知本页——必须自己盯 connectionState 触发恢复。
      peer.onconnectionstatechange = () => {
        if (!isCurrentAttempt() || peerRef.current !== peer) return;
        const connectionState = peer.connectionState;
        if (connectionState === 'failed' || connectionState === 'closed') {
          recover(`connectionState=${connectionState}`);
        } else if (connectionState === 'disconnected') {
          if (disconnectTimerRef.current === null) {
            disconnectTimerRef.current = window.setTimeout(() => {
              disconnectTimerRef.current = null;
              if (peerRef.current === peer && peer.connectionState === 'disconnected') {
                recover('connectionState=disconnected');
              }
            }, disconnectGraceMs);
          }
        } else if (connectionState === 'connected' && disconnectTimerRef.current !== null) {
          window.clearTimeout(disconnectTimerRef.current);
          disconnectTimerRef.current = null;
        }
      };
      peer.ontrack = (event) => {
        if (!isCurrentAttempt()) return;
        const receiver = event.receiver as RTCRtpReceiver & {
          playoutDelayHint?: number;
          jitterBufferTarget?: number | null;
        };
        // 双通道压低接收端缓冲：playoutDelayHint 是旧 API（Chrome 可能忽略），
        // jitterBufferTarget=0 是标准替代；目标 = 帧到即播，最小化抖动缓冲时延
        if ('playoutDelayHint' in receiver) {
          receiver.playoutDelayHint = 0;
        }
        if ('jitterBufferTarget' in receiver) {
          try {
            receiver.jitterBufferTarget = 0;
          } catch {
            // 部分实现仅接受 null/有限正值，设置失败按原值运行
          }
        }
        trackReceivedRef.current = true;
        retryAttemptRef.current = 0;
        // track 静音 = 对端媒体包停止到达（车端编码器停摆/上行链路死亡），
        // 由看门狗在 muteRecoveryMs 后判定恢复；恢复到帧则取消。
        event.track.onmute = () => {
          mutedAtRef.current = Date.now();
        };
        event.track.onunmute = () => {
          mutedAtRef.current = 0;
        };
        if (negotiationTimerRef.current !== null) {
          window.clearTimeout(negotiationTimerRef.current);
          negotiationTimerRef.current = null;
        }
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
          videoRef.current.onloadeddata = () => {
            videoReadyRef.current = true;
            if (videoReadyTimerRef.current !== null) {
              window.clearTimeout(videoReadyTimerRef.current);
              videoReadyTimerRef.current = null;
            }
            if (mountedRef.current) {
              setVideoReady(true);
            }
          };
          scheduleFrameStats();
        }
        // 收到 track 但首帧迟迟不解码时，超时降级重试，避免黑屏且遮罩卡死
        videoReadyTimerRef.current = window.setTimeout(() => {
          if (!videoReadyRef.current) {
            setState('degraded');
            setStats((current) => ({ ...current, degraded: true }));
            closePeer();
            scheduleRetry();
          }
        }, videoReadyTimeoutMs);
        setState('connected');
      };

      const offer = await peer.createOffer();
      if (!isCurrentAttempt()) {
        peer.close();
        startInFlightRef.current = false;
        return;
      }
      await peer.setLocalDescription(offer);
      if (!isCurrentAttempt()) {
        peer.close();
        startInFlightRef.current = false;
        return;
      }
      await sendDriveWebRtcOffer(session.session_id, peer.localDescription?.sdp ?? offer.sdp ?? '');
      if (!isCurrentAttempt()) {
        startInFlightRef.current = false;
        return;
      }
      negotiationTimerRef.current = window.setTimeout(() => {
        if (!trackReceivedRef.current) {
          setState('degraded');
          setStats((current) => ({ ...current, degraded: true }));
          closePeer();
          scheduleRetry();
        }
      }, negotiationTimeoutMs);
      setStats((current) => ({ ...current, active: true, session_id: session.session_id, webrtc_available: true }));
      startInFlightRef.current = false;
    } catch (exc) {
      if (!isCurrentAttempt()) {
        startInFlightRef.current = false;
        return;
      }
      setError(exc instanceof Error ? exc.message : t('driveHooks.webRtcConnectFailed'));
      setState('degraded');
      setStats((current) => ({ ...current, degraded: true }));
      closePeer();
      scheduleRetry();
      startInFlightRef.current = false;
    }
  }, [closePeer, createPeer, disconnectGraceMs, disabled, negotiationTimeoutMs, peerConnectionFactory, recover, scheduleFrameStats, scheduleRetry, t, videoReadyTimeoutMs]);

  useEffect(() => {
    startRef.current = start;
  }, [start]);

  // 挂载/卸载生命周期：只负责 mountedRef 与最终清理，不随 carOnline 变化重建
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      attemptIdRef.current += 1;
      startInFlightRef.current = false;
      shouldRunRef.current = false;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      closePeer();
    };
  }, [closePeer]);

  // carOnline 门控：null 视为未知→乐观启动；false 停止；true 启动。
  // 只在「应运行」状态真正翻转时才 start/stop，避免 null→true 触发整体重启竞态。
  useEffect(() => {
    const shouldRun = carOnline !== false;
    if (shouldRun && !shouldRunRef.current) {
      start();
    } else if (!shouldRun && shouldRunRef.current) {
      attemptIdRef.current += 1;
      startInFlightRef.current = false;
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      closePeer();
    }
    shouldRunRef.current = shouldRun;
  }, [carOnline, closePeer, start]);

  useEffect(() => {
    if (!incomingSignal || incomingSignal.session_id !== sessionIdRef.current || !peerRef.current) {
      return;
    }
    if (incomingSignal.signal_type === 'answer' && incomingSignal.sdp) {
      peerRef.current.setRemoteDescription({ type: 'answer', sdp: incomingSignal.sdp }).catch((exc) => {
        setError(exc instanceof Error ? exc.message : t('driveHooks.setAnswerFailed'));
        setState('error');
      });
    }
    if (incomingSignal.signal_type === 'ice' && incomingSignal.candidate) {
      peerRef.current.addIceCandidate(incomingSignal.candidate).catch((exc) => {
        setError(exc instanceof Error ? exc.message : t('driveHooks.addIceCandidateFailed'));
        setState('error');
      });
    }
  }, [incomingSignal, t]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      getDriveWebRtcStats()
        .then(setStats)
        .catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  // stats 镜像到 ref：recover/看门狗里读最新轮询结果做「被接管」判定，
  // 不经过 state 闭包（避免陈旧 session_id 误判）。
  useEffect(() => {
    statsRef.current = stats;
  }, [stats]);

  // 中途卡死看门狗：只在页面可见且已成功出画后工作。
  // - track muted 超时：对端媒体包停止到达（车端停摆/链路单通）；
  // - 渲染帧停止超时：传输看似正常但解码卡住（等关键帧等不到）。
  // 后台标签 rVFC 不触发、track 可能静音，属于正常现象，必须跳过。
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (!trackReceivedRef.current || !videoReadyRef.current) return;
      const peer = peerRef.current;
      if (!peer || peer.connectionState !== 'connected') return;
      if (mutedAtRef.current > 0 && Date.now() - mutedAtRef.current >= muteRecoveryMs) {
        recover('track muted');
        return;
      }
      if (
        lastPresentationAtRef.current > 0
        && performance.now() - lastPresentationAtRef.current >= stallRecoveryMs
      ) {
        recover('render stall');
      }
    }, watchdogIntervalMs);
    return () => window.clearInterval(timer);
  }, [muteRecoveryMs, recover, stallRecoveryMs, watchdogIntervalMs]);

  // 回到前台时重置渲染/静音时钟：后台期间 rVFC 停止是正常现象，
  // 不重置的话切回页面的第一秒会被看门狗误判为卡死。
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        lastPresentationAtRef.current = performance.now();
        mutedAtRef.current = 0;
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => document.removeEventListener('visibilitychange', onVisibilityChange);
  }, []);

  return useMemo(() => ({
    videoRef,
    state,
    stats,
    metrics,
    error,
    videoReady,
    sessionId: sessionIdRef.current,
    reconnect: start,
  }), [error, metrics, start, state, stats, videoReady]);
};
