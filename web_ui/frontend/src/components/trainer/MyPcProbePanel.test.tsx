import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { MyPcProbePanel } from './MyPcProbePanel';
import type { MyPcProbeResult } from '../../services/api';

const installMyPcMock = vi.hoisted(() => vi.fn());
const createLogStreamMock = vi.hoisted(() => vi.fn());
const getJobStatusMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
  installMyPc: installMyPcMock,
  createLogStream: createLogStreamMock,
  getJobStatus: getJobStatusMock,
}));

class FakeEventSource {
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
}
let es: FakeEventSource | null = null;
createLogStreamMock.mockImplementation(() => {
  es = new FakeEventSource();
  return es;
});

// 探测状态由父组件（TrainerPage）受控持有：本组件只消费 result/loading/error
// 并通过 onRunProbe 请求重新检测，自身不再调用 probeMyPc
const baseProps = {
  host: '192.0.2.10',
  user: 'tester',
  password: 'pw',
  pythonPath: '',
  onApplyPythonPath: vi.fn(),
  loading: false,
  error: null as string | null,
  onRunProbe: vi.fn(),
};

const readyResult: MyPcProbeResult = {
  ok: true,
  platform: 'linux',
  shell: 'posix',
  python_path: '/usr/bin/python3',
  checks: [
    { name: 'ssh', status: 'ok', message: 'ok', hint: '' },
    { name: 'python', status: 'ok', message: 'ok', hint: '' },
    { name: 'donkeycar', status: 'ok', message: 'ok', hint: '' },
    { name: 'donkey_cli', status: 'ok', message: 'ok', hint: '' },
  ],
  suggestions: [],
};

const missingDonkeycarResult: MyPcProbeResult = {
  ...readyResult,
  ok: false,
  checks: [
    ...readyResult.checks.slice(0, 2),
    { name: 'donkeycar', status: 'fail', message: 'missing', hint: '' },
    { name: 'donkey_cli', status: 'fail', message: 'missing', hint: '' },
  ],
};

function renderPanel(result: MyPcProbeResult | null = null) {
  return render(
    <LanguageProvider>
      <MyPcProbePanel {...baseProps} result={result} />
    </LanguageProvider>,
  );
}

// 测试环境默认英文 locale，断言文案时同时兼容中英文
const LOCALE_RE = {
  ready: /环境就绪，可以开始局域网主机训练。|Environment ready\./,
  notReady: /环境未就绪，请按下方提示修复后重试。|Environment not ready\./,
  rerunHint: /安装完成后请点击「检测环境」重新检测。|After installation, click "Run Check" to probe again\./,
  installDone: /训练依赖安装完成，请重新运行环境检测确认。|Training dependencies installed\./,
  installTitle: /一键安装训练依赖|Install Training Dependencies/,
  probeButton: /检测环境|Run Check/,
};

describe('MyPcProbePanel 受控探测状态', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    es = null;
    window.localStorage.clear();
  });

  it('点击「检测环境」调用父组件传入的 onRunProbe（自身不发起探测请求）', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: LOCALE_RE.probeButton }));
    expect(baseProps.onRunProbe).toHaveBeenCalledTimes(1);
  });

  it('探测结果就绪/未就绪文案跟随受控 result 渲染', () => {
    const { rerender } = render(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} result={readyResult} />
      </LanguageProvider>,
    );
    expect(screen.getByText(LOCALE_RE.ready)).toBeInTheDocument();

    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} result={missingDonkeycarResult} />
      </LanguageProvider>,
    );
    expect(screen.getByText(LOCALE_RE.notReady)).toBeInTheDocument();
  });
});

describe('MyPcProbePanel 一键安装训练依赖', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    es = null;
    window.localStorage.clear();
  });
  afterEach(() => {
    es = null;
  });

  it('探测前（无结果）不显示安装按钮', () => {
    renderPanel();
    expect(screen.queryByTestId('mypc-install-button')).toBeNull();
  });

  it('探测完成且缺 donkeycar 时显示安装按钮，并优先使用探测到的 python', async () => {
    renderPanel(missingDonkeycarResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
    expect(screen.getByText(LOCALE_RE.rerunHint)).toBeInTheDocument();

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
    expect(installMyPcMock).toHaveBeenCalledWith(expect.objectContaining({
      python_path: '/usr/bin/python3', // probe 结果优先于空表单值
      host: '192.0.2.10',
    }));
  });

  it('环境就绪时也允许主动安装（用户主动重装/升级）', () => {
    renderPanel(readyResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
  });

  it('探测失败（无 python）时不显示安装按钮', () => {
    renderPanel({ ...missingDonkeycarResult, python_path: '' });
    expect(screen.getByText(LOCALE_RE.notReady)).toBeInTheDocument();
    expect(screen.queryByTestId('mypc-install-button')).toBeNull();
  });

  it('安装中显示运行状态与实时日志尾部，完成后提示重新检测', async () => {
    renderPanel(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    // 流入两行日志
    es!.onmessage!({ data: JSON.stringify({ type: 'log', line: 'Collecting donkeydrifter' }) });
    es!.onmessage!({ data: JSON.stringify({ type: 'log', line: 'Downloading…' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-log').textContent).toContain('Collecting donkeydrifter'));
    expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();
    expect(screen.queryByTestId('mypc-install-done')).toBeNull();

    // 完成
    es!.onmessage!({ data: JSON.stringify({ type: 'status', status: 'completed' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-done')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-done').textContent).toMatch(LOCALE_RE.installDone);
    expect(es!.close).toHaveBeenCalled();
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();
  });

  it('安装失败（HTTP 报错）时显示失败信息', async () => {
    renderPanel(missingDonkeycarResult);

    installMyPcMock.mockRejectedValueOnce(new Error('connection refused'));
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-error').textContent).toContain('connection refused');
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();
  });

  it('任务失败（SSE status=failed）时显示失败信息', async () => {
    renderPanel(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    es!.onmessage!({ data: JSON.stringify({ type: 'status', status: 'failed', }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(es!.close).toHaveBeenCalled();
  });
});
