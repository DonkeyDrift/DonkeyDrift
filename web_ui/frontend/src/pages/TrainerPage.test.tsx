import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { TrainerPage } from './TrainerPage';
import { useStore } from '../store/useStore';
import type { MyPcProbeResult } from '../services/api';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    // 插值 mock：携带参数时返回 key + JSON 参数，便于断言摘要文案口径
    t: (key: string, params?: Record<string, unknown>) =>
      params ? `${key} ${JSON.stringify(params)}` : key,
    lang: 'zh',
  }),
}));

vi.mock('../services/api', () => ({
  getTrainerConfig: vi.fn(() => Promise.reject(new Error('no conf'))),
  getMyPcKnownHosts: vi.fn(() => Promise.resolve([])),
  listTrainerTubs: vi.fn(() => Promise.resolve({ tubs: [], current_tub_path: '' })),
  listFamilyTubSessions: vi.fn(() =>
    Promise.resolve({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: [],
    })
  ),
  loadConfig: vi.fn(),
  loadMyconfig: vi.fn(),
  saveTrainingConfig: vi.fn(),
  probeMyPc: vi.fn(),
}));

const { mockStartMyPc, mockResumeMyPc, mockJobState, mockStartLocal } = vi.hoisted(() => ({
  mockStartMyPc: vi.fn(() => Promise.resolve()),
  mockResumeMyPc: vi.fn(() => Promise.resolve()),
  mockStartLocal: vi.fn(
    (_params: {
      tub: string;
      model: string;
      model_type: string;
      transfer?: string;
      session_ids?: string[];
      session_filter?: Record<string, string[]>;
    }) => Promise.resolve()
  ),
  mockJobState: { job: null as { status: string } | null },
}));
vi.mock('../hooks/useTrainingJob', () => ({
  useTrainingJob: () => ({
    job: mockJobState.job,
    startLocal: mockStartLocal,
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

import { probeMyPc, listFamilyTubSessions, listTrainerTubs } from '../services/api';
import type { FamilyTubSession } from '../services/api';

const mockProbe = vi.mocked(probeMyPc);
const mockListFamilyTubSessions = vi.mocked(listFamilyTubSessions);
const mockListTrainerTubs = vi.mocked(listTrainerTubs);

// 家族源：两个 tub 共 3 段会话（勾选 2 段不构成全选，便于断言分组 payload）
const TUB_A = '/abs/data';
const TUB_B = '/abs/data/tub_1_26-10-23';
const LOCAL_SESSIONS: FamilyTubSession[] = [
  {
    session_id: '26-10-20_0',
    record_count: 120,
    first_index: 0,
    last_index: 119,
    start_time_ms: 1729380000000,
    end_time_ms: 1729380060000,
    tub_path: TUB_A,
    tub_name: 'data',
  },
  {
    session_id: '26-10-21_0',
    record_count: 60,
    first_index: 120,
    last_index: 179,
    start_time_ms: 1729466400000,
    end_time_ms: 1729466440000,
    tub_path: TUB_A,
    tub_name: 'data',
  },
  {
    session_id: '26-10-23_0',
    record_count: 80,
    first_index: 0,
    last_index: 79,
    start_time_ms: 1729552800000,
    end_time_ms: 1729552860000,
    tub_path: TUB_B,
    tub_name: 'tub_1_26-10-23',
  },
];

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
  // clearAllMocks 只清调用记录、不移除既有 mockResolvedValue 实现：
  // 这里显式恢复默认实现，避免用例间相互污染（listTrainerTubs 残留候选会
  // 触发自动填充把 tub 切走并重置会话筛选）
  mockListTrainerTubs.mockResolvedValue({ tubs: [], current_tub_path: '' });
  mockListFamilyTubSessions.mockResolvedValue({
    status: true,
    path: '/abs/data',
    family_root: '/abs',
    sessions: [],
  });
  mockJobState.job = null;
  useStore.setState({
    trainerMode: 'mypc',
    trainerLocalConfig: {
      tub: './data',
      model: '',
      modelType: 'linear',
      transfer: '',
      advancedEnabled: false,
      batchSize: 128,
      trainTestSplit: 0.8,
      maxEpochs: 100,
      showPlot: true,
      useEarlyStop: true,
      earlyStopPatience: 5,
      learningRate: 0.001,
      createTfLite: true,
      pruneValLossDegradationLimit: 0.2,
    },
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

describe('TrainerPage 本地训练会话筛选', () => {
  it('默认不启用筛选：开始训练的请求不带 session_filter（家族全量，与旧行为一致）', async () => {
    useStore.setState({ trainerMode: 'local' });
    render(<TrainerPage />);

    fireEvent.click(startButton());

    await waitFor(() => expect(mockStartLocal).toHaveBeenCalledTimes(1));
    const arg = mockStartLocal.mock.calls[0]?.[0];
    expect(arg?.session_filter).toBeUndefined();
  });

  it('勾选会话子集后开始训练：startLocal 带按 tub 分组的 session_filter', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    fireEvent.click(await screen.findByLabelText(/data\/26-10-20_0/));

    fireEvent.click(startButton());
    await waitFor(() => expect(mockStartLocal).toHaveBeenCalledTimes(1));
    expect(mockStartLocal).toHaveBeenCalledWith(
      expect.objectContaining({
        session_filter: { [TUB_A]: ['26-10-20_0'] },
      })
    );
  });

  it('跨 tub 勾选多段：session_filter 按 tub 聚合（撞名 session_id 不串）', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    fireEvent.click(await screen.findByLabelText(/data\/26-10-20_0/));
    fireEvent.click(await screen.findByLabelText(/tub_1_26-10-23\/26-10-23_0/));

    fireEvent.click(startButton());
    await waitFor(() => expect(mockStartLocal).toHaveBeenCalledTimes(1));
    expect(mockStartLocal).toHaveBeenCalledWith(
      expect.objectContaining({
        session_filter: { [TUB_A]: ['26-10-20_0'], [TUB_B]: ['26-10-23_0'] },
      })
    );
  });

  it('全选时省略 session_filter（等价于训练全部记录）', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    await screen.findByLabelText(/data\/26-10-20_0/);
    fireEvent.click(
      screen.getByRole('button', { name: 'trainer.sessionFilterSelectAll' })
    );

    fireEvent.click(startButton());
    await waitFor(() => expect(mockStartLocal).toHaveBeenCalledTimes(1));
    expect(mockStartLocal.mock.calls[0]?.[0]?.session_filter).toBeUndefined();
  });

  it('启用筛选但一段都不勾：禁用开始按钮并提示', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    fireEvent.click(screen.getByTestId('session-filter-enable'));

    expect(startButton()).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByText('trainer.sessionFilterNoneSelected')).toBeInTheDocument()
    );
  });

  it('自动填充切换 tub 后重置会话筛选状态', async () => {
    mockListTrainerTubs
      .mockResolvedValueOnce({
        tubs: [
          { name: 'data', relative_path: './data', absolute_path: '/abs/data' },
        ],
        current_tub_path: '',
      })
      .mockResolvedValue({
        tubs: [
          { name: 'data2', relative_path: './data2', absolute_path: '/abs/data2' },
        ],
        current_tub_path: '',
      });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    useStore.setState({ trainerMode: 'local', tubPath: '/abs/data' });
    render(<TrainerPage />);

    // 初始 tub ./data（默认）：启用并勾选一段
    fireEvent.click(screen.getByTestId('session-filter-enable'));
    fireEvent.click(await screen.findByLabelText(/data\/26-10-20_0/));

    // 车端加载 tub 变化触发自动填充 → tub 切成 ./data2 → 筛选状态重置
    await act(async () => {
      useStore.setState({ tubPath: '/abs/data2' });
    });
    await waitFor(() =>
      expect(screen.getByTestId('session-filter-enable')).not.toBeChecked()
    );
  });
});

describe('TrainerPage 训练数据范围摘要', () => {
  it('未启用筛选：显示「全部录制 K 个 Tub / 共 M 帧」', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    await waitFor(() =>
      expect(
        screen.getByText(
          'trainer.trainingScopeAll {"tubs":2,"frames":260}'
        )
      ).toBeInTheDocument()
    );
  });

  it('启用筛选且勾选子集：显示「已选 N 段，涉及 K 个 Tub / 共 M 帧」+ 条目列表', async () => {
    useStore.setState({ trainerMode: 'local' });
    mockListFamilyTubSessions.mockResolvedValue({
      status: true,
      path: '/abs/data',
      family_root: '/abs',
      sessions: LOCAL_SESSIONS,
    });
    render(<TrainerPage />);

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    fireEvent.click(await screen.findByLabelText(/data\/26-10-20_0/));

    await waitFor(() =>
      expect(
        screen.getByText(
          'trainer.trainingScopeFiltered {"segments":1,"tubs":1,"frames":120}'
        )
      ).toBeInTheDocument()
    );
    // 条目列表：tub名/会话名
    expect(screen.getByText(/data\/26-10-20_0/)).toBeInTheDocument();
    // 未勾选的会话不进摘要列表
    expect(
      screen.queryByText(/tub_1_26-10-23\/26-10-23_0/)
    ).toBeNull();
  });

  it('会话列表为空：不渲染摘要（Picker 已给出空态提示）', async () => {
    useStore.setState({ trainerMode: 'local' });
    render(<TrainerPage />);

    await waitFor(() => expect(mockListFamilyTubSessions).toHaveBeenCalled());
    expect(screen.queryByTestId('training-scope-summary')).toBeNull();
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
