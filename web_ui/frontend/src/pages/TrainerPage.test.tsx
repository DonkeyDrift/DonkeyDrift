import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { TrainerPage } from './TrainerPage';
import { useStore } from '../store/useStore';
import type { MyPcProbeResult } from '../services/api';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));

vi.mock('../services/api', () => ({
  getTrainerConfig: vi.fn(() => Promise.reject(new Error('no conf'))),
  getMyPcKnownHosts: vi.fn(() => Promise.resolve([])),
  listTrainerTubs: vi.fn(() => Promise.resolve({ tubs: [], current_tub_path: '' })),
  loadConfig: vi.fn(),
  loadMyconfig: vi.fn(),
  saveTrainingConfig: vi.fn(),
  probeMyPc: vi.fn(),
}));

const { mockStartMyPc, mockResumeMyPc, mockJobState } = vi.hoisted(() => ({
  mockStartMyPc: vi.fn(() => Promise.resolve()),
  mockResumeMyPc: vi.fn(() => Promise.resolve()),
  mockJobState: { job: null as { status: string } | null },
}));
vi.mock('../hooks/useTrainingJob', () => ({
  useTrainingJob: () => ({
    job: mockJobState.job,
    startLocal: vi.fn(),
    startOnline: vi.fn(),
    startMyPc: mockStartMyPc,
    resumeMyPc: mockResumeMyPc,
    stopJob: vi.fn(),
    isRunning: false,
  }),
}));

// 与「模式来自 store / 先检测后训练」决策无关的子组件置空渲染，避免牵连它们的依赖；
// MyPcProbePanel 留一个 testid 暴露受控探测结果，作为「检测未就绪」流程走完的可观测标志
vi.mock('../components/trainer/LocalConfigForm', () => ({
  LocalConfigForm: () => <div data-testid="local-config-form" />,
}));
vi.mock('../components/trainer/RemoteConfigForm', () => ({
  RemoteConfigForm: () => <div data-testid="remote-config-form" />,
}));
vi.mock('../components/trainer/MyPcProbePanel', () => ({
  MyPcProbePanel: ({ result }: { result: { ok: boolean } | null }) => (
    <div
      data-testid="mypc-probe-panel"
      data-ok={result === null ? 'null' : String(result.ok)}
    />
  ),
}));
vi.mock('../components/trainer/TubSelector', () => ({ TubSelector: () => null }));
vi.mock('../components/trainer/ProgressPanel', () => ({ ProgressPanel: () => null }));
vi.mock('../components/trainer/LogPanel', () => ({ LogPanel: () => null }));
vi.mock('../components/trainer/ModelsList', () => ({ ModelsList: () => null }));

import { probeMyPc } from '../services/api';

const mockProbe = vi.mocked(probeMyPc);

const probeResult = (over: Partial<MyPcProbeResult> = {}): MyPcProbeResult => ({
  ok: false,
  platform: 'linux',
  shell: 'bash',
  python_path: '',
  checks: [],
  suggestions: [],
  ...over,
});

const startButton = () =>
  screen.getByRole('button', { name: 'trainer.startTraining' });

beforeEach(() => {
  vi.clearAllMocks();
  mockJobState.job = null;
  useStore.setState({
    trainerMode: 'mypc',
    trainerMyPcConfig: {
      host: '192.0.2.10',
      user: 'tester',
      password: 'pw',
      remoteDirBase: '~/projects',
      modelName: 'model',
      modelType: 'linear',
      pythonPath: '',
      keyPath: '',
      tub: './data',
    },
  });
});

describe('TrainerPage 训练模式来自全局 store', () => {
  it('mypc 模式渲染远程表单；store 切到 local 后渲染本地表单（页内不再自持 mode state）', async () => {
    render(<TrainerPage />);
    expect(screen.getByTestId('remote-config-form')).toBeInTheDocument();
    expect(screen.queryByTestId('local-config-form')).toBeNull();

    await act(async () => {
      useStore.getState().setTrainerMode('local');
    });

    expect(screen.getByTestId('local-config-form')).toBeInTheDocument();
    expect(screen.queryByTestId('remote-config-form')).toBeNull();
  });
});

