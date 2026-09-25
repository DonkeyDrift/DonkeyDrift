export type GamepadPreset = 'xbox' | 'z-axis' | 'wheel' | 'custom';
export type GamepadAxisRole = 'steering' | 'throttle';

export interface AxisMapping {
  /** 轴索引，-1 表示未指定 */
  axis: number;
  invert: boolean;
  /** 死区，0 ~ 0.3 */
  deadzone: number;
  /** 输出上限，0.2 ~ 1 */
  max: number;
  /** 中位偏移，默认 0 */
  center: number;
}

export interface GamepadConfig {
  version: 1;
  preset: GamepadPreset;
  steering: AxisMapping;
  throttle: AxisMapping;
  /** 已完成校准的手柄 id（按设备记忆，避免重复弹向导） */
  padId?: string;
}

export const DEFAULT_GAMEPAD_CONFIG: GamepadConfig = {
  version: 1,
  preset: 'z-axis',
  // 转向默认走 Z 轴（axes[2]），中位直行、最小值=左转，无需反向
  steering: { axis: 2, invert: false, deadzone: 0.08, max: 1, center: 0 },
  // 油门沿用左摇杆 Y，前推为负故反向
  throttle: { axis: 1, invert: true, deadzone: 0.08, max: 1, center: 0 },
};

export const GAMEPAD_PRESETS: Record<Exclude<GamepadPreset, 'custom'>, GamepadConfig> = {
  xbox: {
    version: 1,
    preset: 'xbox',
    steering: { axis: 0, invert: false, deadzone: 0.1, max: 1, center: 0 },
    throttle: { axis: 1, invert: true, deadzone: 0.1, max: 1, center: 0 },
  },
  'z-axis': {
    version: 1,
    preset: 'z-axis',
    steering: { axis: 2, invert: false, deadzone: 0.08, max: 1, center: 0 },
    throttle: { axis: 1, invert: true, deadzone: 0.08, max: 1, center: 0 },
  },
  wheel: {
    version: 1,
    preset: 'wheel',
    steering: { axis: 0, invert: false, deadzone: 0.03, max: 1, center: 0 },
    throttle: { axis: 1, invert: true, deadzone: 0.03, max: 1, center: 0 },
  },
};

export const GAMEPAD_PRESET_ORDER: Array<{ id: GamepadPreset; labelKey: string }> = [
  { id: 'xbox', labelKey: 'drive.gamepadPresetXbox' },
  { id: 'z-axis', labelKey: 'drive.gamepadPresetZAxis' },
  { id: 'wheel', labelKey: 'drive.gamepadPresetWheel' },
  { id: 'custom', labelKey: 'drive.gamepadPresetCustom' },
];

export const clampNumber = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

export const clampUnit = (value: number): number => clampNumber(value, -1, 1);

/** 去死区并重新归一化到 0..1 的有效区间 */
export const applyDeadzone = (value: number, deadzone: number): number => {
  const d = clampNumber(deadzone, 0, 0.9);
  if (!Number.isFinite(value) || Math.abs(value) < d) return 0;
  const sign = value > 0 ? 1 : -1;
  return sign * ((Math.abs(value) - d) / (1 - d));
};

/** 单轴映射：中位偏移 → 去死区 → 反向 → 限幅 */
export const mapAxis = (raw: number | undefined, mapping: AxisMapping): number => {
  if (mapping.axis < 0 || raw === undefined || !Number.isFinite(raw)) return 0;
  const centered = raw - mapping.center;
  const value = applyDeadzone(centered, mapping.deadzone);
  const signed = mapping.invert ? -value : value;
  const result = clampUnit(signed * mapping.max);
  // 归一化 -0，避免把负零写进控制帧
  return result === 0 ? 0 : result;
};

/** 轴序号对应的常见含义提示 */
export const axisHint = (index: number, mapping?: string): string => {
  const standard = ['左摇杆 X', '左摇杆 Y', '右摇杆 X / Z', '右摇杆 Y'];
  const generic = ['左摇杆 X', '左摇杆 Y', 'Z / 右摇杆 X', 'Rz / 右摇杆 Y'];
  const table = mapping === 'standard' ? standard : generic;
  return table[index] ?? '';
};

const sameAxis = (a: AxisMapping, b: AxisMapping): boolean =>
  a.axis === b.axis &&
  a.invert === b.invert &&
  Math.abs(a.deadzone - b.deadzone) < 0.005 &&
  Math.abs(a.max - b.max) < 0.005 &&
  Math.abs(a.center - b.center) < 0.005;

export const detectPreset = (config: GamepadConfig): GamepadPreset => {
  const entries = Object.entries(GAMEPAD_PRESETS) as Array<
    [Exclude<GamepadPreset, 'custom'>, GamepadConfig]
  >;
  for (const [id, preset] of entries) {
    if (sameAxis(config.steering, preset.steering) && sameAxis(config.throttle, preset.throttle)) {
      return id;
    }
  }
  return 'custom';
};

/** 读取持久化数据时与默认值深合并，兼容旧版本缺少字段的情况 */
export const mergeGamepadConfig = (partial?: Partial<GamepadConfig> | null): GamepadConfig => ({
  ...DEFAULT_GAMEPAD_CONFIG,
  ...partial,
  version: 1,
  preset: partial?.preset ?? DEFAULT_GAMEPAD_CONFIG.preset,
  steering: { ...DEFAULT_GAMEPAD_CONFIG.steering, ...(partial?.steering ?? {}) },
  throttle: { ...DEFAULT_GAMEPAD_CONFIG.throttle, ...(partial?.throttle ?? {}) },
});
