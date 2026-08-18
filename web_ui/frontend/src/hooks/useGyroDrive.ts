import { useEffect, useRef, useState, useCallback } from 'react';

interface UseGyroDriveOptions {
  enabled?: boolean;
  onChange?: (angle: number, throttle: number) => void;
  steerSensitivity?: number;  // 转向灵敏度，默认 1.0
  throttleSensitivity?: number;  // 油门灵敏度，默认 1.0
}

type DeviceOrientationPermissionState = 'granted' | 'denied' | 'prompt';

type DeviceOrientationEventWithPermission = typeof DeviceOrientationEvent & {
  requestPermission?: () => Promise<DeviceOrientationPermissionState>;
};

/**
 * 设备陀螺仪输入 Hook
 * 设备横屏握持（左侧为头）：
 *   左右倾斜 → angle
 *   前后俯仰 → throttle（前倾加油，后倾刹车）
 */
export const useGyroDrive = ({
  enabled = false,
  onChange,
  steerSensitivity = 1.0,
  throttleSensitivity = 1.0,
}: UseGyroDriveOptions = {}) => {
  const [permissionState, setPermissionState] = useState<'granted' | 'denied' | 'prompt' | 'unsupported'>('unsupported');
  const rafRef = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const orientationRef = useRef({ beta: 0, gamma: 0 });
  const lastValueRef = useRef({ angle: 0, throttle: 0 });

  const requestPermission = useCallback(async () => {
    const OrientationEvent = DeviceOrientationEvent as DeviceOrientationEventWithPermission;
    if (typeof OrientationEvent.requestPermission !== 'function') {
      setPermissionState('unsupported');
      return false;
    }
    try {
      const state = await OrientationEvent.requestPermission();
      setPermissionState(state);
      return state === 'granted';
    } catch {
      setPermissionState('denied');
      return false;
    }
  }, []);

  // 支持性检测在挂载时即执行（不受 enabled 门控），
  // 否则未选中陀螺仪时 permissionState 停留在初始值 'unsupported'，切换菜单里永远灰着
  useEffect(() => {
    if (typeof DeviceOrientationEvent === 'undefined') {
      setPermissionState('unsupported');
      return;
    }
    const OrientationEvent = DeviceOrientationEvent as DeviceOrientationEventWithPermission;
    // iOS 13+ 需要用户手势触发 requestPermission，先标为 prompt
    if (typeof OrientationEvent.requestPermission === 'function') {
      setPermissionState('prompt');
    } else {
      // 非 iOS 设备默认有权限
      setPermissionState('granted');
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    const handleOrientation = (e: DeviceOrientationEvent) => {
      if (e.beta !== null && e.gamma !== null) {
        orientationRef.current = { beta: e.beta, gamma: e.gamma };
      }
    };

    const tick = () => {
      // 横屏：beta 前后俯仰 → 油门
      // gamma 左右倾斜 → 转向
      const { beta, gamma } = orientationRef.current;

      // 归一化：beta 范围 [-90, 90] → [-1, 1]
      const throttle = Math.max(
        -1,
        Math.min(1, (beta / 45) * throttleSensitivity)
      );

      // gamma 范围 [-90, 90] → [-1, 1]
      const angle = Math.max(
        -1,
        Math.min(1, (gamma / 45) * steerSensitivity)
      );

      if (
        Math.abs(angle - lastValueRef.current.angle) > 0.02 ||
        Math.abs(throttle - lastValueRef.current.throttle) > 0.02
      ) {
        lastValueRef.current = { angle, throttle };
        onChangeRef.current?.(angle, throttle);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    window.addEventListener('deviceorientation', handleOrientation);
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener('deviceorientation', handleOrientation);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, steerSensitivity, throttleSensitivity]);

  return {
    permissionState,
    requestPermission,
    angle: lastValueRef.current.angle,
    throttle: lastValueRef.current.throttle,
  };
};
