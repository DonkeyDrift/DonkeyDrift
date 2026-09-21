import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const chartState = vi.hoisted(() => ({
  chart: {
    chartArea: { left: 0, right: 200, top: 0, bottom: 100 },
    scales: { x: { getValueForPixel: (px: number) => px / 20, getPixelForValue: (v: number) => v * 20 } },
    update: vi.fn(),
    destroy: vi.fn(),
    data: { datasets: [] },
    options: {},
  },
}));

vi.mock('chart.js', () => ({
  Chart: { register: vi.fn() },
  CategoryScale: {},
  LinearScale: {},
  PointElement: {},
  LineElement: {},
  Title: {},
  Legend: {},
}));

vi.mock('react-chartjs-2', () => ({
  Line: React.forwardRef((_props: unknown, ref: React.ForwardedRef<unknown>) => {
    React.useImperativeHandle(ref, () => chartState.chart);
    return React.createElement('canvas', { 'data-testid': 'chart-canvas' });
  }),
}));

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: '/' }),
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, lang: 'zh' }),
}));

vi.mock('@/lib/theme', () => ({
  useResolvedTheme: () => 'dark',
}));

const api = vi.hoisted(() => ({
  scanAiClean: vi.fn(),
  getApiErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
  deleteRecords: vi.fn(),
  getRecords: vi.fn(),
  getSessionRecords: vi.fn(),
  restoreRecords: vi.fn(),
}));

vi.mock('../services/api', () => api);

import { TubEditor } from './TubEditor';
import { useStore } from '../store/useStore';

const makeRecords = () =>
  Array.from({ length: 10 }, (_, i) => ({
    _index: i,
    _timestamp_ms: i * 100,
    'user/angle': 0,
    'user/throttle': 0,
  }));

describe('TubEditor AI 一键筛选 (issue #402)', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    api.scanAiClean.mockResolvedValue({ status: true, tubs: [], total_segments: 0, total_frames: 0 });
    api.deleteRecords.mockResolvedValue({ total_physical_records: 10, deleted_indexes: [] });
    api.getRecords.mockResolvedValue({ records: [] });
    api.getSessionRecords.mockResolvedValue({ records: [] });
    api.restoreRecords.mockResolvedValue({});
    useStore.setState({
      records: makeRecords(),
      tubPath: '/tmp/tub',
      fields: ['user/angle', 'user/throttle'],
      activeSessionId: null,
      activeSessionRecords: [],
      currentIndex: 0,
      isPlaying: false,
      isDragging: false,
      selectionStartIndex: null,
      selectionEndIndex: null,
      deletedIndexes: [],
      totalPhysicalRecords: 10,
    });
  });

  it('扫描当前 tub 无片段时提示「未发现碰撞后倒车数据」', async () => {
    api.scanAiClean.mockResolvedValue({
      status: true,
      tubs: [
        { tub_path: '/tmp/tub', record_count: 10, segments: [], segment_count: 0, frame_count: 0 },
      ],
      total_segments: 0,
      total_frames: 0,
    });
    render(<TubEditor />);

    fireEvent.click(screen.getByLabelText('tubEditor.aiFilterEntryAria'));

    await waitFor(() => {
      expect(api.scanAiClean).toHaveBeenCalledWith(['/tmp/tub'], null);
      expect(screen.getByText('tubEditor.aiFilterNoSegments')).toBeInTheDocument();
    });
    expect(screen.queryByText('tubEditor.aiFilterTitle')).not.toBeInTheDocument();
  });

  it('会话视图下按当前会话扫描，识别到片段后弹确认层并可删除', async () => {
    useStore.getState().setActiveSession('s1', makeRecords());
    api.scanAiClean.mockResolvedValue({
      status: true,
      tubs: [
        {
          tub_path: '/tmp/tub',
          record_count: 10,
          segment_count: 1,
          frame_count: 3,
          segments: [
            {
              start_index: 3,
              end_index: 5,
              frame_count: 3,
              indexes: [3, 4, 5],
              reason_code: 'stop_then_reverse',
              detail: { collision_index: 3, reverse_frames: 3 },
            },
          ],
        },
      ],
      total_segments: 1,
      total_frames: 3,
    });
    render(<TubEditor />);

    fireEvent.click(screen.getByLabelText('tubEditor.aiFilterEntryAria'));

    await waitFor(() => {
      expect(api.scanAiClean).toHaveBeenCalledWith(['/tmp/tub'], 's1');
      expect(screen.getByText('tubEditor.aiFilterTitle')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('tubEditor.aiFilterConfirm'));

    await waitFor(() => {
      expect(api.deleteRecords).toHaveBeenCalledWith([3, 4, 5]);
      expect(screen.queryByText('tubEditor.aiFilterTitle')).not.toBeInTheDocument();
    });
  });
});
