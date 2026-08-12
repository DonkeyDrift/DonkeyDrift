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
  it('renders both buttons', () => {
    render(<EnterButtons />);
    expect(screen.getByText('common.enterButtons.donkey')).toBeInTheDocument();
    expect(screen.getByText('common.enterButtons.drifterConsole')).toBeInTheDocument();
  });
  it('opens Donkey launcher', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<EnterButtons />);
    fireEvent.click(screen.getByText('common.enterButtons.donkey'));
    expect(openSpy).toHaveBeenCalledTimes(1);
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
