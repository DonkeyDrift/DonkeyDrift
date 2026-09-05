import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { useTrainingJob } from './useTrainingJob';

vi.mock('../services/api', () => ({
  getJobStatus: vi.fn(),
  createLogStream: vi.fn(),
  startLocalTrain: vi.fn(),
  startOnlineTrain: vi.fn(),
  startMyPcTrain: vi.fn(),
  resumeMyPcTrain: vi.fn(),
  stopTrain: vi.fn(),
  setTrainerConfig: vi.fn(),
}));

import { getJobStatus, createLogStream } from '../services/api';

const mockGetJobStatus = vi.mocked(getJobStatus);
const mockCreateLogStream = vi.mocked(createLogStream);

function fakeEventSource() {
  return {
    onmessage: null as ((event: MessageEvent) => void) | null,
    onerror: null as ((event: Event) => void) | null,
    close: vi.fn(),
  };
}

const runningStatus = {
  job_id: 'job1',
  mode: 'local',
  status: 'running',
  progress: {
    currentEpoch: 3,
    totalEpochs: 10,
    currentStep: 5,
    totalSteps: 20,
    loss: 0.5,
    globalPercent: 32.5,
  },
  started_at: '2026-01-01T00:00:00',
  finished_at: null,
  error: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ trainingJob: null, activeTraining: null, configPath: '' });
});

describe('useTrainingJob 刷新后恢复训练进度', () => {
  it('存在 running 的 activeTraining：拉状态、重建 job、重连 SSE', async () => {
    useStore.setState({ activeTraining: { id: 'job1', mode: 'local' } });
    mockGetJobStatus.mockResolvedValue(runningStatus);
    mockCreateLogStream.mockReturnValue(fakeEventSource() as never);

    renderHook(() => useTrainingJob());

    await waitFor(() => expect(mockGetJobStatus).toHaveBeenCalledWith('job1'));
    await waitFor(() => expect(mockCreateLogStream).toHaveBeenCalledWith('job1'));

    const job = useStore.getState().trainingJob;
    expect(job).not.toBeNull();
    expect(job?.status).toBe('running');
    expect(job?.progress.currentEpoch).toBe(3);
    expect(job?.progress.globalPercent).toBe(32.5);
  });

  it('activeTraining 已终态：展示终态并清空持久化 id，且不重连 SSE', async () => {
    useStore.setState({ activeTraining: { id: 'job2', mode: 'online' } });
    mockGetJobStatus.mockResolvedValue({
      ...runningStatus,
      job_id: 'job2',
      mode: 'online',
      status: 'completed',
      progress: { ...runningStatus.progress, currentEpoch: 10, globalPercent: 100 },
      finished_at: '2026-01-01T01:00:00',
    });

    renderHook(() => useTrainingJob());

    await waitFor(() => expect(mockGetJobStatus).toHaveBeenCalledWith('job2'));
    await waitFor(() => expect(useStore.getState().activeTraining).toBeNull());
    expect(useStore.getState().trainingJob?.status).toBe('completed');
    expect(mockCreateLogStream).not.toHaveBeenCalled();
  });

  it('activeTraining 无效（后端已无此任务）：清空标记并回到空闲态', async () => {
    useStore.setState({ activeTraining: { id: 'gone', mode: 'local' } });
    mockGetJobStatus.mockRejectedValue(new Error('404'));

    renderHook(() => useTrainingJob());

    await waitFor(() => expect(useStore.getState().activeTraining).toBeNull());
    expect(useStore.getState().trainingJob).toBeNull();
  });

  it('没有 activeTraining 时不请求状态', () => {
    renderHook(() => useTrainingJob());
    expect(mockGetJobStatus).not.toHaveBeenCalled();
    expect(mockCreateLogStream).not.toHaveBeenCalled();
  });
});
