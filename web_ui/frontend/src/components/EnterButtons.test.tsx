import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DonkeyEntryLink, DrifterConsoleEntryLink, KimiCodeWebEntryLink, DshEntryLink, ZCodeEntryLink, ZCODE_REMOTE_STORAGE_KEY } from './EnterButtons';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));
vi.mock('@/services/api', () => ({
  launchKimiCodeWeb: vi.fn(),
  launchDsh: vi.fn(),
  getDonkeyUrl: vi.fn(() => 'http://localhost:8090/'),
}));
import { launchDsh, launchKimiCodeWeb } from '@/services/api';
const mockLaunchKimi = vi.mocked(launchKimiCodeWeb);
const mockLaunchDsh = vi.mocked(launchDsh);
beforeEach(() => { vi.clearAllMocks(); });

describe('entry link components (Issue #175 nav-link style)', () => {
  it('renders each entry with the de-emphasized advanced link style', () => {
    render(
      <MemoryRouter>
        <DonkeyEntryLink />
        <DrifterConsoleEntryLink />
        <KimiCodeWebEntryLink />
        <DshEntryLink />
        <ZCodeEntryLink />
      </MemoryRouter>,
    );
    // Drifter Console 已改为 SPA 内路由链接（Issue #234），其余两个仍是按钮入口
    const drifterLink = screen.getByText('common.enterButtons.drifterConsole').closest('a');
    expect(drifterLink).toBeInTheDocument();
    expect(drifterLink?.className).toContain('text-xs');
    expect(drifterLink?.className).toContain('text-zinc-500');
    for (const label of ['common.enterButtons.kimiCodeWeb', 'common.enterButtons.dsh', 'common.enterButtons.zcode']) {
      const btn = screen.getByText(label).closest('button');
      expect(btn).toBeInTheDocument();
      // 弱化处理：更小字号 + 更淡颜色，一眼可辨为高级选项
      expect(btn?.className).toContain('text-xs');
      expect(btn?.className).toContain('text-zinc-500');
    }
  });
});

describe('DonkeyEntryLink', () => {
  it('links to the embedded Donkey menu route in the current tab', () => {
    render(
      <MemoryRouter>
        <DonkeyEntryLink />
      </MemoryRouter>,
    );
    const link = screen.getByText('common.enterButtons.donkey').closest('a');
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/donkey');
    expect(link).not.toHaveAttribute('target');
  });

  it('highlights cyan when the current route is /donkey', () => {
    render(
      <MemoryRouter initialEntries={['/donkey']}>
        <DonkeyEntryLink />
      </MemoryRouter>,
    );
    const link = screen.getByText('common.enterButtons.donkey').closest('a');
    expect(link?.className).toContain('text-cyan-500');
  });
});

describe('DrifterConsoleEntryLink', () => {
  it('links to the embedded Drifter Console route in the current tab', () => {
    render(
      <MemoryRouter>
        <DrifterConsoleEntryLink />
      </MemoryRouter>,
    );
    const link = screen.getByText('common.enterButtons.drifterConsole').closest('a');
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/console');
  });
});

describe('KimiCodeWebEntryLink', () => {
  it('opens Kimi Code Web URL in the pre-opened tab on success', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    mockLaunchKimi.mockResolvedValue({ status: 'ok', url: 'https://kimi.example/web#token=x' });
    render(<KimiCodeWebEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.kimiCodeWeb'));
    expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank');
    await waitFor(() => { expect(fakeWin.location.href).toBe('https://kimi.example/web#token=x'); });
    openSpy.mockRestore();
  });
  it('closes the tab and alerts on failure', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    mockLaunchKimi.mockResolvedValue({ status: 'error', error: 'boom' });
    render(<KimiCodeWebEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.kimiCodeWeb'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    expect(fakeWin.close).toHaveBeenCalled();
    openSpy.mockRestore();
    alertSpy.mockRestore();
  });
});

describe('DshEntryLink', () => {
  it('opens DeepSeek Harness URL in the pre-opened tab on success', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    mockLaunchDsh.mockResolvedValue({ status: 'ok', url: 'http://192.168.3.57:43749' });
    render(<DshEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.dsh'));
    expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank');
    await waitFor(() => { expect(fakeWin.location.href).toBe('http://192.168.3.57:43749'); });
    openSpy.mockRestore();
  });
  it('closes the tab and alerts on failure', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    mockLaunchDsh.mockResolvedValue({ status: 'error', error: 'boom' });
    render(<DshEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.dsh'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    expect(fakeWin.close).toHaveBeenCalled();
    openSpy.mockRestore();
    alertSpy.mockRestore();
  });
});

describe('ZCodeEntryLink（远程控制链接行为，有意替代原 launcher 网页终端）', () => {
  // 占位链接（安全红线：测试里只允许占位示例，绝不出现真实远程链接凭证）
  const STORED_URL = 'https://zcode.z.ai/remote/v4';
  const UPDATED_URL = 'https://zcode.z.ai/remote/v4#updated-placeholder';

  const renderButton = () => {
    render(<ZCodeEntryLink />);
    return screen.getByRole('button', { name: 'common.enterButtons.zcode' });
  };

  // 单击动作有 300ms 去抖延迟（等待可能到来的双击），测试用假定时器推进
  const clickAndFlush = (btn: HTMLElement) => {
    fireEvent.click(btn);
    act(() => {
      vi.advanceTimersByTime(400);
    });
  };

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps the ZCode label and carries the remote-control hint title', () => {
    expect(renderButton()).toHaveAttribute('title', 'common.enterButtons.zcodeTitle');
  });

  it('prompts, saves and opens the link when none is stored', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt');
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
    expect(alertSpy).toHaveBeenCalledWith('common.enterButtons.zcodeInvalid');
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
