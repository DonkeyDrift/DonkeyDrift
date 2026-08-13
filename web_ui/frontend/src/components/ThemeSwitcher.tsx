import React, { useState } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'donkeydrifter.ui.theme';

const SEGMENTS: ReadonlyArray<{ value: ThemeMode; label: string }> = [
  { value: 'light', label: '浅色' },
  { value: 'system', label: '跟随系统' },
  { value: 'dark', label: '深色' },
];

const readStoredTheme = (): ThemeMode => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return 'system';
  } catch {
    return 'system';
  }
};

export const ThemeSwitcher: React.FC = () => {
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);

  const handleChange = (value: ThemeMode) => {
    setTheme(value);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, value);
    } catch {
      /* localStorage unavailable: keep in-memory selection */
    }
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