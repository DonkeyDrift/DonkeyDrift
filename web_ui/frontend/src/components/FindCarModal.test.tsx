import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { FindCarModal } from './FindCarModal';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@/services/api', () => ({
  getConnectorLocalIps: vi.fn(),
  discoverConnectorConsoles: vi.fn(),
}));
import { getConnectorLocalIps, discoverConnectorConsoles } from '@/services/api';
const mockLocalIps = vi.mocked(getConnectorLocalIps);
const mockDiscover = vi.mocked(discoverConnectorConsoles);

beforeEach(() => { vi.clearAllMocks(); });

describe('FindCarModal (局域网直连发现)', () => {
  it('renders nothing when closed', () => {
    render(<FindCarModal open={false} onClose={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows scanning state while awaiting results', async () => {
    mockLocalIps.mockResolvedValue({ ips: [], count: 0 });
    mockDiscover.mockResolvedValue({ status: true, found: [], count: 0, scanned: 0, message: '' });
    render(<FindCarModal open onClose={vi.fn()} />);
    expect(screen.getByText('common.findCar.scanning')).toBeInTheDocument();
    await waitFor(() => expect(mockLocalIps).toHaveBeenCalled());
  });

  it('lists DD and ESP32 links from the two endpoints', async () => {
    mockLocalIps.mockResolvedValue({ ips: [{ ip: '192.168.3.62', interface: 'eth0', priority: 1 }], count: 1 });
    mockDiscover.mockResolvedValue({ status: true, found: [{ ip: '192.168.3.46', port: 80, reachable: true }], count: 1, scanned: 1, message: '' });
    render(<FindCarModal open onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('common.findCar.ddLabel')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'http://192.168.3.62:8000' })).toHaveAttribute('href', 'http://192.168.3.62:8000');
    expect(screen.getByRole('link', { name: 'http://192.168.3.46' })).toHaveAttribute('href', 'http://192.168.3.46');
  });

  it('shows not-found when no ESP32 is found', async () => {
    mockLocalIps.mockResolvedValue({ ips: [], count: 0 });
    mockDiscover.mockResolvedValue({ status: true, found: [], count: 0, scanned: 1, message: '' });
    render(<FindCarModal open onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('common.findCar.notFound')).toBeInTheDocument());
  });

  it('closes on backdrop click', async () => {
    const onClose = vi.fn();
    mockLocalIps.mockResolvedValue({ ips: [], count: 0 });
    mockDiscover.mockResolvedValue({ status: true, found: [], count: 0, scanned: 0, message: '' });
    render(<FindCarModal open onClose={onClose} />);
    await waitFor(() => expect(screen.getByText('common.findCar.notFound')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalled();
  });
});
