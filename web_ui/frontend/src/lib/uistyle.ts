import { useSyncExternalStore } from 'react';

/**
 * UI 风格维度（座舱 / Apple），与主题维度（深/浅，lib/theme.ts）正交：
 * 切换 <html> 的 `ui-apple` class，两个 theme-*.css 里的
 * `html.theme-*.ui-apple { --* }` 纯变量覆写块随即生效，规则体零改动。
 * 与主题不同：风格选择持久化在 localStorage（刷新/重进保持），默认 apple。
 */
export type UiStyle = 'cockpit' | 'apple';

export const UI_STYLE_STORAGE_KEY = 'donkeydrifter.ui.style';
export const UI_STYLE_CLASS = 'ui-apple';

const UI_STYLE_CHANGE_EVENT = 'donkeydrifter:ui-style-changed';

const normalizeUiStyle = (value: string | null): UiStyle =>
  value === 'cockpit' ? 'cockpit' : 'apple';

/** 读取持久化的风格选择；未存/非法值/localStorage 不可用时回退默认 'apple'。 */
export const readStoredUiStyle = (): UiStyle => {
  try {
    return normalizeUiStyle(window.localStorage.getItem(UI_STYLE_STORAGE_KEY));
  } catch {
    return 'apple';
  }
};

/** 模块级内存态，镜像 localStorage；setUiStyle 之外直接改存储时以 applyUiStyle 为准。 */
let currentUiStyle: UiStyle = readStoredUiStyle();

/** 从 <html> class 实况读取当前生效风格（订阅快照，与主题 getResolvedTheme 同款）。 */
export const getUiStyle = (): UiStyle =>
  document.documentElement.classList.contains(UI_STYLE_CLASS) ? 'apple' : 'cockpit';

/** 切换 <html> 的 ui-apple class、持久化并广播风格变化(供 canvas/图表等 JS 配色订阅)。 */
export const applyUiStyle = (style: UiStyle): UiStyle => {
  currentUiStyle = style;
  document.documentElement.classList.toggle(UI_STYLE_CLASS, style === 'apple');
  try {
    window.localStorage.setItem(UI_STYLE_STORAGE_KEY, style);
  } catch {
    /* localStorage 不可用:保持内存态 */
  }
  window.dispatchEvent(new CustomEvent<UiStyle>(UI_STYLE_CHANGE_EVENT, { detail: style }));
  return style;
};

export const setUiStyle = (style: UiStyle): void => {
  applyUiStyle(style);
};

const subscribe = (onChange: () => void) => {
  window.addEventListener(UI_STYLE_CHANGE_EVENT, onChange);
  return () => window.removeEventListener(UI_STYLE_CHANGE_EVENT, onChange);
};

/** 订阅当前生效风格('cockpit' | 'apple'),供 canvas / 图表等 JS 配色使用。 */
export const useUiStyle = (): UiStyle =>
  useSyncExternalStore(subscribe, getUiStyle, () => 'apple');
