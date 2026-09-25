import { describe, it, expect, vi, beforeEach } from 'vitest';

// 回归：导入模型报「Request failed with status code 422」。
// axios 实例默认 Content-Type: application/json 会随 FormData 请求一起发出，
// 后端按 JSON 解析 multipart 体，找不到 file 字段即 422。修复：FormData 请求
// 显式置空 Content-Type，交给浏览器生成带 boundary 的 multipart/form-data。

const mockPost = vi.fn((..._args: unknown[]) => Promise.resolve({ data: { status: true } }));
const mockGet = vi.fn();
const mockDelete = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
      post: (...args: unknown[]) => mockPost(...args),
      get: (...args: unknown[]) => mockGet(...args),
      delete: (...args: unknown[]) => mockDelete(...args),
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    })),
    isAxiosError: vi.fn(() => false),
  },
}));

vi.mock('@/lib/apiHealth', () => ({ registerApiClient: vi.fn() }));

import { importModel, uploadModelLoss } from './api';

describe('FormData 上传统一的 Content-Type 处理', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('importModel 显式置空 Content-Type，避免默认 application/json 污染 multipart', async () => {
    await importModel(new File(['x'], 'm.tflite'), '/car', undefined, undefined);

    expect(mockPost).toHaveBeenCalledWith(
      '/trainer/models/import',
      expect.any(FormData),
      { headers: { 'Content-Type': null } },
    );
  });

  it('uploadModelLoss 同样置空 Content-Type', async () => {
    await uploadModelLoss('m.tflite', '/car', undefined, undefined);

    expect(mockPost).toHaveBeenCalledWith(
      '/trainer/models/m.tflite/loss',
      expect.any(FormData),
      { headers: { 'Content-Type': null } },
    );
  });
});
