import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionFilterPicker, type SessionFilterState } from './SessionFilterPicker';
import type { TubSession } from '../../services/api';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));

const listTubSessionsMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
  listTubSessions: listTubSessionsMock,
}));

const SESSIONS: TubSession[] = [
  {
    session_id: '26-10-20_0',
    record_count: 120,
    first_index: 0,
    last_index: 119,
    start_time_ms: 1729380000000,
    end_time_ms: 1729380060000,
  },
  {
    session_id: '26-10-21_0',
    record_count: 80,
    first_index: 120,
    last_index: 199,
    start_time_ms: 1729466400000,
    end_time_ms: 1729466460000,
  },
];

/** 受控测试环境：状态回流 + 每次 onChange 都被间谍记录，贴近 TrainerPage 用法 */
const onChangeSpy = vi.hoisted(() => vi.fn());

function Harness({ initial = {} }: { initial?: Partial<SessionFilterState> }) {
  const [sf, setSf] = React.useState<SessionFilterState>({
    enabled: false,
    selected: [],
    isFullSelection: false,
    ...initial,
  });
  return (
    <SessionFilterPicker
      tub="./data"
      tubCandidates={[]}
      enabled={sf.enabled}
      selected={sf.selected}
      onChange={(next) => {
        onChangeSpy(next);
        setSf(next);
      }}
    />
  );
}

async function renderEnabled(initial: Partial<SessionFilterState> = {}) {
  render(<Harness initial={{ enabled: true, ...initial }} />);
  // 等会话列表渲染出来（受控初值直接 enabled，列表立即可见）
  await screen.findByLabelText(/26-10-20_0/);
}

const clickSession = (id: string) =>
  fireEvent.click(screen.getByLabelText(new RegExp(id)));

beforeEach(() => {
  vi.clearAllMocks();
  listTubSessionsMock.mockResolvedValue({
    status: true,
    path: '/abs/data',
    sessions: SESSIONS,
  });
});

describe('SessionFilterPicker 默认状态', () => {
  it('默认不启用：只显示开关与提示，不展示会话列表，挂载本身不触发 onChange', async () => {
    render(<Harness />);
    expect(screen.getByTestId('session-filter-enable')).not.toBeChecked();
    expect(screen.queryByText('26-10-20_0')).toBeNull();
    await waitFor(() => expect(listTubSessionsMock).toHaveBeenCalledTimes(1));
    expect(onChangeSpy).not.toHaveBeenCalled();
  });

  it('tub 命中候选时用 absolute_path 拉取会话；手输路径原样透传', async () => {
    render(
      <SessionFilterPicker
        tub="./data"
        tubCandidates={[
          { name: 'data', relative_path: './data', absolute_path: '/abs/data' },
        ]}
        enabled={false}
        selected={[]}
        onChange={vi.fn()}
      />
    );
    await waitFor(() =>
      expect(listTubSessionsMock).toHaveBeenCalledWith('/abs/data')
    );

    vi.clearAllMocks();
    render(
      <SessionFilterPicker
        tub="/manual/path"
        tubCandidates={[]}
        enabled={false}
        selected={[]}
        onChange={vi.fn()}
      />
    );
    await waitFor(() =>
      expect(listTubSessionsMock).toHaveBeenCalledWith('/manual/path')
    );
  });
});

describe('SessionFilterPicker 勾选语义', () => {
  it('勾选子集：回调传出 enabled + 选中 id + isFullSelection=false', async () => {
    render(<Harness />);
    await waitFor(() => expect(listTubSessionsMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [],
      isFullSelection: false,
    });

    await screen.findByLabelText(/26-10-20_0/);
    clickSession('26-10-20_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: ['26-10-20_0'],
      isFullSelection: false,
    });
  });

  it('全选：回调 isFullSelection=true（TrainerPage 据此省略 session_ids）', async () => {
    await renderEnabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'trainer.sessionFilterSelectAll' })
    );
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: ['26-10-20_0', '26-10-21_0'],
      isFullSelection: true,
    });
  });

  it('清空：回调 selected=[] 且 isFullSelection=false，并提示至少勾一段', async () => {
    await renderEnabled({ selected: ['26-10-20_0', '26-10-21_0'] });
    fireEvent.click(
      screen.getByRole('button', { name: 'trainer.sessionFilterClear' })
    );
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [],
      isFullSelection: false,
    });
    expect(
      screen.getByText('trainer.sessionFilterNoneSelected')
    ).toBeInTheDocument();
  });

  it('取消单个勾选从选中集中移除该会话', async () => {
    await renderEnabled({ selected: ['26-10-20_0', '26-10-21_0'] });
    clickSession('26-10-20_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: ['26-10-21_0'],
      isFullSelection: false,
    });
  });
});

describe('SessionFilterPicker 异常提示', () => {
  it('加载失败：温和提示，不抛出', async () => {
    listTubSessionsMock.mockRejectedValue(new Error('network down'));
    render(<Harness initial={{ enabled: true }} />);
    await waitFor(() =>
      expect(
        screen.getByText('trainer.sessionFilterLoadFailed')
      ).toBeInTheDocument()
    );
  });

  it('无会话：提示无可筛选会话', async () => {
    listTubSessionsMock.mockResolvedValue({ status: true, path: '/x', sessions: [] });
    render(<Harness initial={{ enabled: true }} />);
    await waitFor(() =>
      expect(screen.getByText('trainer.sessionFilterEmpty')).toBeInTheDocument()
    );
  });

  it('会话列表变化后自动剔除已不存在的勾选', async () => {
    await renderEnabled({ selected: ['gone_0'] });
    await waitFor(() =>
      expect(onChangeSpy).toHaveBeenLastCalledWith({
        enabled: true,
        selected: [],
        isFullSelection: false,
      })
    );
  });
});
