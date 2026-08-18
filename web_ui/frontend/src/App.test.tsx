import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, act, waitFor } from '@testing-library/react';
import App from './App';
import { useStore } from './store/useStore';

// 回归测试（#135）：顶部导航切回 Tub Manager 不应重新全量拉取 tub，
// 仅在首次加载（含刷新页面恢复 tubPath）和手动刷新时拉取。

vi.mock('./services/api', () => ({
  loadTub: vi.fn(),
  getVersion: vi.fn(() => Promise.resolve('test')),
  getApiErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
  getImageUrl: vi.fn(),
}));

vi.mock('./components/SidePanel', () => ({
  SidePanel: () => <div data-testid="side-panel" />,
}));
vi.mock('./components/TubLibrary', () => ({
  TubLibrary: () => <div data-testid="tub-library" />,
}));
vi.mock('./components/TubEditor', () => ({
  TubEditor: () => <div data-testid="tub-editor" />,
}));
vi.mock('./components/FabActions', () => ({
  FabActions: () => <div data-testid="fab-actions" />,
}));

const { loadTub } = await import('./services/api');

const resetStore = (overrides: Partial<ReturnType<typeof useStore.getState>> = {}) => {
  useStore.setState({
    config: null,
    configPath: '',
    tubPath: '',
    loadedTubPath: null,
    tubRefreshToken: 0,
    records: [],
    originalRecords: [],
    totalRecords: 0,
    totalPhysicalRecords: 0,
    deletedIndexes: [],
    currentIndex: 0,
    fields: [],
    isLoading: false,
    error: null,
    ...overrides,
  });
};

const sampleTub = {
  path: '/tmp/tub',
  records: [{ _index: 0, _timestamp_ms: 0 }],
  fields: ['user/angle'],
  total_physical_records: 1,
  deleted_indexes: [] as number[],
};

describe('TubManagerPage data fetching (#135)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(loadTub).mockResolvedValue(sampleTub);
    resetStore();
  });

  it('fetches the tub on first load when tubPath is set but not loaded yet', async () => {
    resetStore({ tubPath: '/tmp/tub', loadedTubPath: null });
    render(<App />);
    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledTimes(1);
      expect(loadTub).toHaveBeenCalledWith('/tmp/tub');
    });
    // setTub 后 loadedTubPath 已标记，不再重复拉取
    expect(useStore.getState().loadedTubPath).toBe('/tmp/tub');
    await waitFor(() => {
      expect(useStore.getState().isLoading).toBe(false);
    });
    expect(loadTub).toHaveBeenCalledTimes(1);
  });

  it('does not refetch when the tub is already loaded', () => {
    resetStore({ tubPath: '/tmp/tub', loadedTubPath: '/tmp/tub' });
    render(<App />);
    expect(loadTub).not.toHaveBeenCalled();
  });

  it('refetches when requestTubRefresh is invoked', async () => {
    resetStore({ tubPath: '/tmp/tub', loadedTubPath: '/tmp/tub' });
    render(<App />);
    expect(loadTub).not.toHaveBeenCalled();

    act(() => {
      useStore.getState().requestTubRefresh();
    });

    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledTimes(1);
    });
  });

  it('does not fetch when no tubPath is set', () => {
    resetStore({ tubPath: '', loadedTubPath: null });
    render(<App />);
    expect(loadTub).not.toHaveBeenCalled();
  });
});
