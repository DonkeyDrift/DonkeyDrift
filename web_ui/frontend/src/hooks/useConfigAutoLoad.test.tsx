import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { useConfigAutoLoad, loadProject, autoLoadTubFor } from './useConfigAutoLoad';
import { useStore } from '../store/useStore';

vi.mock('@/services/api', () => ({
  loadConfig: vi.fn(),
  loadTub: vi.fn(),
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
  discoverProjects: vi.fn(),
  listChildTubs: vi.fn(),
}));
import { loadConfig, loadTub, discoverProjects, listChildTubs } from '@/services/api';
const mockLoadConfig = vi.mocked(loadConfig);
const mockLoadTub = vi.mocked(loadTub);
const mockDiscover = vi.mocked(discoverProjects);
const mockListChildTubs = vi.mocked(listChildTubs);

const tubPayload = {
  path: '/home/x/mycar/data',
  records: [],
  fields: [],
  total_physical_records: 0,
  deleted_indexes: [],
};

const childTubPayload = {
  path: '/home/x/mycar/data/tub_7_26-10-20',
  records: [{ _index: 0 }],
  fields: ['cam/image_array'],
  total_physical_records: 5930,
  deleted_indexes: [],
};

function Harness() {
  useConfigAutoLoad();
  return null;
}

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
  mockListChildTubs.mockResolvedValue({
    status: true,
    path: '/home/x/mycar/data',
    child_tubs: [],
  } as never);
});

describe('useConfigAutoLoad auto-discover (issue #129)', () => {
  it('auto-loads the project when exactly one mycar project is discovered', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar'],
      count: 1,
      last_project: null,
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);

    render(<Harness />);

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

    render(<Harness />);

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

    render(<Harness />);

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

    render(<Harness />);

    await waitFor(() => { expect(mockDiscover).toHaveBeenCalled(); });
    expect(mockLoadConfig).not.toHaveBeenCalled();
    expect(useStore.getState().config).toBeNull();
  });

  it('falls back silently when discovery fails', async () => {
    mockDiscover.mockRejectedValue(new Error('boom'));

    render(<Harness />);

    await waitFor(() => { expect(mockDiscover).toHaveBeenCalled(); });
    expect(mockLoadConfig).not.toHaveBeenCalled();
    expect(useStore.getState().config).toBeNull();
  });

  it('skips discovery when a configPath is already remembered', async () => {
    useStore.setState({ configPath: '/home/x/savedcar' });
    mockLoadConfig.mockResolvedValue({ status: true, config: { A: 1 } } as never);

    render(<Harness />);

    // 留给既有 configPath 自动加载路径触发(500ms 延迟)
    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/savedcar'); });
    expect(mockDiscover).not.toHaveBeenCalled();
  });
});

describe('useConfigAutoLoad 自动加载与抽屉联动回归（点击「加载器」无反应）', () => {
  it('remembered configPath 下挂载不关闭抽屉，自动加载正常发出', async () => {
    useStore.setState({ configPath: '/home/x/savedcar', activeDrawer: 'loaders' });
    // loadConfig 挂起：只验证调度与抽屉状态，不走到 setConfig
    mockLoadConfig.mockReturnValue(new Promise(() => {}) as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledWith('/home/x/savedcar'); });
    expect(useStore.getState().activeDrawer).toBe('loaders');
    expect(useStore.getState().configAutoLoadTried).toBe(true);
  });

  it('自动加载失败后重开抽屉不再自动重试，抽屉保持打开', async () => {
    useStore.setState({ configPath: '/home/x/savedcar', activeDrawer: 'loaders' });
    mockLoadConfig.mockRejectedValue(new Error('boom') as never);

    const first = render(<Harness />);
    await waitFor(() => { expect(mockLoadConfig).toHaveBeenCalledTimes(1); });
    // 非路径类错误按既有行为置 error 并关上抽屉
    await waitFor(() => { expect(useStore.getState().activeDrawer).toBeNull(); });
    first.unmount();

    // 用户重新打开抽屉：不应再次自动加载（否则会再次被错误联动关上）
    useStore.setState({ activeDrawer: 'loaders', error: null });
    render(<Harness />);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(mockLoadConfig).toHaveBeenCalledTimes(1);
    expect(useStore.getState().activeDrawer).toBe('loaders');
  });
});

