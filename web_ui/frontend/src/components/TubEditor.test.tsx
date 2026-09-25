import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const chartState = vi.hoisted(() => {
  const chart = {
    chartArea: { left: 0, right: 200, top: 0, bottom: 100 },
    scales: { x: { getValueForPixel: (px: number) => px / 20, getPixelForValue: (v: number) => v * 20 } },
    update: vi.fn(),
    destroy: vi.fn(),
    data: { datasets: [] },
    options: {},
  };
  return { chart };
});

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
  useTranslation: () => ({
    // 插值 mock：携带参数时返回 key + JSON 参数，便于断言文案口径（与 useMyPcProbe.test.ts 手法一致）
    t: (key: string, params?: Record<string, unknown>) =>
      params ? `${key} ${JSON.stringify(params)}` : key,
    lang: 'zh',
  }),
}));

vi.mock('@/lib/theme', () => ({
  useResolvedTheme: () => 'dark',
}));

vi.mock('../services/api', () => ({
  deleteRecords: vi.fn(),
  getRecords: vi.fn(() => Promise.resolve({ records: [] })),
  getSessionRecords: vi.fn(() => Promise.resolve({ records: [] })),
  restoreRecords: vi.fn(),
}));

import { TubEditor } from './TubEditor';
import { useStore } from '../store/useStore';

const makeRecords = () =>
  Array.from({ length: 10 }, (_, i) => ({
    _index: i,
    _timestamp_ms: i * 100,
    'user/angle': 0,
    'user/throttle': 0,
  }));

const mountEditor = () => {
  // active=true 使全局快捷键（Escape 等）生效（#178：section 在视口内才响应快捷键）
  render(<TubEditor active />);
  // 重置模块级「两次点击」锚点，避免跨用例污染（Escape 会清锚点与选区）
  fireEvent.keyDown(window, { key: 'Escape' });
  return screen.getByTestId('tub-editor-chart');
};

describe('TubEditor 拖拽框选', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    const records = makeRecords();
    useStore.getState().setActiveSession('s1', records);
    useStore.setState({ totalRecords: records.length });
    useStore.getState().clearSelectionRange();
  });

  it('水平拖拽超过阈值后松手提交选区', async () => {
    const chart = mountEditor();
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseMove(chart, { clientX: 140, clientY: 50 });

    // 拖拽中容器切换为拖拽光标（草稿框激活）
    expect(chart.className).toContain('cursor-ew-resize');

    fireEvent.mouseUp(chart);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  it('水平位移低于阈值时视为点击，不产生拖拽选区', async () => {
    const chart = mountEditor();
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseMove(chart, { clientX: 42, clientY: 50 });
    fireEvent.mouseUp(chart);

    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().selectionEndIndex).toBeNull();
  });

  it('位移小于阈值时保留两次点击锚点行为：第二次点击提交锚点选区', async () => {
    const chart = mountEditor();

    // 第一次点击（伴随 2px 微小移动）：只记录锚点，不产生选区
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseMove(chart, { clientX: 42, clientY: 50 });
    fireEvent.mouseUp(chart);

    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().currentIndex).toBe(2);

    // 第二次点击：锚点 2 → 7 提交选区 [2, 8)（既有两次点击行为不受影响）
    fireEvent.mouseDown(chart, { clientX: 140, clientY: 50, button: 0 });
    fireEvent.mouseUp(chart);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  it('拖拽中离开图表提交选区', async () => {
    const chart = mountEditor();
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseMove(chart, { clientX: 140, clientY: 50 });
    fireEvent.mouseLeave(chart);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  it('拖拽中按 Escape 取消选区', async () => {
    const chart = mountEditor();
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseMove(chart, { clientX: 140, clientY: 50 });
    expect(chart.className).toContain('cursor-ew-resize');

    fireEvent.keyDown(window, { key: 'Escape' });

    // 草稿清除，光标恢复
    expect(chart.className).toContain('cursor-crosshair');

    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().selectionEndIndex).toBeNull();
  });
});

describe('TubEditor 帧计数口径标签', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  it('全局视图渲染「有效 N / 物理 P 帧 · 已删 D」', () => {
    const records = makeRecords();
    useStore.setState({
      records,
      activeSessionId: null,
      activeSessionRecords: [],
      totalPhysicalRecords: 12,
      deletedIndexes: [2, 5],
    });
    mountEditor();

    // 有效 10（物理 12 中有 2 帧已软删除，与录制视频库的「N 帧」口径对齐）
    expect(
      screen.getByText('tubEditor.framesGlobalScope {"count":10,"physical":12,"deleted":2}')
    ).toBeInTheDocument();
  });

  it('会话作用域（activeSessionId 非空）渲染「本录制 M 帧」', () => {
    const records = makeRecords();
    useStore.getState().setActiveSession('s1', records);
    mountEditor();

    expect(screen.getByText('tubEditor.framesSessionScope {"count":10}')).toBeInTheDocument();
  });
});

describe('TubEditor 缩放区域不可选中（与旧版一致）', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    const records = makeRecords();
    useStore.getState().setActiveSession('s1', records);
    useStore.setState({ totalRecords: records.length });
  });

  // 全局 user-select:text（文本可复制）放开后，缩放/框选交互面必须显式 select-none，
  // 否则拖拽框选、滚轮缩放会拖出文本选区，手感与旧版（全局 user-select:none）不一致
  it('图表容器带 select-none，拖拽框选/滚轮缩放不产生文本选区', () => {
    const chart = mountEditor();
    expect(chart.className).toContain('select-none');
  });

  it('底部滑条容器带 select-none', () => {
    const { container } = render(<TubEditor active />);
    const slider = container.querySelector('.tub-editor-scroll-slider');
    expect(slider?.parentElement?.className).toContain('select-none');
  });

  it('缩放倍率指示簇带 select-none', () => {
    mountEditor();
    const zoomLabel = screen.getByText('tubEditor.zoomLabel');
    expect(zoomLabel.parentElement?.className).toContain('select-none');
  });
});
