import { useSyncExternalStore } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_CLASS: Record<ResolvedTheme, string> = {
  dark: 'theme-mus4',
  light: 'theme-light',
};

const THEME_CHANGE_EVENT = 'donkeydrifter:theme-changed';

/** 当前主题模式，仅存内存：页面刷新/重新进入即重置为 'system'（跟随系统）。 */
let currentThemeMode: ThemeMode = 'system';

/** 读取当前主题模式（内存态）；默认 'system' 跟随系统。 */
export const readStoredTheme = (): ThemeMode => currentThemeMode;

const DARK_SCHEME_QUERY = '(prefers-color-scheme: dark)';

/** 读取系统深色偏好;matchMedia 不可用或异常时回退 dark(沿用深色现状)。 */
const getSystemTheme = (): ResolvedTheme => {
  try {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      return window.matchMedia(DARK_SCHEME_QUERY).matches ? 'dark' : 'light';
    }
  } catch {
    /* matchMedia 异常时回退深色 */
  }
  return 'dark';
};

/** 'system' 经 matchMedia 实时解析,跟随系统深色/浅色偏好。 */
export const resolveTheme = (mode: ThemeMode): ResolvedTheme =>
  mode === 'system' ? getSystemTheme() : mode;

export const getResolvedTheme = (): ResolvedTheme =>
  document.documentElement.classList.contains(THEME_CLASS.light) ? 'light' : 'dark';

let systemThemeListenerRegistered = false;

/**
 * 模块级单例:监听系统深色偏好变化。当前选择为"跟随系统"时重新 applyTheme,
 * 广播后所有 useResolvedTheme 消费方自动更新。window/matchMedia 不可用(如测试环境)时跳过。
 */
const ensureSystemThemeListener = (): void => {
  if (systemThemeListenerRegistered || typeof window === 'undefined') return;
  if (typeof window.matchMedia !== 'function') return;
  systemThemeListenerRegistered = true;
  try {
    const media = window.matchMedia(DARK_SCHEME_QUERY);
    const onSystemThemeChange = () => {
      if (readStoredTheme() === 'system') applyTheme('system');
    };
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', onSystemThemeChange);
    } else if (typeof media.addListener === 'function') {
      media.addListener(onSystemThemeChange); // 旧版 Safari 回退
    }
  } catch {
    /* 监听注册失败时保持手动切换可用 */
  }
};

/** 切换 <html> 的皮肤 class 并广播主题变化(供 canvas/图表等 JS 配色订阅)。 */
export const applyTheme = (mode: ThemeMode): ResolvedTheme => {
  ensureSystemThemeListener();
  const resolved = resolveTheme(mode);
  const root = document.documentElement;
  root.classList.remove(THEME_CLASS.dark, THEME_CLASS.light);
  root.classList.add(THEME_CLASS[resolved]);
  window.dispatchEvent(new CustomEvent<ResolvedTheme>(THEME_CHANGE_EVENT, { detail: resolved }));
  return resolved;
};

/** 更新当前主题模式（仅内存，不持久化）并立即生效。 */
export const setTheme = (mode: ThemeMode): void => {
  currentThemeMode = mode;
  applyTheme(mode);
};

const subscribe = (onChange: () => void) => {
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  return () => window.removeEventListener(THEME_CHANGE_EVENT, onChange);
};

/** 订阅当前生效主题('light' | 'dark'),供 canvas / 图表等 JS 配色使用。 */
export const useResolvedTheme = (): ResolvedTheme =>
  useSyncExternalStore(subscribe, getResolvedTheme, () => 'dark');
