import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AutoSyncPanel } from './AutoSyncPanel';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../services/api', () => ({
  getConnectorConfig: vi.fn(),
  setConnectorAutoSync: vi.fn(),
  checkConnectorStatus: vi.fn(),
}));

import { getConnectorConfig, setConnectorAutoSync, checkConnectorStatus } from '../services/api';

const mockGetConfig = vi.mocked(getConnectorConfig);
const mockSetAutoSync = vi.mocked(setConnectorAutoSync);
const mockCheckStatus = vi.mocked(checkConnectorStatus);

beforeEach(() => {
  vi.clearAllMocks();
  mockCheckStatus.mockResolvedValue({
    online: false,
    message: '',
    auto_sync: { enabled: false, triggered: false },
    last_sync: { at: null, result: null },
  });
});

describe('AutoSyncPanel', () => {
  it('加载配置并展示默认关闭的开关与「尚未同步过」', async () => {
    mockGetConfig.mockResolvedValue({
      config: { host: '', user: 'pi', port: 22, car_dir: '~/mycar', auto_sync: false },
    } as never);

    render(<AutoSyncPanel />);

    const toggle = await screen.findByRole('switch', { name: 'connector.autoSyncToggle' });
    expect(toggle).not.toBeChecked();
    expect(screen.getByTestId('auto-sync-last')).toHaveTextContent('connector.autoSyncNever');
  });

  it('展示最近一次同步时间与结果', async () => {
    mockGetConfig.mockResolvedValue({
      config: {
        host: '',
        user: 'pi',
        port: 22,
        car_dir: '~/mycar',
        auto_sync: true,
        last_sync_at: '2026-08-26T10:00:00',
        last_sync_result: '同步成功：已传输 3/4 个文件',
      },
    } as never);

    render(<AutoSyncPanel />);

    const toggle = await screen.findByRole('switch', { name: 'connector.autoSyncToggle' });
    expect(toggle).toBeChecked();
    const last = screen.getByTestId('auto-sync-last');
    expect(last).toHaveTextContent('connector.autoSyncLast');
    expect(last).toHaveTextContent('同步成功：已传输 3/4 个文件');
  });

  it('点击开关调用 auto_sync 端点并更新状态', async () => {
    mockGetConfig.mockResolvedValue({
      config: { host: '', user: 'pi', port: 22, car_dir: '~/mycar', auto_sync: false },
    } as never);
    mockSetAutoSync.mockResolvedValue({
      auto_sync: { enabled: true },
      last_sync: { at: null, result: null },
    } as never);

    render(<AutoSyncPanel />);

    const toggle = await screen.findByRole('switch', { name: 'connector.autoSyncToggle' });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockSetAutoSync).toHaveBeenCalledWith(true);
    });
    await waitFor(() => {
      expect(toggle).toBeChecked();
    });
  });

  it('设置失败时保持原开关状态不误报', async () => {
    mockGetConfig.mockResolvedValue({
      config: { host: '', user: 'pi', port: 22, car_dir: '~/mycar', auto_sync: false },
    } as never);
    mockSetAutoSync.mockRejectedValue(new Error('network'));

    render(<AutoSyncPanel />);

    const toggle = await screen.findByRole('switch', { name: 'connector.autoSyncToggle' });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockSetAutoSync).toHaveBeenCalledWith(true);
    });
    await waitFor(() => {
      expect(toggle).not.toBeChecked();
    });
  });
});
