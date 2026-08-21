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

interface UseDriveWebRtcVideoOptions {
  incomingSignal?: WebRtcSignal | null;
  peerConnectionFactory?: () => RTCPeerConnection;
  negotiationTimeoutMs?: number;
  retryIntervalMs?: number;
  videoReadyTimeoutMs?: number;
  disabled?: boolean;
  clientId?: string;
  carOnline?: boolean | null;
}

export interface DriveVideoMetrics {
  browserFps: number;
  p95FrameIntervalMs: number;
}

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
    return { browserFps: 0, p95FrameIntervalMs: 0 };
  }
  const intervals = timestamps.slice(1).map((value, index) => value - timestamps[index]);
  const elapsed = timestamps[timestamps.length - 1] - timestamps[0];
  const sorted = [...intervals].sort((a, b) => a - b);
  const p95Index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return {
    browserFps: elapsed <= 0 ? 0 : ((timestamps.length - 1) * 1000) / elapsed,
    p95FrameIntervalMs: sorted[p95Index] ?? 0,
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
  } = options;
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const clientIdRef = useRef(clientId ?? createDriveClientId());
  const frameTimestampsRef = useRef<number[]>([]);
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

  const startRef = useRef<() => void>(() => undefined);

  const [state, setState] = useState<DriveVideoState>('idle');
  const [stats, setStats] = useState<DriveWebRtcStats>(EMPTY_STATS);
  const [metrics, setMetrics] = useState<DriveVideoMetrics>({ browserFps: 0, p95FrameIntervalMs: 0 });
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
    videoReadyRef.current = false;
    if (frameCallbackRef.current !== null && videoRef.current?.cancelVideoFrameCallback) {
      videoRef.current.cancelVideoFrameCallback(frameCallbackRef.current);
      frameCallbackRef.current = null;
    }
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

  const scheduleFrameStats = useCallback(() => {
    const video = videoRef.current;
    if (!video?.requestVideoFrameCallback) {
      return;
    }
    const onFrame: VideoFrameRequestCallback = (_now, metadata) => {
      frameTimestampsRef.current = [...frameTimestampsRef.current.slice(-119), metadata.presentationTime];
      const nextMetrics = calculateVideoMetrics(frameTimestampsRef.current);
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
      peer.ontrack = (event) => {
        if (!isCurrentAttempt()) return;
        const receiver = event.receiver as RTCRtpReceiver & { playoutDelayHint?: number };
        if ('playoutDelayHint' in receiver) {
          receiver.playoutDelayHint = 0;
        }
        trackReceivedRef.current = true;
        retryAttemptRef.current = 0;
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
  }, [closePeer, createPeer, disabled, negotiationTimeoutMs, peerConnectionFactory, scheduleFrameStats, t, videoReadyTimeoutMs]);

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
