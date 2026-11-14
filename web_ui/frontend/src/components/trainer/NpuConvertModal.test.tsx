import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { NpuConvertModal, isNpuConvertible } from './NpuConvertModal';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      vars && 'path' in vars ? `${key}:${vars.path}` : key,
    lang: 'zh',
  }),
}));

const mockStartAimoConvert = vi.fn();
const mockGetAimoKeyStatus = vi.fn();
const mockGetJobStatus = vi.fn();
const mockStopTrain = vi.fn();
const mockListTrainerTubs = vi.fn();

let sseHandlers: {
  onmessage: ((ev: { data: string }) => void) | null;
  onerror: (() => void) | null;
} | null = null;

vi.mock('../../services/api', () => ({
  startAimoConvert: (...args: unknown[]) => mockStartAimoConvert(...args),
  getAimoKeyStatus: (...args: unknown[]) => mockGetAimoKeyStatus(...args),
  getJobStatus: (...args: unknown[]) => mockGetJobStatus(...args),
  stopTrain: (...args: unknown[]) => mockStopTrain(...args),
  listTrainerTubs: (...args: unknown[]) => mockListTrainerTubs(...args),
  createLogStream: vi.fn(() => {
    const es = {
      onmessage: null as ((ev: { data: string }) => void) | null,
      onerror: null as (() => void) | null,
      close: vi.fn(),
    };
    sseHandlers = es;
    return es;
  }),
  getApiErrorMessage: vi.fn(() => 'start failed'),
}));

vi.mock('../../store/useStore', () => ({
  useStore: () => ({ configPath: '/car' }),
}));

const renderModal = (props: Partial<Parameters<typeof NpuConvertModal>[0]> = {}) =>
  render(
    <NpuConvertModal
      isOpen
      onClose={props.onClose ?? vi.fn()}
      initialModelPath={props.initialModelPath}
      onCompleted={props.onCompleted}
    />,
  );

const emit = (payload: Record<string, unknown>) => {
  act(() => {
    sseHandlers?.onmessage?.({ data: JSON.stringify(payload) });
  });
};

describe('isNpuConvertible', () => {
  it('识别可转换类型，排除 .h5 / .aidem / .ckpt', () => {
    expect(isNpuConvertible('pilot.tflite', 'file')).toBe(true);
    expect(isNpuConvertible('pilot.onnx', 'file')).toBe(true);
    expect(isNpuConvertible('pilot.TFLITE', 'file')).toBe(true);
    expect(isNpuConvertible('pilot.savedmodel', 'dir')).toBe(true);
    expect(isNpuConvertible('pilot.savedmodel', 'file')).toBe(false);
    expect(isNpuConvertible('pilot.h5', 'file')).toBe(false);
    expect(isNpuConvertible('pilot.aidem', 'file')).toBe(false);
    expect(isNpuConvertible('pilot.ckpt', 'file')).toBe(false);
  });
});