// 子 tub 发现（方案 A）：<car>/data 合法但记录全空（全部被软删）时，自动
// 发现子目录里的子 tub 并回退加载最新一个；无子 tub 时维持现状（仍 setTub 空 data）。
// 默认连接 <car>/data：配置加载后 Tub 加载器输入框默认指向 <car>/data；
// data 文件夹还没有（未录制过）时静默保持该默认路径，不置 error。
describe('useConfigAutoLoad 默认连接 <car>/data（data 缺失不报错）', () => {
  const setupSingleProject = () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar'],
      count: 1,
      last_project: null,
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);
  };

  it('defaults tubPath to <car>/data and stays silent when the data folder is missing', async () => {
    setupSingleProject();
    mockLoadTub.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: 'Directory not found' } },
    } as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    // 默认连接：输入框路径落在 <car>/data，且不弹错误
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');
    expect(useStore.getState().loadedTubPath).toBe('/home/x/mycar/data');
    expect(useStore.getState().error).toBeNull();
  });

  it('clears stale records from a previously loaded tub when defaulting', async () => {
    setupSingleProject();
    useStore.setState({
      tubPath: '/home/x/oldcar/data',
      records: [{ _index: 0, _timestamp_ms: 0 }],
      totalRecords: 1,
    });
    mockLoadTub.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { detail: 'Path is not a valid tub (manifest.json missing)' } },
    } as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');
    // 旧项目的残留记录不随默认路径展示
    expect(useStore.getState().records).toEqual([]);
    expect(useStore.getState().totalRecords).toBe(0);
    expect(useStore.getState().error).toBeNull();
  });

  it('switching projects does not keep loading the old project\'s tub', async () => {
    setupSingleProject();
    // 切换前挂着别的项目的 tub
    useStore.setState({ tubPath: '/home/x/oldcar/data' });
    mockLoadTub.mockResolvedValue(tubPayload as never);

    render(<Harness />);

    // 不恢复旧项目路径，直接默认连接新项目的 data
    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    expect(mockLoadTub).not.toHaveBeenCalledWith('/home/x/oldcar/data');
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');
  });

  it('restores a same-project child tub instead of defaulting to ./data', async () => {
    setupSingleProject();
    useStore.setState({ tubPath: '/home/x/mycar/data/tub_7_26-10-20' });
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === '/home/x/mycar/data/tub_7_26-10-20') {
        return Promise.resolve({ ...childTubPayload });
      }
      return Promise.reject(new Error(`unexpected path ${p}`));
    }) as never);

    render(<Harness />);

    await waitFor(() => {
      expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data/tub_7_26-10-20');
    });
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data/tub_7_26-10-20');
  });
});

