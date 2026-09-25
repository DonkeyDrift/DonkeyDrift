import React, { useEffect } from 'react';
import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useDriveWebsocket, type CarState, type WebRtcSignal } from './useDriveWebsocket';

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

const HookProbe: React.FC<{
  onSignal: (signal: WebRtcSignal) => void;
  enabled?: boolean;
  onState?: (s: CarState) => void;
  onControlRejected?: (reason: string) => void;
}> = ({ onSignal, enabled = true, onState, onControlRejected }) => {
  const { carState } = useDriveWebsocket({ autoReconnect: false, onWebRtcSignal: onSignal, enabled, onControlRejected });
  useEffect(() => {
    onState?.(carState);
  }, [carState, onState]);
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

  it('车端离线（car_connection online=false）时复位录制态', () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onSignal = vi.fn();
    const states: CarState[] = [];
    const onState = (s: CarState) => states.push(s);

    render(<HookProbe onSignal={onSignal} onState={onState} />);
    const ws = FakeWebSocket.instances[0];

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_connection', online: true }) });
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_state', drive_mode: 'user', recording: true, num_records: 5 }) });
      // 车端闪断：online=false 必须同时复位 recording，否则页面残留"录制中"
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_connection', online: false }) });
    });

    const last = states[states.length - 1];
    expect(last.online).toBe(false);
    expect(last.recording).toBe(false);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('WebSocket 断开（onclose）时复位录制态', () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onSignal = vi.fn();
    const states: CarState[] = [];
    const onState = (s: CarState) => states.push(s);

    render(<HookProbe onSignal={onSignal} onState={onState} />);
    const ws = FakeWebSocket.instances[0];

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_connection', online: true }) });
      ws.onmessage?.({ data: JSON.stringify({ type: 'car_state', drive_mode: 'user', recording: true, num_records: 5 }) });
      ws.onclose?.();
    });

    const last = states[states.length - 1];
    expect(last.online).toBe(false);
    expect(last.recording).toBe(false);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('收到 control_rejected 时把 reason 传给 onControlRejected', () => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onSignal = vi.fn();
    const onControlRejected = vi.fn();

    render(<HookProbe onSignal={onSignal} onControlRejected={onControlRejected} />);
    const ws = FakeWebSocket.instances[0];

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ type: 'control_rejected', reason: 'not_driver' }) });
      ws.onmessage?.({ data: JSON.stringify({ type: 'control_rejected' }) });
    });

    expect(onControlRejected).toHaveBeenCalledTimes(2);
    expect(onControlRejected).toHaveBeenNthCalledWith(1, 'not_driver');
    expect(onControlRejected).toHaveBeenNthCalledWith(2, 'unknown');
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
