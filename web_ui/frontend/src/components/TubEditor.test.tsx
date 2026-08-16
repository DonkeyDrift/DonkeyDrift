import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
import type { Plugin } from 'chart.js';

// 捕获 Line 收到的插件与 ref，注入伪造 chart 实例，避免 jsdom 下 chart.js 真实 canvas 渲染
let lastPlugins: Plugin<'line'>[] = [];
let lastChartRef: React.MutableRefObject<unknown> | null = null;
let fakeChartInstance: unknown = null;

vi.mock('react-chartjs-2', () => ({
  Line: React.forwardRef((props: { plugins?: Plugin<'line'>[] }, ref: React.Ref<unknown>) => {
    lastPlugins = props.plugins ?? [];
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

// 伪造 2d context：所有方法为 vi.fn()，便于断言选区框绘制参数
const createFakeCtx = () => {
  const ctx = {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    setLineDash: vi.fn(),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 1,
    lineDashOffset: 0,
    globalAlpha: 1,
  };
  return ctx;
};

const createFakeChart = (ctx: ReturnType<typeof createFakeCtx>) => {
  const chartArea = { left: 0, right: CHART_WIDTH, top: 0, bottom: 400 };
  return {
    chartArea,
    ctx,
    update: vi.fn(),
    scales: {
      x: {
        getPixelForValue: (value: number) => (value / TOTAL_RECORDS) * CHART_WIDTH,
        getValueForPixel: (pixel: number) => (pixel / CHART_WIDTH) * TOTAL_RECORDS,
      },
      y: { top: 0, bottom: 400 },
    },
  } as unknown as Parameters<Plugin<'line'>['afterDraw']>[0];
};

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

const renderWithChart = (ctx: ReturnType<typeof createFakeCtx>) => {
  fakeChartInstance = createFakeChart(ctx);
  lastPlugins = [];
  const view = render(<TubEditor />);
  return view;
};

describe('TubEditor 选区框 (#130)', () => {
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
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    fakeChartInstance = null;
    resetStore();
  });

  it('确认态：框选两个 frame 时选区框按最小可见宽度绘制', () => {
    const ctx = createFakeCtx();
    useStore.setState({
      records: makeRecords(TOTAL_RECORDS),
      totalRecords: TOTAL_RECORDS,
      totalPhysicalRecords: TOTAL_RECORDS,
      // 两个 frame：数组下标 500、501（endIndex 为排他下标 502）
      selectionStartIndex: 500,
      selectionEndIndex: 502,
    });

    renderWithChart(ctx);

    const verticalLinePlugin = lastPlugins.find((p) => p.id === 'verticalLine');
    expect(verticalLinePlugin?.afterDraw).toBeDefined();

    verticalLinePlugin!.afterDraw!(createFakeChart(ctx), {} as never, {} as never);

    // 实际像素宽度 = 2/5000*1000 = 0.4px，不足 1px；应放大到 6px 最小宽度
    const selectionFill = ctx.fillRect.mock.calls.find(
      ([, y, , height]) => y === 0 && height === 400
    );
    expect(selectionFill).toBeDefined();
    expect(selectionFill![0]).toBeCloseTo(100, 5); // 起点：_index 500 → 100px
    expect(selectionFill![2]).toBeGreaterThanOrEqual(6);

    const selectionStroke = ctx.strokeRect.mock.calls.find(
      ([, y, , height]) => y === 0 && height === 400
    );
    expect(selectionStroke).toBeDefined();
    expect(selectionStroke![2]).toBeGreaterThanOrEqual(6);
  });

  it('拖选：像素位移小于 3px 但跨了多个 frame 时，不坍缩成单帧', () => {
    const ctx = createFakeCtx();
    useStore.setState({
      records: makeRecords(TOTAL_RECORDS),
      totalRecords: TOTAL_RECORDS,
      totalPhysicalRecords: TOTAL_RECORDS,
    });

    const { container } = renderWithChart(ctx);

    const chartDiv = container.querySelector<HTMLElement>('.cursor-crosshair');
    expect(chartDiv).not.toBeNull();

    // 每帧仅 0.2px 宽：位移 2px 已跨越约 10 个 frame，但 pixelDelta < 3
    fireEvent.mouseDown(chartDiv!, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.mouseMove(chartDiv!, { clientX: 102, clientY: 100 });
    fireEvent.mouseUp(chartDiv!);

    const state = useStore.getState();
    expect(state.selectionStartIndex).toBe(500);
    // 不再被当作单击处理：选区跨越多个 frame
    expect(state.selectionEndIndex! - state.selectionStartIndex!).toBeGreaterThan(1);
  });
});
