import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useDriveControlLoop } from './useDriveControlLoop';

const Probe: React.FC<{
  connected: boolean;
  send: (payload: Record<string, unknown>) => boolean;
}> = ({ connected, send }) => {
  useDriveControlLoop({
    connected,
    send,
    getControl: () => ({ angle: 0, throttle: 0, drive_mode: 'user' }),
  });
  return null;
};

describe('useDriveControlLoop', () => {
  it('连接时以约 60Hz 持续发送完整控制状态，包含零值', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);

    render(<Probe connected={true} send={send} />);
    vi.advanceTimersByTime(1000);

    expect(send.mock.calls.length).toBeGreaterThanOrEqual(58);
    expect(send.mock.calls.length).toBeLessThanOrEqual(62);
    expect(send).toHaveBeenLastCalledWith({ angle: 0, throttle: 0, drive_mode: 'user' });
    vi.useRealTimers();
  });

  it('断开或卸载后停止发送', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender, unmount } = render(<Probe connected={false} send={send} />);

    vi.advanceTimersByTime(1000);
    expect(send).not.toHaveBeenCalled();

    rerender(<Probe connected={true} send={send} />);
    vi.advanceTimersByTime(1000);
    expect(send).toHaveBeenCalled();

    send.mockClear();
    unmount();
    vi.advanceTimersByTime(1000);
    expect(send).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('页面隐藏（后台页签）时暂停发送，回到前台恢复', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    render(<Probe connected={true} send={send} />);
    vi.advanceTimersByTime(1000);
    expect(send.mock.calls.length).toBeGreaterThanOrEqual(58);

    send.mockClear();
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    vi.advanceTimersByTime(1000);
    expect(send).not.toHaveBeenCalled();

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    vi.advanceTimersByTime(1000);
    expect(send.mock.calls.length).toBeGreaterThanOrEqual(58);
    vi.useRealTimers();
  });
});
