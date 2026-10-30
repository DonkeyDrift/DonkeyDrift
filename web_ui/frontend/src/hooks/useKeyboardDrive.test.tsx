import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useKeyboardDrive } from './useKeyboardDrive';

const HookProbe: React.FC<{ onChange: (a: number, t: number) => void }> = ({ onChange }) => {
  useKeyboardDrive({ enabled: true, onChange });
  return null;
};

const lastCall = (fn: ReturnType<typeof vi.fn>): [number, number] =>
  fn.mock.calls.at(-1) as [number, number];

describe('useKeyboardDrive', () => {
  it('按住 I 油门爬升，松开回中', async () => {
    const onChange = vi.fn();
    render(<HookProbe onChange={onChange} />);

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }));
    });
    await waitFor(() => expect(lastCall(onChange)[1]).toBeGreaterThan(0));

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keyup', { key: 'i' }));
    });
    await waitFor(() => expect(lastCall(onChange)[1]).toBe(0));
  });

  it('窗口 blur（alt-tab/点其它窗口，keyup 永不触发）时按住的键全清，油门自动收回 0（#508）', async () => {
    const onChange = vi.fn();
    render(<HookProbe onChange={onChange} />);

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }));
    });
    await waitFor(() => expect(lastCall(onChange)[1]).toBeGreaterThan(0.1));

    // 不发 keyup，直接失焦：四键全清后由回中逻辑逐帧收回 0
    act(() => {
      window.dispatchEvent(new Event('blur'));
    });
    await waitFor(() => expect(lastCall(onChange)[1]).toBe(0), { timeout: 2000 });
  });
});
