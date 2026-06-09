import React, { useEffect, useState, useRef } from 'react';
import { API_URL } from '../../services/api';
import { Wifi, WifiOff } from 'lucide-react';
import { useDriveWebRtcVideo } from '../../hooks/useDriveWebRtcVideo';
import type { WebRtcSignal } from '../../hooks/useDriveWebsocket';

interface VideoStreamProps {
  className?: string;
  incomingSignal?: WebRtcSignal | null;
}

export const VideoStream: React.FC<VideoStreamProps> = ({ className = '', incomingSignal = null }) => {
  const [status, setStatus] = useState<'loading' | 'connected' | 'error'>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [mjpegFps, setMjpegFps] = useState(0);
  const imgRef = useRef<HTMLImageElement>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { videoRef, state, stats, metrics } = useDriveWebRtcVideo({ incomingSignal });

  const streamUrl = `${API_URL}/drive/video`;
  const degraded = state === 'degraded' || stats.degraded;
  const browserFps = Math.round(metrics.browserFps || stats.browser_fps || 0);
  const p95 = Math.round(metrics.p95FrameIntervalMs || stats.browser_p95_frame_interval_ms || 0);
  const sourceFps = Math.round(stats.source_fps || 0);
  const sentFps = Math.round(stats.sent_fps || 0);

  const resetRetry = () => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  };

  const scheduleRetry = () => {
    resetRetry();
    retryTimerRef.current = setTimeout(() => {
      setRetryCount((c) => c + 1);
    }, 2000);
  };

  useEffect(() => {
    setStatus('loading');
    return () => resetRetry();
  }, [retryCount]);

  useEffect(() => {
    if (!degraded) {
      return;
    }
    let mounted = true;
    const loadStats = async () => {
      try {
        const response = await fetch(`${API_URL}/drive/stats`);
        const data = await response.json();
        if (mounted) {
          setMjpegFps(Number(data.fps) || 0);
        }
      } catch {
        if (mounted) {
          setMjpegFps(0);
        }
      }
    };

    loadStats();
    const timer = setInterval(loadStats, 1000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [degraded]);

  const statusBadge = (() => {
    if (!degraded) {
      return (
        <span className="inline-flex items-center gap-1 text-xs text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded">
          <Wifi className="w-3 h-3" />
          WebRTC
        </span>
      );
    }
    switch (status) {
      case 'connected':
        return (
          <span className="inline-flex items-center gap-1 text-xs text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded">
            <Wifi className="w-3 h-3" />
            MJPEG 降级
          </span>
        );
      case 'loading':
        return (
          <span className="inline-flex items-center gap-1 text-xs text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded">
            <Wifi className="w-3 h-3 animate-pulse" />
            Connecting...
          </span>
        );
      case 'error':
      default:
        return (
          <span className="inline-flex items-center gap-1 text-xs text-red-400 bg-red-400/10 px-2 py-0.5 rounded">
            <WifiOff className="w-3 h-3" />
            Disconnected
          </span>
        );
    }
  })();

  return (
    <div className={`relative bg-zinc-950 border border-zinc-800 rounded-lg overflow-hidden ${className}`}>
      <div className="absolute top-2 left-2 z-10 flex items-center gap-2">
        {statusBadge}
        {degraded && (
          <span className="rounded bg-amber-400/10 px-2 py-0.5 text-xs text-amber-300">
            非 60FPS 验收路径
          </span>
        )}
      </div>
      <div className="absolute right-2 top-2 z-10 rounded-md border border-white/10 bg-zinc-900/35 px-2 py-1 text-center shadow-[0_8px_24px_rgba(0,0,0,0.25)] backdrop-blur-md">
        <div className="text-[10px] text-zinc-400 uppercase leading-none">FPS</div>
        <div className="text-base font-mono leading-tight text-cyan-400">{degraded ? mjpegFps : browserFps}</div>
        {!degraded && (
          <div className="mt-1 flex gap-2 text-[10px] text-zinc-400">
            <span>P95 {p95}ms</span>
            <span>源 {sourceFps}</span>
            <span>发 {sentFps}</span>
          </div>
        )}
      </div>
      {degraded ? (
        <img
          key={retryCount}
          ref={imgRef}
          src={streamUrl}
          alt="Camera feed"
          onLoad={() => setStatus('connected')}
          onError={() => {
            setStatus('error');
            scheduleRetry();
          }}
          className="w-full h-auto object-contain min-h-[360px]"
        />
      ) : (
        <video
          ref={videoRef}
          aria-label="WebRTC camera feed"
          autoPlay
          playsInline
          muted
          className="w-full h-auto object-contain min-h-[360px]"
        />
      )}
      {degraded && status !== 'connected' && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/80 pointer-events-none">
          <div className="text-center text-zinc-500 text-sm">
            {status === 'loading' ? '正在连接摄像头...' : '摄像头未连接'}
          </div>
        </div>
      )}
    </div>
  );
};
