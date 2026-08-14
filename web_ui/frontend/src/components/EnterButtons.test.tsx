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
}));
import { discoverConnectorConsoles } from '@/services/api';
const mockDiscover = vi.mocked(discoverConnectorConsoles);
beforeEach(() => { vi.clearAllMocks(); });

describe('EnterButtons', () => {
  it('renders Kimi Code Web and DrifterConsole buttons', () => {
    render(<EnterButtons />);
    expect(screen.getByText('common.enterButtons.kimiCodeWeb')).toBeInTheDocument();
    expect(screen.getByText('common.enterButtons.drifterConsole')).toBeInTheDocument();
  });
  it('renders Kimi Code Web left of DrifterConsole by default (desktop)', () => {
    render(<EnterButtons />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveTextContent('common.enterButtons.kimiCodeWeb');
    expect(buttons[1]).toHaveTextContent('common.enterButtons.drifterConsole');
  });
  it('renders DrifterConsole left of Kimi Code Web when consoleFirst (mobile)', () => {
    render(<EnterButtons consoleFirst />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveTextContent('common.enterButtons.drifterConsole');
    expect(buttons[1]).toHaveTextContent('common.enterButtons.kimiCodeWeb');
  });
  it('Kimi Code Web button is a placeholder without any action', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.kimiCodeWeb'));
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
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