describe('TrainerPage mypc 先检测后训练', () => {
  it('未检测过时点开始：先自动环境检测，未就绪则不开始训练', async () => {
    mockProbe.mockResolvedValue(probeResult({ ok: false }));
    render(<TrainerPage />);

    fireEvent.click(startButton());

    // 自动触发了一次环境检测
    await waitFor(() => expect(mockProbe).toHaveBeenCalledTimes(1));
    // 检测走完（未就绪 → 环境检测面板收到 not-ready 结果）后仍未开始训练
    await waitFor(() =>
      expect(screen.getByTestId('mypc-probe-panel')).toHaveAttribute(
        'data-ok',
        'false'
      )
    );
    expect(mockStartMyPc).not.toHaveBeenCalled();
  });

  it('检测通过：用检测到的 python 路径开始训练；已就绪后再点开始直接训练、不重复检测', async () => {
    mockProbe.mockResolvedValue(
      probeResult({ ok: true, python_path: '/detected/python' })
    );
    render(<TrainerPage />);

    fireEvent.click(startButton());

    await waitFor(() => expect(mockStartMyPc).toHaveBeenCalledTimes(1));
    // 用检测到的正确路径开始训练，并写回 store 里的 trainerMyPcConfig
    expect(mockStartMyPc).toHaveBeenCalledWith(
      expect.objectContaining({ pythonPath: '/detected/python' })
    );
    await waitFor(() =>
      expect(useStore.getState().trainerMyPcConfig.pythonPath).toBe(
        '/detected/python'
      )
    );

    // 已就绪（myPcEnvReady === true）：再点开始直接训练，不再检测
    mockProbe.mockClear();
    fireEvent.click(startButton());
    await waitFor(() => expect(mockStartMyPc).toHaveBeenCalledTimes(2));
    expect(mockProbe).not.toHaveBeenCalled();
    expect(mockStartMyPc).toHaveBeenLastCalledWith(
      expect.objectContaining({ pythonPath: '/detected/python' })
    );
  });

  it('检测请求失败：按钮恢复后不开始训练', async () => {
    let rejectProbe!: (e: Error) => void;
    mockProbe.mockImplementation(
      () =>
        new Promise((_, reject) => {
          rejectProbe = reject;
        })
    );
    render(<TrainerPage />);

    fireEvent.click(startButton());

    // 检测中：按钮禁用并显示检测中文案
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'trainer.myPcProbeRunning' })
      ).toBeDisabled()
    );

    await act(async () => {
      rejectProbe(new Error('SSH 连不上'));
    });

    // 检测失败后按钮恢复，且未开始训练
    await waitFor(() => expect(startButton()).not.toBeDisabled());
    expect(mockStartMyPc).not.toHaveBeenCalled();
  });
});

describe('TrainerPage mypc 断点续训', () => {
  it('任务已停止时主按钮显示「继续」，点击后先检测环境再走续训接口', async () => {
    mockJobState.job = { status: 'stopped' };
    mockProbe.mockResolvedValue(
      probeResult({ ok: true, python_path: '/detected/python' })
    );
    render(<TrainerPage />);

    const resumeButton = screen.getByRole('button', {
      name: 'trainer.resumeTraining',
    });
    fireEvent.click(resumeButton);

    // 未检测过：先自动环境检测，通过后调用 resumeMyPc 而非 startMyPc
    await waitFor(() => expect(mockProbe).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockResumeMyPc).toHaveBeenCalledTimes(1));
    expect(mockStartMyPc).not.toHaveBeenCalled();
    // 用检测到的正确 python 路径续训
    expect(mockResumeMyPc).toHaveBeenCalledWith(
      expect.objectContaining({ pythonPath: '/detected/python' })
    );
  });
});

describe('TrainerPage mypc 高级选项折叠框', () => {
  it('默认收起：aria-expanded=false 且内容不可见；点击后展开', () => {
    render(<TrainerPage />);

    const toggle = screen.getByRole('button', {
      name: /trainer\.advancedOptions/,
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    // 内容容器存在但不可见（hidden class = display:none）
    const content = screen.getByTestId('advanced-options-content');
    expect(content).not.toBeVisible();

    // 点击展开
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(content).toBeVisible();
  });
});
