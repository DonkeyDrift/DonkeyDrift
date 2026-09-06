import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ZcodeRemoteLink, ZCODE_REMOTE_STORAGE_KEY } from './ZcodeRemoteLink';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

// 占位链接（安全红线：测试里只允许占位示例，绝不出现真实远程链接凭证）
const STORED_URL = 'https://zcode.z.ai/remote/v4';
const UPDATED_URL = 'https://zcode.z.ai/remote/v4#updated-placeholder';

const renderButton = () => {
  render(<ZcodeRemoteLink />);
  return screen.getByRole('button', { name: 'common.zcodeRemote.label' });
};

// 单击动作有 300ms 去抖延迟（等待可能到来的双击），测试用假定时器推进
const clickAndFlush = (btn: HTMLElement) => {
  fireEvent.click(btn);
  act(() => {
    vi.advanceTimersByTime(400);
  });
};

describe('ZcodeRemoteLink', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('renders with the de-emphasized entry style and the click/double-click hint title', () => {
    const btn = renderButton();
    expect(btn).toHaveAttribute('title', 'common.zcodeRemote.title');
    expect(btn.className).toContain('text-xs');
    expect(btn.className).toContain('text-zinc-500');
  });

  it('prompts, saves and opens the link when none is stored', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.zcodeRemote.prompt');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBe(STORED_URL);
    expect(openSpy).toHaveBeenCalledWith(STORED_URL, '_blank', 'noopener');
  });

  it('opens the stored link directly without prompting', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(STORED_URL, '_blank', 'noopener');
  });

  it('re-prompts and updates the stored link on double click (single click suppressed)', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(UPDATED_URL);
    const btn = renderButton();
    // 浏览器双击事件序列：click → click → dblclick
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.doubleClick(btn);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(promptSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBe(UPDATED_URL);
    // 只打开新链接一次，单击的旧链接被去抖抑制
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(UPDATED_URL, '_blank', 'noopener');
  });

  it('alerts and neither saves nor opens a non-https link', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue('http://zcode.z.ai/remote/v4');
    clickAndFlush(renderButton());
    expect(alertSpy).toHaveBeenCalledWith('common.zcodeRemote.invalid');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('does nothing when the prompt is cancelled', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue(null);
    clickAndFlush(renderButton());
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(openSpy).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});
