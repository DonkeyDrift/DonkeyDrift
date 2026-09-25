import '@testing-library/jest-dom/vitest';
import React from 'react';
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GamepadConfigPanel } from './GamepadConfigPanel';
import { useGamepadStore } from '../../store/useGamepadStore';

describe('GamepadConfigPanel', () => {
  beforeEach(() => {
    useGamepadStore.getState().reset();
    // 已绑定手柄：避免首次连接自动弹出校准向导
    useGamepadStore.getState().bindPad('pad-1');
  });

  it('展开后显示 Z 轴预设与实时轴监视', () => {
    render(
      <GamepadConfigPanel
        axes={[0, 0.12, -0.4, 0]}
        padId="pad-1"
        mapping="standard"
        connected
        defaultOpen
      />,
    );

    expect(screen.getByText('手柄设置')).toBeInTheDocument();
    const presetButton = screen.getByRole('button', { name: 'Z 轴（你的手柄）' });
    expect(presetButton).toHaveClass('text-cyan-300');
    expect(screen.getByText('轴监视')).toBeInTheDocument();
  });

  it('切换预设会更新 store', () => {
    render(
      <GamepadConfigPanel axes={[0, 0, 0, 0]} padId="pad-1" connected defaultOpen />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Xbox / PS' }));
    expect(useGamepadStore.getState().config.steering.axis).toBe(0);
    expect(useGamepadStore.getState().config.preset).toBe('xbox');
  });

  it('勾选反向会写入 steering.invert', () => {
    render(
      <GamepadConfigPanel axes={[0, 0, 0, 0]} padId="pad-1" connected defaultOpen />,
    );

    fireEvent.click(screen.getByLabelText('反向（左右互换）'));
    expect(useGamepadStore.getState().config.steering.invert).toBe(true);
  });

  it('未连接手柄时显示未检测提示', () => {
    render(<GamepadConfigPanel axes={[]} connected={false} defaultOpen />);
    expect(screen.getByText('未检测到手柄')).toBeInTheDocument();
  });
});
