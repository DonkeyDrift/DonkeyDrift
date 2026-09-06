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
  launchZcodeRemote: vi.fn(() => Promise.resolve({ status: 'ok' })),
  getDonkeyUrl: vi.fn(() => 'http://localhost:8090/'),
}));
import { launchDsh, launchKimiCodeWeb, launchZcodeRemote } from '@/services/api';
const mockLaunchKimi = vi.mocked(launchKimiCodeWeb);
const mockLaunchDsh = vi.mocked(launchDsh);
const mockLaunchZcodeRemote = vi.mocked(launchZcodeRemote);
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
  // 占位链接（安全红线：测试里只允许占位示例，绝不出现真实远程链接凭证）；
  // 有效链接带 sid/hash 持久化凭证参数（t 为生成时间戳、归一化时现拼刷新），
  // 或带 remoteControlToken（原样通过）；桌面端复制的链接参数可能跟在 # fragment 后
  const STORED_URL = 'https://zcode.z.ai/remote/v4?sid=placeholder-sid&hash=placeholder-hash&t=1';
  const UPDATED_URL = 'https://zcode.z.ai/remote/v4?sid=placeholder-sid2&hash=placeholder-hash2&t=2';
  const BARE_URL = 'https://zcode.z.ai/remote/v4';

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

  // 从 window.open 实参里取出打开 URL 的查询参数
  const openedParams = (openSpy: ReturnType<typeof vi.spyOn>) =>
    new URL(vi.mocked(openSpy).mock.calls[0][0] as string).searchParams;

  // 断言 localStorage 存入的是归一化后的链接：sid/hash 保留、t 被刷成全新毫秒戳
  const expectStored = (sid: string, hash: string, staleT: string) => {
    const stored = new URL(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY) ?? '');
    expect(stored.searchParams.get('sid')).toBe(sid);
    expect(stored.searchParams.get('hash')).toBe(hash);
    const tVal = stored.searchParams.get('t');
    expect(tVal).not.toBe(staleT);
    expect(Number(tVal)).toBeGreaterThan(0);
  };

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    mockLaunchZcodeRemote.mockResolvedValue({ status: 'ok' });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps the ZCode label and carries the remote-control hint title', () => {
    expect(renderButton()).toHaveAttribute('title', 'common.enterButtons.zcodeTitle');
  });

  it('prompts, saves, then opens a fresh-t copy of the link when none is stored', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt', '');
    expectStored('placeholder-sid', 'placeholder-hash', '1');
    // 打开的是现拼的新鲜链接：sid/hash 保留、t 已刷新（不再是存入时的 t=1）
    const params = openedParams(openSpy);
    expect(params.get('sid')).toBe('placeholder-sid');
    expect(params.get('hash')).toBe('placeholder-hash');
    expect(params.get('t')).not.toBe('1');
    // 点击时后台唤醒桌面端
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });

  it('opens a fresh-t rebuild of the stored link without prompting', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledTimes(1);
    const params = openedParams(openSpy);
    expect(params.get('sid')).toBe('placeholder-sid');
    expect(params.get('t')).not.toBe('1');
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });

  it('copies the fresh link to the clipboard on click', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    vi.spyOn(window, 'open').mockImplementation(() => null);
    clickAndFlush(renderButton());
    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = new URL(writeText.mock.calls[0][0]).searchParams;
    expect(copied.get('sid')).toBe('placeholder-sid');
    expect(copied.get('t')).not.toBe('1');
  });

  it('still opens the link when the desktop wake request fails', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    mockLaunchZcodeRemote.mockRejectedValue(new Error('launcher down'));
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    clickAndFlush(renderButton());
    expect(openSpy).toHaveBeenCalledTimes(1);
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
    expectStored('placeholder-sid2', 'placeholder-hash2', '2');
    // 只打开新链接一次，单击的旧链接被去抖抑制
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openedParams(openSpy).get('sid')).toBe('placeholder-sid2');
  });

  it('alerts and neither saves nor opens a non-https link', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue('http://zcode.z.ai/remote/v4?sid=placeholder-sid&hash=placeholder-hash');
    clickAndFlush(renderButton());
    expect(alertSpy).toHaveBeenCalledWith('common.enterButtons.zcodeInvalid');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('alerts and rejects a bare link without sid/hash params', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue(BARE_URL);
    clickAndFlush(renderButton());
    expect(alertSpy).toHaveBeenCalledWith('common.enterButtons.zcodeInvalid');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('falls back to the prompt when the stored link lacks sid/hash', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, BARE_URL);
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledTimes(1);
    expectStored('placeholder-sid', 'placeholder-hash', '1');
    expect(openSpy).toHaveBeenCalledTimes(1);
  });

  it('accepts a desktop-copied link whose params live in the # fragment', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    vi.spyOn(window, 'prompt').mockReturnValue(
      'https://zcode.z.ai/remote/v4#sid=frag-sid&hash=frag-hash&t=9',
    );
    clickAndFlush(renderButton());
    // fragment 参数归并进 query、hash 清空、t 刷新后保存
    const stored = new URL(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY) ?? '');
    expect(stored.searchParams.get('sid')).toBe('frag-sid');
    expect(stored.searchParams.get('hash')).toBe('frag-hash');
    expect(stored.searchParams.get('t')).not.toBe('9');
    expect(stored.hash).toBe('');
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openedParams(openSpy).get('sid')).toBe('frag-sid');
  });

  it('passes a remoteControlToken link through unchanged (no t refresh)', () => {
    const TOKEN_URL = 'https://zcode.z.ai/remote/v4?remoteControlToken=placeholder-token';
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, TOKEN_URL);
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledWith(TOKEN_URL, '_blank', 'noopener');
  });

  it('prefills the prompt with an empty string when the stored link is invalid', () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, BARE_URL);
    vi.spyOn(window, 'open').mockImplementation(() => null);
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt', '');
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
