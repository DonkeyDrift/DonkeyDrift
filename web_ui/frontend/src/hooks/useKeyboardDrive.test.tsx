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

const mountEditable = (kind: 'input' | 'textarea' | 'contenteditable'): HTMLElement => {
  let el: HTMLElement;
  if (kind === 'contenteditable') {
    el = document.createElement('div');
    el.setAttribute('contenteditable', 'true');
    // jsdom 未实现 isContentEditable，按真实浏览器语义补上，使守卫可被触发
    Object.defineProperty(el, 'isContentEditable', { value: true });
  } else {
    el = document.createElement(kind);
  }
  document.body.appendChild(el);
  return el;
};

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

  it.each(['input', 'textarea', 'contenteditable'] as const)(
    '%s 中按 I/J 的 keydown 不产生驾驶量（#512）',
    async (kind) => {
      const onChange = vi.fn();
      render(<HookProbe onChange={onChange} />);

      const el = mountEditable(kind);
      try {
        act(() => {
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'i', bubbles: true }));
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }));
        });
        // 跑若干帧：editable 内的按键不应推动油门或转向
        await new Promise((resolve) => setTimeout(resolve, 150));
        expect(onChange.mock.calls.every(([a, t]) => a === 0 && t === 0)).toBe(true);
      } finally {
        el.remove();
      }
    },
  );

  it('先按住 I 再聚焦输入框，之后 keyup 必须仍能释放油门（#512）', async () => {
    const onChange = vi.fn();
    render(<HookProbe onChange={onChange} />);

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'i' }));
    });
    await waitFor(() => expect(lastCall(onChange)[1]).toBeGreaterThan(0.1));

    const input = mountEditable('input');
    try {
      // 焦点切到输入框后松开：keyup 的 target 是输入框，不能被过滤，否则油门残留
      act(() => {
        input.dispatchEvent(new KeyboardEvent('keyup', { key: 'i', bubbles: true }));
      });
      await waitFor(() => expect(lastCall(onChange)[1]).toBe(0), { timeout: 2000 });
    } finally {
      input.remove();
    }
  });
});
