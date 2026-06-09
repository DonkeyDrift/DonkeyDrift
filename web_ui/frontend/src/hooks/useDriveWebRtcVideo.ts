import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createDriveWebRtcSession,
  getDriveWebRtcStats,
  sendDriveWebRtcIce,
  sendDriveWebRtcOffer,
  type DriveWebRtcStats,
} from '../services/api';
import type { WebRtcSignal } from './useDriveWebsocket';

export type DriveVideoState = 'idle' | 'connecting' | 'connected' | 'unstable' | 'reconnecting' | 'degraded' | 'error';

interface UseDriveWebRtcVideoOptions {
  incomingSignal?: WebRtcSignal | null;
  peerConnectionFactory?: () => RTCPeerConnection;
}

export interface DriveVideoMetrics {
  browserFps: number;
  p95FrameIntervalMs: number;
}

const EMPTY_STATS: DriveWebRtcStats = {
  active: false,
  session_id: null,
  webrtc_available: false,
  source_fps: 0,
  sent_fps: 0,
  browser_fps: 0,
  browser_p95_frame_interval_ms: 0,
  disconnect_count: 0,
  transport: 'webrtc',
  degraded: false,
};

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

export const useDriveWebRtcVideo = (options: UseDriveWebRtcVideoOptions = {}) => {
  const { incomingSignal, peerConnectionFactory } = options;
  const videoRef = useRef<HTMLVideoElement>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const frameTimestampsRef = useRef<number[]>([]);
  const frameCallbackRef = useRef<number | null>(null);

  const [state, setState] = useState<DriveVideoState>('idle');
  const [stats, setStats] = useState<DriveWebRtcStats>(EMPTY_STATS);
  const [metrics, setMetrics] = useState<DriveVideoMetrics>({ browserFps: 0, p95FrameIntervalMs: 0 });
  const [error, setError] = useState<string | null>(null);

  const createPeer = useCallback(() => {
    if (peerConnectionFactory) {
      return peerConnectionFactory();
    }
    return new RTCPeerConnection();
  }, [peerConnectionFactory]);

  const closePeer = useCallback(() => {
    if (frameCallbackRef.current !== null && videoRef.current?.cancelVideoFrameCallback) {
      videoRef.current.cancelVideoFrameCallback(frameCallbackRef.current);
      frameCallbackRef.current = null;
    }
    peerRef.current?.close();
    peerRef.current = null;
  }, []);

  const scheduleFrameStats = useCallback(() => {
    const video = videoRef.current;
    if (!video?.requestVideoFrameCallback) {
      return;
    }
    const onFrame: VideoFrameRequestCallback = (_now, metadata) => {
      frameTimestampsRef.current = [...frameTimestampsRef.current.slice(-119), metadata.presentationTime];
      setMetrics(calculateVideoMetrics(frameTimestampsRef.current));
      frameCallbackRef.current = video.requestVideoFrameCallback(onFrame);
    };
    frameCallbackRef.current = video.requestVideoFrameCallback(onFrame);
  }, []);

  const start = useCallback(async () => {
    if (typeof RTCPeerConnection === 'undefined' && !peerConnectionFactory) {
      setState('degraded');
      setStats((current) => ({ ...current, degraded: true }));
      return;
    }

    setState('connecting');
    try {
      const session = await createDriveWebRtcSession();
      sessionIdRef.current = session.session_id;
      const peer = createPeer();
      peerRef.current = peer;

      peer.addTransceiver?.('video', { direction: 'recvonly' });
      peer.onicecandidate = (event) => {
        if (event.candidate && sessionIdRef.current) {
          sendDriveWebRtcIce(sessionIdRef.current, event.candidate.toJSON()).catch(() => undefined);
        }
      };
      peer.ontrack = (event) => {
        if (videoRef.current) {
          videoRef.current.srcObject = event.streams[0] ?? new MediaStream([event.track]);
          scheduleFrameStats();
        }
        setState('connected');
      };

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await sendDriveWebRtcOffer(session.session_id, offer.sdp ?? '');
      setStats((current) => ({ ...current, active: true, session_id: session.session_id, webrtc_available: true }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'WebRTC 视频连接失败');
      setState('degraded');
      setStats((current) => ({ ...current, degraded: true }));
      closePeer();
    }
  }, [closePeer, createPeer, peerConnectionFactory, scheduleFrameStats]);

  useEffect(() => {
    start();
    return () => closePeer();
  }, [closePeer, start]);

  useEffect(() => {
    if (!incomingSignal || incomingSignal.session_id !== sessionIdRef.current || !peerRef.current) {
      return;
    }
    if (incomingSignal.signal_type === 'answer' && incomingSignal.sdp) {
      peerRef.current.setRemoteDescription({ type: 'answer', sdp: incomingSignal.sdp }).catch((exc) => {
        setError(exc instanceof Error ? exc.message : '设置 WebRTC answer 失败');
        setState('error');
      });
    }
    if (incomingSignal.signal_type === 'ice' && incomingSignal.candidate) {
      peerRef.current.addIceCandidate(incomingSignal.candidate).catch((exc) => {
        setError(exc instanceof Error ? exc.message : '添加 ICE candidate 失败');
        setState('error');
      });
    }
  }, [incomingSignal]);

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
    sessionId: sessionIdRef.current,
    reconnect: start,
  }), [error, metrics, start, state, stats]);
};
