import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { SimCollectCard } from './SimCollectCard';

// 控制 useSimCollectJob 返回的 job 状态
const mock = vi.hoisted(() => ({
  job: null as
    | {
        status: 'pending' | 'running' | 'done' | 'error' | 'stopped';
        step: number;
        total: number;
        cte: number | null;
        speed: number | null;
        result: {
          steps: number;
          mean_cte: number;
          max_cte: number;
          crashed: number;
          result_out: string;
        } | null;
        error: string | null;
        logs: string[];
      }
    | null,
  start: vi.fn((_params: unknown) => Promise.resolve()),
  stop: vi.fn(() => Promise.resolve()),
  reset: vi.fn(),
}));

vi.mock('../../hooks/useSimCollectJob', () => ({
  useSimCollectJob: () => mock,
}));

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

const renderCard = () =>
  render(
    <LanguageProvider>
      <SimCollectCard />
    </LanguageProvider>,
  );

describe('SimCollectCard', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setBrowserLanguage('zh-CN');
    mock.job = null;
    mock.start.mockClear();
    mock.stop.mockClear();
  });

  it('renders title, hint and start button in idle state', () => {
    renderCard();
    expect(screen.getByText('模拟器采集')).toBeInTheDocument();
    expect(screen.getByText('开始采集')).toBeInTheDocument();
    // 说明文字含 Mac
    expect(screen.getByText(/SSH 控制 Mac/)).toBeInTheDocument();
  });

  it('calls start with the configured steps when Start clicked', () => {
    renderCard();
    fireEvent.change(screen.getByDisplayValue('1500'), { target: { value: '300' } });
    fireEvent.click(screen.getByText('开始采集'));
    expect(mock.start).toHaveBeenCalledTimes(1);
    const params = mock.start.mock.calls[0][0] as { steps?: number };
    expect(params.steps).toBe(300);
  });

  it('shows progress and stop button while running', () => {
    mock.job = {
      status: 'running',
      step: 750,
      total: 1500,
      cte: 1.234,
      speed: 1.5,
      result: null,
      error: null,
      logs: [],
    };
    renderCard();
    expect(screen.getByText('停止')).toBeInTheDocument();
    expect(screen.getByText('采集中 750/1500')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText('1.234')).toBeInTheDocument();
  });

  it('renders result summary when done', () => {
    mock.job = {
      status: 'done',
      step: 1500,
      total: 1500,
      cte: 0.5,
      speed: 1.4,
      result: {
        steps: 1500,
        mean_cte: 2.4094,
        max_cte: 7.0614,
        crashed: 0,
        result_out: '/home/dkc/projects/mycar/sim_collect_x',
      },
      error: null,
      logs: [],
    };
    renderCard();
    expect(screen.getByText('采集完成')).toBeInTheDocument();
    expect(screen.getByText('1500')).toBeInTheDocument();
    expect(screen.getByText('2.4094')).toBeInTheDocument();
    expect(screen.getByText('7.0614')).toBeInTheDocument();
    expect(screen.getByText('否')).toBeInTheDocument(); // crashed=0 -> 否
    expect(screen.getByText('/home/dkc/projects/mycar/sim_collect_x')).toBeInTheDocument();
  });

  it('shows error message and logs when failed', () => {
    mock.job = {
      status: 'error',
      step: 0,
      total: 0,
      cte: null,
      speed: null,
      result: null,
      error: '没找到模拟器',
      logs: ['[mac-collect] 错误: 没找到模拟器'],
    };
    renderCard();
    expect(screen.getByText('出错：没找到模拟器')).toBeInTheDocument();
  });
});
