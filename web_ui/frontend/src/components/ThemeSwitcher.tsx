import React, { useEffect } from 'react';
import { Moon, Sun } from 'lucide-react';
import {
  applyTheme,
  readStoredTheme,
  setTheme,
  THEME_STORAGE_KEY,
  useResolvedTheme,
  type ThemeMode,
} from '@/lib/theme';

export { THEME_STORAGE_KEY };
export type { ThemeMode };

/**
 * 静音式单按钮主题切换：单击在深/浅之间来回切，按钮图标显示当前生效主题
 * （浅色=太阳、深色=月亮）。首次访问跟随浏览器 prefers-color-scheme
 * （由 lib/theme.ts 的 system 监听负责实时跟随），用户手动单击一次后
 * 持久化所选的浅色/深色，不再跟随浏览器。
 */
export const ThemeSwitcher: React.FC = () => {
  const resolved = useResolvedTheme();
  const next = resolved === 'dark' ? 'light' : 'dark';

  // 与 index.html 的首屏内联脚本保持一致:挂载时按本地存储再应用一次,
  // 保证 <html> 皮肤 class 与持久化选择始终同步。
  useEffect(() => {
    applyTheme(readStoredTheme());
  }, []);

  return (
    <button
      type="button"
      aria-pressed={resolved === 'dark'}
      aria-label={next === 'light' ? '切换到浅色主题' : '切换到深色主题'}
      title={next === 'light' ? '切换到浅色主题' : '切换到深色主题'}
      onClick={() => setTheme(next)}
      className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300 hover:text-zinc-100 transition-colors"
    >
      {resolved === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
    </button>
  );
};
