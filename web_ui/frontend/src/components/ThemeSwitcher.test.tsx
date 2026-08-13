import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeSwitcher, THEME_STORAGE_KEY } from './ThemeSwitcher';

describe('ThemeSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders 跟随系统, 浅色 and 深色 segments with 跟随系统 active by default', () => {
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '浅色' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'false');
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

  it('restores the persisted selection on render', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '深色' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('falls back to 跟随系统 for unknown stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'true');
  });
});