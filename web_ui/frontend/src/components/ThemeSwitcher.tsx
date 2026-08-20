import React, { useEffect } from 'react';
import { Moon, Sun } from 'lucide-react';
import { applyTheme, readStoredTheme, setTheme, useResolvedTheme, type ThemeMode } from '@/lib/theme';

export type { ThemeMode };

/**
 * 静音式单按钮主题切换：单击在深/浅之间来回切，图标反映当前生效主题，
 * 默认跟随浏览器 prefers-color-scheme（由 lib/theme 负责）；
 * 手动单击只在当前页面视图内切换（仅内存，不持久化），
 * 每次进入/刷新都会重新跟随系统。
 */
export const ThemeSwitcher: React.FC = () => {
  const resolved = useResolvedTheme();

  // 与 index.html 的首屏内联脚本保持一致:挂载时按本地存储再应用一次,
  // 保证 <html> 皮肤 class 与持久化选择始终同步。
  useEffect(() => {
    applyTheme(readStoredTheme());
  }, []);

  const handleClick = () => {
    setTheme(resolved === 'dark' ? 'light' : 'dark');
  };

  return (
    <button
      type="button"
      aria-label={resolved === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
      onClick={handleClick}
      className="theme-switcher-btn flex items-center justify-center w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300 hover:text-zinc-100 transition-colors"
    >
      {resolved === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
    </button>
  );
};
