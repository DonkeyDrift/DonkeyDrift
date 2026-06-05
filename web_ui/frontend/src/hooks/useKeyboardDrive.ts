import { useEffect, useRef } from 'react';

import { DriveParams } from '../store/useDriveStore';

interface UseKeyboardDriveOptions {
  enabled?: boolean;
  onChange?: (angle: number, throttle: number) => void;
  params?: Partial<DriveParams>;
}

/**
 * 键盘驾驶 Hook
 * 按键映射：I-前进 / K-刹车倒车 / J-左转 / L-右转
 * 松开按键自动回中，带平滑过渡
 */
export const useKeyboardDrive = ({
  enabled = true,
  onChange,
  params = {},
}: UseKeyboardDriveOptions = {}) => {
  const keysRef = useRef({ i: false, k: false, j: false, l: false });
  const angleRef = useRef(0);
  const throttleRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const paramsRef = useRef(params);
  paramsRef.current = params;

  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (key in keysRef.current) {
        (keysRef.current as Record<string, boolean>)[key] = true;
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (key in keysRef.current) {
        (keysRef.current as Record<string, boolean>)[key] = false;
      }
    };

    // 60fps 平滑更新
    const tick = () => {
      const keys = keysRef.current;
      const {
        steerRate = 1.2,
        accelRate = 1.0,
        brakeRate = 1.2,
        recenterRate = 0.35,
      } = paramsRef.current;

      let a = angleRef.current;
      let t = throttleRef.current;

      // 转向
      if (keys.l && !keys.j) {
        a = Math.min(1, a + steerRate / 60);
      } else if (keys.j && !keys.l) {
        a = Math.max(-1, a - steerRate / 60);
      } else if (a > 0) {
        a = Math.max(0, a - recenterRate / 60);
      } else if (a < 0) {
        a = Math.min(0, a + recenterRate / 60);
      }

      // 油门
      if (keys.i && !keys.k) {
        t = Math.min(1, t + accelRate / 60);
      } else if (keys.k && !keys.i) {
        t = Math.max(-1, t - brakeRate / 60);
      } else if (t > 0) {
        t = Math.max(0, t - recenterRate / 60);
      } else if (t < 0) {
        t = Math.min(0, t + recenterRate / 60);
      }

      angleRef.current = a;
      throttleRef.current = t;
      onChangeRef.current?.(a, t);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [enabled]);

  return { angle: angleRef.current, throttle: throttleRef.current };
};
