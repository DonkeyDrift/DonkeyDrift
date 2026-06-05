import { useEffect } from 'react';

interface UseDriveHotkeysOptions {
  enabled?: boolean;
  onToggleRecording?: () => void;
  onCycleMode?: () => void;
  onSetModeUser?: () => void;
  onSetModeAutoSteer?: () => void;
  onSetModeFullAuto?: () => void;
}

/**
 * 驾驶快捷键 Hook
 * R - 切换录制
 * M - 循环切换模式
 * U - 人工模式
 * S - AI 转向模式
 * A - 全自动模式
 */
export const useDriveHotkeys = ({
  enabled = true,
  onToggleRecording,
  onCycleMode,
  onSetModeUser,
  onSetModeAutoSteer,
  onSetModeFullAuto,
}: UseDriveHotkeysOptions) => {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // 忽略输入框中的按键
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      const key = e.key.toLowerCase();
      switch (key) {
        case 'r':
          e.preventDefault();
          onToggleRecording?.();
          break;
        case 'm':
          e.preventDefault();
          onCycleMode?.();
          break;
        case 'u':
          e.preventDefault();
          onSetModeUser?.();
          break;
        case 's':
          e.preventDefault();
          onSetModeAutoSteer?.();
          break;
        case 'a':
          e.preventDefault();
          onSetModeFullAuto?.();
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    enabled,
    onToggleRecording,
    onCycleMode,
    onSetModeUser,
    onSetModeAutoSteer,
    onSetModeFullAuto,
  ]);
};
