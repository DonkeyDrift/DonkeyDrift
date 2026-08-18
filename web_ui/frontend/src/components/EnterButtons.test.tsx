import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DrifterConsoleEntryLink, KimiCodeWebEntryLink, DshEntryLink, DshButton } from './EnterButtons';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));
vi.mock('@/services/api', () => ({
  discoverConnectorConsoles: vi.fn(),
  launchKimiCodeWeb: vi.fn(),
  launchDsh: vi.fn(),
}));
import { discoverConnectorConsoles, launchDsh, launchKimiCodeWeb } from '@/services/api';
const mockDiscover = vi.mocked(discoverConnectorConsoles);
const mockLaunchKimi = vi.mocked(launchKimiCodeWeb);
const mockLaunchDsh = vi.mocked(launchDsh);
beforeEach(() => { vi.clearAllMocks(); });

describe('entry link components (Issue #175 nav-link style)', () => {
  it('renders each entry with the de-emphasized advanced link style', () => {
    render(<><DrifterConsoleEntryLink /><KimiCodeWebEntryLink /><DshEntryLink /></>);
    for (const label of ['common.enterButtons.drifterConsole', 'common.enterButtons.kimiCodeWeb', 'common.enterButtons.dsh']) {
      const btn = screen.getByText(label).closest('button');
      expect(btn).toBeInTheDocument();
      // 弱化处理：更小字号 + 更淡颜色，一眼可辨为高级选项
      expect(btn?.className).toContain('text-xs');
      expect(btn?.className).toContain('text-zinc-500');
    }
  });
});

describe('DrifterConsoleEntryLink', () => {
  it('opens Drifter Console on success', async () => {
    mockDiscover.mockResolvedValue({ status: true, found: [{ ip: '192.168.3.46', port: 80, reachable: true }], count: 1, scanned: 256, message: '' });
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<DrifterConsoleEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.drifterConsole'));
    await waitFor(() => { expect(openSpy).toHaveBeenCalledWith('http://192.168.3.46/', '_blank', 'noopener,noreferrer'); });
    openSpy.mockRestore();
  });
  it('alerts on no console', async () => {
    mockDiscover.mockResolvedValue({ status: true, found: [], count: 0, scanned: 256, message: '' });
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    render(<DrifterConsoleEntryLink />);
    fireEvent.click(screen.getByText('common.enterButtons.drifterConsole'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    alertSpy.mockRestore();
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

describe('DshButton', () => {
  it('renders the pill-styled DeepSeek Harness button', () => {
    render(<DshButton />);
    const btn = screen.getByText('common.enterButtons.dsh').closest('button');
    expect(btn).toBeInTheDocument();
    expect(btn?.className).toContain('rounded-full');
  });
  it('opens DeepSeek Harness URL in the pre-opened tab on success', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    mockLaunchDsh.mockResolvedValue({ status: 'ok', url: 'http://192.168.3.57:43749' });
    render(<DshButton />);
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
    render(<DshButton />);
    fireEvent.click(screen.getByText('common.enterButtons.dsh'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    expect(fakeWin.close).toHaveBeenCalled();
    openSpy.mockRestore();
    alertSpy.mockRestore();
  });
});
