import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { useConfigAutoLoad, autoLoadTubFor } from './useConfigAutoLoad';
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

// 手动排程异步边界：让某次 loadTub/listChildTubs 停在挂起态，测试按需
// 决定它何时（以及以成功还是失败）落地
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
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

  // 回归（移除 DD 页面手动 TubLoader、Tub 全自动选择）：<car>/data 本身加载
  // 失败（如 data 只是普通目录、并非合法 tub）时也必须触发子 tub 发现并回退
  // 到最新的子 tub，而不是留给用户手动选择。
  it('falls back to the newest child tub when ./data load itself rejects', async () => {
    setupSingleProject();
    mockListChildTubs.mockResolvedValue({
      status: true,
      path: '/home/x/mycar/data',
      child_tubs: discoveredChildTubs,
    } as never);
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === '/home/x/mycar/data') return Promise.reject(new Error('tub load failed'));
      if (p === '/home/x/mycar/data/tub_7_26-10-20') return Promise.resolve(childTubPayload);
      return Promise.reject(new Error(`unexpected path ${p}`));
    }) as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await waitFor(() => { expect(mockListChildTubs).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await waitFor(() => {
      expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data/tub_7_26-10-20');
    });
    expect(useStore.getState().tubPath).toBe('/home/x/mycar/data/tub_7_26-10-20');
  });

  // 边界：父目录加载失败且无子 tub 时，发现仍要发生，但不得把失败路径或
  // 空数据写进 store（tubPath 保持空、records 不被写入）。
  it('discovers child tubs but writes no tub data when ./data rejects and no child tub exists', async () => {
    setupSingleProject();
    useStore.setState({ records: [], loadedTubPath: null });
    mockLoadTub.mockRejectedValue(new Error('tub load failed') as never);
    // beforeEach 默认 listChildTubs 返回 child_tubs: []

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await waitFor(() => { expect(mockListChildTubs).toHaveBeenCalledWith('/home/x/mycar/data'); });
    expect(mockLoadTub).toHaveBeenCalledTimes(1);
    expect(useStore.getState().tubPath).toBe('');
    expect(useStore.getState().records).toEqual([]);
  });

  // 边界：父目录加载失败且子 tub 发现也失败时，发现仍要被触发，且不写入
  // 任何错误 Tub 数据。
  it('discovers child tubs but writes no tub data when both ./data load and discovery fail', async () => {
    setupSingleProject();
    useStore.setState({ records: [], loadedTubPath: null });
    mockLoadTub.mockRejectedValue(new Error('tub load failed') as never);
    mockListChildTubs.mockRejectedValue(new Error('boom') as never);

    render(<Harness />);

    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith('/home/x/mycar/data'); });
    await waitFor(() => { expect(mockListChildTubs).toHaveBeenCalledWith('/home/x/mycar/data'); });
    expect(mockLoadTub).toHaveBeenCalledTimes(1);
    expect(useStore.getState().tubPath).toBe('');
    expect(useStore.getState().records).toEqual([]);
  });
});

