import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionFilterPicker, type SessionFilterState } from './SessionFilterPicker';
import type { FamilyTubSession } from '../../services/api';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));

const listFamilyTubSessionsMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
  listFamilyTubSessions: listFamilyTubSessionsMock,
}));

// 家族源：_session_id 跨 tub 撞名（data 与 tub_1 都有 26-10-23_0），
// 勾选集合必须用 (tub_path, session_id) 复合键区分
const TUB_A = '/abs/data';
const TUB_B = '/abs/data/tub_1_26-10-23';
const SESSIONS: FamilyTubSession[] = [
  {
    session_id: '26-10-23_0',
    record_count: 120,
    first_index: 0,
    last_index: 119,
    start_time_ms: 1729380000000,
    end_time_ms: 1729380060000,
    tub_path: TUB_A,
    tub_name: 'data',
  },
  {
    session_id: '26-10-23_0',
    record_count: 80,
    first_index: 0,
    last_index: 79,
    start_time_ms: 1729466400000,
    end_time_ms: 1729466460000,
    tub_path: TUB_B,
    tub_name: 'tub_1_26-10-23',
  },
];

const keyA = `${TUB_A}::26-10-23_0`;
const keyB = `${TUB_B}::26-10-23_0`;

/** 受控测试环境：状态回流 + 每次 onChange 都被间谍记录，贴近 TrainerPage 用法 */
const onChangeSpy = vi.hoisted(() => vi.fn());
const onSessionsChangeSpy = vi.hoisted(() => vi.fn());

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
      onSessionsChange={onSessionsChangeSpy}
    />
  );
}

async function renderEnabled(initial: Partial<SessionFilterState> = {}) {
  render(<Harness initial={{ enabled: true, ...initial }} />);
  // 等会话列表渲染出来（受控初值直接 enabled，列表立即可见；两条撞名会话都出现）
  const rows = await screen.findAllByLabelText(/26-10-23_0/);
  expect(rows).toHaveLength(2);
}

const clickSession = (label: string) =>
  fireEvent.click(screen.getByLabelText(new RegExp(label)));

beforeEach(() => {
  vi.clearAllMocks();
  listFamilyTubSessionsMock.mockResolvedValue({
    status: true,
    path: '/abs/data',
    family_root: '/abs',
    sessions: SESSIONS,
  });
});

describe('SessionFilterPicker 默认状态', () => {
  it('默认不启用：只显示开关与提示，不展示会话列表，挂载本身不触发 onChange', async () => {
    render(<Harness />);
    expect(screen.getByTestId('session-filter-enable')).not.toBeChecked();
    expect(screen.queryByText('26-10-23_0')).toBeNull();
    await waitFor(() => expect(listFamilyTubSessionsMock).toHaveBeenCalledTimes(1));
    expect(onChangeSpy).not.toHaveBeenCalled();
  });

  it('tub 命中候选时用 absolute_path 拉取家族会话；手输路径原样透传', async () => {
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
      expect(listFamilyTubSessionsMock).toHaveBeenCalledWith('/abs/data')
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
      expect(listFamilyTubSessionsMock).toHaveBeenCalledWith('/manual/path')
    );
  });

  it('家族会话列表经 onSessionsChange 上报（TrainerPage 渲染训练范围摘要用）', async () => {
    render(<Harness />);
    await waitFor(() =>
      expect(onSessionsChangeSpy).toHaveBeenCalledWith('./data', SESSIONS)
    );
  });
});

describe('SessionFilterPicker 勾选语义（复合键）', () => {
  it('勾选子集：回调传出 enabled + 复合键 + isFullSelection=false', async () => {
    render(<Harness />);
    await waitFor(() => expect(listFamilyTubSessionsMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('session-filter-enable'));
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [],
      isFullSelection: false,
    });

    await screen.findAllByLabelText(/26-10-23_0/);
    clickSession('data/26-10-23_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [keyA],
      isFullSelection: false,
    });
  });

  it('跨 tub 撞名会话可分别勾选：两行 aria-label 含各自 tub 名，互不冲突', async () => {
    await renderEnabled();
    clickSession('data/26-10-23_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [keyA],
      isFullSelection: false,
    });
    clickSession('tub_1_26-10-23/26-10-23_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [keyA, keyB],
      isFullSelection: true,
    });
  });

  it('全选：回调 isFullSelection=true（TrainerPage 据此省略 session_filter）', async () => {
    await renderEnabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'trainer.sessionFilterSelectAll' })
    );
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [keyA, keyB],
      isFullSelection: true,
    });
  });

  it('清空：回调 selected=[] 且 isFullSelection=false，并提示至少勾一段', async () => {
    await renderEnabled({ selected: [keyA, keyB] });
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

  it('取消单个勾选从选中集中移除该复合键（另一个 tub 的同名会话不受影响）', async () => {
    await renderEnabled({ selected: [keyA, keyB] });
    clickSession('data/26-10-23_0');
    expect(onChangeSpy).toHaveBeenLastCalledWith({
      enabled: true,
      selected: [keyB],
      isFullSelection: false,
    });
  });
});

describe('SessionFilterPicker 异常提示', () => {
  it('加载失败：温和提示，不抛出，并上报空列表', async () => {
    listFamilyTubSessionsMock.mockRejectedValue(new Error('network down'));
    render(<Harness initial={{ enabled: true }} />);
    await waitFor(() =>
      expect(
        screen.getByText('trainer.sessionFilterLoadFailed')
      ).toBeInTheDocument()
    );
    expect(onSessionsChangeSpy).toHaveBeenLastCalledWith('./data', []);
  });

  it('无会话：提示无可筛选会话', async () => {
    listFamilyTubSessionsMock.mockResolvedValue({
      status: true,
      path: '/x',
      family_root: '/',
      sessions: [],
    });
    render(<Harness initial={{ enabled: true }} />);
    await waitFor(() =>
      expect(screen.getByText('trainer.sessionFilterEmpty')).toBeInTheDocument()
    );
  });

  it('会话列表变化后自动剔除已不存在的勾选（按复合键匹配）', async () => {
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
