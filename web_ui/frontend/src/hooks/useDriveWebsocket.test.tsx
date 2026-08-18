import React from 'react';
import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useDriveWebsocket, type WebRtcSignal } from './useDriveWebsocket';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;

  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.onclose?.();
  }
}

const HookProbe: React.FC<{ onSignal: (signal: WebRtcSignal) => void; enabled?: boolean }> = ({ onSignal, enabled = true }) => {
  useDriveWebsocket({ autoReconnect: false, onWebRtcSignal: onSignal, enabled });
  return null;
};

describe('useDriveWebsocket', () => {
  it('收到 WebRTC 信令时调用回调且不破坏状态消息处理', () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onSignal = vi.fn();

    render(<HookProbe onSignal={onSignal} />);
    const ws = FakeWebSocket.instances[0];

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_connection', online: true }) });
      ws.onmessage?.({
        data: JSON.stringify({
          type: 'webrtc_signal',
          signal_type: 'answer',
          session_id: 'session-1',
          sdp: 'answer-sdp',
          description_type: 'answer',
        }),
      });
    });

    expect(ws.url).toContain('client_id=');
    expect(ws.url).toContain('role=client');
    expect(onSignal).toHaveBeenCalledWith({
      type: 'webrtc_signal',
      signal_type: 'answer',
      session_id: 'session-1',
      sdp: 'answer-sdp',
      description_type: 'answer',
    });
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('enabled=false 时不建立 WebSocket 连接（滚出视口停后台收发）', () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onSignal = vi.fn();

    render(<HookProbe onSignal={onSignal} enabled={false} />);

    expect(FakeWebSocket.instances).toHaveLength(0);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
