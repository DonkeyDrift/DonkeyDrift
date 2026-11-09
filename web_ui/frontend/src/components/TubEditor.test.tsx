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
import { deleteRecords, getRecords, getSessionRecords } from '../services/api';

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

  it('拖拽越出绘图区右边界仍按边界帧推进（不被提前冻结）', async () => {
    // 真实图表 chartArea 内缩（左轴/图例/刻度留白）：越界拖拽必须继续按边界帧更新草稿框
    const originalArea = chartState.chart.chartArea;
    chartState.chart.chartArea = { left: 40, right: 190, top: 20, bottom: 90 };
    try {
      const chart = mountEditor();
      fireEvent.mouseDown(chart, { clientX: 60, clientY: 50, button: 0 });
      fireEvent.mouseMove(chart, { clientX: 90, clientY: 50 });
      // 越出右边界（clientX 500 > chartArea.right 190）：应夹取到最右一帧
      fireEvent.mouseMove(chart, { clientX: 500, clientY: 50 });
      fireEvent.mouseUp(chart);

      await waitFor(() => {
        expect(useStore.getState().selectionStartIndex).toBe(3);
        expect(useStore.getState().selectionEndIndex).toBe(10);
      });
    } finally {
      chartState.chart.chartArea = originalArea;
    }
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

describe('TubEditor 触摸框选', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    const records = makeRecords();
    useStore.getState().setActiveSession('s1', records);
    useStore.setState({ totalRecords: records.length });
    useStore.getState().clearSelectionRange();
  });

  it('触摸水平滑动超过阈值后抬手提交选区', async () => {
    const chart = mountEditor();
    fireEvent.touchStart(chart, { touches: [{ clientX: 40, clientY: 50 }] });
    fireEvent.touchMove(chart, { touches: [{ clientX: 140, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  it('触摸滑动越出绘图区右边界仍按边界帧推进', async () => {
    const chart = mountEditor();
    fireEvent.touchStart(chart, { touches: [{ clientX: 40, clientY: 50 }] });
    fireEvent.touchMove(chart, { touches: [{ clientX: 90, clientY: 50 }] });
    // 越出右边界（clientX 600 > chartArea.right 200）：应夹取到最右一帧
    fireEvent.touchMove(chart, { touches: [{ clientX: 600, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(10);
    });
  });

  it('两次轻触（位移低于阈值）提交锚点选区', async () => {
    const chart = mountEditor();

    fireEvent.touchStart(chart, { touches: [{ clientX: 40, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });
    expect(useStore.getState().selectionStartIndex).toBeNull();
    expect(useStore.getState().currentIndex).toBe(2);

    fireEvent.touchStart(chart, { touches: [{ clientX: 140, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  // 真实触屏上 touchend 之后浏览器必补发一套兼容鼠标事件（mousemove/mousedown/mouseup）。
  // React 把 touchstart/touchmove 挂成 passive，触摸 handler 里的 preventDefault 抑制不了它们，
  // 若不屏蔽，这组事件会把触摸链路刚提交的选区再走一遍鼠标逻辑（清锚点/清选区/塌缩成单帧），
  // 表现为触屏上「框不住」。下面两例按真实时序先让 rAF（≈16ms）把选区落库，再补发兼容鼠标事件。
  it('触摸滑动提交的选区不被 touchend 后补发的兼容鼠标事件清除', async () => {
    const chart = mountEditor();
    fireEvent.touchStart(chart, { touches: [{ clientX: 40, clientY: 50 }] });
    fireEvent.touchMove(chart, { touches: [{ clientX: 140, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });

    // 等 rAF 先提交（真实浏览器里兼容鼠标事件约 300ms 后才补发，远晚于此）
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(useStore.getState().selectionStartIndex).toBe(2);

    fireEvent.mouseMove(chart, { clientX: 140, clientY: 50 });
    fireEvent.mouseDown(chart, { clientX: 140, clientY: 50, button: 0 });
    fireEvent.mouseUp(chart);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
  });

  it('两次轻触的选区不被补发的兼容鼠标事件塌缩为单帧', async () => {
    const chart = mountEditor();

    // 第一次轻触：只记录锚点，不应因补发的兼容 mousedown 立刻选出单帧
    fireEvent.touchStart(chart, { touches: [{ clientX: 40, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });
    await new Promise((resolve) => setTimeout(resolve, 40));
    fireEvent.mouseDown(chart, { clientX: 40, clientY: 50, button: 0 });
    fireEvent.mouseUp(chart);
    expect(useStore.getState().selectionStartIndex).toBeNull();

    // 第二次轻触：提交锚点→当前的范围 [2, 8)，且不被补发的兼容事件塌缩
    fireEvent.touchStart(chart, { touches: [{ clientX: 140, clientY: 50 }] });
    fireEvent.touchEnd(chart, { touches: [] });
    await new Promise((resolve) => setTimeout(resolve, 40));
    fireEvent.mouseDown(chart, { clientX: 140, clientY: 50, button: 0 });
    fireEvent.mouseUp(chart);

    await waitFor(() => {
      expect(useStore.getState().selectionStartIndex).toBe(2);
      expect(useStore.getState().selectionEndIndex).toBe(8);
    });
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

  it('多选会话（activeSessionIds 多值）渲染「已选 S 段 · M 帧」', () => {
    const records = [...makeRecords(), ...makeRecords()];
    useStore.getState().setActiveSession('s1', records, ['s1', 's2']);
    mountEditor();

    expect(
      screen.getByText('tubEditor.framesSessionScopeMulti {"segments":2,"count":20}')
    ).toBeInTheDocument();
  });
});

describe('TubEditor 多选会话删除后刷新', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    const records = makeRecords();
    useStore.setState({
      records,
      tubPath: '/tmp/tub',
      fields: ['user/angle', 'user/throttle'],
      activeSessionId: null,
      activeSessionRecords: [],
      activeSessionIds: [],
      totalPhysicalRecords: records.length,
      deletedIndexes: [],
      selectionStartIndex: null,
      selectionEndIndex: null,
    });
    vi.mocked(getRecords).mockResolvedValue({ records: [] } as never);
    vi.mocked(deleteRecords).mockResolvedValue({ total_physical_records: 10, deleted_indexes: [] } as never);
  });

  it('activeSessionIds 多值时逐会话拉取并按 ids 顺序合并写回', async () => {
    const s1Records = makeRecords();
    const s2Records = makeRecords().map((r) => ({ ...r, _index: r._index + 100 }));
    useStore.getState().setActiveSession('s1', [...s1Records, ...s2Records], ['s1', 's2']);
    const getSessionRecordsMock = vi.mocked(getSessionRecords);
    getSessionRecordsMock.mockImplementation(async (_path: string, sid: string) => ({
      status: true,
      path: '/tmp/tub',
      records: sid === 's1' ? s1Records : s2Records,
    }));

    mountEditor();
    // 提交选区 [2, 5)：删除 → 触发删除后刷新
    useStore.getState().setSelectionRange(2, 5);
    await waitFor(() => {
      expect(useStore.getState().selectionEndIndex).toBe(5);
    });
    fireEvent.click(screen.getByText('tubEditor.delete'));

    await waitFor(() => {
      expect(deleteRecords).toHaveBeenCalledWith([2, 3, 4]);
      expect(getSessionRecordsMock).toHaveBeenCalledWith('/tmp/tub', 's1');
      expect(getSessionRecordsMock).toHaveBeenCalledWith('/tmp/tub', 's2');
    });
    const state = useStore.getState();
    expect(state.activeSessionIds).toEqual(['s1', 's2']);
    expect(state.activeSessionId).toBe('s1');
    // 合并 records 按 activeSessionIds 顺序
    expect(state.activeSessionRecords).toEqual([...s1Records, ...s2Records]);
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

describe('TubEditor 跨 Tub 只读合并视图', () => {
  beforeAll(() => {
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    // 前组用例（多选会话删除后刷新）实际调用过 deleteRecords，清掉调用记录
    vi.clearAllMocks();
    const records = makeRecords();
    // 跨 tub 多选挂接：setActiveSession 第 4 参 crossTub=true
    useStore.getState().setActiveSession('s1', records, ['s1', 's2'], true);
    useStore.setState({
      tubPath: '/tmp/tub',
      totalPhysicalRecords: records.length,
      deletedIndexes: [],
      selectionStartIndex: null,
      selectionEndIndex: null,
    });
  });

  it('写操作入口全部禁用，且头部出现只读徽标', () => {
    mountEditor();
    expect(screen.getByTestId('cross-tub-readonly-badge')).toBeInTheDocument();
    expect(screen.getByText('tubEditor.crossTubReadOnlyBadge')).toBeInTheDocument();
    expect(screen.getByText('tubEditor.delete')).toBeDisabled();
    expect(screen.getByText('tubEditor.restore')).toBeDisabled();
    expect(screen.getByLabelText('tubEditor.aiFilterEntryAria')).toBeDisabled();
  });

  it('框选了有效范围时删除/恢复按钮仍禁用，title 换成只读提示', () => {
    mountEditor();
    useStore.getState().setSelectionRange(2, 5);
    const deleteBtn = screen.getByText('tubEditor.delete');
    const restoreBtn = screen.getByText('tubEditor.restore');
    expect(deleteBtn).toBeDisabled();
    expect(restoreBtn).toBeDisabled();
    expect(deleteBtn).toHaveAttribute('title', 'tubEditor.crossTubReadOnlyTitle');
    expect(restoreBtn).toHaveAttribute('title', 'tubEditor.crossTubReadOnlyTitle');
  });

  it('Delete 快捷键不触发删除请求（runRecordAction 前置拦截）', () => {
    mountEditor();
    useStore.getState().setSelectionRange(2, 5);
    fireEvent.keyDown(window, { key: 'Delete' });
    expect(vi.mocked(deleteRecords)).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Backspace' });
    expect(vi.mocked(deleteRecords)).not.toHaveBeenCalled();
  });
});
