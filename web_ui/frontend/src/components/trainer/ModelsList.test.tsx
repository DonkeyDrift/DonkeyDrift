import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ModelsList } from './ModelsList';

// 回归测试（issue 001）：loss 曲线浮窗遮挡相邻行操作按钮。
// 修复后：悬停不再弹出；点击 loss 徽章打开真正的 modal（遮罩 + 居中 +
// 点击遮罩 / X / Esc 关闭），不再覆盖列表按钮。

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));

const mockListModels = vi.fn();
vi.mock('../../services/api', () => ({
  listModels: (...args: unknown[]) => mockListModels(...args),
  deleteModel: vi.fn(() => Promise.resolve()),
  downloadModelUrl: vi.fn(() => '/download'),
  loadModelToCar: vi.fn(() => Promise.resolve()),
  importModel: vi.fn(() => Promise.resolve()),
  API_URL: 'http://localhost',
  getApiErrorMessage: vi.fn(() => 'error'),
}));

vi.mock('../../store/useStore', () => ({
  useStore: () => ({ configPath: '/models', trainingJob: null }),
}));

const models = [
  {
    name: 'm1.tflite',
    size: 1024,
    modified: '2026-09-04T00:00:00Z',
    path: '/models/m1.tflite',
    previewPath: '/previews/m1.png',
    finalLoss: 0.1234,
    bestLoss: 0.1,
  },
  {
    name: 'm2.tflite',
    size: 2048,
    modified: '2026-09-04T00:00:00Z',
    path: '/models/m2.tflite',
    finalLoss: 0.5678,
  },
];

describe('ModelsList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListModels.mockResolvedValue({ models });
  });

  it('悬停模型行不会弹出 loss 曲线浮窗', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    const row = screen.getByText('m1.tflite').closest('div.bg-zinc-950');
    fireEvent.mouseEnter(row!);

    expect(screen.queryByRole('img', { name: 'trainer.lossChartAlt' })).toBeNull();
    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
  });

  it('点击 loss 徽章打开 modal', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'trainer.viewLossChart' }));

    const overlay = screen.getByTestId('loss-chart-overlay');
    expect(overlay).toBeInTheDocument();
    // 全屏遮罩而非跟随行的 fixed popover
    expect(overlay.className).toContain('fixed inset-0');
    const img = screen.getByRole('img', { name: 'trainer.lossChartAlt' });
    expect(img).toBeInTheDocument();
    expect(img.getAttribute('src')).toContain('/trainer/models/preview?path=');
    expect(img.getAttribute('src')).toContain(encodeURIComponent(models[0].previewPath));
  });

  it('点击遮罩关闭 modal', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'trainer.viewLossChart' }));

    fireEvent.click(screen.getByTestId('loss-chart-overlay'));

    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
  });

  it('按 Esc 关闭 modal', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'trainer.viewLossChart' }));

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
  });

  it('点击 X 按钮关闭 modal', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'trainer.viewLossChart' }));

    fireEvent.click(screen.getByRole('button', { name: 'trainer.close' }));

    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
  });

  it('点击操作按钮（删除）不会误触打开 loss modal', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'trainer.deleteModel' })[0]);

    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
    expect(screen.getByText('trainer.deleteConfirm')).toBeInTheDocument();
  });

  it('点击操作按钮（复制路径）不会误触打开 loss modal', async () => {
    Object.assign(window.navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'trainer.copyPath' })[0]);

    expect(screen.queryByTestId('loss-chart-overlay')).toBeNull();
  });
});