// 第二轮代码审查缺陷：自动 Tub 全链路失败后 store 残留上一配置的数据
// （需要 clearTub 完整重置）；并发场景下旧的 autoLoadTubFor 请求晚到时，
// 其子 tub 回退结果或失败清理仍会落地，覆盖/清除新请求已加载的 Tub。
// 以下用例直接调用已导出的 autoLoadTubFor，用 deferred Promise 精确编排
// 两次请求的完成顺序；mock 只落在 API 边界（@/services/api）。
describe('useConfigAutoLoad 自动 Tub 失败重置与过期请求覆盖（第二轮审查）', () => {
  const CAR_A = '/home/x/carA';
  const CAR_B = '/home/x/carB';
  const A_DATA = `${CAR_A}/data`;
  const B_DATA = `${CAR_B}/data`;

  const carBRecords = [
    { _index: 0, _timestamp_ms: 5100, 'cam/image_array': 'carB_0.jpg', 'user/angle': 0.05, 'user/throttle': 0.5 },
    { _index: 1, _timestamp_ms: 5200, 'cam/image_array': 'carB_1.jpg', 'user/angle': -0.05, 'user/throttle': 0.45 },
  ];
  const carBFields = ['cam/image_array', 'user/angle', 'user/throttle'];
  // 与 /tub/load 后端响应结构一致
  const carBTubPayload = {
    status: true,
    path: B_DATA,
    record_count: 2,
    total_physical_records: 2,
    records: carBRecords,
    fields: carBFields,
    deleted_indexes: [] as number[],
  };

  it('全链路失败后清空全部 Tub 相关状态，而不是残留上一配置数据', async () => {
    // 上一配置残留（tubPath 被 persist 持久化，records/fields 为运行时旧状态）
    const staleRecords = [
      { _index: 0, _timestamp_ms: 1000, 'cam/image_array': 'old_0.jpg', 'user/angle': 0.1, 'user/throttle': 0.5 },
      { _index: 1, _timestamp_ms: 2000, 'cam/image_array': 'old_1.jpg', 'user/angle': -0.1, 'user/throttle': 0.45 },
    ];
    useStore.setState({
      config: null,
      configPath: '/home/x/mycar',
      configAutoLoadTried: false,
      tubPath: '/home/x/oldcar/data/old_tub',
      loadedTubPath: '/home/x/oldcar/data/old_tub',
      records: staleRecords,
      originalRecords: staleRecords,
      totalRecords: 2,
      tubTotalRecords: 2,
      totalPhysicalRecords: 3,
      deletedIndexes: [2],
      fields: ['cam/image_array', 'user/angle', 'user/throttle'],
      currentIndex: 1,
      activeSessionId: 'sess_261020_1',
      activeSessionRecords: [staleRecords[0]],
      isPlaying: true,
    });
    mockLoadConfig.mockResolvedValue({ status: true, config: { IMAGE_H: 120 } } as never);
    // 持久化 tub、<car>/data、子 tub 发现三条路全部失败
    mockLoadTub.mockRejectedValue(new Error('tub load failed') as never);
    mockListChildTubs.mockRejectedValue(new Error('discovery failed') as never);

    render(<Harness />);

    // 500ms 延迟的 configPath 恢复 → 持久化 tub 失败 → ./data 失败 → 子 tub 发现失败
    await waitFor(
      () => { expect(mockListChildTubs).toHaveBeenCalledWith('/home/x/mycar/data'); },
      { timeout: 3000 },
    );
    await new Promise((resolve) => setTimeout(resolve, 50));

    const s = useStore.getState();
    expect(s.tubPath).toBe('');
    expect(s.loadedTubPath).toBeNull();
    expect(s.records).toEqual([]);
    expect(s.originalRecords).toEqual([]);
    expect(s.totalRecords).toBe(0);
    expect(s.tubTotalRecords).toBe(0);
    expect(s.totalPhysicalRecords).toBe(0);
    expect(s.deletedIndexes).toEqual([]);
    expect(s.fields).toEqual([]);
    expect(s.currentIndex).toBe(0);
    expect(s.activeSessionId).toBeNull();
    expect(s.activeSessionRecords).toEqual([]);
    expect(s.isPlaying).toBe(false);
  });

  it('过期请求晚到的子 tub 回退不得覆盖新请求已成功加载的 Tub', async () => {
    const aChildPath = `${A_DATA}/tub_7_26-10-20`;
    const aChildTubs = [
      {
        name: 'tub_7_26-10-20',
        path: aChildPath,
        record_count: 1,
        total_physical: 1,
        deleted_count: 0,
        last_modified_ms: 2000,
      },
    ];
    const discoveryA = deferred<{ status: boolean; path: string; child_tubs: typeof aChildTubs }>();
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === A_DATA) {
        return Promise.resolve({
          status: true,
          path: A_DATA,
          record_count: 0,
          total_physical_records: 0,
          records: [],
          fields: [] as string[],
          deleted_indexes: [] as number[],
        });
      }
      if (p === aChildPath) {
        return Promise.resolve({
          status: true,
          path: aChildPath,
          record_count: 1,
          total_physical_records: 1,
          records: [{ _index: 0, _timestamp_ms: 100, 'cam/image_array': 'carA_0.jpg', 'user/angle': 0, 'user/throttle': 0.5 }],
          fields: ['cam/image_array', 'user/angle', 'user/throttle'],
          deleted_indexes: [] as number[],
        });
      }
      if (p === B_DATA) return Promise.resolve(carBTubPayload);
      return Promise.reject(new Error(`unexpected loadTub path: ${p}`));
    }) as never);
    mockListChildTubs.mockImplementation(((p: string) => {
      if (p === A_DATA) return discoveryA.promise;
      return Promise.reject(new Error(`unexpected listChildTubs path: ${p}`));
    }) as never);

    // A 先发出：./data 空记录 → 进入子 tub 回退，停在挂起的 discovery 上
    const promiseA = autoLoadTubFor(CAR_A);
    await waitFor(() => { expect(mockListChildTubs).toHaveBeenCalledWith(A_DATA); });

    // B 后发出并完整成功落地
    const promiseB = autoLoadTubFor(CAR_B);
    await promiseB;
    expect(useStore.getState().tubPath).toBe(B_DATA);
    expect(useStore.getState().records).toEqual(carBRecords);

    // 过期的 A 子 tub 结果此刻才返回
    discoveryA.resolve({ status: true, path: A_DATA, child_tubs: aChildTubs });
    await promiseA;
    await new Promise((resolve) => setTimeout(resolve, 20));

    // 最终必须保留 B
    expect(useStore.getState().tubPath).toBe(B_DATA);
    expect(useStore.getState().records).toEqual(carBRecords);
    expect(useStore.getState().fields).toEqual(carBFields);
    expect(useStore.getState().totalPhysicalRecords).toBe(2);
  });

  it('过期请求的失败路径晚于新请求完成时不得再触发子 tub 发现或清除新数据', async () => {
    const loadA = deferred<unknown>();
    mockLoadTub.mockImplementation(((p: string) => {
      if (p === A_DATA) return loadA.promise;
      if (p === B_DATA) return Promise.resolve(carBTubPayload);
      return Promise.reject(new Error(`unexpected loadTub path: ${p}`));
    }) as never);
    // 返回空 child_tubs：即使旧实现仍执行发现，也不会走第二次 loadTub/setTub，
    // 这样「是否调用了发现」这一断言成为旧实现可靠的 RED 信号
    mockListChildTubs.mockResolvedValue({ status: true, path: A_DATA, child_tubs: [] } as never);

    const promiseA = autoLoadTubFor(CAR_A);
    await waitFor(() => { expect(mockLoadTub).toHaveBeenCalledWith(A_DATA); });

    const promiseB = autoLoadTubFor(CAR_B);
    await promiseB;
    expect(useStore.getState().tubPath).toBe(B_DATA);
    expect(useStore.getState().records).toEqual(carBRecords);

    // A 的失败此刻才落地
    loadA.reject(new Error('tub load failed'));
    await promiseA;
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(mockListChildTubs).not.toHaveBeenCalled();
    expect(useStore.getState().tubPath).toBe(B_DATA);
    expect(useStore.getState().records).toEqual(carBRecords);
  });
});
