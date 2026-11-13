import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LanguageProvider } from '@/i18n';
import { useStore } from '../../store/useStore';
import { DriveTargetCard } from './DriveTargetCard';

// 只 mock 三个网络调用，其余导出（getApiErrorMessage 等）保留真实实现
vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    saveSimulatorConfig: vi.fn(),
    discoverSimulator: vi.fn(),
    restartDriving: vi.fn(),
  };
});

import { saveSimulatorConfig, discoverSimulator, restartDriving } from '../../services/api';

const mockSave = vi.mocked(saveSimulatorConfig);
const mockDiscover = vi.mocked(discoverSimulator);
const mockRestart = vi.mocked(restartDriving);

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

const renderCard = (props?: Partial<React.ComponentProps<typeof DriveTargetCard>>) =>
  render(
    <MemoryRouter>
      <LanguageProvider>
        <DriveTargetCard
          target="car"
          carOnline={true}
          simConnected={null}
          onSelectTarget={vi.fn()}
          {...props}
        />
      </LanguageProvider>
    </MemoryRouter>,
  );

describe('DriveTargetCard', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setBrowserLanguage('zh-CN');
    vi.clearAllMocks();
    // 默认：已载入配置目录，真车配置（DONKEY_GYM=false + 已有 SIM_HOST）
    useStore.setState({
      config: { SIM_HOST: '192.168.3.100', DONKEY_GYM: false },
      configPath: '/tmp/mycar',
    });
  });

  it('渲染状态行：当前目标、车端在线状态点与模拟器离线徽标', () => {
    renderCard({ target: 'car', carOnline: true, simConnected: false });
    expect(screen.getByText('驾驶目标')).toBeInTheDocument();
    expect(screen.getByText('当前目标')).toBeInTheDocument();
    // 状态行值 + 分段按钮各一处「真车」
    expect(screen.getAllByText('真车').length).toBe(2);
    expect(screen.getByText('车端在线')).toBeInTheDocument();
    expect(screen.getByText('模拟器离线，重连中…')).toBeInTheDocument();
  });

  it('目标未知且车端离线时渲染「未知 / 车端离线」', () => {
    renderCard({ target: 'unknown', carOnline: false });
    expect(screen.getByText('未知')).toBeInTheDocument();
    expect(screen.getByText('车端离线')).toBeInTheDocument();
  });

  it('点「模拟器」以 DONKEY_GYM=true 且保留原 SIM_HOST 调 saveSimulatorConfig', async () => {
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    const onSelect = vi.fn();
    renderCard({ target: 'car', onSelectTarget: onSelect });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith({
      path: '/tmp/mycar',
      config: { SIM_HOST: '192.168.3.100', DONKEY_GYM: true },
    });
    // SIM_HOST 现值非空时不做发现
    expect(mockDiscover).not.toHaveBeenCalled();
    // 保存成功：回调上层 + 同步全局配置
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('sim'));
    expect(useStore.getState().config?.DONKEY_GYM).toBe(true);
  });

  it('保存成功后出现「重启驾驶生效」按钮，点击调 restartDriving 并显示绿色提示', async () => {
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    mockRestart.mockResolvedValue({ status: 'launched', url: 'http://localhost:8000/#/drive' });
    renderCard({ target: 'car' });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));

    const restartBtn = await screen.findByRole('button', { name: '重启驾驶生效' });
    expect(screen.getByText('已保存，需重启驾驶生效')).toBeInTheDocument();

    fireEvent.click(restartBtn);
    await waitFor(() => expect(mockRestart).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('驾驶进程已重启，等待车端上线…')).toBeInTheDocument();
    // 重启成功后待重启提示与按钮消失
    expect(screen.queryByText('已保存，需重启驾驶生效')).not.toBeInTheDocument();
  });

  it('configPath 为空时给出载入配置目录提示且不调用保存', async () => {
    useStore.setState({ config: null, configPath: '' });
    renderCard({ target: 'car' });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));

    expect(await screen.findByText('请先在左侧 Loaders 抽屉载入配置目录')).toBeInTheDocument();
    expect(mockSave).not.toHaveBeenCalled();
    expect(mockDiscover).not.toHaveBeenCalled();
  });

  it('SIM_HOST 为空且发现不到模拟器时提示先启动 DonkeySim，不保存', async () => {
    useStore.setState({
      config: { SIM_HOST: '', DONKEY_GYM: false },
      configPath: '/tmp/mycar',
    });
    mockDiscover.mockResolvedValue({
      status: true,
      found: [],
      count: 0,
      scanned: 256,
      message: 'none',
    });
    renderCard({ target: 'car' });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));

    await waitFor(() => expect(mockDiscover).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText('未发现模拟器：请先启动 DonkeySim 后重试'),
    ).toBeInTheDocument();
    expect(mockSave).not.toHaveBeenCalled();
  });

  it('SIM_HOST 为空但发现到模拟器时用 found[0].ip 保存', async () => {
    useStore.setState({
      config: { SIM_HOST: '', DONKEY_GYM: false },
      configPath: '/tmp/mycar',
    });
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.55', port: 9091, latency_ms: 3, reachable: true }],
      count: 1,
      scanned: 256,
      message: 'ok',
    });
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    renderCard({ target: 'car' });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));

    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith({
        path: '/tmp/mycar',
        config: { SIM_HOST: '192.168.3.55', DONKEY_GYM: true },
      }),
    );
  });

  // ---- 模拟器选择区（target='sim' 时工具条下方展开，无发现/保存按钮）----

  it('target=sim 时自动调 discoverSimulator 并渲染 IP 列表', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [
        { ip: '192.168.3.55', port: 9091, latency_ms: 3, reachable: true },
        { ip: '192.168.3.66', port: 9091, latency_ms: 8, reachable: true },
      ],
      count: 2,
      scanned: 256,
      message: 'ok',
    });
    renderCard({ target: 'sim' });

    // 无任何按钮触发，挂载后即自动扫描一次
    await waitFor(() => expect(mockDiscover).toHaveBeenCalledWith('/tmp/mycar'));
    expect(await screen.findByText('192.168.3.55:9091')).toBeInTheDocument();
    expect(screen.getByText('192.168.3.66:9091')).toBeInTheDocument();
    expect(screen.getByText('8ms')).toBeInTheDocument();
    expect(mockSave).not.toHaveBeenCalled();
  });

  it('点选列表 IP 以 {SIM_HOST, DONKEY_GYM:true} 自动保存并出现待重启提示', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.55', port: 9091, latency_ms: 3, reachable: true }],
      count: 1,
      scanned: 256,
      message: 'ok',
    });
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    renderCard({ target: 'sim' });

    fireEvent.click(await screen.findByText('192.168.3.55:9091'));

    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith({
        path: '/tmp/mycar',
        config: { SIM_HOST: '192.168.3.55', DONKEY_GYM: true },
      }),
    );
    // 复用现有保存成功链路：待重启徽标 + 已选择 notice + 全局配置同步
    expect(await screen.findByText('已保存，需重启驾驶生效')).toBeInTheDocument();
    expect(await screen.findByText('已选择 192.168.3.55')).toBeInTheDocument();
    expect(useStore.getState().config?.SIM_HOST).toBe('192.168.3.55');
    // 同次停留不重扫：保存触发的重渲染不再发起发现
    expect(mockDiscover).toHaveBeenCalledTimes(1);
  });

  it('点当前已选中的 IP 不重复保存', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [{ ip: '192.168.3.100', port: 9091, latency_ms: 3, reachable: true }],
      count: 1,
      scanned: 256,
      message: 'ok',
    });
    renderCard({ target: 'sim' });

    // 与 config.SIM_HOST 匹配的项高亮
    const selected = await screen.findByText('192.168.3.100:9091');
    expect(selected.closest('button')?.className).toContain('border-cyan-500/50');

    fireEvent.click(selected);
    await act(async () => {});

    expect(mockSave).not.toHaveBeenCalled();
    expect(screen.queryByText('已保存，需重启驾驶生效')).not.toBeInTheDocument();
  });

  it('未发现时显示 WifiOff 提示，手动输入失焦自动保存', async () => {
    mockDiscover.mockResolvedValue({
      status: true,
      found: [],
      count: 0,
      scanned: 256,
      message: 'none',
    });
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    renderCard({ target: 'sim' });

    expect(
      await screen.findByText('未发现模拟器：请先启动 DonkeySim，或在下方手动输入地址'),
    ).toBeInTheDocument();

    const input = screen.getByLabelText('模拟器地址');
    fireEvent.change(input, { target: { value: ' 192.168.9.9 ' } });
    fireEvent.blur(input);

    // trim 后非空且与当前值不同才保存
    await waitFor(() =>
      expect(mockSave).toHaveBeenCalledWith({
        path: '/tmp/mycar',
        config: { SIM_HOST: '192.168.9.9', DONKEY_GYM: true },
      }),
    );
    expect(await screen.findByText('已保存，需重启驾驶生效')).toBeInTheDocument();
  });

  it('重启失败时显示红色错误并给出 /donkey 降级链接', async () => {
    mockSave.mockResolvedValue({ status: true, message: 'ok' });
    mockRestart.mockResolvedValue({ status: 'error', error: '未找到 donkey 命令' });
    renderCard({ target: 'car' });

    fireEvent.click(screen.getByRole('button', { name: '模拟器' }));
    fireEvent.click(await screen.findByRole('button', { name: '重启驾驶生效' }));

    expect(await screen.findByText('未找到 donkey 命令')).toBeInTheDocument();
    const fallback = await screen.findByRole('link', { name: '打开 Donkey 菜单手动启动驾驶' });
    expect(fallback).toHaveAttribute('href', '/donkey');
    // 待重启提示保留，允许重试
    expect(screen.getByText('已保存，需重启驾驶生效')).toBeInTheDocument();
  });
});
