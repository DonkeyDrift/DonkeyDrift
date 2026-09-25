import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useGamepadDrive } from './useGamepadDrive';
import { DEFAULT_GAMEPAD_CONFIG } from '../lib/gamepadMapping';

const HookProbe: React.FC<{
  enabled: boolean;
  onState: (connected: boolean) => void;
}> = ({ enabled, onState }) => {
  const { connected } = useGamepadDrive({ enabled });
  onState(connected);
  return null;
};

const fireGamepadEvent = (type: string) => {
  act(() => {
    window.dispatchEvent(new Event(type));
  });
};

const makePad = (axes: number[]): Gamepad =>
  ({ id: 'test-pad', mapping: 'standard', axes, buttons: [] }) as unknown as Gamepad;

describe('useGamepadDrive', () => {
  it('未选中手柄（enabled=false）时连接检测仍运行', () => {
    const states: boolean[] = [];
    render(<HookProbe enabled={false} onState={(c) => states.push(c)} />);

    expect(states.at(-1)).toBe(false);

    fireGamepadEvent('gamepadconnected');
    expect(states.at(-1)).toBe(true);
  });

  it('手柄全部断开后 connected 复位为 false', () => {
    vi.stubGlobal('navigator', {
      getGamepads: () => [null],
    });
    const states: boolean[] = [];
    render(<HookProbe enabled={false} onState={(c) => states.push(c)} />);

    fireGamepadEvent('gamepadconnected');
    expect(states.at(-1)).toBe(true);

    fireGamepadEvent('gamepaddisconnected');
    expect(states.at(-1)).toBe(false);

    vi.unstubAllGlobals();
  });

  it('不触发 gamepadconnected 事件时，轮询 getGamepads 也能检测到手柄', () => {
    vi.useFakeTimers();
    vi.stubGlobal('navigator', {
      getGamepads: () => [makePad([0, 0, 0, 0])],
    });
    const states: boolean[] = [];
    render(<HookProbe enabled={false} onState={(c) => states.push(c)} />);

    // getGamepads 已返回手柄但从未派发 gamepadconnected（macOS Safari 场景）
    expect(states.at(-1)).toBe(true);

    // 轮询兜底：手柄被移除后 1 秒内 connected 复位
    vi.stubGlobal('navigator', {
      getGamepads: () => [null],
    });
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(states.at(-1)).toBe(false);

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('用户手势（pointerdown/keydown/focus）时立即检测手柄', () => {
    vi.stubGlobal('navigator', {
      getGamepads: () => [makePad([0, 0, 0, 0])],
    });
    const states: boolean[] = [];
    render(<HookProbe enabled={false} onState={(c) => states.push(c)} />);

    expect(states.at(-1)).toBe(true);

    vi.stubGlobal('navigator', {
      getGamepads: () => [null],
    });
    act(() => {
      window.dispatchEvent(new Event('pointerdown'));
    });
    expect(states.at(-1)).toBe(false);

    vi.stubGlobal('navigator', {
      getGamepads: () => [makePad([0, 0, 0, 0])],
    });
    act(() => {
      window.dispatchEvent(new Event('keydown'));
    });
    expect(states.at(-1)).toBe(true);

    vi.unstubAllGlobals();
  });

  it('按配置读取 Z 轴转向，左拨输出负值', async () => {
    const onChange = vi.fn();
    vi.stubGlobal('navigator', {
      getGamepads: () => [makePad([0, 0, -0.8, 0])],
    });

    const Probe: React.FC = () => {
      useGamepadDrive({ enabled: true, config: DEFAULT_GAMEPAD_CONFIG, onChange });
      return null;
    };
    render(<Probe />);

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [angle, throttle] = onChange.mock.calls.at(-1) as [number, number];
    expect(angle).toBeCloseTo(-0.78, 2);
    expect(throttle).toBe(0);

    vi.unstubAllGlobals();
  });

  it('反向配置会把左拨映射为正', async () => {
    const onChange = vi.fn();
    vi.stubGlobal('navigator', {
      getGamepads: () => [makePad([0, 0, -0.8, 0])],
    });

    const Probe: React.FC = () => {
      useGamepadDrive({
        enabled: true,
        config: {
          ...DEFAULT_GAMEPAD_CONFIG,
          steering: { ...DEFAULT_GAMEPAD_CONFIG.steering, invert: true },
        },
        onChange,
      });
      return null;
    };
    render(<Probe />);

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [angle] = onChange.mock.calls.at(-1) as [number, number];
    expect(angle).toBeGreaterThan(0);

    vi.unstubAllGlobals();
  });
});
