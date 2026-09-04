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
    activeDrawer: null,
    configAutoLoadTried: false,
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
      last_project: null,
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
      last_project: null,
    });

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockDiscover).toHaveBeenCalled(); });
    expect(mockLoadConfig).not.toHaveBeenCalled();
    expect(useStore.getState().config).toBeNull();
  });

  it('auto-loads the last browsed project when multiple projects are discovered', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar', '/home/x/mycar2'],
      count: 2,
      last_project: '/home/x/mycar2',
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/mycar2'); });
    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar2/data'); });
    expect(useStore.getState().configPath).toBe('/home/x/mycar2');
  });

  it('falls back to manual browse when last project is not in discovered list', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar', '/home/x/mycar2'],
      count: 2,
      last_project: '/gone/mycar',
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

describe('ConfigLoader 自动加载与抽屉联动回归（点击「加载器」无反应）', () => {
  it('remembered configPath 下挂载不关闭抽屉，自动加载正常发出', async () => {
    useStore.setState({ configPath: '/home/x/savedcar', activeDrawer: 'loaders' });
    // loadConfig 挂起：只验证调度与抽屉状态，不走到 setConfig
    mockLoadConfig.mockReturnValue(new Promise(() => {}) as never);

    render(<ConfigLoader />);

    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/savedcar'); });
    expect(useStore.getState().activeDrawer).toBe('loaders');
    expect(useStore.getState().configAutoLoadTried).toBe(true);
  });

  it('自动加载失败后重开抽屉不再自动重试，抽屉保持打开', async () => {
    useStore.setState({ configPath: '/home/x/savedcar', activeDrawer: 'loaders' });
    mockLoadConfig.mockRejectedValue(new Error('boom') as never);

    const first = render(<ConfigLoader />);
    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledTimes(1); });
    // 非路径类错误按既有行为置 error 并关上抽屉
    await waitFor(() => { expect(useStore.getState().activeDrawer).toBeNull(); });
    first.unmount();

    // 用户重新打开抽屉：不应再次自动加载（否则会再次被错误联动关上）
    useStore.setState({ activeDrawer: 'loaders', error: null });
    render(<ConfigLoader />);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mockLoadConfig).toHaveBeenCalledTimes(1);
    expect(useStore.getState().activeDrawer).toBe('loaders');
  });
});
