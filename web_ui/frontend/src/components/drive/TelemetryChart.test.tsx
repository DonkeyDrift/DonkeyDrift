import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// 共享：记录每次创建的 chart 实例，供断言检查 dataset 数据。
const chartInstances = vi.hoisted(() => {
  const instances: Array<{
    data: { datasets: { label: string; data: number[] }[] };
    options: Record<string, unknown>;
    update: ReturnType<typeof vi.fn>;
    destroy: ReturnType<typeof vi.fn>;
  }> = [];
  return {
    instances,
    reset() {
      instances.length = 0;
    },
  };
});

// mock chart.js 的 Chart 构造器：只记录 config，不真正渲染 canvas。
vi.mock('chart.js', () => {
  class MockChart {
    static register = vi.fn();
    update = vi.fn();
    destroy = vi.fn();
    data: { datasets: { label: string; data: number[] }[] };
    options: Record<string, unknown>;
    constructor(_ctx: unknown, config: { data: { datasets: { label: string; data: number[] }[] }; options: Record<string, unknown> }) {
      this.data = config.data;
      this.options = config.options;
      chartInstances.instances.push(this);
    }
  }
  return {
    Chart: MockChart,
    CategoryScale: {},
    LinearScale: {},
    PointElement: {},
    LineElement: {},
    Title: {},
    Legend: {},
    Tooltip: {},
  };
});

import { TelemetryChart } from './TelemetryChart';
import type { Telemetry } from '../../hooks/useDriveWebsocket';
import { useTelemetryStore } from '../../store/useTelemetryStore';

const sampleTelemetry = (overrides: Partial<Telemetry> = {}): Telemetry => ({
  type: 'telemetry',
  t: 1000,
  gz: 0.1,
  steering: 0.2,
  throttle: 0.3,
  ...overrides,
});

function latestChart() {
  const chart = chartInstances.instances.at(-1);
  if (!chart) throw new Error('no chart created');
  return chart;
}

function dataset(label: string): number[] {
  const ds = latestChart().data.datasets.find((d) => d.label === label);
  if (!ds) throw new Error(`dataset not found: ${label}`);
  return ds.data;
}

async function waitForChart() {
  await waitFor(() => {
    expect(chartInstances.instances.length).toBeGreaterThan(0);
  });
}

