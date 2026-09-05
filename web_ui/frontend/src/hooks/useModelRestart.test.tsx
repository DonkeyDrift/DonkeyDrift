import React from 'react';
import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useModelRestart } from './useModelRestart';
import type { DriveMode } from '../components/drive/DriveModeSelector';

interface ProbeProps {
  online: boolean;
  reportedMode: DriveMode;
  mode?: DriveMode;
  send: (data: Record<string, unknown>) => boolean;
  onTimeout?: () => void;
  timeoutMs?: number;
  settleMs?: number;
}

// 每次渲染把 hook 最新返回值暴露给测试体
let latest: { restarting: boolean; begin: () => void };

const Probe: React.FC<ProbeProps> = ({ online, reportedMode, mode = 'local', send, onTimeout, timeoutMs, settleMs }) => {
  latest = useModelRestart({
    online,
    reportedMode,
    getMode: () => mode,
    send,
    onTimeout,
    timeoutMs,
    settleMs,
  });
  return null;
};

describe('useModelRestart', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('begin 后立即进入 restarting，且不因当前模式相等而误收敛（车尚未掉线）', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    render(<Probe online={true} reportedMode="local" send={send} />);

    act(() => latest.begin());
    expect(latest.restarting).toBe(true);

    // 车还没掉线：reportedMode 是重启前的陈旧值，不得当作收敛信号
    act(() => vi.advanceTimersByTime(500));
    expect(latest.restarting).toBe(true);
    expect(send).not.toHaveBeenCalled();
  });

  it('车掉线再上线后，向车端补发当前模式（含 car_mode）', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender } = render(<Probe online={true} reportedMode="local" send={send} />);
    act(() => latest.begin());

    rerender(<Probe online={false} reportedMode="local" send={send} />);
    rerender(<Probe online={true} reportedMode="local" send={send} />);

    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith({ drive_mode: 'local', car_mode: 2 });
  });

  it('补发后车端回报与当前模式一致即结束重启状态', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender } = render(<Probe online={true} reportedMode="local" send={send} />);
    act(() => latest.begin());
    rerender(<Probe online={false} reportedMode="local" send={send} />);
    rerender(<Probe online={true} reportedMode="local" send={send} />);

    // 车端先报了一条 user（补发前的默认模式），不应收敛
    rerender(<Probe online={true} reportedMode="user" send={send} />);
    expect(latest.restarting).toBe(true);

    // 补发生效，车端报回 local
    rerender(<Probe online={true} reportedMode="local" send={send} />);
    expect(latest.restarting).toBe(false);
  });

  it('车端回报迟迟不一致时，settle 窗口后结束（避免永久抑制模式同步）', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender } = render(
      <Probe online={true} reportedMode="local" send={send} settleMs={3000} />,
    );
    act(() => latest.begin());
    rerender(<Probe online={false} reportedMode="local" send={send} settleMs={3000} />);
    rerender(<Probe online={true} reportedMode="local" send={send} settleMs={3000} />);

    act(() => vi.advanceTimersByTime(2999));
    expect(latest.restarting).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(latest.restarting).toBe(false);
  });

  it('begin 时车已离线：上线即补发，无需先等掉线', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender } = render(<Probe online={false} reportedMode="user" send={send} />);
    act(() => latest.begin());

    rerender(<Probe online={true} reportedMode="user" send={send} />);

    expect(send).toHaveBeenCalledWith({ drive_mode: 'local', car_mode: 2 });
  });

  it('整体超时：结束重启状态并回调 onTimeout', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const onTimeout = vi.fn();
    render(<Probe online={true} reportedMode="user" send={send} onTimeout={onTimeout} timeoutMs={1000} />);
    act(() => latest.begin());

    act(() => vi.advanceTimersByTime(1000));

    expect(latest.restarting).toBe(false);
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });

  it('重启期间用户经快捷键改了模式：补发使用最新模式', () => {
    vi.useFakeTimers();
    const send = vi.fn(() => true);
    const { rerender } = render(<Probe online={true} reportedMode="local" mode="local" send={send} />);
    act(() => latest.begin());

    // 用户在重启窗口内切回手动
    rerender(<Probe online={false} reportedMode="local" mode="user" send={send} />);
    rerender(<Probe online={true} reportedMode="local" mode="user" send={send} />);

    expect(send).toHaveBeenCalledWith({ drive_mode: 'user', car_mode: 0 });
  });
});
