import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConfigLoader } from './ConfigLoader';
import { useStore } from '../store/useStore';
import { loadConfig, loadTub, listChildTubs } from '../services/api';

// 最终代码审查缺陷：浏览配置入口（FileBrowserModal 选择车辆目录）没有像手动
// 加载那样优先恢复持久化的 tubPath，而是直接 autoLoadTubFor(<car>) 加载
// <car>/data——用户上次选定的 tub 被静默替换成本次车辆目录下的默认 data。
// 本测试要求：选择车辆目录后仍 loadConfig(<car>)，但 Tub 应优先恢复
// store 里持久化的路径，而不是直接加载 <car>/data。

const { CAR_DIR } = vi.hoisted(() => ({ CAR_DIR: '/home/x/mycar' }));
const SAVED_TUB = '/saved/tub';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./FileBrowserModal', () => ({
  // 简化的浏览入口：打开时提供一个触发 onSelect('/home/x/mycar') 的按钮，
  // 只替掉目录浏览 UI，配置加载与 tub 恢复链路保持真实。
  FileBrowserModal: ({
    isOpen,
    onSelect,
  }: {
    isOpen: boolean;
    onSelect: (path: string) => void;
  }) => (isOpen ? <button onClick={() => onSelect('/home/x/mycar')}>pick-mycar</button> : null),
}));

// 只在外部边界 mock：autoLoadTubFor（含 listChildTubs 回退）保持真实逻辑
vi.mock('../services/api', () => ({
  loadConfig: vi.fn(),
  loadTub: vi.fn(),
  listChildTubs: vi.fn(),
  discoverProjects: vi.fn(),
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const mockLoadConfig = vi.mocked(loadConfig);
const mockLoadTub = vi.mocked(loadTub);
const mockListChildTubs = vi.mocked(listChildTubs);

// 与后端响应结构一致（routers/tub.py /config 与 /tub/load）
const savedTubRecords = [
  { _index: 0, _timestamp_ms: 1000, 'cam/image_array': 'saved_cam_0.jpg' },
  { _index: 1, _timestamp_ms: 1001, 'cam/image_array': 'saved_cam_1.jpg' },
];
const dataTubRecords = [{ _index: 0, _timestamp_ms: 2000, 'cam/image_array': 'data_cam_0.jpg' }];

const tubResponse = (path: string, records: typeof savedTubRecords) => ({
  status: true,
  record_count: records.length,
  total_physical_records: records.length,
  records,
  fields: ['cam/image_array', 'user/angle'],
  path,
  deleted_indexes: [] as number[],
});

describe('ConfigLoader 浏览选择车辆目录', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      config: null,
      configPath: '',
      tubPath: SAVED_TUB,
      records: [],
      originalRecords: [],
      fields: [],
      totalPhysicalRecords: 0,
      deletedIndexes: [],
      isLoading: false,
      error: null,
    });
    mockLoadConfig.mockImplementation(async (path: string) => ({
      status: true,
      message: `Config loaded from ${path}`,
      config: { DRIVE_LOOP_HZ: 60 },
    }));
    mockLoadTub.mockImplementation(async (path: string) =>
      path === SAVED_TUB ? tubResponse(SAVED_TUB, savedTubRecords) : tubResponse(path, dataTubRecords),
    );
    mockListChildTubs.mockImplementation(async (tubPath: string) => ({
      status: true,
      path: tubPath,
      child_tubs: [],
    }));
  });

  it('应优先恢复持久化的 tubPath，而不是直接加载 <car>/data', async () => {
    render(<ConfigLoader />);

    fireEvent.click(screen.getByLabelText('common.configLoader.browseAria'));
    fireEvent.click(await screen.findByRole('button', { name: 'pick-mycar' }));

    // 等整条加载链走完（finally 复位 isLoading），避免在旧实现异步覆盖前误判
    await waitFor(() => {
      expect(useStore.getState().isLoading).toBe(false);
      expect(mockLoadTub.mock.calls.length).toBeGreaterThan(0);
    });

    expect(mockLoadConfig).toHaveBeenCalledWith(CAR_DIR);
    expect(mockLoadTub).toHaveBeenCalledWith(SAVED_TUB);
    expect(useStore.getState().configPath).toBe(CAR_DIR);
    expect(useStore.getState().tubPath).toBe(SAVED_TUB);
    expect(useStore.getState().records).toEqual(savedTubRecords);
  });
});
