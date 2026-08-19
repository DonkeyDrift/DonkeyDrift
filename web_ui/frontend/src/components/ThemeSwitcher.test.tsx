import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ThemeSwitcher, THEME_STORAGE_KEY } from './ThemeSwitcher';

type SystemThemeChangeHandler = (event: { matches: boolean }) => void;

// jsdom 无 matchMedia 实现;mock 成共享同一监听器集合的对象,
// 使 theme.ts 的模块级单例监听在整个测试文件内始终可达。
let systemDark = true;
const systemThemeChangeHandlers = new Set<SystemThemeChangeHandler>();

const matchMediaMock = (query: string): MediaQueryList =>
  ({
    matches: query === '(prefers-color-scheme: dark)' ? systemDark : false,
    media: query,
    onchange: null,
    addEventListener: (_type: string, handler: SystemThemeChangeHandler) => {
      systemThemeChangeHandlers.add(handler);
    },
    removeEventListener: (_type: string, handler: SystemThemeChangeHandler) => {
      systemThemeChangeHandlers.delete(handler);
    },
    addListener: (handler: SystemThemeChangeHandler) => {
      systemThemeChangeHandlers.add(handler);
    },
    removeListener: (handler: SystemThemeChangeHandler) => {
      systemThemeChangeHandlers.delete(handler);
    },
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;

/** 设置系统深色偏好并触发 change 事件(模拟系统主题切换)。 */
const setSystemDark = (dark: boolean) => {
  systemDark = dark;
  systemThemeChangeHandlers.forEach((handler) => handler({ matches: dark }));
};

const getButton = () => screen.getByRole('button');

describe('ThemeSwitcher（静音式单按钮）', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('theme-mus4', 'theme-light');
    systemDark = true;
    window.matchMedia = vi.fn(matchMediaMock) as unknown as typeof window.matchMedia;
  });

  it('renders a single icon button showing the moon in dark mode', () => {
    render(<ThemeSwitcher />);
    const btn = getButton();
    expect(btn.querySelector('svg.lucide-moon')).not.toBeNull();
    expect(btn.querySelector('svg.lucide-sun')).toBeNull();
    expect(btn).toHaveAttribute('aria-label', '切换到浅色主题');
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
  });

  it('shows the sun icon and light skin when the system prefers light', () => {
    setSystemDark(false);
    render(<ThemeSwitcher />);
    const btn = getButton();
    expect(btn.querySelector('svg.lucide-sun')).not.toBeNull();
    expect(btn).toHaveAttribute('aria-label', '切换到深色主题');
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
  });

  it('toggles to light on click and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(getButton());
    expect(getButton().querySelector('svg.lucide-sun')).not.toBeNull();
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('toggles back to dark on second click and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(getButton()); // → light
    fireEvent.click(getButton()); // → dark
    expect(getButton().querySelector('svg.lucide-moon')).not.toBeNull();
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('follows system theme changes by default when nothing is stored', () => {
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(getButton().querySelector('svg.lucide-moon')).not.toBeNull();
    act(() => setSystemDark(false));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(getButton().querySelector('svg.lucide-sun')).not.toBeNull();
    // 跟随系统期间不写入持久化选择,仅手动单击才存储
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    act(() => setSystemDark(true));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(getButton().querySelector('svg.lucide-moon')).not.toBeNull();
  });

  it('stops following the system after a manual click', () => {
    setSystemDark(false);
    render(<ThemeSwitcher />);
    fireEvent.click(getButton()); // light → dark
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    act(() => setSystemDark(false)); // 系统再变也不跟随
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
  });

  it('applies the persisted skin and icon on mount', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(getButton().querySelector('svg.lucide-sun')).not.toBeNull();
  });

  it('falls back to following the system for unknown stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    setSystemDark(false);
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(getButton().querySelector('svg.lucide-sun')).not.toBeNull();
  });
});
