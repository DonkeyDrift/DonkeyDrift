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
          {d.label}:{d.data.length}
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

describe('TelemetryChart', () => {
  it('无数据时显示等待提示', () => {
    render(<TelemetryChart telemetry={null} />);

    expect(screen.getByText('（等待数据）')).toBeInTheDocument();
  });

  it('收到遥测后显示默认 3 条曲线', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry()} />);

    await waitForDataset('Throttle');
    expect(screen.getByTestId('dataset-Steering')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-GyroZ')).toBeInTheDocument();
    // 默认不显示 GyroX
    expect(screen.queryByTestId('dataset-GyroX')).not.toBeInTheDocument();
  });

  it('暂停后切换为继续按钮', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry()} />);

    await waitForDataset('Throttle');

    fireEvent.click(screen.getByLabelText('暂停'));

    expect(screen.getByLabelText('继续')).toBeInTheDocument();
  });

  it('清空后重置等待状态', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry()} />);

    await waitForDataset('Throttle');

    fireEvent.click(screen.getByLabelText('清空'));

    expect(screen.getByText('（等待数据）')).toBeInTheDocument();
  });

  it('勾选隐藏的曲线后显示对应数据集', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry({ gx: 0.5 })} />);

    await waitForDataset('Throttle');

    // GyroX 默认不显示
    expect(screen.queryByTestId('dataset-GyroX')).not.toBeInTheDocument();

    // 勾选 GyroX 复选框
    const checkboxes = screen.getAllByRole('checkbox');
    const gyroXCheckbox = checkboxes.find((cb) => {
      const label = cb.parentElement?.querySelector('span');
      return label?.textContent === 'GyroX';
    }) as HTMLInputElement;
    fireEvent.click(gyroXCheckbox);

    await waitForDataset('GyroX');
  });

  it('缺失字段的曲线仍渲染数据集（NaN 点断开）', async () => {
    // 只传 steering，throttle/gz 缺失
    const partial: Telemetry = { type: 'telemetry', t: 1, steering: 0.5 };
    render(<TelemetryChart telemetry={partial} />);

    // 三条默认曲线的 dataset 都应渲染（缺失字段写入 NaN，曲线断开但不报错）
    await waitForDataset('Throttle');
    expect(screen.getByTestId('dataset-Steering')).toBeInTheDocument();
    expect(screen.getByTestId('dataset-GyroZ')).toBeInTheDocument();
  });

  it('全屏按钮切换全屏状态', async () => {
    render(<TelemetryChart telemetry={sampleTelemetry()} />);

    await waitForDataset('Throttle');

    fireEvent.click(screen.getByLabelText('全屏'));

    expect(screen.getByLabelText('退出全屏')).toBeInTheDocument();
  });
});
