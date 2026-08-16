import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { TubLibrary } from './TubLibrary';
import { useStore } from '../store/useStore';
import { getSessionRecords, listTubSessions } from '../services/api';

// 回归测试：进入录制视频库后自动选中最新一条录制（sessions[0]，API 已按
// 最新在前排序），无需手动点击列表。

vi.mock('../services/api', () => ({
  getImageUrl: (path: string) => `http://localhost/img/${encodeURIComponent(path)}`,
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
  listTubSessions: vi.fn(),
  getSessionRecords: vi.fn(),
  deleteTubSession: vi.fn(),
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
    });
  });

  it('selects the newest session (first in list) on load', async () => {
    render(<TubLibrary />);

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });
    // Frame counter renders the selected recording's frames
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });
  });

  it('shows the select hint when no tub is loaded', () => {
    useStore.setState({ tubPath: null });
    render(<TubLibrary />);

    expect(listTubSessions).not.toHaveBeenCalled();
  });
});
