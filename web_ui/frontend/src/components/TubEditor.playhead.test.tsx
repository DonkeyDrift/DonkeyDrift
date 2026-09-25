import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// 60fps 回放优化回归（TubEditor 侧）：播放期索引变化只移动 DOM 竖线叠加层，
// 不触发 chart.update 全量重绘（原先每次索引变化都经 markPlaybackActive 让渲染循环
// 60Hz 持续重绘图表，加上组件级 currentIndex 订阅的高频 re-render，主线程被吃满，
// 同页 TubLibrary 回放的 rAF 被饿死而掉帧）。

const fakeChart = vi.hoisted(() => ({
  update: vi.fn(),
  scales: {
    x: {
      getPixelForValue: (v: number) => v * 10,
      getValueForPixel: (px: number) => px / 10,
    },
    y: { top: 10, bottom: 110 },
  },
  chartArea: { left: 0, right: 1000, top: 10, bottom: 110 },
  ctx: {},
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
  Line: React.forwardRef((_props: unknown, ref: React.Ref<unknown>) => {
    React.useEffect(() => {
      if (typeof ref === 'function') ref(fakeChart);
      else if (ref) (ref as { current: unknown }).current = fakeChart;
    }, [ref]);
    return <canvas data-testid="tub-editor-chart" />;
  }),
}));

vi.mock('../services/api', () => ({
  deleteRecords: vi.fn(),
  getRecords: vi.fn(),
  getSessionRecords: vi.fn(),
  restoreRecords: vi.fn(),
}));

import { TubEditor } from './TubEditor';
import { useStore } from '../store/useStore';

const RECORD_COUNT = 10;
const makeRecords = () =>
  Array.from({ length: RECORD_COUNT }, (_, i) => ({
    _index: i,
    _timestamp_ms: i * 16,
    'user/angle': 0.1,
    'user/throttle': 0.2,
  }));

let rafQueue: FrameRequestCallback[];
const pump = (t: number) => {
  const cbs = rafQueue;
  rafQueue = [];
  cbs.forEach((cb) => cb(t));
};

beforeEach(() => {
  vi.clearAllMocks();
  rafQueue = [];
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    rafQueue.push(cb);
    return rafQueue.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {});
  useStore.setState({
    records: makeRecords() as never,
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
    totalPhysicalRecords: RECORD_COUNT,
  });
});

const renderEditor = () =>
  render(
    <MemoryRouter>
      <TubEditor />
    </MemoryRouter>,
  );

describe('TubEditor playhead overlay (60fps playback)', () => {
  it('moves the playhead overlay on index change without any chart.update', () => {
    renderEditor();
    // 挂载后的初始化重绘（主题/数据 effect）泵掉并清零
    pump(1000);
    fakeChart.update.mockClear();

    act(() => {
      useStore.setState({ currentIndex: 5 });
    });
    // 渲染循环不应被唤醒；即便有挂起 rAF 也不许触发 update
    pump(1016);

    const overlay = screen.getByTestId('playhead-overlay');
    expect(overlay.style.display).toBe('');
    // getPixelForValue(5) = 50，减 1px 让 2px 竖线居中
    expect(overlay.style.transform).toBe('translateX(49px)');
    expect(fakeChart.update).not.toHaveBeenCalled();

    // 非受控滑块经 ref 直写 DOM 同步
    const slider = document.querySelector('input[type="range"]') as HTMLInputElement;
    expect(slider.value).toBe('5');
  });

  it('hides the overlay when the playhead is outside the visible chart area', () => {
    renderEditor();
    pump(1000);
    fakeChart.update.mockClear();

    act(() => {
      useStore.setState({ currentIndex: 8 });
    });
    expect(screen.getByTestId('playhead-overlay').style.display).toBe('');

    // x = 200*10 = 2000px，超出 chartArea.right = 1000
    act(() => {
      useStore.setState({ currentIndex: 200 });
    });
    expect(screen.getByTestId('playhead-overlay').style.display).toBe('none');
    expect(fakeChart.update).not.toHaveBeenCalled();
  });

  it('keeps the click-to-inspect chart redraw path alive (exactly one update)', () => {
    const { container } = renderEditor();
    pump(1000);
    fakeChart.update.mockClear();

    const chartArea = container.querySelector('.touch-none') as HTMLElement;
    // clientX=100 → getValueForPixel(100)=10 → 取整并钳到最后一帧 index 9
    fireEvent.mouseDown(chartArea, { clientX: 100, clientY: 50, button: 0 });
    // mousedown 置悬停位触发一次 chart 重绘；setCurrentIndex(9) 只移动叠加层
    pump(1016);

    expect(fakeChart.update).toHaveBeenCalledTimes(1);
    expect(useStore.getState().currentIndex).toBe(9);
    expect(screen.getByTestId('playhead-overlay').style.transform).toBe('translateX(89px)');
  });
});

// 用户报障：TM 页面「上方录制视频库的播放进度条」与「下方 Tub 编辑器图表下的滑块」
// 不同步。根因：下方滑块的 DOM 值只在「没有焦点」时才写——用户点过/拖过它一次，焦点
// 就一直留在 range 上，此后全局播放位置（回放、上方进度条、首末帧按钮、键盘方向键）
// 再怎么变都不会写回它的 DOM 值，下方进度条永久停在旧位置。改为只认「指针按下」的
// 拖动态让位，并在记录集/量程变化后重新校准。
describe('TubEditor 上下播放进度条同步', () => {
  const getSlider = () =>
    document.querySelector('input[type="range"]') as HTMLInputElement;

  it('滑块持有焦点时仍跟随全局播放位置', () => {
    renderEditor();
    pump(1000);
    const slider = getSlider();

    act(() => {
      slider.focus();
    });
    expect(document.activeElement).toBe(slider);

    act(() => {
      useStore.setState({ currentIndex: 4 });
    });

    expect(slider.value).toBe('4');
  });

  it('用户拖动期间不被外部播放位置拽走，抬起后立刻重新对齐', () => {
    renderEditor();
    pump(1000);
    const slider = getSlider();

    act(() => {
      fireEvent.pointerDown(slider);
    });
    act(() => {
      fireEvent.input(slider, { target: { value: '2' } });
    });
    // 拖动中：回放/上方进度条写来的新位置不得把用户拇指拽走
    act(() => {
      useStore.setState({ currentIndex: 7 });
    });
    expect(slider.value).toBe('2');

    act(() => {
      fireEvent.pointerUp(window);
    });
    pump(1016);

    // 抬起：挂起的拖动值落库，滑块与全局播放位置重新一致
    expect(useStore.getState().currentIndex).toBe(2);
    expect(slider.value).toBe('2');
  });

  it('记录集切换后重校量程与位置，不残留越界旧值', () => {
    renderEditor();
    pump(1000);
    const slider = getSlider();

    act(() => {
      useStore.setState({ currentIndex: 9 });
    });
    expect(slider.value).toBe('9');

    // 切到只有 3 帧的录制：全局索引 9 越界，若不重写 value 浏览器只会静默截断显示，
    // 出现「上方已在第 1 帧、下方还停在末尾」的上下不一致
    act(() => {
      useStore.setState({
        activeSessionId: 's2',
        activeSessionRecords: makeRecords().slice(0, 3) as never,
      });
    });

    expect(slider.max).toBe('2');
    expect(slider.value).toBe('2');
  });
});
