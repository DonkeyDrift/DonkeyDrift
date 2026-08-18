import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EnterButtons } from './EnterButtons';

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

describe('EnterButtons', () => {
  it('renders Kimi Code Web, DeepSeek Harness and DrifterConsole buttons', () => {
    render(<EnterButtons />);
    expect(screen.getByText('common.enterButtons.kimiCodeWeb')).toBeInTheDocument();
    expect(screen.getByText('common.enterButtons.dsh')).toBeInTheDocument();
    expect(screen.getByText('common.enterButtons.drifterConsole')).toBeInTheDocument();
  });
  it('renders Kimi Code Web and DeepSeek Harness left of DrifterConsole by default (desktop)', () => {
    render(<EnterButtons />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);
    expect(buttons[0]).toHaveTextContent('common.enterButtons.kimiCodeWeb');
    expect(buttons[1]).toHaveTextContent('common.enterButtons.dsh');
    expect(buttons[2]).toHaveTextContent('common.enterButtons.drifterConsole');
  });
  it('renders DrifterConsole left of Kimi Code Web and DeepSeek Harness when consoleFirst (mobile)', () => {
    render(<EnterButtons consoleFirst />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);
    expect(buttons[0]).toHaveTextContent('common.enterButtons.drifterConsole');
    expect(buttons[1]).toHaveTextContent('common.enterButtons.kimiCodeWeb');
    expect(buttons[2]).toHaveTextContent('common.enterButtons.dsh');
  });
  it('opens Kimi Code Web URL in the pre-opened tab on success', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    mockLaunchKimi.mockResolvedValue({ status: 'ok', url: 'https://kimi.example/web#token=x' });
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.kimiCodeWeb'));
    expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank');
    await waitFor(() => { expect(fakeWin.location.href).toBe('https://kimi.example/web#token=x'); });
    openSpy.mockRestore();
  });
  it('closes the tab and alerts on Kimi Code Web failure', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    mockLaunchKimi.mockResolvedValue({ status: 'error', error: 'boom' });
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.kimiCodeWeb'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    expect(fakeWin.close).toHaveBeenCalled();
    openSpy.mockRestore();
    alertSpy.mockRestore();
  });
  it('opens DeepSeek Harness URL in the pre-opened tab on success', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    mockLaunchDsh.mockResolvedValue({ status: 'ok', url: 'http://192.168.3.57:43749' });
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.dsh'));
    expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank');
    await waitFor(() => { expect(fakeWin.location.href).toBe('http://192.168.3.57:43749'); });
    openSpy.mockRestore();
  });
  it('closes the tab and alerts on DeepSeek Harness failure', async () => {
    const fakeWin = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => fakeWin as unknown as Window);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    mockLaunchDsh.mockResolvedValue({ status: 'error', error: 'boom' });
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.dsh'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    expect(fakeWin.close).toHaveBeenCalled();
    openSpy.mockRestore();
    alertSpy.mockRestore();
  });
  it('opens Drifter Console on success', async () => {
    mockDiscover.mockResolvedValue({ status: true, found: [{ ip: '192.168.3.46', port: 80, reachable: true }], count: 1, scanned: 256, message: '' });
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.drifterConsole'));
    await waitFor(() => { expect(openSpy).toHaveBeenCalledWith('http://192.168.3.46/', '_blank', 'noopener,noreferrer'); });
    openSpy.mockRestore();
  });
  it('alerts on no console', async () => {
    mockDiscover.mockResolvedValue({ status: true, found: [], count: 0, scanned: 256, message: '' });
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.drifterConsole'));
    await waitFor(() => { expect(alertSpy).toHaveBeenCalled(); });
    alertSpy.mockRestore();
  });
});
