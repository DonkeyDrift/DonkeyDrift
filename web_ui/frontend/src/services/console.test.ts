import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { consoleRequest, consoleProxyUrl, CONSOLE_REQUEST_TIMEOUT_MS } from './console';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

describe('consoleRequest 代理请求兜底超时', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('未提供 signal 时自动附加 signal，并在超时后中止挂起的请求', () => {
    mockFetch.mockImplementation((_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        );
      }),
    );
    const pending = consoleRequest('192.168.1.10', 'api/mute');
    expect(mockFetch).toHaveBeenCalledWith(
      consoleProxyUrl('192.168.1.10', 'api/mute'),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    vi.advanceTimersByTime(CONSOLE_REQUEST_TIMEOUT_MS);
    return expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('调用方显式提供 signal 时原样透传，不附加超时', () => {
    const controller = new AbortController();
    consoleRequest('192.168.1.10', 'api/mute', { signal: controller.signal });
    expect(mockFetch).toHaveBeenCalledWith(
      consoleProxyUrl('192.168.1.10', 'api/mute'),
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});
