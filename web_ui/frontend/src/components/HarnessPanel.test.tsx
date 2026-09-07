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
  checkHarnessUpdates,
  installHarnessUpdate,
  flashFirmware,
} from '../services/api';

const mockCatalog = vi.mocked(getHarnessCatalog);
const mockStatus = vi.mocked(getHarnessStatus);
const mockDownload = vi.mocked(downloadHarness);
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
});
