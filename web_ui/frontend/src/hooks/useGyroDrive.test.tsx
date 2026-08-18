import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useGyroDrive } from './useGyroDrive';

const HookProbe: React.FC<{
  enabled: boolean;
  onState: (state: string) => void;
}> = ({ enabled, onState }) => {
  const { permissionState } = useGyroDrive({ enabled });
  onState(permissionState);
  return null;
};

const stubDeviceOrientation = (requestPermission?: () => Promise<string>) => {
  vi.stubGlobal('DeviceOrientationEvent', class {
    static requestPermission = requestPermission;
  });
};

describe('useGyroDrive permissionState', () => {
  it('未选中陀螺仪（enabled=false）时也完成支持性检测（非 iOS 默认 granted）', () => {
    stubDeviceOrientation(undefined);
    const states: string[] = [];
    render(<HookProbe enabled={false} onState={(s) => states.push(s)} />);

    expect(states.at(-1)).toBe('granted');
    vi.unstubAllGlobals();
  });

  it('iOS（存在 requestPermission）时初始为 prompt 而非 unsupported', () => {
    stubDeviceOrientation(() => Promise.resolve('granted'));
    const states: string[] = [];
    render(<HookProbe enabled={false} onState={(s) => states.push(s)} />);

    expect(states.at(-1)).toBe('prompt');
    vi.unstubAllGlobals();
  });

  it('不支持 DeviceOrientationEvent 时为 unsupported', () => {
    vi.stubGlobal('DeviceOrientationEvent', undefined);
    const states: string[] = [];
    render(<HookProbe enabled={false} onState={(s) => states.push(s)} />);

    expect(states.at(-1)).toBe('unsupported');
    vi.unstubAllGlobals();
  });
});
