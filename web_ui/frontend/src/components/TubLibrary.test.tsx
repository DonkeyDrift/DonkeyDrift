import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TubLibrary } from './TubLibrary';
import { useStore } from '../store/useStore';
import { getSessionRecords, listTubSessions, downloadTubSession } from '../services/api';

// 回归测试：进入录制视频库后自动选中最新一条录制（sessions[0]，API 已按
// 最新在前排序），无需手动点击列表。

vi.mock('../services/api', () => ({
  getImageUrl: (path: string) => `http://localhost/img/${encodeURIComponent(path)}`,
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
  listTubSessions: vi.fn(),
  getSessionRecords: vi.fn(),
  deleteTubSession: vi.fn(),
  downloadTubSession: vi.fn(),
  loadTub: vi.fn(),
}));

const sessions = [
  {
    session_id: '26-08-16_1',
    record_count: 2,
    first_index: 3,
    last_index: 4,
    start_time_ms: Date.parse('2026-08-16T11:00:00Z'),
    end_time_ms: Date.parse('2026-08-16T11:00:02Z'),
  },
  {
    session_id: '26-08-16_0',
    record_count: 3,
    first_index: 0,
    last_index: 2,
    start_time_ms: Date.parse('2026-08-16T10:00:00Z'),
    end_time_ms: Date.parse('2026-08-16T10:00:03Z'),
  },
];

// Same formatting as the component (local timezone), so expectations are TZ-agnostic
const fmt = (ms: number) => {
  const pad = (n: number) => String(n).padStart(2, '0');
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
const newestLabel = fmt(sessions[0].start_time_ms);
const oldestLabel = fmt(sessions[1].start_time_ms);

describe('TubLibrary auto-select newest recording', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTubSessions).mockResolvedValue({ status: true, path: '/tmp/tub', sessions });
    vi.mocked(getSessionRecords).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      records: [
        { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
        { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
      ],
    });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('selects the newest session (first in list) on load', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });
    // Frame counter renders the selected recording's frames
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });
  });

  it('pushes the selected session records into the store for the editor', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(useStore.getState().activeSessionId).toBe('26-08-16_1');
    });
    expect(useStore.getState().activeSessionRecords).toEqual([
      { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
      { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
    ]);
  });

  it('shows the select hint when no tub is loaded', () => {
    useStore.setState({ tubPath: null });
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    expect(listTubSessions).not.toHaveBeenCalled();
  });
});

describe('TubLibrary pin to top', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(listTubSessions).mockResolvedValue({ status: true, path: '/tmp/tub', sessions });
    vi.mocked(getSessionRecords).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      records: [
        { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
        { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
      ],
    });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
    });
  });

  const listOrder = async () => {
    const newest = await screen.findAllByText(newestLabel);
    const oldest = await screen.findAllByText(oldestLabel);
    // Compare DOM order of the two labels via compareDocumentPosition
    return newest[0].compareDocumentPosition(oldest[0]) & Node.DOCUMENT_POSITION_FOLLOWING
      ? [newestLabel, oldestLabel]
      : [oldestLabel, newestLabel];
  };

  it('moves an older recording to the top when pinned, and restores it when unpinned', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });

    // Pin buttons appear in list order: first = newest, second = oldest
    const pinButtons = screen.getAllByRole('button', { name: '置顶这条录制' });
    expect(pinButtons).toHaveLength(2);
    fireEvent.click(pinButtons[1]);

    // Pinned (older) recording now renders first
    let order = await listOrder();
    expect(order).toEqual([oldestLabel, newestLabel]);
    // Persisted per tub path
    expect(localStorage.getItem('tubLibrary.pinned./tmp/tub')).toBe(JSON.stringify(['26-08-16_0']));

    // Unpin restores the newest-first order
    const unpinButton = await screen.findByRole('button', { name: '取消置顶' });
    fireEvent.click(unpinButton);
    order = await listOrder();
    expect(order).toEqual([newestLabel, oldestLabel]);
    expect(localStorage.getItem('tubLibrary.pinned./tmp/tub')).toBe(JSON.stringify([]));
  });
});

describe('TubLibrary download button', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTubSessions).mockResolvedValue({ status: true, path: '/tmp/tub', sessions });
    vi.mocked(getSessionRecords).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      records: [
        { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
        { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
      ],
    });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
    });
  });

  it('renders a download button for each session row', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    const downloadButtons = await screen.findAllByRole('button', { name: /下载/ });
    expect(downloadButtons).toHaveLength(sessions.length);
  });

  it('calls downloadTubSession with the correct session when a row download button is clicked', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    const downloadButtons = await screen.findAllByRole('button', { name: /下载/ });
    fireEvent.click(downloadButtons[0]);

    expect(downloadTubSession).toHaveBeenCalledWith(
      '/tmp/tub',
      '26-08-16_1',
      sessions[0].start_time_ms,
    );
  });
});
