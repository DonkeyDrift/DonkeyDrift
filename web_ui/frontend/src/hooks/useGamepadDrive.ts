import { useEffect, useRef, useState } from 'react';
import { DEFAULT_GAMEPAD_CONFIG, GamepadConfig, mapAxis } from '../lib/gamepadMapping';

interface UseGamepadDriveOptions {
  /** 是否为当前输入源：为 true 时输出 angle/throttle */
  enabled?: boolean;
  /** 面板打开（输入源不一定是手柄）时也需要轴快照 */
  monitor?: boolean;
  config?: GamepadConfig;
  onChange?: (angle: number, throttle: number) => void;
}

export interface GamepadSnapshot {
  connected: boolean;
  padId: string;
  mapping: string;
  axes: number[];
  angle: number;
  throttle: number;
}

/**
 * 游戏手柄输入 Hook（HTML5 Gamepad API）
 * 轴序号 / 反向 / 死区 / 上限全部来自 GamepadConfig，可兼容不同布局的手柄。
 * enabled=false 且在 monitor=false 时不启动轮询，但仍监听连接/断开事件。
 */
export const useGamepadDrive = ({
  enabled = true,
  monitor = false,
  config = DEFAULT_GAMEPAD_CONFIG,
  onChange,
}: UseGamepadDriveOptions = {}): GamepadSnapshot => {
  const [connected, setConnected] = useState(false);
  const [snapshot, setSnapshot] = useState<{ padId: string; mapping: string; axes: number[] }>({
    padId: '',
    mapping: '',
    axes: [],
  });
  const rafRef = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const configRef = useRef(config);
  configRef.current = config;
  const lastValueRef = useRef({ angle: 0, throttle: 0 });

  // 连接检测常驻运行（不受 enabled/monitor 门控），否则切换菜单里手柄选项永远灰着。
  // 除 gamepadconnected/gamepaddisconnected 事件外，再以「轮询 + 用户手势」兜底：
  // macOS Safari/Chrome 只有在页面获得焦点时按过手柄按键后才把手柄暴露给页面，
  // 且 Safari 的 gamepadconnected 事件触发不可靠，必须轮询 getGamepads() 才稳定。
  useEffect(() => {
    const detect = () => {
      const pads = navigator.getGamepads?.() ?? [];
      setConnected(pads.filter((p) => p !== null && p.connected !== false).length > 0);
    };

    const handleConnect = () => setConnected(true);
    const handleDisconnect = () => detect();

    window.addEventListener('gamepadconnected', handleConnect);
    window.addEventListener('gamepaddisconnected', handleDisconnect);
    // Safari 需要用户手势后才暴露手柄：页面交互/获得焦点时立即检测一次
    window.addEventListener('focus', detect);
    window.addEventListener('pointerdown', detect);
    window.addEventListener('keydown', detect);
    // 轮询兜底：事件缺失时也能在 1 秒内跟上手柄插拔
    const timer = window.setInterval(detect, 1000);
    detect();

    return () => {
      window.removeEventListener('gamepadconnected', handleConnect);
      window.removeEventListener('gamepaddisconnected', handleDisconnect);
      window.removeEventListener('focus', detect);
      window.removeEventListener('pointerdown', detect);
      window.removeEventListener('keydown', detect);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!enabled && !monitor) return;

    let lastSnapshotAt = 0;
    const poll = () => {
      const pads = navigator.getGamepads?.() ?? [];
      const pad = Array.from(pads).find((p) => p !== null) ?? null;

      if (pad) {
        setConnected(true);
        if (enabled) {
          const current = configRef.current;
          const angle = mapAxis(pad.axes[current.steering.axis], current.steering);
          const throttle = mapAxis(pad.axes[current.throttle.axis], current.throttle);
          const last = lastValueRef.current;
          if (Math.abs(angle - last.angle) > 0.01 || Math.abs(throttle - last.throttle) > 0.01) {
            lastValueRef.current = { angle, throttle };
            onChangeRef.current?.(angle, throttle);
          }
        }
        const now = Date.now();
        if (monitor && now - lastSnapshotAt >= 50) {
          lastSnapshotAt = now;
          setSnapshot({ padId: pad.id, mapping: pad.mapping, axes: Array.from(pad.axes) });
        }
      } else {
        setConnected(false);
      }

      rafRef.current = requestAnimationFrame(poll);
    };

    rafRef.current = requestAnimationFrame(poll);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, monitor]);

  return {
    connected,
    padId: snapshot.padId,
    mapping: snapshot.mapping,
    axes: snapshot.axes,
    angle: lastValueRef.current.angle,
    throttle: lastValueRef.current.throttle,
  };
};
