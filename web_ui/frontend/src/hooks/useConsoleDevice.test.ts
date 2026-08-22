import '@testing-library/jest-dom/vitest';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useConsoleDevice, invalidateConsoleDeviceCache } from './useConsoleDevice';

vi.mock('../services/api', () => ({
  discoverConnectorConsoles: vi.fn(),
}));

import { discoverConnectorConsoles } from '../services/api';

const mockDiscover = vi.mocked(discoverConnectorConsoles);

const STORAGE_KEY = 'donkeydrifter.console.ip';

const scanResult = (ip: string) => ({
  status: true,
  found: [{ ip, port: 80, reachable: true }],
  count: 1,
  scanned: 256,
  message: '',
});

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  invalidateConsoleDeviceCache();
});

describe('useConsoleDevice', () => {
  it('scans once and caches the discovered ip in sessionStorage', async () => {
    mockDiscover.mockResolvedValue(scanResult('192.168.3.46'));
    const { result } = renderHook(() => useConsoleDevice());

    await waitFor(() => expect(result.current.ip).toBe('192.168.3.46'));
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('192.168.3.46');
    expect(mockDiscover).toHaveBeenCalledTimes(1);
  });

  it('reuses the sessionStorage cache without rescanning', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, '192.168.4.1');
    const { result } = renderHook(() => useConsoleDevice());

    await waitFor(() => expect(result.current.ip).toBe('192.168.4.1'));
    expect(mockDiscover).not.toHaveBeenCalled();
  });

  it('refresh invalidates a stale cached ip and re-scans', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, '192.168.4.1');
    mockDiscover.mockResolvedValue(scanResult('192.168.3.46'));
    const { result } = renderHook(() => useConsoleDevice());

    // 先吃到 sessionStorage 里的旧 IP（车端已换网，该地址实际已失效）
    await waitFor(() => expect(result.current.ip).toBe('192.168.4.1'));
    expect(mockDiscover).not.toHaveBeenCalled();

    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.ip).toBe('192.168.3.46'));
    expect(mockDiscover).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('192.168.3.46');
  });

  it('keeps retrying slowly when no console is found, and recovers when it appears', async () => {
    vi.useFakeTimers();
    try {
      mockDiscover.mockResolvedValue({
        status: true,
        found: [],
        count: 0,
        scanned: 256,
        message: '',
      });
      const { result } = renderHook(() => useConsoleDevice());

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.ip).toBeNull();
      expect(mockDiscover).toHaveBeenCalledTimes(1);

      // 车端上线后，慢速重试自动恢复
      mockDiscover.mockResolvedValue(scanResult('192.168.3.46'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });
      expect(result.current.ip).toBe('192.168.3.46');
    } finally {
      vi.useRealTimers();
    }
  });
});
