import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { ModelsList } from './ModelsList';
import { useStore } from '../../store/useStore';
import { listModels } from '../../services/api';

// 回归测试（issue 001）：loss 曲线浮窗遮挡相邻行操作按钮。
// 修复后：悬停不再弹出；点击 loss 徽章打开真正的 modal（遮罩 + 居中 +
// 点击遮罩 / X / Esc 关闭），不再覆盖列表按钮。

vi.mock('../../services/api', () => ({
  API_URL: 'http://localhost:8000',
  listModels: vi.fn(),
  deleteModel: vi.fn(),
  downloadModelUrl: (path: string) => `http://localhost:8000/download/${encodeURIComponent(path)}`,
  loadModelToCar: vi.fn(),
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const model = {
  name: 'pilot_001.h5',
  size: 2048,
  modified: '2026-09-01T10:00:00Z',
  path: '/models/pilot_001.h5',
  previewPath: '/models/pilot_001.png',
  finalLoss: 0.1234,
  bestLoss: 0.12,
};

const renderList = () =>
  render(
    <LanguageProvider>
      <ModelsList />
    </LanguageProvider>,
  );

describe('ModelsList loss chart modal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    Object.defineProperty(window.navigator, 'language', { value: 'zh-CN', configurable: true });
    vi.mocked(listModels).mockResolvedValue({ models: [model] } as never);
    useStore.setState({ configPath: '/tmp/mycar/config.py', trainingJob: null } as never);
    Object.assign(window.navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  const openModal = async () => {
    const badge = await screen.findByRole('button', { name: '查看损失曲线' });
    fireEvent.click(badge);
    return screen.findByRole('dialog');
  };

  it('悬停模型行不弹出 loss 浮窗', async () => {
    renderList();
    const row = await screen.findByText('pilot_001.h5');

    fireEvent.mouseEnter(row);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByAltText('训练损失图表')).not.toBeInTheDocument();
  });

  it('点击 loss 徽章在 modal 中打开损失曲线图', async () => {
    renderList();

    const dialog = await openModal();
    // 全屏遮罩而非跟随行的 fixed popover
    expect(dialog.className).toContain('fixed inset-0');
    const img = screen.getByAltText('训练损失图表');
    expect(img.getAttribute('src')).toContain('/trainer/models/preview?path=');
    expect(img.getAttribute('src')).toContain(encodeURIComponent(model.previewPath));
  });

  it('点击遮罩关闭 modal', async () => {
    renderList();
    const dialog = await openModal();

    fireEvent.click(dialog);

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('按 Esc 关闭 modal', async () => {
    renderList();
    await openModal();

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('点击关闭按钮关闭 modal', async () => {
    renderList();
    await openModal();

    fireEvent.click(screen.getByRole('button', { name: '关闭' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('点击操作按钮不打开 loss modal', async () => {
    renderList();
    const copyButton = await screen.findByRole('button', { name: '复制路径' });

    fireEvent.click(copyButton);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
