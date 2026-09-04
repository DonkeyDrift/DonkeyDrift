import '@testing-library/jest-dom/vitest';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PilotArenaPage } from './PilotArenaPage';

// mock chart.js 的 Chart 构造器：只记录 config，不真正渲染 canvas
// （jsdom 无 canvas 实现，真实 Chart 构造会非确定性地抛 "can't acquire context"）。
// 沿用 TelemetryChart.test.tsx 惯例；覆盖直接 import chart.js 的模块。
// 注意：本文件里真实 Chart 构造路径已被下面的 react-chartjs-2 mock 切断，
// 此 chart.js mock 属防御性兜底；但 react-chartjs-2 的 mock 不可删——
// 删除后真实 chart.js 会在 jsdom 下随机崩溃（flake 复发）。
vi.mock('chart.js', () => {
  class MockChart {
    static register = vi.fn();
    update = vi.fn();
    destroy = vi.fn();
    config: { data?: { labels?: unknown; datasets?: unknown[] }; options?: Record<string, unknown> };
    data: { labels?: unknown; datasets?: unknown[] } | undefined;
    options: Record<string, unknown>;
    constructor(_ctx: unknown, config: { data?: { labels?: unknown; datasets?: unknown[] }; options?: Record<string, unknown> }) {
      this.config = config;
      this.data = config.data;
      this.options = config.options ?? {};
    }
  }
  return {
    Chart: MockChart,
    LineController: class {},
    BarController: class {},
    RadarController: class {},
    DoughnutController: class {},
    PolarAreaController: class {},
    BubbleController: class {},
    PieController: class {},
    ScatterController: class {},
    CategoryScale: {},
    LinearScale: {},
    PointElement: {},
    LineElement: {},
    Title: {},
    Legend: {},
    Tooltip: {},
  };
});

// 关键：本页经 react-chartjs-2 渲染 <Line>。react-chartjs-2 是外部化依赖
// （vitest 默认 externalize node_modules），其内部 import 的 chart.js 不经过
// 上面的 vi.mock 注册表，真实 chart.js 仍会被加载并在 jsdom 下随机崩溃。
// 因此直接 mock react-chartjs-2：PilotArenaPage 只用到 Line 导出，
// 以返回 null 的组件替代，彻底绕开 canvas 渲染。
vi.mock('react-chartjs-2', () => ({
  Line: () => null,
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${String(opts.v ?? opts.n ?? opts.value ?? '')}` : key,
    lang: 'zh',
  }),
}));
vi.mock('@/services/api', () => ({
  getArenaPredictions: vi.fn(),
  getImageUrl: vi.fn((path: string) => `http://localhost:5188/api/tub/image?path=${encodeURIComponent(path)}`),
  listArenaModels: vi.fn(),
  listArenaModelTypes: vi.fn(),
  loadArenaPilot: vi.fn(),
  predictArenaPilot: vi.fn(),
  unloadArenaPilot: vi.fn(() => Promise.resolve()),
  getApiErrorMessage: vi.fn((error: unknown) => String(error)),
}));
import * as api from '@/services/api';
import { useStore } from '../store/useStore';

