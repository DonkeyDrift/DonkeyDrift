import React, { useEffect } from 'react';
import { Moon, Sun, Monitor } from 'lucide-react';
import {
  applyTheme,
  readStoredTheme,
  setTheme,
  useResolvedTheme,
  useThemeMode,
  THEME_STORAGE_KEY,
  type ThemeMode,
} from '@/lib/theme';

export { THEME_STORAGE_KEY };
export type { ThemeMode };

const NEXT_MODE: Record<ThemeMode, ThemeMode> = {
  system: 'light',
  light: 'dark',
  dark: 'system',
};

const MODE_LABEL: Record<ThemeMode, string> = {
  system: '跟随系统主题',
  light: '浅色主题',
  dark: '深色主题',
};

/**
 * 三态主题切换按钮：浅色 → 深色 → 跟随系统，循环切换，图标反映当前模式。
 * - 首次访问（未手动切换过）默认"跟随系统"，随浏览器 prefers-color-scheme 实时同步；
 * - 手动单击可显式选择浅色/深色；再切回"跟随系统"后恢复与浏览器深浅色同步。
 */
export const ThemeSwitcher: React.FC = () => {
  const mode = useThemeMode();
  const resolved = useResolvedTheme();

  // 与 index.html 的首屏内联脚本保持一致:挂载时按本地存储再应用一次,
  // 保证 <html> 皮肤 class 与持久化选择始终同步。
  useEffect(() => {
    applyTheme(readStoredTheme());
  }, []);

  const handleClick = () => {
    setTheme(NEXT_MODE[mode]);
  };

  const ariaLabel = (() => {
    if (mode === 'system') {
      return `跟随系统主题（当前${resolved === 'dark' ? '深色' : '浅色'}），点击切换到浅色`;
    }
    const next = NEXT_MODE[mode];
    return `当前${MODE_LABEL[mode]}，点击切换到${next === 'system' ? '跟随系统' : next === 'dark' ? '深色' : '浅色'}`;
  })();

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={handleClick}
      className="theme-switcher-btn flex items-center justify-center w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300 hover:text-zinc-100 transition-colors"
    >
      {mode === 'system' ? (
        <Monitor className="w-4 h-4" />
      ) : mode === 'light' ? (
        <Sun className="w-4 h-4" />
      ) : (
        <Moon className="w-4 h-4" />
      )}
    </button>
  );
};
