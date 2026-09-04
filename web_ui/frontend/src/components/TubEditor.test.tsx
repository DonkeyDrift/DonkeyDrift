import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, cleanup, waitFor } from '@testing-library/react';

// 捕获 Line 的 ref 并注入伪造 chart 实例，避免 jsdom 下 chart.js 真实 canvas 渲染
let lastChartRef: React.MutableRefObject<unknown> | null = null;
let fakeChartInstance: unknown = null;

vi.mock('react-chartjs-2', () => ({
  Line: React.forwardRef((_props: Record<string, unknown>, ref: React.Ref<unknown>) => {
    lastChartRef = ref as React.MutableRefObject<unknown>;
    if (fakeChartInstance) {
      lastChartRef.current = fakeChartInstance;
    }
    return <div data-testid="mock-chart" />;
  }),
}));

import { TubEditor } from './TubEditor';
import { useStore } from '../store/useStore';

const TOTAL_RECORDS = 5000;
const CHART_WIDTH = 1000;

const createFakeChart = () => ({
  chartArea: { left: 0, right: CHART_WIDTH, top: 0, bottom: 400 },
  ctx: {},
  update: vi.fn(),
  scales: {
    x: {
      getPixelForValue: (value: number) => (value / TOTAL_RECORDS) * CHART_WIDTH,
      getValueForPixel: (pixel: number) => (pixel / CHART_WIDTH) * TOTAL_RECORDS,
    },
    y: { top: 0, bottom: 400 },
  },
});

const makeRecords = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    _index: i,
    _timestamp_ms: i,
    'user/angle': 0.1,
    'user/throttle': 0.2,
  }));

const resetStore = () => {
  useStore.setState({
    records: [],
    activeSessionId: null,
    activeSessionRecords: [],
    totalRecords: 0,
    totalPhysicalRecords: 0,
    deletedIndexes: [],
    currentIndex: 0,
    selectionStartIndex: null,
    selectionEndIndex: null,
    selectionHistory: [],
    selectionHistoryIndex: -1,
    isPlaying: false,
    isDragging: false,
  });
};

const renderWithChart = () => {
  fakeChartInstance = createFakeChart();
  // active=true 使全局快捷键（Escape）生效
  return render(<TubEditor active />);
};

describe('TubEditor 拖拽框选（Issue #002）', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: CHART_WIDTH,
      bottom: 400,
      width: CHART_WIDTH,
      height: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    resetStore();
    useStore.setState({
      records: makeRecords(TOTAL_RECORDS),
      totalRecords: TOTAL_RECORDS,
      totalPhysicalRecords: TOTAL_RECORDS,
    });
  });

  afterEach(() => {
    // 重置模块级两次点击锚点，避免跨用例泄漏
    fireEvent.keyDown(window, { key: 'Escape' });
    cleanup();
    vi.restoreAllMocks();
    fakeChartInstance = null;
    lastChartRef = null;
    resetStore();
  });

  it('拖拽位移超过阈值时，mouseup 提交框选范围', async () => {
    const { container } = renderWithChart();
    const chartDiv = container.querySelector<HTMLElement>('.cursor-crosshair');
    expect(chartDiv).not.toBeNull();

    // 100px → 帧 500，300px → 帧 1500
    fireEvent.mouseDown(chartDiv!, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.mouseMove(chartDiv!, { clientX: 300, clientY: 100 });

    // 拖拽中容器切换为拖拽光标（草稿框激活）
    expect(chartDiv!.className).toContain('cursor-ew-resize');

    fireEvent.mouseUp(chartDiv!);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(500);
      expect(useStore.getState().selectionEndIndex).toBe(1501);
    });
  });

  it('位移小于阈值时视为点击：不提交拖拽选区，保留两次点击锚点行为', () => {
    const { container } = renderWithChart();
    const chartDiv = container.querySelector<HTMLElement>('.cursor-crosshair');
    expect(chartDiv).not.toBeNull();

    // 第一次点击（伴随 2px 微小移动）：只记录锚点，不产生选区
    fireEvent.mouseDown(chartDiv!, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.mouseMove(chartDiv!, { clientX: 102, clientY: 100 });
    fireEvent.mouseUp(chartDiv!);

    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().currentIndex).toBe(500);

    // 第二次点击：锚点 500 → 1500 提交选区（既有两次点击行为不受影响）
    fireEvent.mouseDown(chartDiv!, { clientX: 300, clientY: 100, button: 0 });
    fireEvent.mouseUp(chartDiv!);

    expect(useStore.getState().selectionStartIndex).toBe(500);
    expect(useStore.getState().selectionEndIndex).toBe(1501);
  });

  it('拖拽中鼠标移出图表时，提交到离开点', async () => {
    const { container } = renderWithChart();
    const chartDiv = container.querySelector<HTMLElement>('.cursor-crosshair');
    expect(chartDiv).not.toBeNull();

    fireEvent.mouseDown(chartDiv!, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.mouseMove(chartDiv!, { clientX: 300, clientY: 100 });
    fireEvent.mouseLeave(chartDiv!, { clientX: 300, clientY: 100 });
    fireEvent.mouseOut(chartDiv!, { clientX: 300, clientY: 100 });

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(500);
      expect(useStore.getState().selectionEndIndex).toBe(1501);
    });
  });

  it('Escape 取消进行中的拖拽：清除草稿且不提交选区', async () => {
    const { container } = renderWithChart();
    const chartDiv = container.querySelector<HTMLElement>('.cursor-crosshair');
    expect(chartDiv).not.toBeNull();

    fireEvent.mouseDown(chartDiv!, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.mouseMove(chartDiv!, { clientX: 300, clientY: 100 });
    expect(chartDiv!.className).toContain('cursor-ew-resize');

    fireEvent.keyDown(window, { key: 'Escape' });

    // 草稿清除，光标恢复
    expect(chartDiv!.className).toContain('cursor-crosshair');

    fireEvent.mouseUp(chartDiv!);

    // 等待可能的 rAF flush，确认未提交任何选区
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().selectionEndIndex).toBeNull();
  });
});
