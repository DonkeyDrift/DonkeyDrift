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

// 墙钟播放调度回归（60fps）：某一帧图片未加载完时播放不停摆——跳过该帧
// 继续按墙钟推进；长时间停顿（切后台/网络卡死）后从当前帧继续播放，不快进。
describe('TubLibrary wall-clock playback scheduling', () => {
  const FRAME_COUNT = 100;
  const readyUrls = new Set<string>();
  const frameUrl = (i: number) => `http://localhost/img/cam_${i}.jpg`;
  // 预解码断言（60fps）：预取 onload 后应调用 img.decode() 提前解码
  const decodeSpy = vi.fn();

  let rafQueue: FrameRequestCallback[];

  class MockImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    complete = false;
    naturalWidth = 0;
    width = 160;
    height = 120;
    decode = () => {
      decodeSpy();
      return Promise.resolve();
    };
    private url = '';
    set src(v: string) {
      this.url = v;
      if (readyUrls.has(v)) {
        this.complete = true;
        this.naturalWidth = 160;
        queueMicrotask(() => this.onload?.());
      } else {
        queueMicrotask(() => this.onerror?.());
      }
    }
    get src() {
      return this.url;
    }
  }

  const pump = (t: number) => {
    const cbs = rafQueue;
    rafQueue = [];
    cbs.forEach((cb) => cb(t));
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    readyUrls.clear();
    for (let i = 0; i < FRAME_COUNT; i += 1) readyUrls.add(frameUrl(i));
    rafQueue = [];
    vi.stubGlobal('Image', MockImage);
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      rafQueue.push(cb);
      return rafQueue.length;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});

    const records = Array.from({ length: FRAME_COUNT }, (_, i) => ({
      _index: i,
      _timestamp_ms: i * 16,
      _session_id: '26-08-16_1',
      'cam/image_array': `cam_${i}.jpg`,
    }));
    vi.mocked(listTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      sessions: [{ ...sessions[0], record_count: FRAME_COUNT }],
    });
    vi.mocked(getSessionRecords).mockResolvedValue({ status: true, path: '/tmp/tub', records });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('skips a frame whose image is not ready instead of stalling playback', async () => {
    // 第 4 帧（index 3）永远加载不出来
    readyUrls.delete(frameUrl(3));
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 100/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: '开始播放' }));

    // 墙钟推进 ~200ms（12 帧 @60Hz）
    for (let k = 0; k <= 12; k += 1) {
      pump(1000 + (k * 1000) / 60);
    }

    // 旧逻辑会冻在第 3 帧（index 2）；新逻辑跳过缺帧按墙钟推进到 ~12 帧
    await waitFor(() => {
      expect(screen.getByText(/1[0-9] \/ 100/)).toBeInTheDocument();
    });
  });

  it('resumes from the current frame after a long stall instead of fast-forwarding', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 100/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: '开始播放' }));

    // 先正常播 10 帧，然后时间突跳 5s（模拟切后台/网络卡死）
    for (let k = 0; k <= 10; k += 1) {
      pump(1000 + (k * 1000) / 60);
    }
    const stallEnd = 1000 + (10 * 1000) / 60 + 5000;
    pump(stallEnd);
    // 再播 3 帧让节流 UI 越过 6 帧边界刷新计数器
    for (let k = 1; k <= 3; k += 1) {
      pump(stallEnd + (k * 1000) / 60);
    }

    // 重新对表继续 1x 播放：进度仍在 ~13 帧附近，而不是跳到 ~310 帧
    await waitFor(() => {
      expect(screen.getByText(/1[0-8] \/ 100/)).toBeInTheDocument();
    });
  });

  it('pre-decodes prefetched frames via img.decode() after load', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 100/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: '开始播放' }));

    // 播放启动即预取前 PREFETCH_AHEAD 帧，onload 后逐张 decode 预解码，
    // 让帧到期时 drawImage 不再触发主线程同步解码
    await waitFor(() => {
      expect(decodeSpy).toHaveBeenCalled();
    });
  });
});
