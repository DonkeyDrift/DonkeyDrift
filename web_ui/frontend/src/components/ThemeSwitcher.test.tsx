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

const hasIcon = (name: 'monitor' | 'sun' | 'moon') =>
  getButton().querySelector(`svg.lucide-${name}`);

describe('ThemeSwitcher（三态：跟随系统 / 浅色 / 深色）', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('theme-mus4', 'theme-light');
    systemDark = true;
    window.matchMedia = vi.fn(matchMediaMock) as unknown as typeof window.matchMedia;
  });

  it('默认跟随系统：系统为深色时显示跟随系统图标并应用深色皮肤', () => {
    render(<ThemeSwitcher />);
    expect(hasIcon('monitor')).not.toBeNull();
    expect(hasIcon('sun')).toBeNull();
    expect(hasIcon('moon')).toBeNull();
    expect(getButton()).toHaveAttribute('aria-label', '跟随系统主题（当前深色），点击切换到浅色');
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('默认跟随系统：系统为浅色时应用浅色皮肤并显示跟随系统图标', () => {
    setSystemDark(false);
    render(<ThemeSwitcher />);
    expect(hasIcon('monitor')).not.toBeNull();
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(getButton()).toHaveAttribute('aria-label', '跟随系统主题（当前浅色），点击切换到浅色');
  });

  it('首次点击从跟随系统切到浅色并持久化', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(getButton());
    expect(hasIcon('sun')).not.toBeNull();
    expect(hasIcon('monitor')).toBeNull();
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('第二次点击切到深色并持久化', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(getButton()); // 跟随系统 → 浅色
    fireEvent.click(getButton()); // 浅色 → 深色
    expect(hasIcon('moon')).not.toBeNull();
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('第三次点击切回跟随系统并持久化 system，随后恢复跟随系统变化', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(getButton()); // → 浅色
    fireEvent.click(getButton()); // → 深色
    fireEvent.click(getButton()); // → 跟随系统
    expect(hasIcon('monitor')).not.toBeNull();
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('system');
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    act(() => setSystemDark(false));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(hasIcon('monitor')).not.toBeNull();
  });

  it('跟随系统模式下随系统深浅色实时切换且不写入持久化', () => {
    render(<ThemeSwitcher />);
    expect(hasIcon('monitor')).not.toBeNull();
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    act(() => setSystemDark(false));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(hasIcon('monitor')).not.toBeNull();
    // 跟随系统期间不写入持久化选择,仅手动单击才存储
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    act(() => setSystemDark(true));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
  });

  it('手动选择浅色后不再跟随系统变化', () => {
    render(<ThemeSwitcher />); // 系统深色
    fireEvent.click(getButton()); // → 显式浅色
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    act(() => setSystemDark(false)); // 系统变浅色也不影响显式选择
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(hasIcon('sun')).not.toBeNull();
    act(() => setSystemDark(true)); // 系统再变深色仍保持浅色
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('手动选择深色后不再跟随系统变化', () => {
    setSystemDark(false);
    render(<ThemeSwitcher />); // 系统浅色
    fireEvent.click(getButton()); // → 显式浅色（与当前视觉一致）
    fireEvent.click(getButton()); // → 深色
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(hasIcon('moon')).not.toBeNull();
    act(() => setSystemDark(true)); // 系统变深色也不影响显式选择
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('挂载时按已持久化选择应用皮肤与图标', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(hasIcon('sun')).not.toBeNull();
  });

  it('未知存储值回退到跟随系统', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    setSystemDark(false);
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(hasIcon('monitor')).not.toBeNull();
  });
});
