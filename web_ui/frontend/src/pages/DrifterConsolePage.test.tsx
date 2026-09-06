import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DrifterConsolePage } from './DrifterConsolePage';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));
vi.mock('@/services/api', () => ({
  discoverConnectorConsoles: vi.fn(),
}));
vi.mock('@/services/console', () => ({
  consoleGetText: vi.fn(() => Promise.resolve('')),
}));
import { discoverConnectorConsoles } from '@/services/api';
const mockDiscover = vi.mocked(discoverConnectorConsoles);

const emptyResult = { status: true, found: [], count: 0, scanned: 256, message: '' };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DrifterConsolePage 扫描状态显示（Issue #234）', () => {
  it('扫描进行中显示「正在扫描」而不是「未发现设备」，扫描结束无设备才显示「未发现设备」', async () => {
    let resolveScan!: (v: typeof emptyResult) => void;
    mockDiscover.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveScan = resolve;
        }),
    );
    render(<DrifterConsolePage />);
    // 扫描未返回期间：主区域与设备下拉都应是 scanning 文案，不能出现 noDevice
    expect(screen.getAllByText('console.scanning').length).toBeGreaterThan(0);
    expect(screen.queryByText('console.noDevice')).not.toBeInTheDocument();
    // 扫描结束且无设备：才显示「未发现设备」（设备下拉与主区域各一处）
    resolveScan(emptyResult);
    await waitFor(() =>
      expect(screen.getAllByText('console.noDevice').length).toBeGreaterThan(0),
    );
  });

  it('扫描发现设备后自动选中第一台并加载内嵌 DC iframe', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      const iframe = document.querySelector('iframe');
      expect(iframe).not.toBeNull();
      expect(iframe?.getAttribute('src')).toContain('http://192.168.3.46/');
    });
  });

  it('重扫后旧 IP 不在列表时自动切换到新发现的第一台（车换 IP 自愈）', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.46/',
      );
    });

    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.88', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    fireEvent.click(screen.getByRole('button', { name: 'console.rescan' }));
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.88/',
      );
    });
  });

  it('重扫未发现设备（车暂时离线）时保持当前选择不动', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.46/',
      );
    });

    mockDiscover.mockResolvedValue(emptyResult);
    fireEvent.click(screen.getByRole('button', { name: 'console.rescan' }));
    await waitFor(() => expect(mockDiscover).toHaveBeenCalledTimes(2));
    expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
      'http://192.168.3.46/',
    );
  });

  it('内嵌 DC iframe 带 allowFullScreen，车端图表/终端全屏键可用', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')).not.toBeNull();
    });
    expect(document.querySelector('iframe')).toHaveAttribute('allowfullscreen');
  });
});
