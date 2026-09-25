import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { HarnessPanel } from './HarnessPanel';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, string | number>) => {
      if (key === 'harness.backgroundOn' && vars?.hours) return 'On (every ' + vars.hours + ' hours)';
      return key;
    },
  }),
}));

vi.mock('../services/api', () => ({
  getHarnessCatalog: vi.fn(),
  getHarnessStatus: vi.fn(),
  downloadHarness: vi.fn(),
  installHarness: vi.fn(),
  checkHarnessUpdates: vi.fn(),
  installHarnessUpdate: vi.fn(),
  flashFirmware: vi.fn(),
}));

import {
  getHarnessCatalog,
  getHarnessStatus,
  downloadHarness,
  installHarness,
  checkHarnessUpdates,
  installHarnessUpdate,
  flashFirmware,
} from '../services/api';

const mockCatalog = vi.mocked(getHarnessCatalog);
const mockStatus = vi.mocked(getHarnessStatus);
const mockDownload = vi.mocked(downloadHarness);
const mockInstall = vi.mocked(installHarness);
const mockCheck = vi.mocked(checkHarnessUpdates);
const mockInstallUpdate = vi.mocked(installHarnessUpdate);
const mockFlash = vi.mocked(flashFirmware);

const catalogFixture = {
  ok: true,
  checked_at: '2026-09-07T10:00:00',
  harnesses: [
    {
      id: 'codex',
      name: 'Codex',
      vendor: 'OpenAI',
      remote_default: null,
      components: [
        {
          id: 'codex-cli',
          kind: 'cli',
          name: 'Codex CLI',
          installed: false,
          version: null,
          path: null,
          install: { type: 'npm', package: '@openai/codex', doc_url: null },
        },
        {
          id: 'chatgpt-desktop',
          kind: 'desktop',
          name: 'ChatGPT Desktop',
          installed: false,
          version: null,
          path: null,
          install: { type: 'url', doc_url: 'https://openai.com/chatgpt/download/' },
        },
      ],
    },
  ],
};

const installedCatalogFixture = {
  ...catalogFixture,
  harnesses: [
    {
      ...catalogFixture.harnesses[0],
      components: [
        {
          id: 'codex-cli',
          kind: 'cli',
          name: 'Codex CLI',
          installed: true,
          version: '1.2.3',
          path: '/usr/bin/codex',
          install: { type: 'npm', package: '@openai/codex', doc_url: null },
        },
        {
          id: 'chatgpt-desktop',
          kind: 'desktop',
          name: 'ChatGPT Desktop',
          installed: false,
          version: null,
          path: null,
          install: { type: 'url', doc_url: 'https://openai.com/chatgpt/download/' },
        },
      ],
    },
  ],
};

const statusFixture = {
  background_enabled: true,
  interval_s: 86400,
  last_check_at: '2026-09-07T10:00:00',
  last_check_ok: true,
  updateable_count: 1,
  updates: [
    {
      kind: 'project',
      id: 'donkeydrift',
      name: 'DonkeyDrifter',
      installed: true,
      installed_version: '0.1.2',
      latest_version: '0.2.0',
      updateable: true,
    },
  ],
};

// 已安装且「有更新」的目录：codex-cli 1.2.3 → 1.3.0。
const updateAvailableCatalogFixture = {
  ...installedCatalogFixture,
  harnesses: [
    {
      ...installedCatalogFixture.harnesses[0],
      components: [
        {
          ...installedCatalogFixture.harnesses[0].components[0],
          latest_version: '1.3.0',
          update_available: true,
        },
        installedCatalogFixture.harnesses[0].components[1],
      ],
    },
  ],
};

const emptyStatusFixture = { ...statusFixture, updateable_count: 0, updates: [] };

beforeEach(() => {
  vi.clearAllMocks();
  mockCatalog.mockResolvedValue(catalogFixture as never);
  mockStatus.mockResolvedValue(statusFixture as never);
});

