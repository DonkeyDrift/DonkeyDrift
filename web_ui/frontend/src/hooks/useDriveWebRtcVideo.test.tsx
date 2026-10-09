import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getDriveWebRtcIceServers, useDriveWebRtcVideo } from './useDriveWebRtcVideo';
import type { WebRtcSignal } from './useDriveWebsocket';
// 印章夹具由 Python 参考实现生成：ts = 车端捕获时刻（秒），rgba = 240×24 采样区
import fixture from '../utils/__fixtures__/frameStamp.json';

vi.mock('../services/api', () => ({
  API_URL: '/api',
  createDriveClientId: vi.fn(() => 'client-1'),
  createDriveWebRtcSession: vi.fn(async () => ({ session_id: 'session-1' })),
  sendDriveWebRtcOffer: vi.fn(async () => ({ success: true })),
  sendDriveWebRtcIce: vi.fn(async () => ({ success: true })),
  sendDriveWebRtcBrowserStats: vi.fn(async () => ({ success: true })),
  getDriveWebRtcStats: vi.fn(async () => ({
    source_fps: 60,
    sent_fps: 60,
    browser_fps: 0,
    browser_p95_frame_interval_ms: 0,
    degraded: false,
  })),
}));

class FakePeerConnection {
  localDescription: RTCSessionDescriptionInit | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  candidates: RTCIceCandidateInit[] = [];
  closed = false;
  connectionState: RTCPeerConnectionState = 'new';
  ontrack: ((event: RTCTrackEvent) => void) | null = null;
  onicecandidate: ((event: RTCPeerConnectionIceEvent) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  statsReports: unknown[] = [];

  addTransceiver = vi.fn();

  async createOffer() {
    return { type: 'offer' as RTCSdpType, sdp: 'offer-sdp' };
  }

  async setLocalDescription(description: RTCSessionDescriptionInit) {
    this.localDescription = description;
  }

  async setRemoteDescription(description: RTCSessionDescriptionInit) {
    this.remoteDescription = description;
  }

  async addIceCandidate(candidate: RTCIceCandidateInit) {
    this.candidates.push(candidate);
  }

  async getStats() {
    return new Map(this.statsReports.map((report, index) => [String(index), report]));
  }

  close() {
    this.closed = true;
  }
}

const HookProbe: React.FC<{
  signal?: WebRtcSignal | null;
  onState: (value: ReturnType<typeof useDriveWebRtcVideo>) => void;
  factory?: () => RTCPeerConnection;
  negotiationTimeoutMs?: number;
  retryIntervalMs?: number;
  videoReadyTimeoutMs?: number;
  disconnectGraceMs?: number;
  stallRecoveryMs?: number;
  muteRecoveryMs?: number;
  watchdogIntervalMs?: number;
}> = ({
  signal,
  onState,
  factory,
  negotiationTimeoutMs,
  retryIntervalMs,
  videoReadyTimeoutMs,
  disconnectGraceMs,
  stallRecoveryMs,
  muteRecoveryMs,
  watchdogIntervalMs,
}) => {
  const state = useDriveWebRtcVideo({
    incomingSignal: signal,
    peerConnectionFactory: factory,
    negotiationTimeoutMs,
    retryIntervalMs,
    videoReadyTimeoutMs,
    disconnectGraceMs,
    stallRecoveryMs,
    muteRecoveryMs,
    watchdogIntervalMs,
  });
  onState(state);
  return <video ref={state.videoRef} />;
};

const lastCallValue = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.at(-1)?.[0];

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('getDriveWebRtcIceServers', () => {
  it('未配置时返回空数组', () => {
    vi.stubEnv('VITE_DRIVE_WEBRTC_ICE_SERVERS', '');

    expect(getDriveWebRtcIceServers()).toEqual([]);
  });

  it('解析有效 TURN JSON 配置', () => {
    vi.stubEnv('VITE_DRIVE_WEBRTC_ICE_SERVERS', '[{"urls":["turn:192.168.3.96:3478?transport=udp"],"username":"donkey","credential":"secret"}]');

    expect(getDriveWebRtcIceServers()).toEqual([
      { urls: ['turn:192.168.3.96:3478?transport=udp'], username: 'donkey', credential: 'secret' },
    ]);
  });

  it('非法 JSON 返回空数组', () => {
    vi.stubEnv('VITE_DRIVE_WEBRTC_ICE_SERVERS', 'not-json');

    expect(getDriveWebRtcIceServers()).toEqual([]);
  });

  it('顶层非数组返回空数组', () => {
    vi.stubEnv('VITE_DRIVE_WEBRTC_ICE_SERVERS', '{"urls":"turn:host"}');

    expect(getDriveWebRtcIceServers()).toEqual([]);
  });
});

describe('useDriveWebRtcVideo', () => {
  it('浏览器不支持 RTCPeerConnection 时降级', async () => {
    vi.stubGlobal('RTCPeerConnection', undefined);
    const onState = vi.fn();

    render(<HookProbe onState={onState} />);

    await waitFor(() => {
      expect(lastCallValue(onState).state).toBe('degraded');
    });
  });

  it('创建 WebRTC session 并优先发送 localDescription 中的 offer', async () => {
    const api = await import('../services/api');
    class LocalDescriptionPeerConnection extends FakePeerConnection {
      async setLocalDescription(description: RTCSessionDescriptionInit) {
        await super.setLocalDescription(description);
        this.localDescription = { type: 'offer', sdp: 'local-offer-sdp' };
      }
    }
    const pc = new LocalDescriptionPeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} />);

    await waitFor(() => {
      expect(api.createDriveWebRtcSession).toHaveBeenCalled();
      expect(api.sendDriveWebRtcOffer).toHaveBeenCalledWith('session-1', 'local-offer-sdp');
      expect(pc.localDescription?.sdp).toBe('local-offer-sdp');
    });
  });