describe('TelemetryChart', () => {
  beforeAll(() => {
    // jsdom 无 canvas，给 getContext 返回一个空对象即可满足 Chart 构造。
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
  });

  beforeEach(() => {
    chartInstances.reset();
    useTelemetryStore.getState().reset();
  });

  it('无数据时显示等待提示', () => {
    render(<TelemetryChart />);

    expect(screen.getByText('（等待数据）')).toBeInTheDocument();
  });

  it('收到遥测后默认显示全部曲线', async () => {
    useTelemetryStore.getState().push(sampleTelemetry());
    render(<TelemetryChart />);

    await waitForChart();
    const labels = latestChart().data.datasets.map((d) => d.label);
    expect(labels).toEqual(
      expect.arrayContaining(['油门', '转向', '陀螺仪 Z', 'RC 转向', 'RC 油门', '陀螺仪 X', '加速度 X', 'Pilot 角度', 'Pilot 油门']),
    );
    expect(labels).toHaveLength(12);
  });

  it('RC 手柄输入写入 RC 曲线', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5, rc_throttle: 0.8 }));
    render(<TelemetryChart />);

    await waitFor(() => {
      expect(dataset('RC 转向')).toContain(-0.5);
    });
    expect(dataset('RC 油门')).toContain(0.8);
  });

  it('gyro/accel 曲线按 scale 缩放后写入缓冲', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ gz: 0.5, ax: 4.9 }));
    render(<TelemetryChart />);

    // gz scale=0.2 -> 0.5*0.2=0.1
    await waitFor(() => {
      const vals = dataset('陀螺仪 Z').filter((v): v is number => Number.isFinite(v));
      expect(vals.length).toBeGreaterThan(0);
      expect(vals[0]).toBeCloseTo(0.1, 10);
    });

    // ax scale=1/9.8 -> 4.9/9.8≈0.5（默认已勾选）
    await waitFor(() => {
      const vals = dataset('加速度 X').filter((v): v is number => Number.isFinite(v));
      expect(vals.length).toBeGreaterThan(0);
      expect(vals[0]).toBeCloseTo(0.5, 10);
    });
  });

  it('取消勾选默认显示的曲线后隐藏对应数据集', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ gx: 0.5 }));
    render(<TelemetryChart />);

    await waitForChart();

    // GyroX 默认已显示
    expect(latestChart().data.datasets.map((d) => d.label)).toContain('陀螺仪 X');

    // 取消勾选 GyroX 复选框
    const checkboxes = screen.getAllByRole('checkbox');
    const gyroXCheckbox = checkboxes.find((cb) => {
      const label = cb.parentElement?.querySelector('span');
      return label?.textContent === '陀螺仪 X';
    }) as HTMLInputElement;
    fireEvent.click(gyroXCheckbox);

    await waitFor(() => {
      expect(latestChart().data.datasets.map((d) => d.label)).not.toContain('陀螺仪 X');
    });
  });

  it('缺失字段的曲线仍渲染数据集（NaN 点断开）', async () => {
    // 只传 steering，throttle/gz 缺失
    const partial: Telemetry = { type: 'telemetry', t: 1, steering: 0.5 };
    useTelemetryStore.getState().push(partial);
    render(<TelemetryChart />);

    // 全部默认曲线（油门/转向/陀螺仪 Z 属不同分组，但组件默认管全部曲线）都应渲染
    await waitForChart();
    const labels = latestChart().data.datasets.map((d) => d.label);
    expect(labels).toEqual(expect.arrayContaining(['油门', '转向', '陀螺仪 Z']));
  });

  it('数据集未禁用 parsing（否则曲线不渲染，回归 #修复遥测曲线）', async () => {
    useTelemetryStore.getState().push(sampleTelemetry());
    render(<TelemetryChart />);

    await waitForChart();
    for (const ds of latestChart().data.datasets) {
      expect((ds as unknown as { parsing?: boolean }).parsing).not.toBe(false);
    }
  });

  it('group 模式下只渲染该分组的曲线与图例', async () => {
    useTelemetryStore.getState().push(sampleTelemetry({ rc_steering: -0.5, pilot_angle: 0.3 }));
    render(
      <TelemetryChart
        title="driveViz.chartTitleSteering"
        group="steering"
      />,
    );

    expect(screen.getByText('转向 / 姿态')).toBeInTheDocument();

    await waitForChart();
    const labels = latestChart().data.datasets.map((d) => d.label);
    expect(labels).toEqual(expect.arrayContaining(['转向', '陀螺仪 Z', 'RC 转向']));
    expect(labels).not.toEqual(expect.arrayContaining(['油门', 'RC 油门']));

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

  it('y 轴整体隐藏：去掉横向网格线与左侧刻度数字，但保留 [-1,1] 量程', async () => {
    useTelemetryStore.getState().push(sampleTelemetry());
    render(<TelemetryChart />);

    await waitForChart();
    const y = (latestChart().options.scales as Record<string, unknown>).y as Record<string, unknown>;
    expect(y.display).toBe(false);
    expect(y.min).toBe(-1);
    expect(y.max).toBe(1);
  });

  it('面板标题渲染在曲线画布下方', async () => {
    render(<TelemetryChart title="driveViz.chartTitleSteering" group="steering" />);

    const title = screen.getByText('转向 / 姿态');
    const canvas = document.querySelector('canvas');
    expect(canvas).toBeTruthy();
    // title 在 DOM 顺序上位于 canvas 之后（即渲染在画布下方）
    expect(canvas!.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('「全选」框：半选时点击→全选，已全选时点击→全不选', async () => {
    useTelemetryStore.getState().push(sampleTelemetry());
    render(<TelemetryChart group="steering" />);

    await waitForChart();
    // steering 组 6 条曲线全部 defaultOn=true，初始全选
    expect(latestChart().data.datasets).toHaveLength(6);

    const checkboxes = screen.getAllByRole('checkbox');
    const selectAll = checkboxes.find((cb) => cb.parentElement?.querySelector('span')?.textContent === '全选') as HTMLInputElement;
    expect(selectAll.checked).toBe(true);

    // 取消一条曲线 → 半选：全选框 indeterminate、unchecked，曲线数 5
    const gyroX = checkboxes.find((cb) => cb.parentElement?.querySelector('span')?.textContent === '陀螺仪 X') as HTMLInputElement;
    fireEvent.click(gyroX);
    await waitFor(() => {
      expect(selectAll.indeterminate).toBe(true);
    });
    expect(selectAll.checked).toBe(false);
    expect(latestChart().data.datasets).toHaveLength(5);

    // 半选时点击全选 → 全选（6 条），全选框 checked
    fireEvent.click(selectAll);
    await waitFor(() => {
      expect(latestChart().data.datasets).toHaveLength(6);
      expect(selectAll.checked).toBe(true);
    });

    // 已全选时点击全选 → 全不选（0 条）
    fireEvent.click(selectAll);
    await waitFor(() => {
      expect(latestChart().data.datasets).toHaveLength(0);
      expect(selectAll.checked).toBe(false);
    });
  });

});
