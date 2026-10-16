import '@testing-library/jest-dom/vitest';
import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

import { TelemetryChart, CURVES, curvesByGroup, BUFFER_SIZE } from './TelemetryChart';
import { RingSeries, drawRingCurves } from './telemetryCurveRenderer';
import type { Telemetry } from '../../hooks/useDriveWebsocket';
import { useTelemetryStore } from '../../store/useTelemetryStore';

// 记录器 ctx：替代真实 2D 上下文，把每条曲线的路径点与颜色记录下来供断言。
// （自绘渲染器只用到 clearRect/beginPath/moveTo/lineTo/stroke + strokeStyle/lineWidth。）
class RecorderCtx {
  paths: Array<{ color: string; points: Array<[number, number]> }> = [];
  private current: { color: string; points: Array<[number, number]> } | null = null;
  strokeStyle = '';
  lineWidth = 1;
  clearRect = vi.fn();
  setTransform = vi.fn();
  beginPath() {
    this.current = { color: this.strokeStyle, points: [] };
  }
  moveTo(x: number, y: number) {
    this.current?.points.push([x, y]);
  }
  lineTo(x: number, y: number) {
    this.current?.points.push([x, y]);
  }
  stroke() {
    if (this.current) this.paths.push(this.current);
    this.current = null;
  }
  reset() {
    this.paths.length = 0;
    this.clearRect.mockClear();
  }
}

// 测试统一量取 320×112（≈ overlay 实际比例）：y(v) = 56 − v·55
const CANVAS_W = 320;
const CANVAS_H = 112;
const yOf = (v: number) => CANVAS_H / 2 - v * (CANVAS_H / 2 - 1);

const recorder = new RecorderCtx();

beforeAll(() => {
  // jsdom 无 canvas：getContext 返回记录器；布局恒为 0，给容器固定尺寸让路径可断言。
  HTMLCanvasElement.prototype.getContext = vi.fn(() => recorder) as never;
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: CANVAS_W,
    height: CANVAS_H,
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    bottom: CANVAS_H,
    right: CANVAS_W,
    toJSON: () => ({}),
  } as DOMRect);
});

const sampleTelemetry = (overrides: Partial<Telemetry> = {}): Telemetry => ({
  type: 'telemetry',
  t: 1000,
  gz: 0.1,
  steering: 0.2,
  throttle: 0.3,
  ...overrides,
});

const colorOf = (key: string): string => {
  const c = CURVES.find((x) => x.key === key);
  if (!c) throw new Error(`curve not found: ${key}`);
  return c.color;
};

/** 默认显示的曲线（合并单图后为核心驾驶信号，gyro/accel 默认关）。 */
const defaultOnCurves = CURVES.filter((c) => c.defaultOn);

/** 最近一次绘制中该曲线的路径（每次绘制按曲线顺序各追加一条）。 */
const lastPathOf = (key: string) => {
  const path = recorder.paths.filter((p) => p.color === colorOf(key)).at(-1);
  if (!path) throw new Error(`path not found for ${key}`);
  return path;
};

const drawnColors = () => recorder.paths.map((p) => p.color);

function findCheckbox(label: string): HTMLInputElement {
  const cb = screen
    .getAllByRole('checkbox')
    .find((el) => el.parentElement?.querySelector('span')?.textContent === label);
  if (!cb) throw new Error(`checkbox not found: ${label}`);
  return cb as HTMLInputElement;
}

describe('RingSeries', () => {
  it('push 后按最旧→最新读取，未填满处为 NaN', () => {
    const s = new RingSeries(4);
    s.push(1);
    s.push(2);
    s.push(3);
    expect([s.at(0), s.at(1), s.at(2), s.at(3)]).toEqual([1, 2, 3, NaN]);
  });

  it('填满后环形覆盖最旧点', () => {
    const s = new RingSeries(4);
    for (const v of [1, 2, 3, 4, 5]) s.push(v);
    expect([s.at(0), s.at(1), s.at(2), s.at(3)]).toEqual([2, 3, 4, 5]);
  });
});

describe('drawRingCurves', () => {
  it('按 [-1,1]→[height,0] 映射画折线，NaN 断开曲线', () => {
    const s = new RingSeries(4);
    s.push(0);
    s.push(1);
    s.push(NaN);
    s.push(-1);
    const ctx = new RecorderCtx();
    drawRingCurves(ctx as unknown as CanvasRenderingContext2D, 300, 100, [{ color: '#fff', series: s }]);

    expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, 300, 100);
    expect(ctx.paths).toHaveLength(1);
    expect(ctx.paths[0].color).toBe('#fff');
    expect(ctx.lineWidth).toBe(1.5);
    // x 均分：0/100/200/300；v=1 → y=1，v=-1 → y=99；NaN 断开 → 第三点重新起笔
    expect(ctx.paths[0].points).toEqual([
      [0, 50],
      [100, 1],
      [300, 99],
    ]);
  });

  it('少于 2 个点时只清屏不绘制', () => {
    const ctx = new RecorderCtx();
    drawRingCurves(ctx as unknown as CanvasRenderingContext2D, 300, 100, [
      { color: '#fff', series: new RingSeries(1) },
    ]);
    expect(ctx.clearRect).toHaveBeenCalledTimes(1);
    expect(ctx.paths).toHaveLength(0);
  });
});

