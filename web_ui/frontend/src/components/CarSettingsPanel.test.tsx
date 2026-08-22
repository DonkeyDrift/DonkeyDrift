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
    expect(iframe.src).toContain('http://192.168.3.46/?embedded=1&settings=1&wifi=1');

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
