import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getDriveWebRtcIceServers, useDriveWebRtcVideo } from './useDriveWebRtcVideo';
import type { WebRtcSignal } from './useDriveWebsocket';

vi.mock('../services/api', () => ({
  createDriveWebRtcSession: vi.fn(async () => ({ session_id: 'session-1' })),
  sendDriveWebRtcOffer: vi.fn(async () => ({ success: true })),
  sendDriveWebRtcIce: vi.fn(async () => ({ success: true })),
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