describe('HarnessPanel', () => {
  it('加载目录并展示 Harness 名称与组件', async () => {
    render(<HarnessPanel />);

    expect(await screen.findByText('Codex')).toBeInTheDocument();
    expect(screen.getByText('Codex CLI')).toBeInTheDocument();
    expect(screen.getByText('ChatGPT Desktop')).toBeInTheDocument();
    expect(screen.getAllByText('harness.notInstalled').length).toBeGreaterThan(0);
  });

  it('展示已安装组件版本', async () => {
    mockCatalog.mockResolvedValue(installedCatalogFixture as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    expect(screen.getByText(/harness\.installed/)).toBeInTheDocument();
    expect(screen.getByText(/1\.2\.3/)).toBeInTheDocument();
  });

  it('点击「立即检查」调用 checkHarnessUpdates 并刷新状态', async () => {
    mockCheck.mockResolvedValue({ ok: true, checked_at: '', updates: [], updateable_count: 0, errors: [] } as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    fireEvent.click(screen.getByRole('button', { name: 'harness.checkNow' }));

    await waitFor(() => {
      expect(mockCheck).toHaveBeenCalled();
    });
  });

  it('展示一键更新区的可更新项与更新按钮', async () => {
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    expect(screen.getByText('DonkeyDrifter')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'harness.update' })).toBeInTheDocument();
  });

  it('点击可更新项「更新」调用 installHarnessUpdate', async () => {
    mockInstallUpdate.mockResolvedValue({ status: 'ok', message: 'ok' } as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    fireEvent.click(screen.getByRole('button', { name: 'harness.update' }));

    await waitFor(() => {
      expect(mockInstallUpdate).toHaveBeenCalledWith('project', 'donkeydrift');
    });
  });

  it('未装组件展示「下载」按钮，点击调用 downloadHarness', async () => {
    mockDownload.mockResolvedValue({ status: 'ok', message: 'ok' } as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    fireEvent.click(screen.getAllByRole('button', { name: 'harness.download' })[0]);

    await waitFor(() => {
      expect(mockDownload).toHaveBeenCalledWith('codex', 'codex-cli');
    });
  });

  it('固件可更新项展示「刷写固件」按钮并调用 flashFirmware', async () => {
    const fwStatus = {
      ...statusFixture,
      updates: [
        {
          kind: 'firmware',
          id: 'firmware',
          name: 'MUS4 固件',
          installed: true,
          installed_version: '1.8.74',
          latest_version: '1.8.75',
          updateable: true,
          asset: '/tmp/fw.bin',
          vehicle_ip: '192.168.4.1',
        },
      ],
    };
    mockStatus.mockResolvedValue(fwStatus as never);
    mockFlash.mockResolvedValue({ status: 'ok', message: 'ok' } as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    fireEvent.click(screen.getByRole('button', { name: 'harness.flashFirmware' }));

    await waitFor(() => {
      expect(mockFlash).toHaveBeenCalledWith('192.168.4.1', '/tmp/fw.bin');
    });
  });

  it('并发更新：两个任务的进行中状态互不干扰', async () => {
    const twoUpdatesStatus = {
      ...statusFixture,
      updateable_count: 2,
      updates: [
        {
          kind: 'project',
          id: 'donkeydrift',
          name: 'DonkeyDrifter',
          installed: true,
          installed_version: '0.1.2',
          latest_version: '0.2.0',
          updateable: true,
        },
        {
          kind: 'component',
          id: 'donkeycar',
          name: 'donkeycar',
          installed: true,
          installed_version: '5.1.0',
          latest_version: '5.2.0',
          updateable: true,
        },
      ],
    };
    mockStatus.mockResolvedValue(twoUpdatesStatus as never);
    // 每个更新项一个可手动 resolve 的 Promise，模拟并发耗时任务
    const resolvers: Record<string, () => void> = {};
    mockInstallUpdate.mockImplementation(
      ((kind: string, id: string) =>
        new Promise((resolve) => {
          resolvers[id] = () => resolve({ status: 'ok', message: 'ok' });
        })) as never,
    );
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    const buttons = screen.getAllByRole('button', { name: 'harness.update' });
    expect(buttons).toHaveLength(2);

    // 点第一个：只有它进入「安装中」，另一个保持可点的「更新」
    fireEvent.click(buttons[0]);
    expect((await screen.findAllByRole('button', { name: 'harness.installing' })).length).toBe(1);
    expect(screen.getByRole('button', { name: 'harness.update' })).toBeInTheDocument();

    // 再点第二个：两个「安装中」并存，前一个的进度态不丢
    fireEvent.click(screen.getByRole('button', { name: 'harness.update' }));
    expect((await screen.findAllByRole('button', { name: 'harness.installing' })).length).toBe(2);

    // 先完成第一个：它恢复「更新」，第二个仍在「安装中」
    resolvers['donkeydrift']();
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'harness.installing' })).toHaveLength(1);
    });
    expect(screen.getByRole('button', { name: 'harness.update' })).toBeInTheDocument();

    // 完成第二个：两个都恢复
    resolvers['donkeycar']();
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'harness.update' })).toHaveLength(2);
    });
  });

  it('已安装组件无更新时不显示「更新」按钮，版本行保持绿色已安装', async () => {
    mockCatalog.mockResolvedValue(installedCatalogFixture as never);
    mockStatus.mockResolvedValue(emptyStatusFixture as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    expect(screen.queryByRole('button', { name: 'harness.update' })).not.toBeInTheDocument();
    const installedLine = screen.getByText(/harness\.installed/);
    expect(installedLine.className).toContain('text-emerald-400');
    expect(screen.queryByText(/harness\.updateAvailable/)).not.toBeInTheDocument();
  });

  it('已安装组件有更新时显示琥珀色「有新更新」文案与更新按钮', async () => {
    mockCatalog.mockResolvedValue(updateAvailableCatalogFixture as never);
    mockStatus.mockResolvedValue(emptyStatusFixture as never);
    mockInstall.mockResolvedValue({ status: 'ok', message: 'ok' } as never);
    render(<HarnessPanel />);

    await screen.findByText('Codex');
    const updateLine = screen.getByText(/harness\.updateAvailable/);
    expect(updateLine.className).toContain('text-amber-400');
    expect(updateLine.textContent).toContain('1.2.3');
    expect(updateLine.textContent).toContain('1.3.0');

    // 更新按钮点击后走组件安装（升级到最新）
    fireEvent.click(screen.getByRole('button', { name: 'harness.update' }));
    await waitFor(() => {
      expect(mockInstall).toHaveBeenCalledWith('codex', 'codex-cli');
    });
  });
});
