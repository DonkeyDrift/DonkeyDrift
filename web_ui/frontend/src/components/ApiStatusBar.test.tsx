import '@testing-library/jest-dom/vitest';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { ApiStatusBar } from './ApiStatusBar';
import { __resetApiHealth, registerApiClient } from '@/lib/apiHealth';

/**
 * 统一异步状态提示（apple 象限）：
 * - 首屏有在飞请求且还没成功过 → 骨架条；
 * - 任一次请求失败 → 可见错误条（含重试按钮），文案本地化，不回显后端原文。
 *
 * 观测层通过 registerApiClient 挂到 axios 实例上（services/api.ts 调用），
 * 这里用一个假的 axios 客户端把拦截器回调取出来手动触发。
 */
type Handlers = {
  request: ((config: unknown) => unknown)[];
  response: ((response: unknown) => unknown)[];
  rejected: ((error: unknown) => Promise<unknown>)[];
};

const makeFakeClient = (handlers: Handlers) => ({
  interceptors: {
    request: { use: (fn: (config: unknown) => unknown) => handlers.request.push(fn) },
    response: {
      use: (ok: (response: unknown) => unknown, bad: (error: unknown) => Promise<unknown>) => {
        handlers.response.push(ok);
        handlers.rejected.push(bad);
      },
    },
  },
});

describe('ApiStatusBar', () => {
  let handlers: Handlers;

  beforeEach(() => {
    __resetApiHealth();
    handlers = { request: [], response: [], rejected: [] };
    registerApiClient(makeFakeClient(handlers));
  });

  it('没有在飞请求时什么都不渲染', () => {
    const { container } = render(<ApiStatusBar />);
    expect(container).toBeEmptyDOMElement();
  });

  it('首屏请求在飞时显示加载骨架', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.request.forEach((fn) => fn({}));
    });
    expect(screen.getByTestId('api-skeleton')).toBeInTheDocument();
    expect(screen.getByTestId('api-skeleton')).toHaveAttribute('aria-busy', 'true');
  });

  it('请求失败时显示错误条、重试按钮与本地化文案（不回显后端原文）', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.rejected.forEach((fn) => {
        fn(new Error('KV unavailable')).catch(() => undefined);
      });
    });
    const bar = screen.getByTestId('api-error-bar');
    expect(bar).toBeInTheDocument();
    expect(bar).toHaveTextContent('数据加载失败，请重试');
    expect(bar).not.toHaveTextContent('KV unavailable');
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument();
  });

  it('关闭错误条后回到空闲态', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.rejected.forEach((fn) => {
        fn(new Error('boom')).catch(() => undefined);
      });
    });
    expect(screen.getByTestId('api-error-bar')).toBeInTheDocument();
    act(() => {
      screen.getByRole('button', { name: '关闭' }).click();
    });
    expect(screen.queryByTestId('api-error-bar')).not.toBeInTheDocument();
  });

  it('轮询型失败也会被提示（在飞计数不误报为骨架）', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.request.forEach((fn) => fn({}));
      handlers.response.forEach((fn) => fn({ data: [] }));
    });
    expect(screen.queryByTestId('api-skeleton')).not.toBeInTheDocument();
    act(() => {
      handlers.request.forEach((fn) => fn({}));
      handlers.rejected.forEach((fn) => {
        fn(new Error('network')).catch(() => undefined);
      });
    });
    expect(screen.getByTestId('api-error-bar')).toBeInTheDocument();
  });

  // 误报防线（2026-09-18 冒烟实测踩到）：POST 动作类请求的 4xx 是预期状态
  // （无相机时 `POST /api/drive/webrtc/session` 恒 400），不能因此常挂红条。
  it('POST 的 4xx（动作未就绪）不触发错误条', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.rejected.forEach((fn) => {
        fn({ config: { method: 'post' }, response: { status: 400 } }).catch(() => undefined);
      });
    });
    expect(screen.queryByTestId('api-error-bar')).not.toBeInTheDocument();
  });

  it('GET 的 4xx（尚未配置）不触发错误条，GET 5xx 触发', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.rejected.forEach((fn) => {
        fn({ config: { method: 'get' }, response: { status: 404 } }).catch(() => undefined);
      });
    });
    expect(screen.queryByTestId('api-error-bar')).not.toBeInTheDocument();
    act(() => {
      handlers.request.forEach((fn) => fn({}));
      handlers.rejected.forEach((fn) => {
        fn({ config: { method: 'get' }, response: { status: 503 } }).catch(() => undefined);
      });
    });
    expect(screen.getByTestId('api-error-bar')).toBeInTheDocument();
  });

  it('后续任一请求成功即清掉错误条（瞬时失败不长期挂红）', () => {
    render(<ApiStatusBar />);
    act(() => {
      handlers.rejected.forEach((fn) => {
        fn(new Error('network')).catch(() => undefined);
      });
    });
    expect(screen.getByTestId('api-error-bar')).toBeInTheDocument();
    act(() => {
      handlers.request.forEach((fn) => fn({}));
      handlers.response.forEach((fn) => fn({ data: [] }));
    });
    expect(screen.queryByTestId('api-error-bar')).not.toBeInTheDocument();
  });
});

// 让 vi 的未使用告警闭嘴（本文件不使用 mock）
void vi;
