import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SkinSwitcher } from './SkinSwitcher';
import { UI_STYLE_STORAGE_KEY, setUiStyle } from '@/lib/uistyle';

const cockpitBtn = () => screen.getByRole('button', { name: '座舱' });
const appleBtn = () => screen.getByRole('button', { name: 'Apple' });
const htmlClassList = () => document.documentElement.classList;

describe('SkinSwitcher（座舱/Apple 分段切换）', () => {
  beforeEach(() => {
    window.localStorage.clear();
    htmlClassList().remove('ui-apple');
  });

  it('renders two segments and applies the persisted default (apple)', () => {
    render(<SkinSwitcher />);
    expect(htmlClassList().contains('ui-apple')).toBe(true);
    expect(appleBtn()).toHaveAttribute('aria-pressed', 'true');
    expect(cockpitBtn()).toHaveAttribute('aria-pressed', 'false');
    // 挂载时把默认值同步进存储
    expect(window.localStorage.getItem(UI_STYLE_STORAGE_KEY)).toBe('apple');
  });

  it('switches to cockpit on click and persists', () => {
    render(<SkinSwitcher />);
    fireEvent.click(cockpitBtn());
    expect(htmlClassList().contains('ui-apple')).toBe(false);
    expect(cockpitBtn()).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem(UI_STYLE_STORAGE_KEY)).toBe('cockpit');
  });

  it('switches back to apple on second click', () => {
    render(<SkinSwitcher />);
    fireEvent.click(cockpitBtn());
    fireEvent.click(appleBtn());
    expect(htmlClassList().contains('ui-apple')).toBe(true);
    expect(appleBtn()).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem(UI_STYLE_STORAGE_KEY)).toBe('apple');
  });

  it('restores a persisted cockpit choice on mount', () => {
    window.localStorage.setItem(UI_STYLE_STORAGE_KEY, 'cockpit');
    render(<SkinSwitcher />);
    expect(htmlClassList().contains('ui-apple')).toBe(false);
    expect(cockpitBtn()).toHaveAttribute('aria-pressed', 'true');
  });

  it('treats unknown stored values as the apple default', () => {
    window.localStorage.setItem(UI_STYLE_STORAGE_KEY, 'donkey');
    render(<SkinSwitcher />);
    expect(htmlClassList().contains('ui-apple')).toBe(true);
    expect(window.localStorage.getItem(UI_STYLE_STORAGE_KEY)).toBe('apple');
  });

  it('broadcasts a CustomEvent so canvas/chart consumers can react', () => {
    const seen: string[] = [];
    window.addEventListener('donkeydrifter:ui-style-changed', (e) => {
      seen.push((e as CustomEvent<string>).detail);
    });
    render(<SkinSwitcher />);
    fireEvent.click(cockpitBtn());
    fireEvent.click(appleBtn());
    expect(seen).toEqual(['apple', 'cockpit', 'apple']);
  });

  it('setUiStyle drives the same <html> class without rendering the switcher', () => {
    setUiStyle('cockpit');
    expect(htmlClassList().contains('ui-apple')).toBe(false);
    setUiStyle('apple');
    expect(htmlClassList().contains('ui-apple')).toBe(true);
  });
});
