import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// mock react-chartjs-2 的 Line，避免 jsdom 下 chart.js 真实 canvas 渲染
vi.mock('react-chartjs-2', () => ({
  Line: (props: { data: { datasets: { label: string; data: number[] }[] } }) => (
    <div data-testid="mock-chart">
      {props.data.datasets.map((d) => (
        <div key={d.label} data-testid={`dataset-${d.label}`}>
          {d.label}:{JSON.stringify(d.data)}
        </div>
      ))}
    </div>
  ),
}));

// mock chart.js 的 register，避免 jsdom 缺 canvas 报错
vi.mock('chart.js', async () => {
  const actual = await vi.importActual<typeof import('chart.js')>('chart.js');
  return {
    ...actual,
    ChartJS: { register: vi.fn() },
  };
});

import { TelemetryChart } from './TelemetryChart';
import type { Telemetry } from '../../hooks/useDriveWebsocket';

const sampleTelemetry = (overrides: Partial<Telemetry> = {}): Telemetry => ({
  type: 'telemetry',
  t: 1000,
  gz: 0.1,
  steering: 0.2,
  throttle: 0.3,
  ...overrides,
});

// 等待 RAF 驱动的重绘把数据集渲染出来
function waitForDataset(label: string) {
  return waitFor(() => {
    expect(screen.getByTestId(`dataset-${label}`)).toBeInTheDocument();
  });
}

// 解析 mock 数据集渲染的 JSON 数据（NaN 序列化为 null）
function datasetValues(label: string): (number | null)[] {
  const text = screen.getByTestId(`dataset-${label}`).textContent ?? '';
  return JSON.parse(text.slice(text.indexOf(':') + 1));
}

describe('TelemetryChart', () => {
  it('无数据时显示等待提示', () => {
    render(<TelemetryChart telemetry={null} />);

    expect(screen.getByText('（等待数据）')).toBeInTheDocument();
  });

  it('收到遥测后显示默认 5 条曲线', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry()} />);

    await waitForDataset('油门');
    expect(screen.getByTestId('dataset-转向')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-陀螺仪 Z')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-RC 转向')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-RC 油门')).toBeInTheDocument();
    // 默认不显示 GyroX
    expect(screen.queryByTestId('dataset-陀螺仪 X')).not.toBeInTheDocument();
  });

  it('RC 手柄输入写入 RC 曲线', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry({ rc_steering: -0.5, rc_throttle: 0.8 })} />);

    await waitFor(() => {
      expect(datasetValues('RC 转向')).toContain(-0.5);
    });
    expect(datasetValues('RC 油门')).toContain(0.8);
  });

  it('gyro/accel 曲线按 scale 缩放后写入缓冲', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry({ gz: 0.5, ax: 4.9 })} />);

    // gz scale=0.2 -> 0.5*0.2=0.1
    await waitFor(() => {
      const vals = datasetValues('陀螺仪 Z').filter((v): v is number => v !== null);
      expect(vals.length).toBeGreaterThan(0);
      expect(vals[0]).toBeCloseTo(0.1, 10);
    });

    // 勾选默认隐藏的 AccX 复选框
    const checkboxes = screen.getAllByRole('checkbox');
    const accXCheckbox = checkboxes.find((cb) => {
      const label = cb.parentElement?.querySelector('span');
      return label?.textContent === '加速度 X';
    }) as HTMLInputElement;
    fireEvent.click(accXCheckbox);

    // ax scale=1/9.8 -> 4.9/9.8≈0.5
    await waitFor(() => {
      const vals = datasetValues('加速度 X').filter((v): v is number => v !== null);
      expect(vals.length).toBeGreaterThan(0);
      expect(vals[0]).toBeCloseTo(0.5, 10);
    });
  });

  it('勾选隐藏的曲线后显示对应数据集', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry({ gx: 0.5 })} />);

    await waitForDataset('油门');

    // GyroX 默认不显示
    expect(screen.queryByTestId('dataset-陀螺仪 X')).not.toBeInTheDocument();

    // 勾选 GyroX 复选框
    const checkboxes = screen.getAllByRole('checkbox');
    const gyroXCheckbox = checkboxes.find((cb) => {
      const label = cb.parentElement?.querySelector('span');
      return label?.textContent === '陀螺仪 X';
    }) as HTMLInputElement;
    fireEvent.click(gyroXCheckbox);

    await waitForDataset('陀螺仪 X');
  });

  it('缺失字段的曲线仍渲染数据集（NaN 点断开）', async () => {
    // 只传 steering，throttle/gz 缺失
    const partial: Telemetry = { type: 'telemetry', t: 1, steering: 0.5 };
    render(<TelemetryChart telemetry={partial} />);

    // 三条默认曲线的 dataset 都应渲染（缺失字段写入 NaN，曲线断开但不报错）
    await waitForDataset('油门');
    expect(screen.getByTestId('dataset-转向')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-陀螺仪 Z')).toBeInTheDocument();
  });

  it('group 模式下只渲染该分组的曲线与图例', async () => {
    render(
      <TelemetryChart
        telemetry={sampleTelemetry({ rc_steering: -0.5, pilot_angle: 0.3 })}
        title="driveViz.chartTitleSteering"
        group="steering"
      />,
    );

    expect(screen.getByText('转向 / 姿态')).toBeInTheDocument();

    await waitForDataset('转向');
    expect(screen.getByTestId('dataset-陀螺仪 Z')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-RC 转向')).toBeInTheDocument();
    expect(screen.queryByTestId('dataset-油门')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dataset-RC 油门')).not.toBeInTheDocument();

    const labels = screen
      .getAllByRole('checkbox')
      .map((cb) => cb.parentElement?.querySelector('span')?.textContent);
    expect(labels).toHaveLength(6);
    expect(labels).toEqual(
      expect.arrayContaining(['转向', '陀螺仪 Z', 'RC 转向', '陀螺仪 X', '陀螺仪 Y', 'Pilot 角度']),
    );
    expect(labels).not.toEqual(expect.arrayContaining(['油门', 'RC 油门', '加速度 X']));
  });

});
