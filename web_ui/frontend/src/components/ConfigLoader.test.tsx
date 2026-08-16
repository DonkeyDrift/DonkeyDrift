import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { ConfigLoader } from './ConfigLoader';
import { useStore } from '../store/useStore';

vi.mock('@/i18n', () => {
  // t 必须是稳定引用，否则 handleManualLoad 的 useCallback 依赖每次渲染
  // 都变化，会触发 effect 反复 setError 的更新循环
  const t = (key: string) => key;
  return {
    useTranslation: () => ({ t }),
  };
});
vi.mock('@/services/api', () => ({
  loadConfig: vi.fn(),
  loadTub: vi.fn(),
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
  discoverProjects: vi.fn(),
}));
import { loadConfig, loadTub, discoverProjects } from '@/services/api';
const mockLoadConfig = vi.mocked(loadConfig);
const mockLoadTub = vi.mocked(loadTub);
const mockDiscover = vi.mocked(discoverProjects);

const tubPayload = {
  path: '/home/x/mycar/data',
  records: [],
  fields: [],
  total_physical_records: 0,
  deleted_indexes: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    config: null,
    configPath: '',
    tubPath: '',
    error: null,
    isLoading: false,
  });
  mockLoadTub.mockResolvedValue(tubPayload as never);
});

describe('ConfigLoader auto-discover (issue #129)', () => {
  it('auto-loads the project when exactly one mycar project is discovered', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar'],
      count: 1,
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/mycar'); });
    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    expect(useStore.getState().configPath).toBe('/home/x/mycar');
    expect(useStore.getState().config).toEqual({ IMAGE_H: 120 });
  });

  it('does not auto-load when multiple projects are discovered', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar', '/home/x/mycar2'],
      count: 2,
    });

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockDiscover).toHaveBeenCalled(); });
    expect(mockLoadConfig).not.toHaveBeenCalled();
    expect(useStore.getState().config).toBeNull();
  });

  it('falls back silently when discovery fails', async () => {
    mockDiscover.mockRejectedValue(new Error('boom'));

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockDiscover).toHaveBeenCalled(); });
    expect(mockLoadConfig).not.toHaveBeenCalled();
    expect(useStore.getState().config).toBeNull();
  });

  it('skips discovery when a configPath is already remembered', async () => {
    useStore.setState({ configPath: '/home/x/savedcar' });
    mockLoadConfig.mockResolvedValue({ status: true, config: { A: 1 } } as never);

    render(<ConfigLoader />);

    // 留给既有 configPath 自动加载路径触发
    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/savedcar'); });
    expect(mockDiscover).not.toHaveBeenCalled();
  });
});
