import { useCallback, useEffect, useRef, useState } from 'react';

interface UseGamepadDriveOptions {
  enabled?: boolean;
  onChange?: (angle: number, throttle: number) => void;
  deadzone?: number;   // 死区，0~0.3
  maxThrottle?: number; // 最大油门限制
}

/**
 * 游戏手柄输入 Hook
 * 基于 HTML5 Gamepad API
 * 左摇杆横向 → angle，纵向 → throttle（前推为正）
 */
export const useGamepadDrive = ({
  enabled = true,
  onChange,
  deadzone = 0.1,
  maxThrottle = 1.0,
}: UseGamepadDriveOptions = {}) => {
  const [connected, setConnected] = useState(false);
  const rafRef = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const lastValueRef = useRef({ angle: 0, throttle: 0 });

  const applyDeadzone = useCallback((v: number) => {
    if (Math.abs(v) < deadzone) return 0;
    const sign = v > 0 ? 1 : -1;
    return sign * ((Math.abs(v) - deadzone) / (1 - deadzone));
  }, [deadzone]);

  useEffect(() => {
    if (!enabled) return;

    const handleConnect = () => {
      setConnected(true);
    };
    const handleDisconnect = () => {
      const pads = navigator.getGamepads().filter(Boolean);
      if (pads.length === 0) {
        setConnected(false);
      }
    };

    window.addEventListener('gamepadconnected', handleConnect);
    window.addEventListener('gamepaddisconnected', handleDisconnect);

    const poll = () => {
      const gamepads = navigator.getGamepads();
      const pad = gamepads.find((p) => p !== null);

      if (pad) {
        // 左摇杆：axes[0] 横向，axes[1] 纵向（注意: 前推为负值）
        const x = applyDeadzone(pad.axes[0]);
        const y = applyDeadzone(pad.axes[1]);

        const angle = Math.max(-1, Math.min(1, x));
        const throttle = Math.max(-1, Math.min(1, -y * maxThrottle));

        // 有变化时才触发回调
        if (
          Math.abs(angle - lastValueRef.current.angle) > 0.01 ||
          Math.abs(throttle - lastValueRef.current.throttle) > 0.01
        ) {
          lastValueRef.current = { angle, throttle };
          onChangeRef.current?.(angle, throttle);
        }
      }

      rafRef.current = requestAnimationFrame(poll);
    };

    rafRef.current = requestAnimationFrame(poll);

    return () => {
      window.removeEventListener('gamepadconnected', handleConnect);
      window.removeEventListener('gamepaddisconnected', handleDisconnect);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, applyDeadzone, maxThrottle]);

  return { connected, angle: lastValueRef.current.angle, throttle: lastValueRef.current.throttle };
};
