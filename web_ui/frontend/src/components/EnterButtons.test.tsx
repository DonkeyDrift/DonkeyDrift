import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DonkeyEntryLink, DrifterConsoleEntryLink, KimiCodeWebEntryLink, DshEntryLink } from './EnterButtons';

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
      </MemoryRouter>,
    );
    // Drifter Console 已改为 SPA 内路由链接（Issue #234），其余两个仍是按钮入口
    const drifterLink = screen.getByText('common.enterButtons.drifterConsole').closest('a');
    expect(drifterLink).toBeInTheDocument();
    expect(drifterLink?.className).toContain('text-xs');
    expect(drifterLink?.className).toContain('text-zinc-500');
    for (const label of ['common.enterButtons.kimiCodeWeb', 'common.enterButtons.dsh']) {
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
