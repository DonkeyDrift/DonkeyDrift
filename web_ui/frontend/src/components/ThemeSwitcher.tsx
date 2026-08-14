import React, { useEffect, useState } from 'react';
import { applyTheme, readStoredTheme, setTheme, THEME_STORAGE_KEY, type ThemeMode } from '@/lib/theme';

export { THEME_STORAGE_KEY };
export type { ThemeMode };

const SEGMENTS: ReadonlyArray<{ value: ThemeMode; label: string }> = [
  { value: 'light', label: '浅色' },
  { value: 'system', label: '跟随系统' },
  { value: 'dark', label: '深色' },
];

export const ThemeSwitcher: React.FC = () => {
  const [theme, setThemeState] = useState<ThemeMode>(readStoredTheme);

  // 与 index.html 的首屏内联脚本保持一致:挂载时按本地存储再应用一次,
  // 保证 <html> 皮肤 class 与持久化选择始终同步。
  useEffect(() => {
    applyTheme(readStoredTheme());
  }, []);

  const handleChange = (value: ThemeMode) => {
    setThemeState(value);
    setTheme(value);
  };

  return (
    <div className="flex items-center gap-1 rounded-full bg-zinc-800 border border-zinc-700 p-1">
      {SEGMENTS.map(({ value, label }) => {
        const active = value === theme;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => handleChange(value)}
            className={`px-3 py-1 rounded-full text-xs transition-colors ${
              active
                ? 'bg-cyan-600 text-white'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
};
