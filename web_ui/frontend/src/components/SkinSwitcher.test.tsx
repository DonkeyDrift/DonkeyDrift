import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SkinSwitcher } from './SkinSwitcher';
import { useUiPrefsStore } from '../store/useUiPrefsStore';

describe('SkinSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiPrefsStore.setState({ skin: 'donkey' });
  });

  it('渲染出 ESP32 UI 与 Donkey UI 两个分段', () => {
    render(<SkinSwitcher />);

    expect(screen.getByRole('button', { name: 'ESP32 UI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Donkey UI' })).toBeInTheDocument();
  });

  it('默认激活 Donkey UI 分段', () => {
    render(<SkinSwitcher />);

    const donkey = screen.getByRole('button', { name: 'Donkey UI' });
    const esp32 = screen.getByRole('button', { name: 'ESP32 UI' });

    expect(donkey).toHaveAttribute('aria-pressed', 'true');
    expect(donkey.className).toContain('bg-zinc-950');
    expect(esp32).toHaveAttribute('aria-pressed', 'false');
    expect(esp32.className).not.toContain('bg-zinc-950');
  });

  it('点击 ESP32 UI 分段后切换为 mus4 皮肤且激活态跟随', () => {
    render(<SkinSwitcher />);

    fireEvent.click(screen.getByRole('button', { name: 'ESP32 UI' }));

    expect(useUiPrefsStore.getState().skin).toBe('mus4');

    const esp32 = screen.getByRole('button', { name: 'ESP32 UI' });
    expect(esp32).toHaveAttribute('aria-pressed', 'true');
    expect(esp32.className).toContain('bg-zinc-950');
    expect(screen.getByRole('button', { name: 'Donkey UI' })).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });

  it('点击 Donkey UI 分段后切回 donkey 默认皮肤', () => {
    useUiPrefsStore.setState({ skin: 'mus4' });
    render(<SkinSwitcher />);

    fireEvent.click(screen.getByRole('button', { name: 'Donkey UI' }));

    expect(useUiPrefsStore.getState().skin).toBe('donkey');
    expect(screen.getByRole('button', { name: 'Donkey UI' })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });
});
