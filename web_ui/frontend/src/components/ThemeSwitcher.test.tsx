import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeSwitcher, THEME_STORAGE_KEY } from './ThemeSwitcher';

describe('ThemeSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove('theme-mus4', 'theme-light');
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

  it('applies the skin class on <html> for each selection', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '浅色' }));
    expect(document.documentElement.classList.contains('theme-light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '深色' }));
    expect(document.documentElement.classList.contains('theme-mus4')).toBe(true);
    expect(document.documentElement.classList.contains('theme-light')).toBe(false);
  });

  it('resolves 跟随系统 to the dark skin for now (跟随系统 not implemented yet)', () => {
    render(<ThemeSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }));
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

  it('falls back to 跟随系统 for unknown stored values', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'unknown');
    render(<ThemeSwitcher />);
    expect(screen.getByRole('button', { name: '跟随系统' })).toHaveAttribute('aria-pressed', 'true');
  });
});