// 过期写回守卫（切换配置目录后来回闪动回归）：所有异步写回前校验项目
// 目录（configPath）是否仍是发起时的路径，已被切换则本次结果整体作废。
describe('loadProject/autoLoadTubFor 过期写回守卫', () => {
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

  it('autoLoadTubFor: tub 加载在途时项目目录已切换，晚到结果不写回', async () => {
    // 新项目 mycar-2 已是当前配置，旧项目 mycar 的自动加载还在途
    useStore.setState({
      configPath: '/home/x/mycar-2',
      config: { B: 1 },
      tubPath: '/home/x/mycar-2/data',
      records: [],
    });
    let resolveA!: (value: unknown) => void;
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === '/home/x/mycar/data') return new Promise((r) => { resolveA = r; });
      return Promise.reject(new Error(`unexpected path ${p}`));
    }) as never);

    const pending = autoLoadTubFor('/home/x/mycar');
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');

    resolveA(childTubPayload);
    await pending;
    // 过期作废：旧项目的记录不写回，也不改写新项目已接管的状态
    expect(useStore.getState().records).toEqual([]);
    expect(useStore.getState().configPath).toBe('/home/x/mycar-2');
  });

  it('loadProject: 恢复本项目 tub 在途时项目目录已切换，放弃写回', async () => {
    useStore.setState({
      configPath: '/home/x/mycar',
      config: { A: 1 },
      tubPath: '/home/x/mycar/data/tub_7',
      records: [],
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { A: 2 } } as never);
    let resolveRestore!: (value: unknown) => void;
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === '/home/x/mycar/data/tub_7') return new Promise((r) => { resolveRestore = r; });
      return Promise.reject(new Error(`unexpected path ${p}`));
    }) as never);

    const pending = loadProject('/home/x/mycar', (key) => key);
    await flush();
    // 恢复请求已发出，此刻用户切换到 mycar-2
    expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data/tub_7');
    useStore.setState({ configPath: '/home/x/mycar-2', config: { B: 1 } });

    resolveRestore(childTubPayload);
    await pending;
    expect(useStore.getState().records).toEqual([]);
    expect(useStore.getState().configPath).toBe('/home/x/mycar-2');
  });

  it('loadProject: loadConfig 在途时别的项目已加载完成，本次整体放弃', async () => {
    useStore.setState({ configPath: '', config: null, tubPath: '', records: [] });
    let resolveCfg!: (value: unknown) => void;
    mockLoadConfig.mockReturnValue(new Promise((r) => { resolveCfg = r; }) as never);

    const pending = loadProject('/home/x/mycar', (key) => key);
    // mycar 的 loadConfig 还在途，mycar-2 已抢先加载完成
    useStore.setState({ configPath: '/home/x/mycar-2', config: { B: 1 } });
    resolveCfg({ status: true, config: { A: 1 } });
    await pending;

    expect(mockLoadTub).not.toHaveBeenCalled();
    expect(useStore.getState().configPath).toBe('/home/x/mycar-2');
  });
});

describe('useConfigAutoLoad child tub fallback', () => {
  // 与后端返回顺序一致：last_modified 降序，第一条即最新
  const discoveredChildTubs = [
    {
      name: 'tub_7_26-10-20',
      path: '/home/x/mycar/data/tub_7_26-10-20',
      record_count: 5930,
      total_physical: 5930,
      deleted_count: 0,
      last_modified_ms: 2000,
    },
    {
      name: 'tub_6_26-10-20',
      path: '/home/x/mycar/data/tub_6_26-10-20',
      record_count: 1793,
      total_physical: 1793,
      deleted_count: 0,
      last_modified_ms: 1000,
    },
  ];

  const setupSingleProject = () => {
    mockDiscover.mockResolvedValue({
      status: true,
      root: '/home/x',
      projects: ['/home/x/mycar'],
      count: 1,
      last_project: null,
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);
  };

  it('falls back to the newest child tub when ./data has no live records', async () => {
    setupSingleProject();
    // listChildTubs 已按 last_modified 降序，第一条即最新
    mockListChildTubs.mockResolvedValue({
      status: true,
      path: '/home/x/mycar/data',
      child_tubs: discoveredChildTubs,
    } as never);
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === '/home/x/mycar/data') return Promise.resolve(tubPayload);
      if (p === '/home/x/mycar/data/tub_7_26-10-20') return Promise.resolve(childTubPayload);
      return Promise.reject(new Error(`unexpected path ${p}`));
    }) as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await waitFor(() => {
      expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data/tub_7_26-10-20');
    });
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data/tub_7_26-10-20');
  });

  it('keeps the empty ./data tub when no child tub exists', async () => {
    setupSingleProject();

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mockListChildTubs).toHaveBeenCalledWith('/home/x/mycar/data');
    // 只有 ./data 一次加载，没有第二次回退
    expect(mockLoadTub).toHaveBeenCalledTimes(1);
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');
  });

  it('keeps the empty ./data tub when child tub discovery fails', async () => {
    setupSingleProject();
    mockListChildTubs.mockRejectedValue(new Error('boom') as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(mockLoadTub).toHaveBeenCalledTimes(1);
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data');
  });
});
