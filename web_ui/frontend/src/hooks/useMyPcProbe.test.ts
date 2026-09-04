import '@testing-library/jest-dom/vitest';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useMyPcProbe } from './useMyPcProbe';
import type { MyPcProbeResult } from '../services/api';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) =>
      params ? `${key} ${JSON.stringify(params)}` : key,
    lang: 'zh',
  }),
}));
vi.mock('../services/api', () => ({
  probeMyPc: vi.fn(),
}));

import { probeMyPc } from '../services/api';

const mockProbe = vi.mocked(probeMyPc);

const args = {
  host: '192.0.2.10',
  user: 'tester',
  password: 'pw',
  remoteDirBase: '~/projects',
  pythonPath: '',
};

const probeData = (over: Partial<MyPcProbeResult> = {}): MyPcProbeResult => ({
  ok: true,
  platform: 'linux',
  shell: 'bash',
  python_path: '/usr/bin/python3',
  checks: [],
  suggestions: [],
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useMyPcProbe', () => {
  it('检测成功：返回结果并写入 result，loading 复位', async () => {
    mockProbe.mockResolvedValue(probeData());
    const { result } = renderHook(() => useMyPcProbe());

    let data: MyPcProbeResult | null | undefined;
    await act(async () => {
      data = await result.current.runProbe(args);
    });

    expect(data).toEqual(probeData());
    expect(result.current.result?.ok).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
    // 表单字段映射到 API 的 snake_case 参数（keyPath 留空时不传）
    expect(mockProbe).toHaveBeenCalledWith({
      host: args.host,
      user: args.user,
      password: args.password,
      remote_dir_base: args.remoteDirBase,
      python_path: args.pythonPath,
      key_path: undefined,
    });
  });

  it('检测期间 loading 为 true，结束后复位', async () => {
    let resolveProbe!: (v: MyPcProbeResult) => void;
    mockProbe.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveProbe = resolve;
        })
    );
    const { result } = renderHook(() => useMyPcProbe());

    act(() => {
      void result.current.runProbe(args);
    });
    await waitFor(() => expect(result.current.loading).toBe(true));

    await act(async () => {
      resolveProbe(probeData());
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.result?.ok).toBe(true);
  });

  it('检测请求失败：返回 null 并写入 error，不更新 result', async () => {
    mockProbe.mockRejectedValue(new Error('SSH 连不上'));
    const { result } = renderHook(() => useMyPcProbe());

    let data: MyPcProbeResult | null | undefined;
    await act(async () => {
      data = await result.current.runProbe(args);
    });

    expect(data).toBeNull();
    expect(result.current.result).toBeNull();
    expect(result.current.error).toContain('trainer.myPcProbeFailed');
    expect(result.current.error).toContain('SSH 连不上');
    expect(result.current.loading).toBe(false);
  });
});