describe('TelemetryChart', () => {
  beforeEach(() => {
    recorder.reset();
    useTelemetryStore.getState().reset();
  });

  it('无数据时显示等待提示', () => {
    render(<TelemetryChart />);

    expect(screen.getByText('（等待数据）')).toBeInTheDocument();
  });

  it('收到遥测后按默认开关绘制曲线（核心信号开、gyro/accel 关）', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5 }));
    render(<TelemetryChart />);

    await waitFor(() => {
      expect(lastPathOf('rc_steering').points.length).toBeGreaterThan(0);
    });
    const colors = new Set(drawnColors());
    for (const c of CURVES) {
      expect(colors.has(c.color)).toBe(c.defaultOn);
    }
  });

  it('RC 手柄输入写入 RC 曲线（y 轴 [-1,1] 映射）', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5, rc_throttle: 0.8 }));
    render(<TelemetryChart />);

    await waitFor(() => {
      expect(lastPathOf('rc_steering').points.length).toBeGreaterThan(0);
    });
    expect(lastPathOf('rc_steering').points[0]).toEqual([0, yOf(-0.5)]);
    expect(lastPathOf('rc_throttle').points[0]).toEqual([0, yOf(0.8)]);
  });

  it('gyro/accel 曲线按 scale 缩放后写入缓冲', async () => {
    // gyro/accel 默认关：受控打开后验证写入与缩放
    useTelemetryStore.getState().push(sampleTelemetry({ gz: 0.5, ax: 4.9 }));
    render(<TelemetryChart visibleKeys={new Set(['gz', 'ax'])} />);

    // gz scale=0.2 → 0.1；ax scale=1/9.8 → 0.5
    await waitFor(() => {
      expect(lastPathOf('gz').points.length).toBeGreaterThan(0);
    });
    expect(lastPathOf('gz').points[0][1]).toBeCloseTo(yOf(0.1), 6);
    expect(lastPathOf('ax').points[0][1]).toBeCloseTo(yOf(0.5), 6);
  });

  it('连续多帧按窗口「最旧→最新」从左到右推进', async () => {
    render(<TelemetryChart />);
    // 等挂载绘制就绪后再推帧（订阅前 push 只保留最后一帧，是 store 既有语义）
    await waitFor(() => {
      expect(recorder.paths.length).toBeGreaterThanOrEqual(defaultOnCurves.length);
    });
    recorder.reset();
    useTelemetryStore.getState().push(sampleTelemetry({ steering: 0.1 }));
    useTelemetryStore.getState().push(sampleTelemetry({ steering: 0.3 }));
    useTelemetryStore.getState().push(sampleTelemetry({ steering: -0.2 }));

    await waitFor(() => {
      expect(lastPathOf('steering').points).toHaveLength(3);
    });
    const step = CANVAS_W / (BUFFER_SIZE - 1);
    const pts = lastPathOf('steering').points;
    expect(pts[0][0]).toBeCloseTo(0, 6);
    expect(pts[0][1]).toBeCloseTo(yOf(0.1), 6);
    expect(pts[1][0]).toBeCloseTo(step, 6);
    expect(pts[1][1]).toBeCloseTo(yOf(0.3), 6);
    expect(pts[2][0]).toBeCloseTo(step * 2, 6);
    expect(pts[2][1]).toBeCloseTo(yOf(-0.2), 6);
  });

  it('取消勾选默认显示的曲线后停止绘制对应曲线', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5 }));
    render(<TelemetryChart />);

    await waitFor(() => {
      expect(lastPathOf('rc_steering').points.length).toBeGreaterThan(0);
    });

    // 清空历史绘制，只看点击后的重绘结果
    recorder.reset();
    fireEvent.click(findCheckbox('RC 转向'));

    await waitFor(() => {
      expect(drawnColors()).toHaveLength(defaultOnCurves.length - 1);
    });
    expect(drawnColors()).not.toContain(colorOf('rc_steering'));
  });

  it('缺失字段的曲线该点断开（不画线段）', async () => {
    const partial: Telemetry = { type: 'telemetry', t: 1, steering: 0.5 };
    useTelemetryStore.getState().push(partial);
    render(<TelemetryChart />);

    await waitFor(() => {
      expect(lastPathOf('steering').points).toHaveLength(1);
    });
    expect(lastPathOf('throttle').points).toHaveLength(0);
  });

  it('group 模式下只绘制该分组的曲线，图例只含本组', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5, rc_throttle: 0.8 }));
    render(
      <TelemetryChart
        title="driveViz.chartTitle"
        group="steering"
      />,
    );

    expect(screen.getByText('遥测曲线')).toBeInTheDocument();

    await waitFor(() => {
      expect(lastPathOf('rc_steering').points.length).toBeGreaterThan(0);
    });
    // 默认只画本组 defaultOn 曲线（转向/RC 转向/Pilot 角度），不含油门组任何曲线
    expect(new Set(drawnColors())).toEqual(
      new Set(curvesByGroup('steering').filter((c) => c.defaultOn).map((c) => c.color)),
    );

    const legendLabels = screen
      .getAllByRole('checkbox')
      .map((cb) => cb.parentElement?.querySelector('span')?.textContent);
    // 非受控非 overlay 模式下图例左侧会多出一个「全选」勾选框
    expect(legendLabels).toHaveLength(7);
    expect(legendLabels).toEqual(
      expect.arrayContaining(['全选', '转向', '陀螺仪 Z', 'RC 转向', '陀螺仪 X', '陀螺仪 Y', 'Pilot 角度']),
    );
    expect(legendLabels).not.toEqual(expect.arrayContaining(['油门', 'RC 油门', '加速度 X']));
  });

  it('overlay 模式不渲染图例（由父组件在画面外部渲染）', () => {
    render(<TelemetryChart overlay />);

    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('面板标题渲染在曲线画布下方', () => {
    render(<TelemetryChart title="driveViz.chartTitle" group="steering" />);

    const title = screen.getByText('遥测曲线');
    const canvas = document.querySelector('canvas');
    expect(canvas).toBeTruthy();
    // title 在 DOM 顺序上位于 canvas 之后（即渲染在画布下方）
    expect(canvas!.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('「全选」框：半选时点击→全选，已全选时点击→全不选', async () => {
    useTelemetryStore.getState().push(sampleTelemetry());
    render(<TelemetryChart group="steering" />);

    await waitFor(() => {
      expect(recorder.paths.length).toBeGreaterThanOrEqual(3);
    });
    // steering 组默认开 3 条（转向/RC 转向/Pilot 角度）→ 初始为半选
    const selectAll = findCheckbox('全选');
    expect(selectAll.checked).toBe(false);
    expect(selectAll.indeterminate).toBe(true);

    // 半选时点击全选 → 全组 6 条，全选框 checked
    recorder.reset();
    fireEvent.click(selectAll);
    await waitFor(() => {
      expect(drawnColors()).toHaveLength(6);
    });
    expect(drawnColors()).toContain(colorOf('gx'));
    expect(selectAll.checked).toBe(true);

    // 已全选时点击全选 → 全不选（0 条）
    recorder.reset();
    fireEvent.click(selectAll);
    await waitFor(() => {
      expect(drawnColors()).toHaveLength(0);
    });
    expect(selectAll.checked).toBe(false);
  });

  it('受控模式：visibleKeys 决定绘制集合，onToggleCurve 生效', async () => {
    function Harness() {
      const [keys, setKeys] = useState(new Set<string>(['steering']));
      return (
        <TelemetryChart
          visibleKeys={keys}
          onToggleCurve={(key) =>
            setKeys((prev) => {
              const next = new Set(prev);
              if (next.has(key)) {
                next.delete(key);
              } else {
                next.add(key);
              }
              return next;
            })
          }
        />
      );
    }
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5 }));
    render(<Harness />);

    await waitFor(() => {
      expect(lastPathOf('steering').points.length).toBeGreaterThan(0);
    });
    expect(drawnColors()).not.toContain(colorOf('rc_steering'));

    fireEvent.click(findCheckbox('RC 转向'));

    await waitFor(() => {
      expect(lastPathOf('rc_steering').points.length).toBeGreaterThan(0);
    });
  });

  it('受控模式透传 onToggleAllCurves：内置图例渲染「全选」并回调', async () => {
    const onToggleAll = vi.fn();
    useTelemetryStore.getState().push(sampleTelemetry());
    render(
      <TelemetryChart
        visibleKeys={new Set(['steering'])}
        onToggleCurve={() => {}}
        onToggleAllCurves={onToggleAll}
      />,
    );

    await waitFor(() => {
      expect(lastPathOf('steering').points.length).toBeGreaterThan(0);
    });
    // 1/12 选中 → 半选；点击「全选」透传 select=true（不传该 prop 时受控模式不渲染全选）
    const selectAll = findCheckbox('全选');
    expect(selectAll.indeterminate).toBe(true);
    fireEvent.click(selectAll);
    expect(onToggleAll).toHaveBeenCalledWith(true);
  });

  it('active=false 时不订阅遥测（缓冲保持空）', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ steering: 0.7 }));
    render(<TelemetryChart active={false} />);

    // 挂载仍会空画一次（缓冲全 NaN → 无线段），但数据不会写入
    await waitFor(() => {
      expect(recorder.paths.length).toBeGreaterThan(0);
    });
    expect(lastPathOf('steering').points).toHaveLength(0);
  });
});
