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
  fetchZcodeRemoteLink: vi.fn(() => Promise.resolve({ status: 'error', error: 'down' })),
  getDonkeyUrl: vi.fn(() => 'http://localhost:8090/'),
}));
import { launchDsh, launchKimiCodeWeb, launchZcodeRemote, fetchZcodeRemoteLink } from '@/services/api';
const mockLaunchKimi = vi.mocked(launchKimiCodeWeb);
const mockLaunchDsh = vi.mocked(launchDsh);
const mockLaunchZcodeRemote = vi.mocked(launchZcodeRemote);
const mockFetchZcodeRemoteLink = vi.mocked(fetchZcodeRemoteLink);
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

describe('ZCodeEntryLink（点击实时取活链，localStorage 兜底）', () => {
  // 占位链接（安全红线：测试里只允许占位示例，绝不出现真实远程链接凭证）；
  // 有效链接带 sid/hash 持久化凭证参数（t 为生成时间戳、归一化时现拼刷新），
  // 或带 remoteControlToken（原样通过）；桌面端复制的链接参数可能跟在 # fragment 后
  const STORED_URL = 'https://zcode.z.ai/remote/v4?sid=placeholder-sid&hash=placeholder-hash&t=1';
  const UPDATED_URL = 'https://zcode.z.ai/remote/v4?sid=placeholder-sid2&hash=placeholder-hash2&t=2';
  const BARE_URL = 'https://zcode.z.ai/remote/v4';
  const LIVE_URL = 'https://zcode.z.ai/remote/v4?sid=live-sid&hash=live-hash&t=100';

  const renderButton = () => {
    render(<ZCodeEntryLink />);
    return screen.getByRole('button', { name: 'common.enterButtons.zcode' });
  };

  // window.open 假窗口：单击先同步开 about:blank 占位，拿到链接后写
  // location.href 完成导航；记录所有假窗口，取最后被导航的目标 URL
  type FakeWin = { location: { href: string }; close: ReturnType<typeof vi.fn>; opener: unknown };
  let fakeWins: FakeWin[];
  let openSpy: ReturnType<typeof vi.spyOn>;
  const mockOpenWindows = () => {
    fakeWins = [];
    openSpy = vi.spyOn(window, 'open').mockImplementation((url?: string | URL) => {
      const w: FakeWin = { location: { href: String(url ?? '') }, close: vi.fn(), opener: {} };
      fakeWins.push(w);
      return w as unknown as Window;
    });
  };
  const lastNavigated = () =>
    fakeWins.map((w) => w.location.href).filter((h) => h && h !== 'about:blank').pop();
  const navigatedParams = () => new URL(lastNavigated() ?? 'http://invalid/').searchParams;

  // 单击动作有 300ms 去抖延迟（等待可能到来的双击），随后是取链微任务链，
  // 多轮刷新微任务确保跑完
  const clickAndFlush = async (btn: HTMLElement) => {
    fireEvent.click(btn);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    for (let i = 0; i < 5; i += 1) await act(async () => {});
  };

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
    // 默认后端取链失败（离线/旧版无端点），各用例按需覆盖返回值
    mockFetchZcodeRemoteLink.mockResolvedValue({ status: 'error', error: 'down' });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps the ZCode label and carries the remote-control hint title', () => {
    expect(renderButton()).toHaveAttribute('title', 'common.enterButtons.zcodeTitle');
  });

  it('opens the live link from the backend without prompting and stores it as fallback', async () => {
    mockFetchZcodeRemoteLink.mockResolvedValue({ status: 'ok', url: LIVE_URL });
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    await clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    // 占位标签直接导航到活链，活链落 localStorage 作为离线兜底存档
    expect(lastNavigated()).toBe(LIVE_URL);
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBe(LIVE_URL);
  });

  it('opens the live link via a direct window.open fallback when the placeholder is blocked', async () => {
    mockFetchZcodeRemoteLink.mockResolvedValue({ status: 'ok', url: LIVE_URL });
    const blockedSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    await clickAndFlush(renderButton());
    expect(blockedSpy).toHaveBeenCalledWith(LIVE_URL, '_blank', 'noopener');
  });

  it('falls back to a fresh-t rebuild of the stored link when the backend has no live link', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    await clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    const params = navigatedParams();
    expect(params.get('sid')).toBe('placeholder-sid');
    expect(params.get('t')).not.toBe('1');
    // 兜底路径后台唤醒桌面端
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });

  it('keeps working when the link request rejects', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    mockFetchZcodeRemoteLink.mockRejectedValue(new Error('backend down'));
    mockOpenWindows();
    await clickAndFlush(renderButton());
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
  });

  it('prompts, saves, then navigates the same placeholder when neither backend nor store works', async () => {
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    await clickAndFlush(renderButton());
    // 无活链无存档：保留占位标签并弹出录入框
    expect(fakeWins[0].close).not.toHaveBeenCalled();
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt', '');
    expectStored('placeholder-sid', 'placeholder-hash', '1');
    // 录入保存后直接导航同一个占位标签（已脱离点击手势，不再新开窗口），
    // 打开的是现拼的新鲜链接：sid/hash 保留、t 已刷新（不再是存入时的 t=1）
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
    expect(navigatedParams().get('t')).not.toBe('1');
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });

  it('copies the fresh link to the clipboard on click', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    mockOpenWindows();
    await clickAndFlush(renderButton());
    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = new URL(writeText.mock.calls[0][0]).searchParams;
    expect(copied.get('sid')).toBe('placeholder-sid');
    expect(copied.get('t')).not.toBe('1');
  });

  it('still opens the link when the desktop wake request fails', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    mockLaunchZcodeRemote.mockRejectedValue(new Error('launcher down'));
    mockOpenWindows();
    await clickAndFlush(renderButton());
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
  });

  it('re-prompts and updates the stored link on double click (single click suppressed)', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, STORED_URL);
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(UPDATED_URL);
    const btn = renderButton();
    // 浏览器双击事件序列：click → click → dblclick
    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.doubleClick(btn);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    for (let i = 0; i < 5; i += 1) await act(async () => {});
    expect(promptSpy).toHaveBeenCalledTimes(1);
    expectStored('placeholder-sid2', 'placeholder-hash2', '2');
    // 单击被去抖抑制，只开一次窗口并导航到新链接
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(navigatedParams().get('sid')).toBe('placeholder-sid2');
  });

  it('alerts and neither saves nor navigates a non-https link', async () => {
    mockOpenWindows();
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue('http://zcode.z.ai/remote/v4?sid=placeholder-sid&hash=placeholder-hash');
    await clickAndFlush(renderButton());
    expect(alertSpy).toHaveBeenCalledWith('common.enterButtons.zcodeInvalid');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(lastNavigated()).toBeUndefined();
    // 录入无效：占位标签被关闭
    expect(fakeWins[0].close).toHaveBeenCalledTimes(1);
  });

  it('alerts and rejects a bare link without sid/hash params', async () => {
    mockOpenWindows();
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue(BARE_URL);
    await clickAndFlush(renderButton());
    expect(alertSpy).toHaveBeenCalledWith('common.enterButtons.zcodeInvalid');
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(lastNavigated()).toBeUndefined();
    expect(fakeWins[0].close).toHaveBeenCalledTimes(1);
  });

  it('falls back to the prompt when the stored link lacks sid/hash', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, BARE_URL);
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    await clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledTimes(1);
    expectStored('placeholder-sid', 'placeholder-hash', '1');
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
  });

  it('accepts a desktop-copied link whose params live in the # fragment', async () => {
    mockOpenWindows();
    vi.spyOn(window, 'prompt').mockReturnValue(
      'https://zcode.z.ai/remote/v4#sid=frag-sid&hash=frag-hash&t=9',
    );
    await clickAndFlush(renderButton());
    // fragment 参数归并进 query、hash 清空、t 刷新后保存
    const stored = new URL(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY) ?? '');
    expect(stored.searchParams.get('sid')).toBe('frag-sid');
    expect(stored.searchParams.get('hash')).toBe('frag-hash');
    expect(stored.searchParams.get('t')).not.toBe('9');
    expect(stored.hash).toBe('');
    expect(navigatedParams().get('sid')).toBe('frag-sid');
  });

  it('passes a remoteControlToken link through unchanged (no t refresh)', async () => {
    const TOKEN_URL = 'https://zcode.z.ai/remote/v4?remoteControlToken=placeholder-token';
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, TOKEN_URL);
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockImplementation(() => null);
    await clickAndFlush(renderButton());
    expect(promptSpy).not.toHaveBeenCalled();
    expect(lastNavigated()).toBe(TOKEN_URL);
  });

  it('prefills the prompt with an empty string when the stored link is invalid', async () => {
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, BARE_URL);
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    await clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt', '');
  });

  it('does nothing when the prompt is cancelled', async () => {
    mockOpenWindows();
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'prompt').mockReturnValue(null);
    await clickAndFlush(renderButton());
    expect(localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY)).toBeNull();
    expect(lastNavigated()).toBeUndefined();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(fakeWins[0].close).toHaveBeenCalledTimes(1);
    // 取消 = 没有真正打开，不唤醒桌面端
    expect(mockLaunchZcodeRemote).not.toHaveBeenCalled();
  });

  it('still opens the entered link when the storage write fails (private mode)', async () => {
    // 隐私模式/存储禁用时 setItem 抛错——本次仍按手中链接打开并唤醒，
    // 只是不落盘（下次点击会再 prompt）
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError');
    });
    mockOpenWindows();
    vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    await clickAndFlush(renderButton());
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });

  it('treats a throwing storage read as no saved link and falls back to the prompt', async () => {
    // getItem 抛 SecurityError（存储禁用）时按无存档处理：prompt 预填空串、
    // 录入后正常打开，点击不失效
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError');
    });
    mockOpenWindows();
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(STORED_URL);
    await clickAndFlush(renderButton());
    expect(promptSpy).toHaveBeenCalledWith('common.enterButtons.zcodePrompt', '');
    expect(navigatedParams().get('sid')).toBe('placeholder-sid');
    expect(mockLaunchZcodeRemote).toHaveBeenCalledTimes(1);
  });
});