const summaryFixture = {
  angle: { count: 1, mae: 0.15, rmse: 0.15, bias: 0.15, max_abs_error: 0.15 },
  throttle: { count: 1, mae: 0.3, rmse: 0.3, bias: 0.3, max_abs_error: 0.3 },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    'requestAnimationFrame',
    (cb: FrameRequestCallback) => window.setTimeout(() => cb(performance.now()), 0),
  );
  vi.stubGlobal('cancelAnimationFrame', (handle: number) => window.clearTimeout(handle));
  useStore.setState({
    configPath: '/tmp/tub',
    tubPath: '/tmp/tub',
    records: [
      { _index: 0, _timestamp_ms: 0, 'cam/image_array': '0_cam_image_array_.jpg', 'user/angle': 0.1, 'user/throttle': 0.2 },
    ],
    currentIndex: 0,
    config: null,
    isPlaying: false,
    isLooping: false,
  });
  vi.mocked(api.listArenaModelTypes).mockResolvedValue(['tflite_linear']);
  vi.mocked(api.listArenaModels).mockResolvedValue({
    models: [{ path: '/tmp/DKG-1.tflite', name: 'DKG-1.tflite' }],
  } as unknown as Awaited<ReturnType<typeof api.listArenaModels>>);
  vi.mocked(api.loadArenaPilot).mockResolvedValue({
    status: true,
    pilot: {
      id: 'pilot-1',
      name: 'DKG-1.tflite',
      model_path: '/tmp/DKG-1.tflite',
      model_type: 'tflite_linear',
      loaded_at: '2026-09-04T00:00:00Z',
    },
  } as unknown as Awaited<ReturnType<typeof api.loadArenaPilot>>);
  vi.mocked(api.predictArenaPilot).mockResolvedValue({
    status: true,
    record_index: 0,
    user: { angle: 0.1, throttle: 0.2 },
    pilot: { angle: 0.25, throttle: 0.5 },
  } as unknown as Awaited<ReturnType<typeof api.predictArenaPilot>>);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function loadPilotAndGeneratePlot() {
  render(<PilotArenaPage />);
  const loadButton = await screen.findByRole('button', { name: 'arena.loadAndPredict' });
  await waitFor(() => expect(loadButton).toBeEnabled());
  fireEvent.click(loadButton);
  await waitFor(() => expect(api.loadArenaPilot).toHaveBeenCalled());

  // 曲线 pilot 选择器无 label；页面有 4 个 combobox，按 option 文本稳健定位
  const plotSelect = screen.getAllByRole('combobox').find((select) =>
    within(select).queryByText('arena.selectLoadedPilot'),
  );
  if (!plotSelect) throw new Error('未找到曲线 pilot 选择器');
  fireEvent.change(plotSelect, { target: { value: 'pilot-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'arena.generatePlot' }));
  await waitFor(() => expect(api.getArenaPredictions).toHaveBeenCalled());
}

describe('PilotArenaPage 模型贴合摘要', () => {
  it('生成曲线后渲染 angle/throttle 两侧误差指标', async () => {
    vi.mocked(api.getArenaPredictions).mockResolvedValue({
      points: [
        { index: 0, user_angle: 0.1, user_throttle: 0.2, pilot_angle: 0.25, pilot_throttle: 0.5 },
      ],
      summary: summaryFixture,
    } as unknown as Awaited<ReturnType<typeof api.getArenaPredictions>>);

    await loadPilotAndGeneratePlot();

    expect(api.getArenaPredictions).toHaveBeenCalledWith(
      'pilot-1',
      expect.objectContaining({ config_path: '/tmp/tub', limit: 200 }),
    );
    expect(await screen.findByText('arena.plotSummary')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.300')).toBeInTheDocument();
    expect(screen.getByText('arena.metricRmse:0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricRmse:0.300')).toBeInTheDocument();
    expect(screen.getByText('arena.metricBias:+0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMaxErr:0.300')).toBeInTheDocument();
    expect(screen.getAllByText('arena.metricFrames:1')).toHaveLength(2);
  });

  it('单侧无数据时该侧显示无数据占位，另一侧正常展示', async () => {
    vi.mocked(api.getArenaPredictions).mockResolvedValue({
      points: [],
      summary: { angle: null, throttle: summaryFixture.throttle },
    } as unknown as Awaited<ReturnType<typeof api.getArenaPredictions>>);

    await loadPilotAndGeneratePlot();

    expect(await screen.findByText('arena.plotSummary')).toBeInTheDocument();
    expect(screen.getByText('arena.metricAngle: arena.metricNoData')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.300')).toBeInTheDocument();
  });
});
