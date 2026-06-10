import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getDriveWebRtcIceServers, useDriveWebRtcVideo } from './useDriveWebRtcVideo';
import type { WebRtcSignal } from './useDriveWebsocket';

vi.mock('../services/api', () => ({
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
  ontrack: ((event: RTCTrackEvent) => void) | null = null;
  onicecandidate: ((event: RTCPeerConnectionIceEvent) => void) | null = null;
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
}> = ({ signal, onState, factory, negotiationTimeoutMs, retryIntervalMs }) => {
  const state = useDriveWebRtcVideo({ incomingSignal: signal, peerConnectionFactory: factory, negotiationTimeoutMs, retryIntervalMs });
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

  it('创建 WebRTC session 并发送 offer', async () => {
    const api = await import('../services/api');
    const pc = new FakePeerConnection();
    const factory = () => pc as unknown as RTCPeerConnection;
    const onState = vi.fn();

    render(<HookProbe onState={onState} factory={factory} />);

    await waitFor(() => {
      expect(api.createDriveWebRtcSession).toHaveBeenCalled();
      expect(api.sendDriveWebRtcOffer).toHaveBeenCalledWith('session-1', 'offer-sdp');
      expect(pc.localDescription?.sdp).toBe('offer-sdp');
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
      inbound_fps: 58,
      frames_dropped: 3,
      jitter_ms: 4.2,
      jitter_buffer_delay_ms: 12.5,
    }));
    expect(receiver.playoutDelayHint).toBe(0);
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
});
