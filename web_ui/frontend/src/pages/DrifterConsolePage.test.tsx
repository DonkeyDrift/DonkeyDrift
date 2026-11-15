import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DrifterConsolePage } from './DrifterConsolePage';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));
vi.mock('@/services/api', () => ({
  discoverConnectorConsoles: vi.fn(),
}));
vi.mock('@/services/console', () => ({
  consoleGetText: vi.fn(() => Promise.resolve('')),
}));
import { discoverConnectorConsoles } from '@/services/api';
const mockDiscover = vi.mocked(discoverConnectorConsoles);

const emptyResult = { status: true, found: [], count: 0, scanned: 256, message: '' };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DrifterConsolePage 扫描状态显示（Issue #234）', () => {
  it('扫描进行中显示「正在扫描」而不是「未发现设备」，扫描结束无设备才显示「未发现设备」', async () => {
    let resolveScan!: (v: typeof emptyResult) => void;
    mockDiscover.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveScan = resolve;
        }),
    );
    render(<DrifterConsolePage />);
    // 扫描未返回期间：主区域与设备下拉都应是 scanning 文案，不能出现 noDevice
    expect(screen.getAllByText('console.scanning').length).toBeGreaterThan(0);
    expect(screen.queryByText('console.noDevice')).not.toBeInTheDocument();
    // 扫描结束且无设备：才显示「未发现设备」（设备下拉与主区域各一处）
    resolveScan(emptyResult);
    await waitFor(() =>
      expect(screen.getAllByText('console.noDevice').length).toBeGreaterThan(0),
    );
  });

  it('扫描发现设备后自动选中第一台并加载内嵌 DC iframe', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      const iframe = document.querySelector('iframe');
      expect(iframe).not.toBeNull();
      expect(iframe?.getAttribute('src')).toContain('http://192.168.3.46/');
    });
  });

  it('重扫后旧 IP 不在列表时自动切换到新发现的第一台（车换 IP 自愈）', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.46/',
      );
    });

    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.88', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    fireEvent.click(screen.getByRole('button', { name: 'console.rescan' }));
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.88/',
      );
    });
  });

  it('重扫未发现设备（车暂时离线）时保持当前选择不动', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.46/',
      );
    });

    mockDiscover.mockResolvedValue(emptyResult);
    fireEvent.click(screen.getByRole('button', { name: 'console.rescan' }));
    await waitFor(() => expect(mockDiscover).toHaveBeenCalledTimes(2));
    expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
      'http://192.168.3.46/',
    );
  });

  it('内嵌 DC iframe 带 allowFullScreen，车端图表/终端全屏键可用', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      expect(document.querySelector('iframe')).not.toBeNull();
    });
    expect(document.querySelector('iframe')).toHaveAttribute('allowfullscreen');
  });
});

describe('DrifterConsolePage 内嵌 DC 的 ?ui= 契约（Apple 唯一风格）', () => {
  it('iframe src 恒为 ui=apple', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
      count: 1,
      scanned: 256,
      message: '',
    });
    render(<DrifterConsolePage />);
    await waitFor(() => {
      const src = document.querySelector('iframe')?.getAttribute('src') ?? '';
      expect(src).toContain('http://192.168.3.46/');
      expect(src).toContain('ui=apple');
    });
  });

  it('残留旧键 donkeydrifter.ui.style=cockpit 被静默忽略：仍渲染 Apple', async () => {
    // 2026-09-20 双风格机制移除后不再读取该键：不迁移、不清除，渲染恒为 Apple。
    window.localStorage.setItem('donkeydrifter.ui.style', 'cockpit');
    try {
      mockDiscover.mockResolvedValue({
        status: true,
        found: [{ ip: '192.168.3.46', port: 80, reachable: true }],
        count: 1,
        scanned: 256,
        message: '',
      });
      render(<DrifterConsolePage />);
      await waitFor(() => {
        const src = document.querySelector('iframe')?.getAttribute('src') ?? '';
        expect(src).toContain('ui=apple');
        expect(src).not.toContain('ui=cockpit');
      });
      // <html> 不再被挂 ui-apple class（类机制已随 uistyle.ts 删除）
      expect(document.documentElement.classList.contains('ui-apple')).toBe(false);
    } finally {
      window.localStorage.removeItem('donkeydrifter.ui.style');
    }
  });
});

describe('DrifterConsolePage 工具条/布局一致性（UI 一致性修复）', () => {
  it('页面高度跟随动态顶栏 --header-h：100vh 基线 + supports dvh 增强，不再写死 3.5rem', () => {
    // 移动端顶栏含第二行控制簇（实测 101px）+ 顶栏 border-b 1px：写死 3.5rem 会溢出。
    // vh 基线保证不支持 dvh 的浏览器不丢 height；支持者经 @supports 升级到动态视口
    // （与 DonkeyMenuPage 同款双写法）。
    mockDiscover.mockResolvedValue(emptyResult);
    const { container } = render(<DrifterConsolePage />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toContain('h-[calc(100vh-var(--header-h,3.5rem))]');
    expect(root.className).toContain('supports-[height:100dvh]:h-[calc(100dvh-var(--header-h,3.5rem))]');
    expect(root.className).not.toContain('100vh-3.5rem');
  });

  it('设备下拉聚焦时边框转透明，与全站 select/输入控件聚焦语言一致', () => {
    mockDiscover.mockResolvedValue(emptyResult);
    render(<DrifterConsolePage />);
    expect(screen.getByRole('combobox')).toHaveClass('focus:border-transparent');
  });

  it('手动 IP 输入框有 sr-only 标签（console.manualIp）并关闭自动大写/拼写/自动填充', () => {
    mockDiscover.mockResolvedValue(emptyResult);
    render(<DrifterConsolePage />);
    const input = screen.getByLabelText('console.manualIp');
    expect(input).toHaveAttribute('placeholder', '192.168.x.x');
    expect(input).toHaveAttribute('autocapitalize', 'none');
    expect(input).toHaveAttribute('spellcheck', 'false');
    expect(input).toHaveAttribute('autocomplete', 'off');
  });

  it('手动 IP 为空时「连接」禁用；输入后可用且 Enter 直连', async () => {
    mockDiscover.mockResolvedValue(emptyResult);
    render(<DrifterConsolePage />);
    const connect = screen.getByRole('button', { name: 'console.connect' });
    expect(connect).toBeDisabled();
    const input = screen.getByLabelText('console.manualIp');
    fireEvent.change(input, { target: { value: '192.168.3.99' } });
    expect(connect).toBeEnabled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(document.querySelector('iframe')?.getAttribute('src')).toContain(
        'http://192.168.3.99/',
      ),
    );
  });

  it('扫描中的空态显示旋转加载指示（同 CarSettingsPanel 空态），失败态不显示', async () => {
    let resolveScan!: (v: typeof emptyResult) => void;
    mockDiscover.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveScan = resolve;
        }),
    );
    render(<DrifterConsolePage />);
    const scanningState = screen.getByText('console.scanning').closest('div');
    expect(scanningState?.querySelector('svg.animate-spin')).not.toBeNull();
    resolveScan(emptyResult);
    await waitFor(() => expect(screen.getByText('console.scanFailed')).toBeInTheDocument());
    const failedState = screen.getByText('console.scanFailed').closest('div');
    expect(failedState?.querySelector('svg')).toBeNull();
  });
});
