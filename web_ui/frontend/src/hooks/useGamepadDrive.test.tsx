import React from 'react';
import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useGamepadDrive } from './useGamepadDrive';

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
});