describe('NpuConvertModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sseHandlers = null;
    mockGetAimoKeyStatus.mockResolvedValue({ sdk: true, key: true, keySource: 'env' });
    mockListTrainerTubs.mockResolvedValue({
      tubs: [{ name: 'tub_a', relative_path: './data/tub_a', absolute_path: '/car/data/tub_a' }],
      current_tub_path: '',
    });
    mockStartAimoConvert.mockResolvedValue({ job_id: 'j1', status: 'pending' });
    mockGetJobStatus.mockResolvedValue({ result_path: null });
  });

  it('未配置 SDK/Key 时显示警告横幅', async () => {
    mockGetAimoKeyStatus.mockResolvedValue({ sdk: false, key: false, keySource: null });
    renderModal({});

    await waitFor(() => expect(screen.getByTestId('npu-key-warning')).toBeInTheDocument());
    // sdk 缺失作为标题行，两项各自的修复提示都展示
    expect(screen.getByText('trainer.npuConvertSdkMissing')).toBeInTheDocument();
    expect(screen.getByText('trainer.npuConvertSdkHint')).toBeInTheDocument();
    expect(screen.getByText('trainer.npuConvertKeyHint')).toBeInTheDocument();
  });

  it('仅缺 Key（SDK 已装）时标题行为 Key 未配置', async () => {
    mockGetAimoKeyStatus.mockResolvedValue({ sdk: true, key: false, keySource: null });
    renderModal({});

    await waitFor(() => expect(screen.getByTestId('npu-key-warning')).toBeInTheDocument());
    expect(screen.getByText('trainer.npuConvertKeyMissing')).toBeInTheDocument();
  });

  it('路径为空时开始按钮禁用，填入后以映射参数提交', async () => {
    renderModal({});

    const start = await waitFor(() => screen.getByTestId('npu-convert-start'));
    expect(start).toBeDisabled();
    expect(mockGetAimoKeyStatus).toHaveBeenCalled();
    expect(mockListTrainerTubs).toHaveBeenCalledWith('/car');

    fireEvent.change(screen.getByTestId('npu-model-path'), {
      target: { value: './models/pilot.tflite' },
    });
    expect(start).not.toBeDisabled();
    fireEvent.click(start);

    await waitFor(() => expect(mockStartAimoConvert).toHaveBeenCalledWith(
      expect.objectContaining({
        model_path: './models/pilot.tflite',
        out_dir: './models',
        working_dir: '/car',
        precision: 'INT8',
        calib_tubs: null,
        calib_mix_synth: 0,
        calib_dataset: 'imagenet',
      }),
    ));
  });

  it('选择校准 tub 后以 tub 路径与合成图数量提交', async () => {
    renderModal({ initialModelPath: '/car/models/pilot.tflite' });

    const start = await waitFor(() => screen.getByTestId('npu-convert-start'));
    fireEvent.change(screen.getByTestId('npu-calib-tub'), {
      target: { value: '/car/data/tub_a' },
    });
    fireEvent.click(start);

    await waitFor(() => expect(mockStartAimoConvert).toHaveBeenCalledWith(
      expect.objectContaining({
        calib_tubs: '/car/data/tub_a',
        calib_mix_synth: 30,
      }),
    ));
  });

  it('SSE 日志/进度驱动界面，终态后查询产物路径并回调 onCompleted', async () => {
    const onCompleted = vi.fn();
    renderModal({ initialModelPath: './models/pilot.tflite', onCompleted });

    fireEvent.click(await waitFor(() => screen.getByTestId('npu-convert-start')));
    await waitFor(() => expect(sseHandlers).not.toBeNull());

    emit({ type: 'log', line: '[3/5] 已提交，轮询中...' });
    emit({ type: 'progress', data: { globalPercent: 60 } });
    expect(screen.getByTestId('npu-convert-log')).toHaveTextContent('[3/5] 已提交，轮询中...');
    expect(screen.getByText('60%')).toBeInTheDocument();

    mockGetJobStatus.mockResolvedValue({ result_path: '/car/models/pilot.ctx.bin.aidem' });
    emit({ type: 'status', status: 'completed', error: null });

    await waitFor(() =>
      expect(screen.getByTestId('npu-result-path')).toHaveTextContent(
        'trainer.npuConvertResult:/car/models/pilot.ctx.bin.aidem',
      ),
    );
    expect(onCompleted).toHaveBeenCalledTimes(1);
  });

  it('运行中点停止调用 stopTrain', async () => {
    mockStopTrain.mockResolvedValue({ status: 'stopped' });
    renderModal({ initialModelPath: './models/pilot.tflite' });

    fireEvent.click(await waitFor(() => screen.getByTestId('npu-convert-start')));
    const stop = await waitFor(() => screen.getByTestId('npu-convert-stop'));
    fireEvent.click(stop);

    await waitFor(() => expect(mockStopTrain).toHaveBeenCalledWith('j1'));
  });

  it('提交失败时显示错误信息', async () => {
    mockStartAimoConvert.mockRejectedValue({ response: { data: { detail: 'boom' } } });
    renderModal({ initialModelPath: './models/pilot.tflite' });

    fireEvent.click(await waitFor(() => screen.getByTestId('npu-convert-start')));

    await waitFor(() => expect(screen.getByTestId('npu-start-error')).toBeInTheDocument());
  });
});
