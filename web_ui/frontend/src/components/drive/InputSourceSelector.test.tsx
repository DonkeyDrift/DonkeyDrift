import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InputSourceSelector } from './InputSourceSelector';

describe('InputSourceSelector', () => {
  it('默认只显示当前选中的输入源', () => {
    render(<InputSourceSelector value="joystick" onChange={vi.fn()} />);

    expect(screen.getByText('摇杆')).toBeInTheDocument();
    expect(screen.queryByText('键盘')).not.toBeInTheDocument();
    expect(screen.queryByText('手柄')).not.toBeInTheDocument();
    expect(screen.queryByText('陀螺仪')).not.toBeInTheDocument();
  });

  it('点击按钮时展开并显示其余选项', () => {
    render(<InputSourceSelector value="joystick" onChange={vi.fn()} />);

    fireEvent.click(screen.getByText('摇杆'));

    expect(screen.getByText('键盘')).toBeInTheDocument();
    expect(screen.getByText('手柄')).toBeInTheDocument();
    expect(screen.getByText('陀螺仪')).toBeInTheDocument();
    expect(screen.getByText('ESP32 手柄')).toBeInTheDocument();
  });

  it('可选择 ESP32 手柄输入源', () => {
    const onChange = vi.fn();
    render(<InputSourceSelector value="joystick" onChange={onChange} />);

    fireEvent.click(screen.getByText('摇杆'));
    fireEvent.click(screen.getByText('ESP32 手柄'));

    expect(onChange).toHaveBeenCalledWith('esp32');
  });

  it('选择新输入源后触发 onChange 并收起菜单', () => {
    const onChange = vi.fn();
    const { rerender } = render(<InputSourceSelector value="joystick" onChange={onChange} />);

    fireEvent.click(screen.getByText('摇杆'));
    fireEvent.click(screen.getByText('键盘'));

    expect(onChange).toHaveBeenCalledWith('keyboard');

    rerender(<InputSourceSelector value="keyboard" onChange={onChange} />);

    expect(screen.getByText('键盘')).toBeInTheDocument();
    expect(screen.queryByText('摇杆')).not.toBeInTheDocument();
  });

  it('未连接手柄时手柄选项不可选', () => {
    const onChange = vi.fn();
    render(<InputSourceSelector value="joystick" onChange={onChange} gamepadConnected={false} />);

    fireEvent.click(screen.getByText('摇杆'));

    const gamepadButton = screen.getByRole('button', { name: '手柄' });
    expect(gamepadButton).toBeDisabled();

    fireEvent.click(gamepadButton);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('已连接手柄时显示绿色指示灯', () => {
    render(<InputSourceSelector value="gamepad" onChange={vi.fn()} gamepadConnected />);

    const indicator = document.querySelector('.bg-emerald-400');
    expect(indicator).toBeInTheDocument();
  });

  it('在菜单选项上按下指针（菜单内部）时保持展开', () => {
    render(<InputSourceSelector value="joystick" onChange={vi.fn()} />);

    fireEvent.click(screen.getByText('摇杆'));

    const keyboardButton = screen.getByRole('button', { name: '键盘' });
    fireEvent.pointerDown(keyboardButton);

    expect(keyboardButton).toBeInTheDocument();
    expect(screen.getByText('手柄')).toBeInTheDocument();
  });

  it('按 Escape 后收起菜单', () => {
    render(<InputSourceSelector value="joystick" onChange={vi.fn()} />);

    fireEvent.click(screen.getByText('摇杆'));
    expect(screen.getByText('键盘')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByText('键盘')).not.toBeInTheDocument();
  });

  it('点击菜单外部后收起菜单', () => {
    render(<InputSourceSelector value="joystick" onChange={vi.fn()} />);

    fireEvent.click(screen.getByText('摇杆'));
    expect(screen.getByText('键盘')).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByText('键盘')).not.toBeInTheDocument();
  });
});
