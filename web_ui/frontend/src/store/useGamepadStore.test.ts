import { beforeEach, describe, expect, it } from 'vitest';
import { useGamepadStore } from './useGamepadStore';

describe('useGamepadStore', () => {
  beforeEach(() => {
    useGamepadStore.getState().reset();
  });

  it('默认使用 Z 轴转向且不反向', () => {
    const { config } = useGamepadStore.getState();
    expect(config.steering.axis).toBe(2);
    expect(config.steering.invert).toBe(false);
    expect(config.throttle.axis).toBe(1);
    expect(config.throttle.invert).toBe(true);
  });

  it('应用 Xbox 预设后转向改用轴 0', () => {
    useGamepadStore.getState().setPreset('xbox');
    const { config } = useGamepadStore.getState();
    expect(config.steering.axis).toBe(0);
    expect(config.preset).toBe('xbox');
  });

  it('手动改动映射后 preset 变为自定义', () => {
    useGamepadStore.getState().patchAxis('steering', { invert: true });
    const { config } = useGamepadStore.getState();
    expect(config.steering.invert).toBe(true);
    expect(config.preset).toBe('custom');
  });

  it('设置死区时同步作用于转向与油门', () => {
    useGamepadStore.getState().setDeadzone(0.15);
    const { config } = useGamepadStore.getState();
    expect(config.steering.deadzone).toBe(0.15);
    expect(config.throttle.deadzone).toBe(0.15);
  });

  it('记录已校准手柄 id', () => {
    useGamepadStore.getState().bindPad('pad-42');
    expect(useGamepadStore.getState().config.padId).toBe('pad-42');
  });
});
