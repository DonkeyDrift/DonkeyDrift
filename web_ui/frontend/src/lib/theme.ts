import { useSyncExternalStore } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'donkeydrifter.ui.theme';

/** 各生效主题对应的 <html> class:深色 = MUS4 皮肤,浅色 = MUS4 Light 皮肤。 */
export const THEME_CLASS: Record<ResolvedTheme, string> = {
  dark: 'theme-mus4',
  light: 'theme-light',
};

const THEME_CHANGE_EVENT = 'donkeydrifter:theme-changed';

export const readStoredTheme = (): ThemeMode => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return 'system';
  } catch {
    return 'system';
  }
};

/**
 * TODO: “跟随系统”暂未实现,system 暂时解析为 dark(沿用深色现状)。
 * 实现后应读取 window.matchMedia('(prefers-color-scheme: dark)') 并监听变化。
 */
export const resolveTheme = (mode: ThemeMode): ResolvedTheme =>
  mode === 'light' ? 'light' : 'dark';

export const getResolvedTheme = (): ResolvedTheme =>
  document.documentElement.classList.contains(THEME_CLASS.light) ? 'light' : 'dark';

/** 切换 <html> 的皮肤 class 并广播主题变化(供 canvas/图表等 JS 配色订阅)。 */
export const applyTheme = (mode: ThemeMode): ResolvedTheme => {
  const resolved = resolveTheme(mode);
  const root = document.documentElement;
  root.classList.remove(THEME_CLASS.dark, THEME_CLASS.light);
  root.classList.add(THEME_CLASS[resolved]);
  window.dispatchEvent(new CustomEvent<ResolvedTheme>(THEME_CHANGE_EVENT, { detail: resolved }));
  return resolved;
};

/** 持久化用户选择并立即生效。 */
export const setTheme = (mode: ThemeMode): void => {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    /* localStorage 不可用时仅保留内存中的选择 */
  }
  applyTheme(mode);
};

const subscribe = (onChange: () => void) => {
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
};

/** 订阅当前生效主题('light' | 'dark'),供 canvas / 图表等 JS 配色使用。 */
export const useResolvedTheme = (): ResolvedTheme =>
  useSyncExternalStore(subscribe, getResolvedTheme, () => 'dark');
