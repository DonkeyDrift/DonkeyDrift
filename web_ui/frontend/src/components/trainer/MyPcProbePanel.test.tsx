import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { MyPcProbePanel } from './MyPcProbePanel';
const probeMyPcMock = vi.hoisted(() => vi.fn());
const installMyPcMock = vi.hoisted(() => vi.fn());
const createLogStreamMock = vi.hoisted(() => vi.fn());
const getJobStatusMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
  probeMyPc: probeMyPcMock,
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

const baseProps = {
  host: '192.168.1.10',
  user: 'u',
  password: 'p',
  remoteDirBase: '~/projects',
  pythonPath: '',
  onApplyPythonPath: vi.fn(),
};

const readyResult = {
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

const missingDonkeycarResult = {
  ...readyResult,
  ok: false,
  checks: [
    ...readyResult.checks.slice(0, 2),
    { name: 'donkeycar', status: 'fail', message: 'missing', hint: '' },
    { name: 'donkey_cli', status: 'fail', message: 'missing', hint: '' },
  ],
};

function renderPanel() {
  return render(
    <LanguageProvider>
      <MyPcProbePanel {...baseProps} />
    </LanguageProvider>,
  );
}

// 测试环境默认英文 locale，断言文案时同时兼容中英文
const LOCALE_RE = {
  ready: /环境就绪，可以开始本机训练。|Environment ready\./,
  notReady: /环境未就绪，请按下方提示修复后重试。|Environment not ready\./,
  rerunHint: /安装完成后请点击「检测环境」重新检测。|After installation, click "Run Check" to probe again\./,
  installDone: /训练依赖安装完成，请重新运行环境检测确认。|Training dependencies installed\./,
  installTitle: /一键安装训练依赖|Install Training Dependencies/,
  probeButton: /检测环境|Run Check/,
};

async function runProbe(result: typeof readyResult) {
  probeMyPcMock.mockResolvedValueOnce(result);
  fireEvent.click(screen.getByRole('button', { name: LOCALE_RE.probeButton }));
  // 探测结果可能是就绪或未就绪，等待任意一种结论出现
  await screen.findByText(/环境就绪|环境未就绪|Environment ready|Environment not ready/);
}

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
    renderPanel();
    await runProbe(missingDonkeycarResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
    expect(screen.getByText(LOCALE_RE.rerunHint)).toBeInTheDocument();

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
    expect(installMyPcMock).toHaveBeenCalledWith(expect.objectContaining({
      python_path: '/usr/bin/python3', // probe 结果优先于空表单值
      host: '192.168.1.10',
    }));
  });

  it('环境就绪时也允许主动安装（用户主动重装/升级）', async () => {
    renderPanel();
    await runProbe(readyResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
  });

  it('探测失败（无 python）时不显示安装按钮', async () => {
    renderPanel();
    probeMyPcMock.mockResolvedValueOnce({
      ...missingDonkeycarResult,
      python_path: '',
    });
    fireEvent.click(screen.getByRole('button', { name: LOCALE_RE.probeButton }));
    await screen.findByText(LOCALE_RE.notReady);
    expect(screen.queryByTestId('mypc-install-button')).toBeNull();
  });

  it('安装中显示运行状态与实时日志尾部，完成后提示重新检测', async () => {
    renderPanel();
    await runProbe(missingDonkeycarResult);

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
    renderPanel();
    await runProbe(missingDonkeycarResult);

    installMyPcMock.mockRejectedValueOnce(new Error('connection refused'));
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-error').textContent).toContain('connection refused');
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();
  });

  it('任务失败（SSE status=failed）时显示失败信息', async () => {
    renderPanel();
    await runProbe(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    es!.onmessage!({ data: JSON.stringify({ type: 'status', status: 'failed', }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(es!.close).toHaveBeenCalled();
  });
});
