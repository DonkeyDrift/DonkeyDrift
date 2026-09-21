import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { DriveModeSelector, driveModeToRcMode, rcModeToDriveMode } from './DriveModeSelector';
import { applyTheme } from '@/lib/theme';

describe('DriveModeSelector', () => {
  afterEach(() => {
    applyTheme('dark');
  });
  it('渲染手动/半自动/全自动三个模式按钮', () => {
    render(<DriveModeSelector value="user" onChange={vi.fn()} />);

    expect(screen.getByRole('button', { name: '手动' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '半自动' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '全自动' })).toBeInTheDocument();
  });

  it('点击按钮时触发 onChange', () => {
    const onChange = vi.fn();
    render(<DriveModeSelector value="user" onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: '全自动' }));

    expect(onChange).toHaveBeenCalledWith('local');
  });

  it('激活按钮按 ESP32 模式配色着色（手动绿/半自动琥珀/全自动蓝，语义类映射 --ok/--warn/--accent）', () => {
    const { rerender } = render(<DriveModeSelector value="user" onChange={vi.fn()} />);

    expect(screen.getByRole('button', { name: '手动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '手动' })).toHaveAttribute('data-mode', 'user');
    expect(screen.getByRole('button', { name: '手动' })).toHaveClass('bg-emerald-500/25', 'text-emerald-400');
    expect(screen.getByRole('button', { name: '半自动' })).not.toHaveClass('mode-active');

    rerender(<DriveModeSelector value="local_angle" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '半自动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '半自动' })).toHaveClass('bg-amber-400/10', 'text-amber-400');

    rerender(<DriveModeSelector value="local" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '全自动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '全自动' })).toHaveClass('bg-cyan-600/20', 'text-cyan-400');
  });

  it('配色走语义类 + CSS 变量：切主题/风格类名不变，无硬编码 hex', () => {
    render(<DriveModeSelector value="local" onChange={vi.fn()} />);
    const button = screen.getByRole('button', { name: '全自动' });
    const darkClassName = button.className;
    expect(darkClassName).not.toContain('#');

    act(() => {
      applyTheme('light');
    });
    // 浅色/深色/Apple 象限配色由 theme-*.css 变量接管，类名保持一致
    expect(button.className).toBe(darkClassName);

    act(() => {
      applyTheme('dark');
    });
    expect(button.className).toBe(darkClassName);
  });

  it('disabled 时按钮不可点击', () => {
    const onChange = vi.fn();
    render(<DriveModeSelector value="user" onChange={onChange} disabled />);

    const button = screen.getByRole('button', { name: '半自动' });
    expect(button).toBeDisabled();

    fireEvent.click(button);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('DriveMode mapping helpers', () => {
  it('driveModeToRcMode 映射 user/local_angle/local 到 0/1/2', () => {
    expect(driveModeToRcMode('user')).toBe(0);
    expect(driveModeToRcMode('local_angle')).toBe(1);
    expect(driveModeToRcMode('local')).toBe(2);
  });

  it('rcModeToDriveMode 映射 0/1/2 到 user/local_angle/local，非法值回退 user', () => {
    expect(rcModeToDriveMode(0)).toBe('user');
    expect(rcModeToDriveMode(1)).toBe('local_angle');
    expect(rcModeToDriveMode(2)).toBe('local');
    expect(rcModeToDriveMode(3)).toBe('user');
    expect(rcModeToDriveMode(-1)).toBe('user');
  });
});
