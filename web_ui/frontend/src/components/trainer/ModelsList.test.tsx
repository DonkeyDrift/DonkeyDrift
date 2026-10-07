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
const mockLoadModelToCar = vi.fn((..._args: unknown[]) => Promise.resolve({ message: 'ok' }));
vi.mock('../../services/api', () => ({
  listModels: (...args: unknown[]) => mockListModels(...args),
  deleteModel: vi.fn(() => Promise.resolve()),
  downloadModelUrl: vi.fn(() => '/download'),
  loadModelToCar: (...args: unknown[]) => mockLoadModelToCar(...args),
  importModel: vi.fn(() => Promise.resolve()),
  uploadModelLoss: vi.fn(() => Promise.resolve()),
  // NpuConvertModal 依赖（行内「转 NPU」按钮打开弹窗时才会调用）
  getAimoKeyStatus: vi.fn(() => Promise.resolve({ sdk: true, key: true, keySource: 'env' })),
  listTrainerTubs: vi.fn(() => Promise.resolve({ tubs: [], current_tub_path: '' })),
  startAimoConvert: vi.fn(() => Promise.resolve({ job_id: 'j1', status: 'pending' })),
  stopTrain: vi.fn(() => Promise.resolve()),
  getJobStatus: vi.fn(() => Promise.resolve({ result_path: null })),
  createLogStream: vi.fn(() => ({ onmessage: null, onerror: null, close: vi.fn() })),
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
  {
    name: 'm3.tflite',
    size: 4096,
    modified: '2026-09-04T00:00:00Z',
    path: '/models/m3.tflite',
  },
];

describe('ModelsList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListModels.mockResolvedValue({ models });
  });

  it('悬停有 loss 图的模型行延迟后显示 loss 曲线浮窗，移出消失', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    const row = screen.getByText('m1.tflite').closest('div.bg-zinc-950');
    fireEvent.mouseEnter(row!);

    // 防抖：尚未到 300ms 阈值，浮窗不出现
    expect(screen.queryByTestId('loss-chart-tooltip')).toBeNull();

    await waitFor(
      () => expect(screen.getByTestId('loss-chart-tooltip')).toBeInTheDocument(),
      { timeout: 1500 },
    );

    fireEvent.mouseLeave(row!);
    expect(screen.queryByTestId('loss-chart-tooltip')).toBeNull();
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

  it('无 loss 数据的模型显示补传入口与无数据提示', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m3.tflite')).toBeInTheDocument());

    expect(screen.getByText('trainer.noLossData')).toBeInTheDocument();
    // m2（无图但有 finalLoss）与 m3（完全无 loss）都提供补传入口
    expect(screen.getAllByRole('button', { name: 'trainer.uploadLoss' })).toHaveLength(2);
  });

  it('点击补传按钮打开补传对话框', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m3.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'trainer.uploadLoss' })[1]);

    expect(screen.getByTestId('upload-loss-dialog')).toBeInTheDocument();
  });

  it('加载到车端传相对路径 ./models/<name>（后端拒绝绝对路径）', async () => {
    // 回归：列表项 m.path 是绝对路径，而 /drive/load_model 只接受 models/
    // 内的相对路径；直接传 m.path 会 400「model_path 必须是相对路径」。
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'trainer.loadToCar' })[0]);

    await waitFor(() =>
      expect(mockLoadModelToCar).toHaveBeenCalledWith('./models/m1.tflite', '/models'),
    );
  });

  it('可转换类型的行显示「转 NPU」按钮，点击打开弹窗并预填路径', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    // 三个 .tflite 行都有按钮
    expect(screen.getAllByRole('button', { name: 'trainer.npuConvert' })).toHaveLength(3);

    fireEvent.click(screen.getAllByRole('button', { name: 'trainer.npuConvert' })[0]);

    const dialog = screen.getByTestId('npu-convert-dialog');
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByTestId('npu-model-path').getAttribute('value'),
    ).toBe(models[0].path);
  });

  it('.h5 / .aidem 行不显示「转 NPU」按钮', async () => {
    mockListModels.mockResolvedValue({
      models: [
        { name: 'pilot.h5', size: 1, modified: '2026-10-01T00:00:00Z', path: '/m/pilot.h5' },
        { name: 'pilot.aidem', size: 1, modified: '2026-10-01T00:00:00Z', path: '/m/pilot.aidem' },
      ],
    });
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('pilot.h5')).toBeInTheDocument());

    expect(screen.queryByRole('button', { name: 'trainer.npuConvert' })).toBeNull();
  });

  it('头部「转 NPU」按钮打开空路径弹窗', async () => {
    render(<ModelsList />);
    await waitFor(() => expect(screen.getByText('m1.tflite')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('npu-convert-open'));

    expect(screen.getByTestId('npu-convert-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('npu-model-path').getAttribute('value')).toBe('');
  });
});
