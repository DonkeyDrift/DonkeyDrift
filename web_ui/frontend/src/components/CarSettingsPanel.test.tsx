import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CarSettingsPanel } from './CarSettingsPanel';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../services/api', () => ({
  discoverConnectorConsoles: vi.fn(),
}));

import { discoverConnectorConsoles } from '../services/api';

const mockDiscover = vi.mocked(discoverConnectorConsoles);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CarSettingsPanel', () => {
  it('挂载后自动扫描一次（无需手动点击重新扫描）', async () => {
    mockDiscover.mockResolvedValue({ found: [] } as never);
    render(<CarSettingsPanel />);

    await waitFor(() => {
      expect(mockDiscover).toHaveBeenCalledTimes(1);
    });
    // 扫描结束（scanning=false）后也不再重复扫描
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'console.rescan' })).toBeEnabled();
    });
    expect(mockDiscover).toHaveBeenCalledTimes(1);
  });

  it('挂载自动扫描失败时静默跳过，不渲染错误且可手动重扫', async () => {
    mockDiscover.mockRejectedValue(new Error('network down'));
    render(<CarSettingsPanel />);

    await waitFor(() => {
      expect(mockDiscover).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByRole('button', { name: 'console.rescan' })).toBeEnabled();
    expect(screen.getAllByText('console.noDevice').length).toBeGreaterThan(0);

    mockDiscover.mockResolvedValue({
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
    } as never);
    fireEvent.click(screen.getByRole('button', { name: 'console.rescan' }));
    await waitFor(() => {
      expect(mockDiscover).toHaveBeenCalledTimes(2);
    });
  });

  it('手柄校准按钮位于重新扫描右侧，点击后 postMessage(dd-open-joystick-cal) 到内嵌车端 iframe', async () => {
    mockDiscover.mockResolvedValue({
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
    } as never);
    const { container } = render(<CarSettingsPanel />);

    const rescanBtn = await screen.findByRole('button', { name: 'console.rescan' });
    const calBtn = await screen.findByRole('button', { name: 'connector.joystickCal' });
    // 同一工具行，且手柄校准在重新扫描之后（右侧）
    expect(rescanBtn.parentElement).toBe(calBtn.parentElement);
    expect(
      rescanBtn.compareDocumentPosition(calBtn) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const iframe = await waitFor(() => {
      const f = container.querySelector('iframe');
      expect(f).not.toBeNull();
      return f as HTMLIFrameElement;
    });
    // v1.8.64 起不带 &wifi=1：配网板块不再出现在 CC 内嵌设置视图
    expect(iframe.src).toContain('http://192.168.3.46/?embedded=1&settings=1');
    expect(iframe.src).not.toContain('wifi=1');
    // v1.8.65 起传 lang 与 theme（跟随 DD 当前语言/主题）
    expect(iframe.src).toMatch(/[?&]lang=/);
    expect(iframe.src).toMatch(/[?&]theme=(light|dark)/);

    const postSpy = vi.spyOn(iframe.contentWindow as Window, 'postMessage');
    fireEvent.click(calBtn);
    expect(postSpy).toHaveBeenCalledWith({ type: 'dd-open-joystick-cal' }, 'http://192.168.3.46');
  });

  it('未扫描到设备时手柄校准按钮禁用', async () => {
    mockDiscover.mockResolvedValue({ found: [] } as never);
    render(<CarSettingsPanel />);
    const calBtn = await screen.findByRole('button', { name: 'connector.joystickCal' });
    await waitFor(() => {
      expect(calBtn).toBeDisabled();
    });
  });
});
