import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { GamepadBridgeCard } from './GamepadBridgeCard';

// mock 方式照 ConsoleControls.test.tsx：useConsoleDevice 与 services/console 全 mock
vi.mock('../../hooks/useConsoleDevice', () => ({
  useConsoleDevice: vi.fn(),
  invalidateConsoleDeviceCache: vi.fn(),
}));
vi.mock('../../services/console', () => ({
  consoleGetJson: vi.fn(),
  consolePostText: vi.fn(),
}));

import { useConsoleDevice, invalidateConsoleDeviceCache } from '../../hooks/useConsoleDevice';
import { consoleGetJson, consolePostText } from '../../services/console';

const mockUseConsoleDevice = vi.mocked(useConsoleDevice);
const mockInvalidate = vi.mocked(invalidateConsoleDeviceCache);
const mockGetJson = vi.mocked(consoleGetJson);
const mockPostText = vi.mocked(consolePostText);
const mockRefresh = vi.fn();

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

// /api/slot-info 三种典型响应（字段名与固件 WebConsoleServer.cpp / RC_BLE_Bridge.ino 对齐）
const CAR_WITH_BRIDGE = { app: 'car', running: 'ota_0', other: 'ota_1', other_kind: 'bridge' };
const CAR_NO_BRIDGE = { app: 'car', running: 'ota_0', other: 'ota_1', other_kind: 'empty' };
const BRIDGE = { app: 'bridge', running: 'ota_1', other: 'ota_0', other_kind: 'car' };

const renderCard = () =>
  render(
    <LanguageProvider>
      <GamepadBridgeCard />
    </LanguageProvider>,
  );

describe('GamepadBridgeCard', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setBrowserLanguage('zh-CN');
    vi.clearAllMocks();
    mockUseConsoleDevice.mockReturnValue({ ip: '192.168.1.10', resolving: false, refresh: mockRefresh });
  });

  it('桥已就绪（app=car, other_kind=bridge）时显示「手柄桥已就绪」与可用主按钮', async () => {
    mockGetJson.mockResolvedValue(CAR_WITH_BRIDGE);
    renderCard();

    expect(await screen.findByText('手柄桥已就绪')).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: '切换到手柄桥' });
    expect(btn).toBeEnabled();
    expect(mockGetJson).toHaveBeenCalledWith('192.168.1.10', 'api/slot-info');
  });

  it('点击主按钮先弹确认框，确认后才 POST /api/switch-slot 并进入「切换中」', async () => {
    mockGetJson.mockResolvedValue(CAR_WITH_BRIDGE);
    mockPostText.mockResolvedValue('ACK:SWITCHING');
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: '切换到手柄桥' }));
    expect(await screen.findByText('切换到手柄桥？')).toBeInTheDocument();
    expect(mockPostText).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '确认切换' }));
    await waitFor(() => {
      expect(mockPostText).toHaveBeenCalledWith('192.168.1.10', 'api/switch-slot', '');
    });
    expect(await screen.findByText(/切换中/)).toBeInTheDocument();
  });

  it('桥未安装（other_kind=empty）时按钮禁用并附补种说明', async () => {
    mockGetJson.mockResolvedValue(CAR_NO_BRIDGE);
    renderCard();

    expect(await screen.findByText('未检测到手柄桥')).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: '切换到手柄桥' });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/未检测到手柄桥固件，需先补种/)).toBeInTheDocument();
  });

  it('桥模式（app=bridge）显示绿色运行状态与「切回真车」按钮', async () => {
    mockGetJson.mockResolvedValue(BRIDGE);
    renderCard();

    expect(await screen.findByText(/手柄桥运行中/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切回真车' })).toBeEnabled();
  });

  it('切换后轮询到 app 翻转：车 → 桥后显示桥模式（不失效设备缓存）', async () => {
    mockGetJson.mockResolvedValue(CAR_WITH_BRIDGE);
    mockPostText.mockResolvedValue('ACK:SWITCHING');
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: '切换到手柄桥' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认切换' }));
    await waitFor(() => expect(mockPostText).toHaveBeenCalled());

    // 设备重启完成后 slot-info 返回桥模式
    mockGetJson.mockResolvedValue(BRIDGE);
    expect(
      await screen.findByRole('button', { name: '切回真车' }, { timeout: 5000 }),
    ).toBeEnabled();
    expect(screen.getByText(/手柄桥运行中/)).toBeInTheDocument();
    // 只有切回车固件才失效缓存
    expect(mockInvalidate).not.toHaveBeenCalled();
  });

  it('桥 → 车切换成功后调用 invalidateConsoleDeviceCache 刷新设备缓存', async () => {
    mockGetJson.mockResolvedValue(BRIDGE);
    mockPostText.mockResolvedValue('ACK:SWITCHING');
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: '切回真车' }));
    expect(await screen.findByText('切回真车？')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认切换' }));
    await waitFor(() => {
      expect(mockPostText).toHaveBeenCalledWith('192.168.1.10', 'api/switch-slot', '');
    });

    mockGetJson.mockResolvedValue(CAR_WITH_BRIDGE);
    await waitFor(() => expect(mockInvalidate).toHaveBeenCalledTimes(1), { timeout: 5000 });
    expect(await screen.findByText('手柄桥已就绪')).toBeInTheDocument();
  });

  it('读取槽位信息失败时显示兜底文案与重试按钮，并触发设备重扫', async () => {
    mockGetJson.mockRejectedValue(new Error('boom'));
    renderCard();

    expect(await screen.findByText(/无法读取槽位信息/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
    await waitFor(() => expect(mockRefresh).toHaveBeenCalled());
  });

  it('POST 切换请求失败时不进入切换中，显示红色错误', async () => {
    mockGetJson.mockResolvedValue(CAR_WITH_BRIDGE);
    mockPostText.mockRejectedValue(new Error('NACK:NO_IMAGE'));
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: '切换到手柄桥' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认切换' }));

    expect(await screen.findByText('切换请求失败，请检查车辆连接')).toBeInTheDocument();
    expect(screen.queryByText(/切换中/)).not.toBeInTheDocument();
  });
});
