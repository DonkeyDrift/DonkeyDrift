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
// 懒加载页面 mock 成占位 div：导航保活测试只关心路由切换与 TM 保活，不渲染真实页面
vi.mock('./pages/TrainerPage', () => ({ TrainerPage: () => <div data-testid="trainer-page" /> }));
vi.mock('./pages/DrivePage', () => ({ DrivePage: () => <div data-testid="drive-page" /> }));
vi.mock('./pages/PilotArenaPage', () => ({ PilotArenaPage: () => <div data-testid="pilot-page" /> }));
vi.mock('./pages/CarConnectorPage', () => ({ CarConnectorPage: () => <div data-testid="connector-page" /> }));

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

describe('TubManager keep-alive navigation (#135 round 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(loadTub).mockResolvedValue(sampleTub);
    resetStore();
  });

  const go = (hash: string) => {
    act(() => {
      window.location.hash = hash;
    });
  };

  // #178 起 TM 并入统一流程大页面，任何流程页 path 下都保持常驻挂载；
  // 只有切到独立路由 /connector 才会卸载，且回切后因已加载而不重新拉取 tub。
  it('keeps Tub Manager mounted across flow sections and avoids refetch', async () => {
    resetStore({ tubPath: '/tmp/tub', loadedTubPath: null });
    const { container } = render(<App />);
    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledTimes(1);
    });

    const library = container.querySelector('[data-testid="tub-library"]') as HTMLElement;
    const editor = container.querySelector('[data-testid="tub-editor"]') as HTMLElement;
    expect(library).not.toBeNull();
    expect(editor).not.toBeNull();

    // 切到 Drive / Trainer / Pilot：TM 仍挂载、未重新拉取
    for (const hash of ['#/drive', '#/trainer', '#/pilot', '#/tub']) {
      go(hash);
      await waitFor(() => {
        expect(container.querySelector('[data-testid="tub-library"]')).not.toBeNull();
        expect(container.querySelector('[data-testid="tub-editor"]')).not.toBeNull();
      });
    }
    expect(loadTub).toHaveBeenCalledTimes(1);

    // 切到独立路由 Car Connector：流程页卸载，TM 随之卸载
    go('#/connector');
    await waitFor(() => {
      expect(container.querySelector('[data-testid="tub-library"]')).toBeNull();
    });

    // 回切流程页：TM 重新挂载，但因 tub 已加载不重新拉取
    go('#/');
    await waitFor(() => {
      expect(container.querySelector('[data-testid="tub-library"]')).not.toBeNull();
    });
    expect(loadTub).toHaveBeenCalledTimes(1);
  });
});
