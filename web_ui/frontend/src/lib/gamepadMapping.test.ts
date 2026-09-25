import { describe, expect, it } from 'vitest';
import {
  DEFAULT_GAMEPAD_CONFIG,
  GAMEPAD_PRESETS,
  applyDeadzone,
  clampNumber,
  detectPreset,
  mapAxis,
  mergeGamepadConfig,
} from './gamepadMapping';

describe('gamepadMapping', () => {
  it('死区内的输入归零，死区外重新归一化', () => {
    expect(applyDeadzone(0.05, 0.1)).toBe(0);
    expect(applyDeadzone(-0.05, 0.1)).toBe(0);
    expect(applyDeadzone(0.5, 0.1)).toBeCloseTo((0.5 - 0.1) / 0.9, 5);
    expect(applyDeadzone(-1, 0.1)).toBeCloseTo(-1, 5);
  });

  it('Z 轴中位直行，最小值输出左转为负', () => {
    const mapping = DEFAULT_GAMEPAD_CONFIG.steering;
    expect(mapping.axis).toBe(2);
    expect(mapAxis(0, mapping)).toBe(0);
    expect(mapAxis(-1, mapping)).toBeCloseTo(-1, 5);
    expect(mapAxis(1, mapping)).toBeCloseTo(1, 5);
  });

  it('反向把左右对调', () => {
    const mapping = { ...DEFAULT_GAMEPAD_CONFIG.steering, invert: true };
    expect(mapAxis(-1, mapping)).toBeCloseTo(1, 5);
    expect(mapAxis(1, mapping)).toBeCloseTo(-1, 5);
  });

  it('中位偏移可补偿不自居中的轴', () => {
    const mapping = { ...DEFAULT_GAMEPAD_CONFIG.steering, center: 0.5, deadzone: 0.05 };
    expect(mapAxis(0.5, mapping)).toBe(0);
    expect(mapAxis(0.9, mapping)).toBeGreaterThan(0);
  });

  it('上限缩放输出', () => {
    const mapping = { ...DEFAULT_GAMEPAD_CONFIG.steering, max: 0.5 };
    expect(mapAxis(1, mapping)).toBeCloseTo(0.5, 5);
  });

  it('未指定轴时输出 0', () => {
    expect(mapAxis(0.8, { ...DEFAULT_GAMEPAD_CONFIG.steering, axis: -1 })).toBe(0);
    expect(mapAxis(undefined, DEFAULT_GAMEPAD_CONFIG.steering)).toBe(0);
  });

  it('油门预设为 Y 轴反向', () => {
    expect(DEFAULT_GAMEPAD_CONFIG.throttle.axis).toBe(1);
    expect(DEFAULT_GAMEPAD_CONFIG.throttle.invert).toBe(true);
    expect(mapAxis(-1, DEFAULT_GAMEPAD_CONFIG.throttle)).toBeCloseTo(1, 5);
  });

  it('detectPreset 能识别预设与自定义', () => {
    expect(detectPreset(DEFAULT_GAMEPAD_CONFIG)).toBe('z-axis');
    expect(detectPreset(GAMEPAD_PRESETS.xbox)).toBe('xbox');
    expect(detectPreset({ ...DEFAULT_GAMEPAD_CONFIG, steering: { ...DEFAULT_GAMEPAD_CONFIG.steering, invert: true } })).toBe('custom');
  });

  it('mergeGamepadConfig 为旧数据补齐默认字段', () => {
    const merged = mergeGamepadConfig({ steering: { axis: 3 } as never });
    expect(merged.steering.axis).toBe(3);
    expect(merged.steering.deadzone).toBe(DEFAULT_GAMEPAD_CONFIG.steering.deadzone);
    expect(merged.throttle.axis).toBe(1);
    expect(merged.version).toBe(1);
  });

  it('clampNumber 限制范围', () => {
    expect(clampNumber(2, 0, 1)).toBe(1);
    expect(clampNumber(-2, 0, 1)).toBe(0);
  });
});
