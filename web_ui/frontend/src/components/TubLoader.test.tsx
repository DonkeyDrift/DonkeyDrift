import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TubLoader } from './TubLoader';
import { useStore } from '../store/useStore';
import { loadTub, listChildTubs } from '../services/api';

// 子 tub 发现（方案 A）：手动输入的目录不是有效 tub（或全删）时，
// 加载失败后列出该目录下的子 tub，点击即按同款流程加载。

vi.mock('../services/api', () => ({
  loadTub: vi.fn(),
  listChildTubs: vi.fn(),
}));

const childTubs = [
  {
    name: 'tub_7_26-10-20',
    path: '/mycar/data/tub_7_26-10-20',
    record_count: 5930,
    total_physical: 5930,
    deleted_count: 0,
    last_modified_ms: Date.parse('2026-10-20T12:00:00Z'),
  },
];

const loadedPayload = {
  status: true,
  path: '/mycar/data/tub_7_26-10-20',
  record_count: 5930,
  total_physical_records: 5930,
  records: [{ _index: 0 }],
  fields: ['cam/image_array'],
  deleted_indexes: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    tubPath: '',
    records: [],
    totalRecords: 0,
    fields: [],
    config: { DRIVE_LOOP_HZ: '60' },
    isLoading: false,
    error: null,
  });
  vi.mocked(loadTub).mockRejectedValue(new Error('not a tub') as never);
});

describe('TubLoader child tub suggestion', () => {
  it('shows clickable child tubs after a failed manual load and loads the selected one', async () => {
    vi.mocked(listChildTubs).mockResolvedValue({
      status: true,
      path: '/mycar/data',
      child_tubs: childTubs,
    } as never);
    render(<TubLoader />);

    const input = screen.getByLabelText('Tub 路径输入框');
    fireEvent.change(input, { target: { value: '/mycar/data' } });
    fireEvent.click(screen.getByRole('button', { name: '加载 Tub' }));

    // 加载失败后列出子 tub，点击即加载该子 tub
    const entry = await screen.findByText('tub_7_26-10-20');
    vi.mocked(loadTub).mockResolvedValue(loadedPayload as never);
    fireEvent.click(entry);

    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledWith('/mycar/data/tub_7_26-10-20');
    });
    await waitFor(() => {
      expect(useStore.getState().tubPath).toBe('/mycar/data/tub_7_26-10-20');
    });
    // 加载成功后引导列表清空
    expect(screen.queryByText('tub_7_26-10-20')).not.toBeInTheDocument();
  });

  it('shows only the original error when no child tub exists', async () => {
    vi.mocked(listChildTubs).mockResolvedValue({
      status: true,
      path: '/mycar/data',
      child_tubs: [],
    } as never);
    render(<TubLoader />);

    fireEvent.change(screen.getByLabelText('Tub 路径输入框'), { target: { value: '/mycar/data' } });
    fireEvent.click(screen.getByRole('button', { name: '加载 Tub' }));

    await waitFor(() => {
      expect(listChildTubs).toHaveBeenCalledWith('/mycar/data');
    });
    expect(screen.queryByText(/该目录下发现以下子 Tub/)).not.toBeInTheDocument();
  });

  it('clears the suggestion list when the input changes', async () => {
    vi.mocked(listChildTubs).mockResolvedValue({
      status: true,
      path: '/mycar/data',
      child_tubs: childTubs,
    } as never);
    render(<TubLoader />);

    fireEvent.change(screen.getByLabelText('Tub 路径输入框'), { target: { value: '/mycar/data' } });
    fireEvent.click(screen.getByRole('button', { name: '加载 Tub' }));
    await screen.findByText('tub_7_26-10-20');

    fireEvent.change(screen.getByLabelText('Tub 路径输入框'), { target: { value: '/other' } });
    expect(screen.queryByText('tub_7_26-10-20')).not.toBeInTheDocument();
  });
});
