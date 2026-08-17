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

/** 设置系统深色偏好并触发 change 事件(模拟系统主题切换,act 内触发使订阅方同步重渲)。 */
const setSystemDark = (dark: boolean) => {
  systemDark = dark;
  act(() => {
    systemThemeChangeHandlers.forEach((handler) => handler({ matches: dark }));
  });
};

describe('ThemeSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('theme-mus4', 'theme-light');
    systemDark = true;
    window.matchMedia = vi.fn(matchMediaMock) as unknown as typeof window.matchMedia;
  });

  it('renders a single toggle button showing the moon icon in dark mode', () => {
    render(<ThemeSwitcher />);
    const button = screen.getByRole('button', { name: '切换到浅色主题' });
    expect(button).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the sun icon when the resolved theme is light', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '切换到深色主题' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
  });

  it('click toggles dark to light and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '切换到浅色主题' }));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    expect(screen.getByRole('button', { name: '切换到深色主题' })).toBeInTheDocument();
  });

  it('click again toggles back to dark and persists the selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '切换到浅色主题' }));
    fireEvent.click(screen.getByRole('button', { name: '切换到深色主题' }));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(screen.getByRole('button', { name: '切换到浅色主题' })).toBeInTheDocument();
  });

  it('follows the system theme in real time when nothing is stored', () => {
    render(<ThemeSwitcher />);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(screen.getByRole('button', { name: '切换到浅色主题' })).toBeInTheDocument();
    setSystemDark(false);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(screen.getByRole('button', { name: '切换到深色主题' })).toBeInTheDocument();
    setSystemDark(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(screen.getByRole('button', { name: '切换到浅色主题' })).toBeInTheDocument();
  });

  it('stops following the system theme after a manual click', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '切换到浅色主题' }));
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    setSystemDark(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
  });

  it('falls back to following the system for unknown stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    render(<ThemeSwitcher />);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('unknown');
    setSystemDark(false);
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
  });
});