  it('默认 RTCPeerConnection 注入 ICE servers 配置', async () => {
    vi.stubEnv('VITE_DRIVE_WEBRTC_ICE_SERVERS', '[{"urls":["turn:192.168.3.96:3478?transport=udp"],"username":"donkey","credential":"secret"}]');
    const configs: RTCConfiguration[] = [];
    class RecordingPeerConnection extends FakePeerConnection {
      constructor(config?: RTCConfiguration) {
        super();
        configs.push(config ?? {});
      }
    }
    vi.stubGlobal('RTCPeerConnection', RecordingPeerConnection);
    const onState = vi.fn();

    render(<HookProbe onState={onState} />);

    await waitFor(() => expect(configs[0]).toEqual({
      iceServers: [{ urls: ['turn:192.168.3.96:3478?transport=udp'], username: 'donkey', credential: 'secret' }],
    }));
  });

  it('offer 发出后未收到视频 track 时降级', async () => {
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} negotiationTimeoutMs={10} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    await waitFor(() => {
      expect(lastCallValue(onState).state).toBe('degraded');
    });
  });

  it('收到 track 但首帧未就绪时超时降级', async () => {
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} negotiationTimeoutMs={1000} videoReadyTimeoutMs={10} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));

    await act(async () => {
      pc.ontrack?.({
        streams: [{} as MediaStream],
        track: {} as MediaStreamTrack,
        receiver: { playoutDelayHint: undefined } as RTCRtpReceiver & { playoutDelayHint?: number },
      } as unknown as RTCTrackEvent);
    });

    await waitFor(() => expect(lastCallValue(onState).state).toBe('connected'));
    await waitFor(() => expect(lastCallValue(onState).state).toBe('degraded'));
  });

  it('降级后会自动重试 WebRTC session', async () => {
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} negotiationTimeoutMs={10} retryIntervalMs={20} />);

    await waitFor(() => expect(lastCallValue(onState).state).toBe('degraded'));
    await waitFor(() => expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(2));
  });

  it('回传浏览器端真实 FPS 和 P95 指标', async () => {
    const api = await import('../services/api');
    const callbacks: VideoFrameRequestCallback[] = [];
    Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', {
      configurable: true,
      value: vi.fn((callback: VideoFrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    });
    Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', {
      configurable: true,
      value: vi.fn(),
    });
    const pc = new FakePeerConnection();
    pc.statsReports = [{
      type: 'inbound-rtp',
      kind: 'video',
      framesPerSecond: 58,
      framesDropped: 3,
      jitter: 0.0042,
      jitterBufferDelay: 0.25,
      jitterBufferEmittedCount: 20,
    }];
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();
    const receiver = { playoutDelayHint: undefined } as RTCRtpReceiver & { playoutDelayHint?: number };

    render(<HookProbe onState={onState} factory={factory} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    await act(async () => {
      pc.ontrack?.({ streams: [{} as MediaStream], track: {} as MediaStreamTrack, receiver } as unknown as RTCTrackEvent);
    });
    await act(async () => {
      callbacks.shift()?.(0, { presentationTime: 0 } as VideoFrameCallbackMetadata);
      callbacks.shift()?.(1000, { presentationTime: 1000 } as VideoFrameCallbackMetadata);
    });

    await waitFor(() => expect(api.sendDriveWebRtcBrowserStats).toHaveBeenCalledWith('session-1', {
      browser_fps: 1,
      browser_p95_frame_interval_ms: 1000,
      e2e_latency_p50_ms: undefined,
      e2e_latency_p95_ms: undefined,
      e2e_samples: 0,
      inbound_fps: 58,
      frames_dropped: 3,
      jitter_ms: 4.2,
      jitter_buffer_delay_ms: 12.5,
    }));
    expect(receiver.playoutDelayHint).toBe(0);
  });

  it('captureTime 存在时回传真实端到端时延 p50/p95', async () => {
    const api = await import('../services/api');
    const callbacks: VideoFrameRequestCallback[] = [];
    Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', {
      configurable: true,
      value: vi.fn((callback: VideoFrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    });
    Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', {
      configurable: true,
      value: vi.fn(),
    });
    const pc = new FakePeerConnection();
    pc.statsReports = [];
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();
    // 带标准 jitterBufferTarget 的接收端：应被置 0（压低抖动缓冲）
    const receiver = { playoutDelayHint: undefined, jitterBufferTarget: 0.5 } as unknown as RTCRtpReceiver & {
      playoutDelayHint?: number;
      jitterBufferTarget?: number | null;
    };

    render(<HookProbe onState={onState} factory={factory} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    await act(async () => {
      pc.ontrack?.({ streams: [{} as MediaStream], track: {} as MediaStreamTrack, receiver } as unknown as RTCTrackEvent);
    });
    await act(async () => {
      // 两帧采样：e2e = expectedDisplayTime − captureTime → [25, 40]
      callbacks.shift()?.(0, { presentationTime: 0, captureTime: -25, expectedDisplayTime: 0 } as VideoFrameCallbackMetadata);
      callbacks.shift()?.(1000, { presentationTime: 1000, captureTime: 960, expectedDisplayTime: 1000 } as VideoFrameCallbackMetadata);
    });

    await waitFor(() => expect(api.sendDriveWebRtcBrowserStats).toHaveBeenCalledWith('session-1', {
      browser_fps: 1,
      browser_p95_frame_interval_ms: 1000,
      e2e_latency_p50_ms: 25,
      e2e_latency_p95_ms: 40,
      e2e_samples: 2,
      inbound_fps: undefined,
      frames_dropped: undefined,
      jitter_ms: undefined,
      jitter_buffer_delay_ms: undefined,
    }));
    expect(receiver.playoutDelayHint).toBe(0);
    expect(receiver.jitterBufferTarget).toBe(0);
  });

  it('无 captureTime 时用像素印章兜底采样真实端到端时延', async () => {
    const api = await import('../services/api');
    // 冻结本机钟：syncClock 的 NTP 中点与读帧时刻同源 → e2e 精确等于
    // (server_time − stamp)·1000 = 42ms（server_time 由测试钉在 stamp+42ms）
    const FIXED_NOW = 1_700_000_000_000;
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW);
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ server_time: fixture.ts + 0.042 }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    // jsdom 无 canvas 后端：伪造 ctx，getImageData 吐出 Python 生成的印章像素
    const fakeCtx = {
      drawImage: vi.fn(),
      getImageData: vi.fn(() => ({
        data: new Uint8ClampedArray(fixture.rgba),
        width: fixture.width,
        height: fixture.height,
      })),
    };
    const ctxSpy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue(fakeCtx as unknown as CanvasRenderingContext2D);
    const callbacks: VideoFrameRequestCallback[] = [];
    Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', {
      configurable: true,
      value: vi.fn((callback: VideoFrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    });
    Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', {
      configurable: true,
      value: vi.fn(),
    });
    const pc = new FakePeerConnection();
    pc.statsReports = [];
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    try {
      render(<HookProbe onState={onState} factory={factory} />);

      await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
      // 等 3 次 NTP 采样发完，再冲刷微任务让 clockOffsetRef 落库
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await act(async () => {
        pc.ontrack?.({ streams: [{} as MediaStream], track: {} as MediaStreamTrack, receiver: {} as RTCRtpReceiver } as unknown as RTCTrackEvent);
      });
      // jsdom 视频无解码数据：桩出可采样状态（印章区 240×24 要求源 ≥ 240×24）
      const video = document.querySelector('video') as HTMLVideoElement;
      Object.defineProperty(video, 'readyState', { configurable: true, value: 4 });
      Object.defineProperty(video, 'videoWidth', { configurable: true, value: 640 });
      Object.defineProperty(video, 'videoHeight', { configurable: true, value: 480 });
      await act(async () => {
        // 帧不带 captureTime（部分浏览器不提供）→ 触发像素印章兜底通路
        callbacks.shift()?.(0, { presentationTime: 0 } as VideoFrameCallbackMetadata);
        callbacks.shift()?.(1000, { presentationTime: 1000 } as VideoFrameCallbackMetadata);
      });

      await waitFor(() => expect(api.sendDriveWebRtcBrowserStats).toHaveBeenCalled());
      const payload = (api.sendDriveWebRtcBrowserStats as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1];
      expect(payload.e2e_samples).toBe(2);
      expect(payload.e2e_latency_p50_ms).toBeCloseTo(42, 0);
      expect(payload.e2e_latency_p95_ms).toBeCloseTo(42, 0);
      expect(payload.browser_fps).toBe(1);
      expect(payload.browser_p95_frame_interval_ms).toBe(1000);
    } finally {
      nowSpy.mockRestore();
      ctxSpy.mockRestore();
    }
  });

  it('处理 answer 和 ICE 信令', async () => {
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();
    const { rerender } = render(
      <HookProbe onState={onState} factory={factory} />
    );

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));

    await act(async () => {
      rerender(<HookProbe
        onState={onState}
        factory={factory}
        signal={{
          type: 'webrtc_signal',
          signal_type: 'answer',
          session_id: lastCallValue(onState).sessionId,
          sdp: 'answer-sdp',
          description_type: 'answer',
        }}
      />);
    });

    await waitFor(() => expect(pc.remoteDescription?.sdp).toBe('answer-sdp'));

    await act(async () => {
      rerender(<HookProbe
        onState={onState}
        factory={factory}
        signal={{
          type: 'webrtc_signal',
          signal_type: 'ice',
          session_id: lastCallValue(onState).sessionId,
          candidate: { candidate: 'candidate:1', sdpMid: '0', sdpMLineIndex: 0 },
        }}
      />);
    });

    await waitFor(() => expect(pc.candidates).toEqual([
      { candidate: 'candidate:1', sdpMid: '0', sdpMLineIndex: 0 },
    ]));
  });

  it('connectionState 变为 failed 时自动重连', async () => {
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    await act(async () => {
      pc.connectionState = 'failed';
      pc.onconnectionstatechange?.();
    });

    await waitFor(() => expect(lastCallValue(onState).state).toBe('reconnecting'));
    await waitFor(() => expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(2));
  });

  it('disconnected 宽限内自愈不重连，超过宽限仍断开才重连', async () => {
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} disconnectGraceMs={30} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    // 宽限内恢复 connected：不重连
    await act(async () => {
      pc.connectionState = 'disconnected';
      pc.onconnectionstatechange?.();
      await new Promise((resolve) => setTimeout(resolve, 5));
      pc.connectionState = 'connected';
      pc.onconnectionstatechange?.();
    });
    expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(1);
    // 再次 disconnected 且超过宽限仍断开：重连
    await act(async () => {
      pc.connectionState = 'disconnected';
      pc.onconnectionstatechange?.();
    });
    await waitFor(() => expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(2));
  });

  it('渲染帧停滞后看门狗自动重连', async () => {
    const callbacks: VideoFrameRequestCallback[] = [];
    Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', {
      configurable: true,
      value: vi.fn((callback: VideoFrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    });
    Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', {
      configurable: true,
      value: vi.fn(),
    });
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    pc.connectionState = 'connected';
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} stallRecoveryMs={1000} watchdogIntervalMs={10} />);

    const nowSpy = vi.spyOn(performance, 'now').mockReturnValue(1000);
    try {
      await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
      await act(async () => {
        pc.ontrack?.({
          streams: [{} as MediaStream],
          track: {} as MediaStreamTrack,
          receiver: {} as RTCRtpReceiver,
        } as unknown as RTCTrackEvent);
      });
      await act(async () => {
        document.querySelector('video')?.dispatchEvent(new Event('loadeddata'));
      });
      await waitFor(() => expect(lastCallValue(onState).videoReady).toBe(true));
      // 出一帧渲染（此刻 performance.now=1000）后停摆：把本地时钟拨过 stallRecoveryMs
      await act(async () => {
        callbacks.at(-1)?.(0, { presentationTime: 0 } as VideoFrameCallbackMetadata);
      });
      nowSpy.mockReturnValue(61_000);

      await waitFor(() => expect(lastCallValue(onState).state).toBe('reconnecting'));
      await waitFor(() => expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(2));
    } finally {
      nowSpy.mockRestore();
    }
  });

  it('track muted 超时后看门狗自动重连', async () => {
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    pc.connectionState = 'connected';
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();
    const track = {} as MediaStreamTrack;

    render(<HookProbe onState={onState} factory={factory} muteRecoveryMs={20} watchdogIntervalMs={10} />);

    await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
    await act(async () => {
      pc.ontrack?.({
        streams: [{} as MediaStream],
        track,
        receiver: {} as RTCRtpReceiver,
      } as unknown as RTCTrackEvent);
      document.querySelector('video')?.dispatchEvent(new Event('loadeddata'));
      track.onmute?.(new Event('mute'));
    });
    await waitFor(() => expect(lastCallValue(onState).videoReady).toBe(true));

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    await waitFor(() => expect(lastCallValue(onState).state).toBe('reconnecting'));
    await waitFor(() => expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(2));
  });

  it('会话被其他客户端接管时不重连，回退 MJPEG', async () => {
    const api = await import('../services/api');
    const { getDriveWebRtcStats } = await import('../services/api');
    (getDriveWebRtcStats as ReturnType<typeof vi.fn>).mockResolvedValue({
      session_id: 'session-other',
      degraded: false,
    });
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} />);

    try {
      await waitFor(() => expect(pc.localDescription?.sdp).toBe('offer-sdp'));
      // 等 stats 轮询（1s 间隔）拿到「别人的会话」
      await waitFor(() => expect(lastCallValue(onState).stats.session_id).toBe('session-other'), { timeout: 3000 });

      await act(async () => {
        pc.connectionState = 'failed';
        pc.onconnectionstatechange?.();
      });

      await waitFor(() => expect(lastCallValue(onState).state).toBe('idle'));
      expect(api.createDriveWebRtcSession).toHaveBeenCalledTimes(1);
    } finally {
      (getDriveWebRtcStats as ReturnType<typeof vi.fn>).mockResolvedValue({
        source_fps: 60,
        sent_fps: 60,
        browser_fps: 0,
        browser_p95_frame_interval_ms: 0,
        degraded: false,
      });
    }
  });
});
