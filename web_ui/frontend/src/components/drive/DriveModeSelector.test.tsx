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

  it('激活按钮按 ESP32 模式配色着色（手动绿/半自动琥珀/全自动蓝）', () => {
    const { rerender } = render(<DriveModeSelector value="user" onChange={vi.fn()} />);

    expect(screen.getByRole('button', { name: '手动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '手动' })).toHaveAttribute('data-mode', 'user');
    expect(screen.getByRole('button', { name: '手动' }).className).toContain('#39d98a');
    expect(screen.getByRole('button', { name: '半自动' })).not.toHaveClass('mode-active');

    rerender(<DriveModeSelector value="local_angle" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '半自动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '半自动' }).className).toContain('#ffcc66');

    rerender(<DriveModeSelector value="local" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '全自动' })).toHaveClass('mode-active');
    expect(screen.getByRole('button', { name: '全自动' }).className).toContain('#5cc8ff');
  });

  it('浅色主题下激活按钮使用同色相墨色配色,切回深色恢复原配色', () => {
    const { rerender } = render(<DriveModeSelector value="user" onChange={vi.fn()} />);

    act(() => {
      applyTheme('light');
    });

    expect(screen.getByRole('button', { name: '手动' }).className).toContain('#1fae6b');
    expect(screen.getByRole('button', { name: '手动' }).className).not.toContain('#39d98a');

    rerender(<DriveModeSelector value="local_angle" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '半自动' }).className).toContain('#b57d0e');
    expect(screen.getByRole('button', { name: '半自动' }).className).not.toContain('#ffcc66');

    rerender(<DriveModeSelector value="local" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: '全自动' }).className).toContain('#0c9bd6');
    expect(screen.getByRole('button', { name: '全自动' }).className).not.toContain('#5cc8ff');

    act(() => {
      applyTheme('dark');
    });
    expect(screen.getByRole('button', { name: '全自动' }).className).toContain('#5cc8ff');
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
