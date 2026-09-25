import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  AxisMapping,
  DEFAULT_GAMEPAD_CONFIG,
  GAMEPAD_PRESETS,
  GamepadAxisRole,
  GamepadConfig,
  GamepadPreset,
  detectPreset,
  mergeGamepadConfig,
} from '../lib/gamepadMapping';

interface GamepadStore {
  config: GamepadConfig;
  /** 应用预设（custom 只切换标记，不改数值） */
  setPreset: (preset: GamepadPreset) => void;
  /** 修改单个轴的映射，并重新推断 preset */
  patchAxis: (role: GamepadAxisRole, patch: Partial<AxisMapping>) => void;
  /** 同时设置转向/油门死区 */
  setDeadzone: (deadzone: number) => void;
  /** 记录已完成校准的手柄 id */
  bindPad: (padId: string) => void;
  reset: () => void;
}

export const useGamepadStore = create<GamepadStore>()(
  persist(
    (set, get) => ({
      config: DEFAULT_GAMEPAD_CONFIG,

      setPreset: (preset) => {
        const padId = get().config.padId;
        if (preset === 'custom') {
          set((state) => ({ config: { ...state.config, preset: 'custom' } }));
          return;
        }
        set({ config: { ...GAMEPAD_PRESETS[preset], padId } });
      },

      patchAxis: (role, patch) => {
        set((state) => {
          const next: GamepadConfig = {
            ...state.config,
            [role]: { ...state.config[role], ...patch },
          };
          return { config: { ...next, preset: detectPreset(next) } };
        });
      },

      setDeadzone: (deadzone) => {
        set((state) => {
          const next: GamepadConfig = {
            ...state.config,
            steering: { ...state.config.steering, deadzone },
            throttle: { ...state.config.throttle, deadzone },
          };
          return { config: { ...next, preset: detectPreset(next) } };
        });
      },

      bindPad: (padId) => {
        set((state) => ({ config: { ...state.config, padId } }));
      },

      reset: () => set({ config: DEFAULT_GAMEPAD_CONFIG }),
    }),
    {
      name: 'donkey-gamepad-config',
      version: 1,
      merge: (persisted, current) => {
        const saved = (persisted as { config?: Partial<GamepadConfig> } | undefined)?.config;
        return { ...current, config: mergeGamepadConfig(saved) };
      },
    },
  ),
);
