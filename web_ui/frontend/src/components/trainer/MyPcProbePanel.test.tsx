import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
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

function emit(event: { data: string }) {
  act(() => {
    es!.onmessage!(event);
  });
}

// 探测状态由父组件（TrainerPage）受控持有：本组件只消费 result/loading/error
// 并通过 onRunProbe 请求重新检测，自身不再调用 probeMyPc
const baseProps = {
  host: '192.0.2.10',
  user: 'tester',
  password: 'pw',
  pythonPath: '',
  remoteDirBase: '~/projects',
  onApplyPythonPath: vi.fn(),
  loading: false,
  error: null as string | null,
  onRunProbe: vi.fn(),
};

const readyResult: MyPcProbeResult = {
  ok: true,
  platform: 'macos',
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
  installTitle: /一键配置环境|One-Click Environment Setup/,
  probeButton: /检测环境|Run Check/,
  repoPath: /DonkeyDrift 路径|DonkeyDrift Path/,
  gymPath: /GymDonkeyCar 路径|GymDonkeyCar Path/,
  pathRequired: /请填写 DonkeyDrift 和 GymDonkeyCar 路径|Enter both DonkeyDrift and GymDonkeyCar paths/,
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

describe('MyPcProbePanel 一键配置环境', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installMyPcMock.mockReset();
    getJobStatusMock.mockReset();
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

  it('路径有可访问表单语义，编辑在 rerender 后保留并 trim 后发送', async () => {
    const { rerender } = renderPanel(missingDonkeycarResult);
    const repoInput = screen.getByLabelText(LOCALE_RE.repoPath);
    const gymInput = screen.getByLabelText(LOCALE_RE.gymPath);

    expect(repoInput).toHaveValue('~/projects/DonkeyDrift');
    expect(gymInput).toHaveValue('~/projects/GymDonkeyCar');
    for (const input of [repoInput, gymInput]) {
      expect(input).toHaveAttribute('id');
      expect(input).toHaveAttribute('name');
      expect(input).toBeRequired();
      expect(input).toHaveAttribute('autocomplete', 'off');
      expect(input).toHaveAttribute('spellcheck', 'false');
    }

    fireEvent.change(repoInput, { target: { value: '  /srv/DonkeyDrift  ' } });
    fireEvent.change(gymInput, { target: { value: '  /srv/GymDonkeyCar  ' } });
    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} result={readyResult} />
      </LanguageProvider>,
    );
    expect(repoInput).toHaveValue('  /srv/DonkeyDrift  ');
    expect(gymInput).toHaveValue('  /srv/GymDonkeyCar  ');

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
    expect(installMyPcMock).toHaveBeenCalledWith(expect.objectContaining({
      repo_path: '/srv/DonkeyDrift',
      gym_path: '/srv/GymDonkeyCar',
    }));
  });

  it('remoteDirBase 异步变化时，未编辑的路径跟随新默认值', () => {
    const { rerender } = renderPanel(missingDonkeycarResult);
    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} remoteDirBase="~/synced" result={missingDonkeycarResult} />
      </LanguageProvider>,
    );

    expect(screen.getByLabelText(LOCALE_RE.repoPath)).toHaveValue('~/synced/DonkeyDrift');
    expect(screen.getByLabelText(LOCALE_RE.gymPath)).toHaveValue('~/synced/GymDonkeyCar');
  });

  it('remoteDirBase 变化时保留自定义路径，仅更新仍等于旧默认值的字段', () => {
    const { rerender } = renderPanel(missingDonkeycarResult);
    fireEvent.change(screen.getByLabelText(LOCALE_RE.repoPath), {
      target: { value: '/custom/DonkeyDrift' },
    });
    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} remoteDirBase="~/synced" result={missingDonkeycarResult} />
      </LanguageProvider>,
    );

    expect(screen.getByLabelText(LOCALE_RE.repoPath)).toHaveValue('/custom/DonkeyDrift');
    expect(screen.getByLabelText(LOCALE_RE.gymPath)).toHaveValue('~/synced/GymDonkeyCar');
  });

  it('探测完成且缺 donkeycar 时显示安装按钮，并优先使用探测到的 python', async () => {
    renderPanel(missingDonkeycarResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
    expect(screen.getByText(LOCALE_RE.rerunHint)).toBeInTheDocument();

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
    expect(installMyPcMock).toHaveBeenCalledWith(expect.objectContaining({
      python_path: '/usr/bin/python3',
      host: '192.0.2.10',
    }));
  });

  it('环境就绪时也允许主动安装（用户主动重装/升级）', () => {
    renderPanel(readyResult);
    expect(screen.getByTestId('mypc-install-button')).toBeInTheDocument();
  });

  it('支持的 Windows 主机即使没有 python_path 也可启动安装', async () => {
    renderPanel({ ...missingDonkeycarResult, platform: 'windows', python_path: '' });
    expect(screen.getByText(LOCALE_RE.notReady)).toBeInTheDocument();

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
  });

  it('不支持的平台不显示安装按钮并说明原因', () => {
    renderPanel({ ...readyResult, platform: 'linux' });
    expect(screen.queryByTestId('mypc-install-button')).toBeNull();
    expect(screen.getByText(/仅支持 macOS 和 Windows|supports macOS and Windows only/)).toBeInTheDocument();
  });

  it('SSH 检测失败时不显示安装按钮', () => {
    const sshFailedResult: MyPcProbeResult = {
      ...missingDonkeycarResult,
      checks: [
        { name: 'ssh', status: 'fail', message: 'connection refused', hint: '' },
        ...missingDonkeycarResult.checks.slice(1),
      ],
    };
    renderPanel(sshFailedResult);
    expect(screen.queryByTestId('mypc-install-button')).toBeNull();
  });

  it('空白路径阻止提交，显示可访问错误且不调用 API', async () => {
    renderPanel(missingDonkeycarResult);
    const repoInput = screen.getByLabelText(LOCALE_RE.repoPath);
    fireEvent.change(repoInput, { target: { value: '   ' } });
    fireEvent.click(screen.getByTestId('mypc-install-button'));

    const pathError = await screen.findByRole('alert');
    expect(pathError).toHaveTextContent(LOCALE_RE.pathRequired);
    expect(repoInput).toHaveAttribute('aria-invalid', 'true');
    expect(installMyPcMock).not.toHaveBeenCalled();
  });

  it('安装请求未完成时阻止重复提交', async () => {
    renderPanel(missingDonkeycarResult);
    installMyPcMock.mockImplementationOnce(() => new Promise(() => {}));
    const button = screen.getByTestId('mypc-install-button');

    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));
    expect(button).toBeDisabled();
  });

  it('安装完成后重新检测清空 result，完成状态与日志仍保留', async () => {
    const { rerender } = renderPanel(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    emit({ data: JSON.stringify({ type: 'log', line: 'Collecting donkeydrifter' }) });
    emit({ data: JSON.stringify({ type: 'log', line: 'Downloading…' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-log').textContent).toContain('Collecting donkeydrifter'));
    expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();
    expect(screen.queryByTestId('mypc-install-done')).toBeNull();

    emit({ data: JSON.stringify({ type: 'status', status: 'completed' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-done')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-done').textContent).toMatch(LOCALE_RE.installDone);
    expect(screen.getByTestId('mypc-install-log').textContent).toContain('Downloading…');
    expect(es!.close).toHaveBeenCalled();
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();

    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} result={null} />
      </LanguageProvider>,
    );
    expect(screen.getByTestId('mypc-install-done')).toBeInTheDocument();
    expect(screen.getByTestId('mypc-install-log').textContent).toContain('Downloading…');
  });

  it('安装失败（HTTP 报错）时显示失败信息', async () => {
    renderPanel(missingDonkeycarResult);

    installMyPcMock.mockRejectedValueOnce(new Error('connection refused'));
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-error').textContent).toContain('connection refused');
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();
  });

  it('任务失败后重新检测清空 result，错误与日志仍保留', async () => {
    const { rerender } = renderPanel(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    emit({ data: JSON.stringify({ type: 'log', line: 'uv install failed' }) });
    emit({ data: JSON.stringify({ type: 'status', status: 'failed', error: 'resolver failed: numpy' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-error').textContent).toContain('resolver failed: numpy');
    expect(screen.getByTestId('mypc-install-log').textContent).toContain('uv install failed');
    expect(es!.close).toHaveBeenCalled();

    rerender(
      <LanguageProvider>
        <MyPcProbePanel {...baseProps} result={null} />
      </LanguageProvider>,
    );
    expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument();
    expect(screen.getByTestId('mypc-install-log').textContent).toContain('uv install failed');
  });

  it('卸载后 installMyPc 晚到 resolve 不创建 SSE', async () => {
    let resolveInstall!: (value: { job_id: string; status: string }) => void;
    installMyPcMock.mockImplementationOnce(() => new Promise((resolve) => {
      resolveInstall = resolve;
    }));
    const { unmount } = renderPanel(missingDonkeycarResult);
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(installMyPcMock).toHaveBeenCalledTimes(1));

    unmount();
    await act(async () => {
      resolveInstall({ job_id: 'late-job', status: 'running' });
      await Promise.resolve();
    });

    expect(createLogStreamMock).not.toHaveBeenCalled();
  });

  it('SSE 断开后 running 会继续轮询直至 completed', async () => {
    renderPanel(missingDonkeycarResult);
    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());
    getJobStatusMock
      .mockResolvedValueOnce({ status: 'running' })
      .mockResolvedValueOnce({ status: 'completed' });

    vi.useFakeTimers();
    try {
      act(() => {
        es!.onerror!();
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(getJobStatusMock).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(getJobStatusMock).toHaveBeenCalledTimes(2);
      expect(screen.getByTestId('mypc-install-done')).toBeInTheDocument();
      expect(screen.queryByTestId('mypc-install-running')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('SSE 状态查询 reject 后继续 running 并轮询到 completed，期间禁止新任务', async () => {
    renderPanel(missingDonkeycarResult);
    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());
    getJobStatusMock
      .mockRejectedValueOnce(new Error('status unavailable'))
      .mockResolvedValueOnce({ status: 'running' })
      .mockResolvedValueOnce({ status: 'completed' });

    vi.useFakeTimers();
    try {
      act(() => {
        es!.onerror!();
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(getJobStatusMock).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('mypc-install-reconnecting')).toHaveTextContent(/正在重连|Reconnecting/);
      expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();
      expect(screen.queryByTestId('mypc-install-error')).toBeNull();
      expect(screen.getByTestId('mypc-install-button')).toBeDisabled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(getJobStatusMock).toHaveBeenCalledTimes(2);
      expect(screen.queryByTestId('mypc-install-reconnecting')).toBeNull();
      expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(getJobStatusMock).toHaveBeenCalledTimes(3);
      expect(screen.getByTestId('mypc-install-done')).toBeInTheDocument();
      expect(installMyPcMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('SSE 状态查询持续 reject 时保持重连且不启动新任务', async () => {
    renderPanel(missingDonkeycarResult);
    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());
    getJobStatusMock.mockRejectedValue(new Error('network down'));

    vi.useFakeTimers();
    try {
      act(() => {
        es!.onerror!();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });

      expect(getJobStatusMock).toHaveBeenCalledTimes(4);
      expect(screen.getByTestId('mypc-install-reconnecting')).toHaveTextContent(/正在重连|Reconnecting/);
      expect(screen.getByTestId('mypc-install-running')).toBeInTheDocument();
      expect(screen.queryByTestId('mypc-install-error')).toBeNull();
      expect(screen.getByTestId('mypc-install-button')).toBeDisabled();
      expect(installMyPcMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('任务停止（SSE status=stopped）时结束安装并显示错误', async () => {
    renderPanel(missingDonkeycarResult);

    installMyPcMock.mockResolvedValueOnce({ job_id: 'job1', status: 'running' });
    fireEvent.click(screen.getByTestId('mypc-install-button'));
    await waitFor(() => expect(es).not.toBeNull());

    emit({ data: JSON.stringify({ type: 'status', status: 'stopped', error: 'stopped by remote user' }) });
    await waitFor(() => expect(screen.getByTestId('mypc-install-error')).toBeInTheDocument());
    expect(screen.getByTestId('mypc-install-error').textContent).toContain('stopped by remote user');
    expect(screen.queryByTestId('mypc-install-running')).toBeNull();
    expect(es!.close).toHaveBeenCalled();
  });
});
