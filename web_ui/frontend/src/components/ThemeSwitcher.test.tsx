import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

describe('ThemeSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('theme-mus4', 'theme-light');
    systemDark = true;
    window.matchMedia = vi.fn(matchMediaMock) as unknown as typeof window.matchMedia;
  });

  it('renders 跟随系统, 浅色 and 深色 segments with 深色 active by default', () => {
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '浅色' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'false');
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
  });

  it('switches to 浅色 on click and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '浅色' }));
    expect(screen.getByRole('button', { name: '浅色' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'false');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('switches to 深色 on click and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '深色' }));
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'false');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('applies the skin class on <html> for each selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '浅色' }));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '深色' }));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('resolves 跟随系统 to the dark skin when the system prefers dark', () => {
    setSystemDark(true);
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('resolves 跟随系统 to the light skin when the system prefers light', () => {
    setSystemDark(false);
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
  });

  it('follows system theme changes while 跟随系统 is selected', () => {
    setSystemDark(true);
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    setSystemDark(false);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    setSystemDark(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('does not follow system theme changes by default', () => {
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    setSystemDark(false);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('applies the persisted skin class on mount', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
  });

  it('restores the persisted selection on render', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('falls back to 深色 for unknown stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true');
  });
});