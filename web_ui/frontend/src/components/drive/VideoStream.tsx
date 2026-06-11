import React, { useEffect, useState, useRef } from 'react';
import { API_URL, getDriveVideoTransport, type DriveVideoTransport } from '../../services/api';
import { Wifi, WifiOff } from 'lucide-react';
import { useDriveWebRtcVideo } from '../../hooks/useDriveWebRtcVideo';
import type { WebRtcSignal } from '../../hooks/useDriveWebsocket';

export const DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS = 3000;

interface VideoStreamProps {
  className?: string;
  incomingSignal?: WebRtcSignal | null;
  transport?: DriveVideoTransport;
  clientId?: string;
  onLatencyChange?: (latencyMs: number) => void;
}

export const VideoStream: React.FC<VideoStreamProps> = ({ className = '', incomingSignal = null, transport, clientId, onLatencyChange }) => {
  const [status, setStatus] = useState<'loading' | 'connected' | 'error'>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [mjpegFps, setMjpegFps] = useState(0);
  const [carOnline, setCarOnline] = useState<boolean | null>(null);
  const [mjpegFallbackAllowed, setMjpegFallbackAllowed] = useState(false);
  const [aspectRatio, setAspectRatio] = useState<string>('16/9');
  const imgRef = useRef<HTMLImageElement>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mjpegFadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevWebRtcVisibleRef = useRef(false);
  const selectedTransport = transport ?? getDriveVideoTransport();
  const forceMjpeg = selectedTransport === 'mjpeg';
  const { videoRef, state, stats, metrics, videoReady } = useDriveWebRtcVideo({ incomingSignal, disabled: forceMjpeg, clientId, carOnline: carOnline ?? false });

  const streamUrl = `${API_URL}/drive/video`;
  const webRtcConnected = state === 'connected' && !stats.degraded;
  const webRtcVisible = webRtcConnected && videoReady;
  const degraded = forceMjpeg || mjpegFallbackAllowed;
  const [mjpegVisible, setMjpegVisible] = useState(!webRtcVisible);
  const browserFps = Math.round(metrics.browserFps || stats.browser_fps || 0);
  const latencyMs = Math.round(metrics.p95FrameIntervalMs || stats.browser_p95_frame_interval_ms || 0);

  const resetRetry = () => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  };

  const resetFallbackTimer = () => {
    if (fallbackTimerRef.current) {
      clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
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
    if (forceMjpeg) {
      resetFallbackTimer();
      return;
    }
    if (webRtcConnected) {
      resetFallbackTimer();
      setMjpegFallbackAllowed(false);
      return;
    }
    if (!fallbackTimerRef.current) {
      fallbackTimerRef.current = setTimeout(() => {
        fallbackTimerRef.current = null;
        setMjpegFallbackAllowed(true);
      }, DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS);
    }
    return () => undefined;
  }, [forceMjpeg, webRtcConnected]);

  useEffect(() => resetFallbackTimer, []);

  // 动态根据实际 WebRTC 视频画面调整容器宽高比
  useEffect(() => {
    if (!webRtcVisible) return;
    const video = videoRef.current;
    if (!video) return;
    const updateRatio = () => {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        setAspectRatio(`${video.videoWidth}/${video.videoHeight}`);
      }
    };
    if (video.readyState >= 1) {
      updateRatio();
    } else {
      video.addEventListener('loadedmetadata', updateRatio, { once: true });
    }
  }, [webRtcVisible]);

  useEffect(() => {
    const wasVisible = prevWebRtcVisibleRef.current;
    if (webRtcVisible && !wasVisible) {
      // WebRTC 刚连上：等它完全渐入（500ms）后再淡出 MJPEG，避免中间 Gap 闪烁
      mjpegFadeTimerRef.current = setTimeout(() => {
        setMjpegVisible(false);
      }, 500);
    } else if (!webRtcVisible) {
      if (mjpegFadeTimerRef.current) {
        clearTimeout(mjpegFadeTimerRef.current);
        mjpegFadeTimerRef.current = null;
      }
      setMjpegVisible(true);
    }
    prevWebRtcVisibleRef.current = webRtcVisible;
    return () => {
      if (mjpegFadeTimerRef.current) {
        clearTimeout(mjpegFadeTimerRef.current);
        mjpegFadeTimerRef.current = null;
      }
    };
  }, [webRtcVisible]);

  useEffect(() => {
    const wasVisible = prevWebRtcVisibleRef.current;
    if (webRtcVisible && !wasVisible) {
      // WebRTC 刚连上：等它完全渐入（500ms）后再淡出 MJPEG，避免中间 Gap 闪烁
      mjpegFadeTimerRef.current = setTimeout(() => {
        setMjpegVisible(false);
      }, 500);
    } else if (!webRtcVisible) {
      if (mjpegFadeTimerRef.current) {
        clearTimeout(mjpegFadeTimerRef.current);
        mjpegFadeTimerRef.current = null;
      }
      setMjpegVisible(true);
    }
    prevWebRtcVisibleRef.current = webRtcVisible;
    return () => {
      if (mjpegFadeTimerRef.current) {
        clearTimeout(mjpegFadeTimerRef.current);
        mjpegFadeTimerRef.current = null;
      }
    };
  }, [webRtcVisible]);

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
          setCarOnline(Boolean(data.online));
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

  useEffect(() => {
    onLatencyChange?.(latencyMs);
  }, [latencyMs, onLatencyChange]);

  const statusMeta = (() => {
    if (forceMjpeg) {
      return { icon: Wifi, text: 'MJPEG', color: 'text-amber-400', pulse: false };
    }
    if (webRtcConnected) {
      return { icon: Wifi, text: 'WebRTC', color: 'text-emerald-400', pulse: false };
    }
    if (!degraded) {
      return { icon: Wifi, text: 'Connecting...', color: 'text-zinc-400', pulse: true };
    }
    switch (status) {
      case 'connected':
        return { icon: Wifi, text: 'MJPEG 降级', color: 'text-amber-400', pulse: false };
      case 'loading':
        return { icon: Wifi, text: 'Connecting...', color: 'text-zinc-400', pulse: true };
      case 'error':
      default:
        return { icon: WifiOff, text: 'Disconnected', color: 'text-red-400', pulse: false };
    }
  })();
  const StatusIcon = statusMeta.icon;

  return (
    <div className={`relative bg-zinc-950 border border-zinc-800 rounded-lg overflow-hidden ${className}`} style={{ aspectRatio }}>
      <div className="absolute top-2 left-2 z-30 flex items-start gap-2">
        <div className="rounded-md border border-white/10 bg-zinc-900/35 px-2 py-1 text-center shadow-[0_8px_24px_rgba(0,0,0,0.25)] backdrop-blur-md min-w-[4.5rem]">
          <div className={`text-[10px] leading-none flex items-center justify-center gap-1 ${statusMeta.color}`}>
            <StatusIcon className={`w-3 h-3 ${statusMeta.pulse ? 'animate-pulse' : ''}`} />
            {statusMeta.text}
          </div>
          <div className="text-base font-mono leading-tight text-cyan-400">{latencyMs > 0 ? `${latencyMs}ms` : '-'}</div>
        </div>
        {degraded && (
          <span className="rounded bg-amber-400/10 px-2 py-0.5 text-xs text-amber-300">
            非 60FPS 验收路径
          </span>
        )}
      </div>
      <div className="absolute right-2 top-2 z-30 rounded-md border border-white/10 bg-zinc-900/35 px-2 py-1 text-center shadow-[0_8px_24px_rgba(0,0,0,0.25)] backdrop-blur-md">
        <div className="text-[10px] text-zinc-400 uppercase leading-none">FPS</div>
        <div className="text-base font-mono leading-tight text-cyan-400">{webRtcConnected ? browserFps : mjpegFps}</div>
      </div>
      {/* MJPEG 层：始终预加载，WebRTC 完全显示后才淡出，避免中间 Gap 闪烁 */}
      <img
        key={retryCount}
        ref={imgRef}
        src={streamUrl}
        alt="Camera feed"
        onLoad={() => {
          setStatus('connected');
          if (imgRef.current && imgRef.current.naturalWidth > 0 && imgRef.current.naturalHeight > 0) {
            setAspectRatio(`${imgRef.current.naturalWidth}/${imgRef.current.naturalHeight}`);
          }
        }}
        onError={() => {
          setStatus('error');
          scheduleRetry();
        }}
        className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-500 ${mjpegVisible ? 'opacity-100' : 'opacity-0'}`}
      />
      {/* WebRTC 层：覆盖在 MJPEG 上方，首帧就绪后先渐入，完全显示后 MJPEG 再淡出 */}
      {!forceMjpeg && (
        <video
          ref={videoRef}
          aria-label="WebRTC camera feed"
          autoPlay
          playsInline
          muted
          className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-500 ${
            webRtcVisible ? 'opacity-100 z-10' : 'opacity-0 pointer-events-none'
          }`}
        />
      )}
      {!webRtcVisible && status !== 'connected' && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/80 pointer-events-none z-20">
          <div className="text-center text-zinc-500 text-sm">
            {carOnline === false
              ? '车端离线：等待 DriveApiBridge 连接到 /api/drive/ws?role=car'
              : status === 'loading' ? '正在连接摄像头...' : '摄像头未连接'}
          </div>
        </div>
      )}
    </div>
  );
};
