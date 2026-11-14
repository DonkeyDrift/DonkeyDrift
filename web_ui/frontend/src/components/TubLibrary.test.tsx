import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TubLibrary } from './TubLibrary';
import { useStore } from '../store/useStore';
import { getSessionRecords, listFamilyTubSessions, downloadTubSession, deleteTubSession, getImageUrl, loadTub } from '../services/api';

// 回归测试：进入录制视频库后自动选中最新一条录制（sessions[0]，API 已按
// 最新在前排序），无需手动点击列表。

vi.mock('../services/api', () => ({
  getImageUrl: vi.fn((path: string) => `http://localhost/img/${encodeURIComponent(path)}`),
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
  listFamilyTubSessions: vi.fn(),
  getSessionRecords: vi.fn(),
  deleteTubSession: vi.fn(),
  downloadTubSession: vi.fn(),
  loadTub: vi.fn(),
}));

// 家族聚合视图（方案 B）：会话带 tub_path/tub_name，默认全部在当前工作 tub
const sessions = [
  {
    session_id: '26-08-16_1',
    record_count: 2,
    first_index: 3,
    last_index: 4,
    start_time_ms: Date.parse('2026-08-16T11:00:00Z'),
    end_time_ms: Date.parse('2026-08-16T11:00:02Z'),
    tub_path: '/tmp/tub',
    tub_name: 'tub',
  },
  {
    session_id: '26-08-16_0',
    record_count: 3,
    first_index: 0,
    last_index: 2,
    start_time_ms: Date.parse('2026-08-16T10:00:00Z'),
    end_time_ms: Date.parse('2026-08-16T10:00:03Z'),
    tub_path: '/tmp/tub',
    tub_name: 'tub',
  },
];

const familyResponse = {
  status: true,
  path: '/tmp/tub',
  family_root: '/tmp',
  sessions,
};

const familyRecords = {
  status: true,
  path: '/tmp/tub',
  records: [
    { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
    { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
  ],
};

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
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
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

    expect(listFamilyTubSessions).not.toHaveBeenCalled();
  });
});

describe('TubLibrary pin to top', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
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
    // Persisted per tub path（家族视图置顶存复合键 tub_path::session_id）
    expect(localStorage.getItem('tubLibrary.pinned./tmp/tub')).toBe(JSON.stringify(['/tmp/tub::26-08-16_0']));

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
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
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

// ---------------------------------------------------------------------------
// 子 tub 发现（方案 A）：tubPath 已加载但 sessions 为空（如 509 条记录全部被
// 软删）时，/tub/sessions 附带 child_tubs 字段，列表区渲染引导面板；
// 点击条目 loadTub 子 tub 并 setTub 切换全局 tubPath。
// ---------------------------------------------------------------------------
describe('TubLibrary child tub guidance', () => {
  const childTubs = [
    {
      name: 'tub_7_26-10-20',
      path: '/tmp/tub/tub_7_26-10-20',
      record_count: 5930,
      total_physical: 5930,
      deleted_count: 0,
      last_modified_ms: Date.parse('2026-10-20T12:00:00Z'),
    },
    {
      name: 'tub_6_26-10-20',
      path: '/tmp/tub/tub_6_26-10-20',
      record_count: 1793,
      total_physical: 1793,
      deleted_count: 0,
      last_modified_ms: Date.parse('2026-10-20T11:00:00Z'),
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [],
      child_tubs: childTubs,
    });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('renders the guidance panel and switches to the child tub on click', async () => {
    vi.mocked(loadTub).mockResolvedValue({
      status: true,
      path: '/tmp/tub/tub_7_26-10-20',
      record_count: 5930,
      total_physical_records: 5930,
      records: [],
      fields: [],
      deleted_indexes: [],
    } as never);
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    // 引导标题 + 两个子 tub 条目（目录名 + 有效帧数）
    expect(await screen.findByText(/当前 Tub 没有有效录制/)).toBeInTheDocument();
    const entry = screen.getByRole('button', { name: '切换到子 Tub tub_7_26-10-20' });
    expect(entry).toHaveTextContent('5930 帧');
    expect(screen.getByRole('button', { name: '切换到子 Tub tub_6_26-10-20' })).toBeInTheDocument();

    fireEvent.click(entry);
    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledWith('/tmp/tub/tub_7_26-10-20');
    });
    // setTub 切换全局 tubPath → 录制库按新目录重拉
    await waitFor(() => {
      expect(useStore.getState().tubPath).toBe('/tmp/tub/tub_7_26-10-20');
    });
  });

  it('keeps the plain empty hint when there are no child tubs either', async () => {
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [],
    });
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    expect(await screen.findByText('暂无录制')).toBeInTheDocument();
    expect(screen.queryByText(/当前 Tub 没有有效录制/)).not.toBeInTheDocument();
  });
});

// 回归测试（总帧数口径统一）：左侧录制列表头展示「共 N 条录制 · 合计有效帧数」，
// 合计为所有 sessions 的 record_count 之和（有效帧，迭代跳过软删除），
// 与 Tub 编辑器的有效帧数口径对齐。
describe('TubLibrary recordings summary total frames', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [
        { ...sessions[0], record_count: 7 },
        { ...sessions[1], record_count: 4 },
      ],
    });
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('renders the summed record_count of all recordings in the list header', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    // 两条录制各自的 record_count（7 + 4）合计为 11 帧
    await waitFor(() => {
      expect(screen.getByText('共 2 条录制 · 11 帧')).toBeInTheDocument();
    });
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
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
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

// 回归测试（统一流程大页面 #178）：TM 并入 FlowPage 后经 /tub 深链进入，
// 播放控制不再按「pathname === '/'」判断，而是按「tub-manager section 是否在
// 视口内（active）」。在 /tub 下按空格应在 TM 区内切换播放/暂停，而不是让页面滚动。
describe('TubLibrary spacebar playback control', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('toggles playback when space is pressed while the Tub Manager section is active', async () => {
    render(
      <MemoryRouter initialEntries={['/tub']}>
        <TubLibrary active />
      </MemoryRouter>,
    );

    // Wait for the selected session's records to load before pressing space
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { code: 'Space' });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '停止播放' })).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { code: 'Space' });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '开始播放' })).toBeInTheDocument();
    });
  });

  it('does not toggle playback when the Tub Manager section is not active', async () => {
    render(
      <MemoryRouter initialEntries={['/tub']}>
        <TubLibrary />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { code: 'Space' });
    // Still showing the start label — space did not toggle playback
    expect(screen.getByRole('button', { name: '开始播放' })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 刷新（缓存治理）：录制库 section 常驻挂载，录制列表与选中帧只在 tubPath
// 变化/删除/AI 清理后拉取，Drive 页新录制的场次不会自动出现，新老数据混在
// 一起。手动「刷新」按钮清空浏览器暂存数据后全量重拉（列表 + 选中帧 + 全局
// tub + 图片 URL 换纪元绕过 HTTP 缓存）；自动刷新在激活期间每 30s 静默轮询，
// 播放中与后台标签页暂停。
// ---------------------------------------------------------------------------
const extraSession = {
  session_id: '26-08-16_2',
  record_count: 5,
  first_index: 5,
  last_index: 9,
  start_time_ms: Date.parse('2026-08-16T12:00:00Z'),
  end_time_ms: Date.parse('2026-08-16T12:00:05Z'),
  tub_path: '/tmp/tub',
  tub_name: 'tub',
};

describe('TubLibrary manual refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 墙钟播放 describe 泄漏的 Image/rAF stub 会改变本组用例的绘制行为，先恢复
    vi.unstubAllGlobals();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue(familyRecords);
    vi.mocked(loadTub).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      record_count: 0,
      total_physical_records: 0,
      records: [],
      fields: [],
      deleted_indexes: [],
    } as never);
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('reloads the list, the selected clip and the global tub when clicked', async () => {
    render(
      <MemoryRouter>
        <TubLibrary />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });
    expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);
    expect(getSessionRecords).toHaveBeenCalledTimes(1);

    // 新录制出现后点「刷新」：列表、选中帧与全局 tub 全部重拉
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [...sessions, extraSession],
    });
    fireEvent.click(screen.getByRole('button', { name: '刷新录制库（清空浏览器暂存的数据）' }));

    await waitFor(() => {
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledTimes(2);
    });
    // 选中录制未变，帧按同一 session 重拉
    expect(getSessionRecords).toHaveBeenLastCalledWith('/tmp/tub', '26-08-16_1');
    // 全局 tub 同步重载（编辑器等面板拿到新数据）
    expect(loadTub).toHaveBeenCalledWith('/tmp/tub');
    // 列表头合计出现新录制：2+3+5 = 10 帧
    await waitFor(() => {
      expect(screen.getByText('共 3 条录制 · 10 帧')).toBeInTheDocument();
    });
    // setTub 清空 activeSession 后由刷新流程恢复，编辑器联动不丢
    await waitFor(() => {
      expect(useStore.getState().activeSessionId).toBe('26-08-16_1');
    });
  });

  it('auto-selects the new newest recording when the selection disappeared', async () => {
    render(
      <MemoryRouter>
        <TubLibrary />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    // 原选中录制被删，只剩新录制 → 刷新后自动选中新的最新一条
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [extraSession],
    });
    vi.mocked(getSessionRecords).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      records: [
        { _index: 5, _timestamp_ms: 3, _session_id: '26-08-16_2', 'cam/image_array': 'cam_5.jpg' },
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: '刷新录制库（清空浏览器暂存的数据）' }));

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_2');
    });
  });
});

describe('TubLibrary auto refresh', () => {
  const freshRecords = [
    { _index: 3, _timestamp_ms: 1, _session_id: '26-08-16_1', 'cam/image_array': 'cam_3.jpg' },
    { _index: 4, _timestamp_ms: 2, _session_id: '26-08-16_1', 'cam/image_array': 'cam_4.jpg' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    // 墙钟播放 describe 泄漏的 Image/rAF stub 会改变本组用例的绘制行为，先恢复
    vi.unstubAllGlobals();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      records: freshRecords,
    });
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('polls the session list every 30s while active and picks up a new recording', async () => {
    vi.useFakeTimers();
    try {
      render(
        <MemoryRouter>
          <TubLibrary active />
        </MemoryRouter>,
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);

      vi.mocked(listFamilyTubSessions).mockResolvedValue({
        status: true,
        path: '/tmp/tub',
        family_root: '/tmp',
        sessions: [...sessions, extraSession],
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(2);
      // 新录制出现在列表头合计里（2+3+5 = 10 帧）；选中录制帧数未变，不重拉帧
      expect(screen.getByText('共 3 条录制 · 10 帧')).toBeInTheDocument();
      expect(getSessionRecords).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not poll while the section is inactive', async () => {
    vi.useFakeTimers();
    try {
      render(
        <MemoryRouter>
          <TubLibrary />
        </MemoryRouter>,
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(120_000);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('pauses polling during playback and reloads a grown clip after it', async () => {
    vi.useFakeTimers();
    try {
      render(
        <MemoryRouter>
          <TubLibrary active />
        </MemoryRouter>,
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole('button', { name: '开始播放' }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(90_000);
      });
      // 播放中不轮询，避免打断回放
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole('button', { name: '停止播放' }));
      // 选中录制新增了帧 → 播放结束后 30s 内的轮询静默重拉其帧
      vi.mocked(listFamilyTubSessions).mockResolvedValue({
        status: true,
        path: '/tmp/tub',
        family_root: '/tmp',
        sessions: [{ ...sessions[0], record_count: 4 }, sessions[1]],
      });
      vi.mocked(getSessionRecords).mockResolvedValue({
        status: true,
        path: '/tmp/tub',
        records: [
          ...freshRecords,
          { _index: 5, _timestamp_ms: 3, _session_id: '26-08-16_1', 'cam/image_array': 'cam_5.jpg' },
          { _index: 6, _timestamp_ms: 4, _session_id: '26-08-16_1', 'cam/image_array': 'cam_6.jpg' },
        ],
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(2);
      // 帧重拉后帧计数与量程更新（1 / 4）
      expect(screen.getByText(/1 \/ 4/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// 家族聚合视图（方案 B）：录制库列出「当前工作 tub 所属家族」的全部录制会话，
// 每条带 tub_path/tub_name。_session_id 跨 tub 会撞名（如 tub_6/tub_7 都是
// 26-10-20_0），选中/置顶用 (tub_path, session_id) 复合键；选中异 tub 会话
// 先 loadTub+setTub 切全局工作 tub，列表重拉后选中目标（而非家族最新）。
// ---------------------------------------------------------------------------
describe('TubLibrary family aggregation', () => {
  const sessionA = {
    session_id: '26-10-20_1',
    record_count: 2,
    first_index: 0,
    last_index: 1,
    start_time_ms: Date.parse('2026-10-20T12:00:00Z'),
    end_time_ms: Date.parse('2026-10-20T12:00:02Z'),
    tub_path: '/tmp/tub',
    tub_name: 'tub',
  };
  // 异 tub 会话：_session_id 与真实场景一样可能撞名，时间更早（排在后面）
  const sessionB = {
    session_id: '26-10-20_0',
    record_count: 3,
    first_index: 0,
    last_index: 2,
    start_time_ms: Date.parse('2026-10-20T10:00:00Z'),
    end_time_ms: Date.parse('2026-10-20T10:00:03Z'),
    tub_path: '/tmp/tub_2',
    tub_name: 'tub_2',
  };
  const mixedFamily = {
    status: true,
    path: '/tmp/tub',
    family_root: '/tmp',
    sessions: [sessionA, sessionB],
  };
  const labelA = fmt(sessionA.start_time_ms);
  const labelB = fmt(sessionB.start_time_ms);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(mixedFamily);
    vi.mocked(getSessionRecords).mockImplementation(async (tubPath: string, sessionId: string) => ({
      status: true,
      path: tubPath,
      records: tubPath === '/tmp/tub_2'
        ? [0, 1, 2].map((i) => ({ _index: i, _timestamp_ms: i + 1, _session_id: sessionId, 'cam/image_array': `cam_b${i}.jpg` }))
        : familyRecords.records,
    }));
    vi.mocked(loadTub).mockResolvedValue({
      status: true,
      path: '/tmp/tub_2',
      record_count: 0,
      total_physical_records: 0,
      records: [],
      fields: [],
      deleted_indexes: [],
    } as never);
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
    });
  });

  it('renders a tub_name badge on rows so same-day cross-tub sessions are distinguishable', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText(labelA)).toBeInTheDocument();
    });
    expect(screen.getByText(labelB)).toBeInTheDocument();
    expect(screen.getByText('tub')).toBeInTheDocument();
    expect(screen.getByText('tub_2')).toBeInTheDocument();
  });

  it('selecting another family tub session switches the working tub, then selects the target', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    // 挂载自动选中家族最新（同 tub 会话 A）
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-20_1');
    });

    const rowB = screen.getByText(labelB).closest('button');
    expect(rowB).not.toBeNull();
    fireEvent.click(rowB as HTMLButtonElement);

    // 异 tub 选中：先 loadTub + setTub 切全局工作 tub
    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledWith('/tmp/tub_2');
    });
    await waitFor(() => {
      expect(useStore.getState().tubPath).toBe('/tmp/tub_2');
    });
    // 列表按新 tub 重拉后选中的是点击的目标 B，而不是家族最新 A；
    // 切换只发生一次（refreshSessions 的 pending 命中后直接选中，不再重复 loadTub）
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub_2', '26-10-20_0');
    });
    expect(loadTub).toHaveBeenCalledTimes(1);
    // 切换瞬间旧选中 A 配新 tub 路径的错拉被守卫挡住
    expect(getSessionRecords).not.toHaveBeenCalledWith('/tmp/tub_2', '26-10-20_1');
    // 目标会话的帧已加载（1 / 3）
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 3/)).toBeInTheDocument();
    });
  });

  it('selecting a same-tub session does not touch the global working tub', async () => {
    // 同 tub 的另一条会话 C（更早）
    const sessionC = {
      ...sessionB,
      session_id: '26-10-20_2',
      start_time_ms: Date.parse('2026-10-20T11:00:00Z'),
      end_time_ms: Date.parse('2026-10-20T11:00:01Z'),
      tub_path: '/tmp/tub',
      tub_name: 'tub',
    };
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [sessionA, sessionC],
    });
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-20_1');
    });

    const rowC = screen.getByText(fmt(sessionC.start_time_ms)).closest('button');
    fireEvent.click(rowC as HTMLButtonElement);

    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-20_2');
    });
    // 同 tub 选中：不触发 loadTub/setTub，全局工作 tub 不变
    expect(loadTub).not.toHaveBeenCalled();
    expect(useStore.getState().tubPath).toBe('/tmp/tub');
  });
});

// ---------------------------------------------------------------------------
// 多选会话筛选（家族视图，跨 tub 版）：ctrl/⌘ 切换、shift 范围选、行首
// checkbox（等价 ctrl+点击）——多选手势一律不切换全局 tub；集合按 tub 去重
// 判定编辑器挂接（单 tub=全局 → 挂会话作用域，必要时先切 tub；跨 tub → 回退
// 整 tub 视图）；合并/批量删除按 start_time_ms 升序；合并帧带 __tubPath 标按
// 各会话自己的 tub 取图。
// ---------------------------------------------------------------------------
describe('TubLibrary multi-select session filter', () => {
  // 每条会话的可区分帧（合并顺序断言用）
  const recordsFor: Record<string, { _index: number; _timestamp_ms: number; _session_id: string; 'cam/image_array': string }[]> = {
    '26-08-16_1': [0, 1].map((i) => ({ _index: i + 3, _timestamp_ms: i + 1, _session_id: '26-08-16_1', 'cam/image_array': `cam_a${i}.jpg` })),
    '26-08-16_0': [0, 1, 2].map((i) => ({ _index: i, _timestamp_ms: i + 3, _session_id: '26-08-16_0', 'cam/image_array': `cam_b${i}.jpg` })),
    '26-08-16_2': [0, 1, 2, 3, 4].map((i) => ({ _index: i + 5, _timestamp_ms: i + 6, _session_id: '26-08-16_2', 'cam/image_array': `cam_c${i}.jpg` })),
    '26-10-20_1': [0, 1].map((i) => ({ _index: i, _timestamp_ms: i + 1, _session_id: '26-10-20_1', 'cam/image_array': `cam_x${i}.jpg` })),
    '26-10-20_0': [0, 1, 2].map((i) => ({ _index: i, _timestamp_ms: i + 2, _session_id: '26-10-20_0', 'cam/image_array': `cam_d${i}.jpg` })),
    '26-10-21_2': [0, 1].map((i) => ({ _index: i, _timestamp_ms: i + 1, _session_id: '26-10-21_2', 'cam/image_array': `cam_g${i}.jpg` })),
    '26-10-21_1': [0, 1].map((i) => ({ _index: i, _timestamp_ms: i + 2, _session_id: '26-10-21_1', 'cam/image_array': `cam_f${i}.jpg` })),
    '26-10-21_0': [0, 1].map((i) => ({ _index: i, _timestamp_ms: i + 3, _session_id: '26-10-21_0', 'cam/image_array': `cam_e${i}.jpg` })),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
    vi.mocked(listFamilyTubSessions).mockResolvedValue(familyResponse);
    vi.mocked(getSessionRecords).mockImplementation(async (_tubPath: string, sessionId: string) => ({
      status: true,
      path: '/tmp/tub',
      records: recordsFor[sessionId] ?? [],
    }));
    vi.mocked(deleteTubSession).mockResolvedValue({
      status: true,
      message: 'ok',
      deleted_count: 2,
      record_count: 0,
      deleted_indexes: [],
    } as never);
    vi.mocked(loadTub).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      record_count: 0,
      total_physical_records: 0,
      records: [],
      fields: [],
      deleted_indexes: [],
    } as never);
    useStore.setState({
      tubPath: '/tmp/tub',
      fields: ['cam/image_array', 'user/angle'],
      config: { DRIVE_LOOP_HZ: '60' } as never,
      activeSessionId: null,
      activeSessionRecords: [],
      activeSessionIds: [],
    });
  });

  const rowButton = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement;

  it('ctrl+click adds a session to the multi-selection and merges records in start_time order', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    // 挂载自动选中最新一条（锚点 = 26-08-16_1，单选）
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    fireEvent.click(rowButton(oldestLabel), { ctrlKey: true });

    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_0', '26-08-16_1']);
    });
    const state = useStore.getState();
    // 锚点 = 最后点击行；同 tub 多选挂接编辑器作用域（非跨 tub，可编辑）
    expect(state.activeSessionId).toBe('26-08-16_0');
    expect(state.activeSessionCrossTub).toBe(false);
    // 合并 records 按 start_time_ms 升序（10:00 在前），与点击先后无关
    expect(state.activeSessionRecords.map((r) => r['cam/image_array'])).toEqual([
      'cam_b0.jpg', 'cam_b1.jpg', 'cam_b2.jpg', 'cam_a0.jpg', 'cam_a1.jpg',
    ]);
    // 两行均多选态：行首 checkbox aria-checked；锚点行主高亮、成员行次高亮
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toHaveAttribute('aria-checked', 'true');
    expect(checkboxes[1]).toHaveAttribute('aria-checked', 'true');
    expect(rowButton(newestLabel).className).toContain('border-cyan-500/40');
    expect(rowButton(oldestLabel).className).toContain('border-cyan-400');
    // 操作条显示段数与合计帧数（2 + 3 = 5）
    expect(screen.getByText('已选 2 段 · 共 5 帧')).toBeInTheDocument();
  });

  it('shift+click selects the closed range from the anchor row in list order', async () => {
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [sessions[0], extraSession, sessions[1]],
    });
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    // 锚点（最新）shift+点击最旧 → 闭区间全选（3 段，time-asc：_0 < _1 < _2）
    fireEvent.click(rowButton(oldestLabel), { shiftKey: true });
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_0', '26-08-16_1', '26-08-16_2']);
    });
    expect(useStore.getState().activeSessionId).toBe('26-08-16_0');
    let checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.map((c) => c.getAttribute('aria-checked'))).toEqual(['true', 'true', 'true']);

    // 反向范围：普通点击中间行（锚点重置），shift+点击最新 → 仅 {最新, 中间}
    fireEvent.click(rowButton(fmt(extraSession.start_time_ms)));
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_2']);
    });
    fireEvent.click(rowButton(newestLabel), { shiftKey: true });
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_1', '26-08-16_2']);
    });
    checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.map((c) => c.getAttribute('aria-checked'))).toEqual(['true', 'true', 'false']);
  });

  it('row checkbox toggles like ctrl+click and removes the session on second click', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    // 勾选旧行 → 加入集合，锚点移到旧行
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_0', '26-08-16_1']);
      expect(useStore.getState().activeSessionId).toBe('26-08-16_0');
    });

    // 再次勾选 → 移出集合；移出的是锚点行，锚点回最近添加的剩余成员（新行）
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_1']);
      expect(useStore.getState().activeSessionId).toBe('26-08-16_1');
    });
  });

  it('ctrl+clicking the only selected row clears to empty and suppresses auto re-select', async () => {
    vi.useFakeTimers();
    try {
      render(<MemoryRouter><TubLibrary active /></MemoryRouter>);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getSessionRecords).toHaveBeenCalledTimes(1);

      // ctrl+点击唯一选中行 → 取消到空集合：编辑器回退整 tub 视图
      fireEvent.click(rowButton(newestLabel), { ctrlKey: true });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(useStore.getState().activeSessionId).toBeNull();
      expect(useStore.getState().activeSessionRecords).toEqual([]);

      // 30s 轮询仍会重拉列表，但不再自动选中（getSessionRecords 不新增调用）
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(2);
      expect(getSessionRecords).toHaveBeenCalledTimes(1);
      expect(useStore.getState().activeSessionId).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('ctrl+clicking a cross-tub row joins the set without switching the working tub', async () => {
    const sessionA = {
      session_id: '26-10-20_1',
      record_count: 2,
      first_index: 0,
      last_index: 1,
      start_time_ms: Date.parse('2026-10-20T12:00:00Z'),
      end_time_ms: Date.parse('2026-10-20T12:00:02Z'),
      tub_path: '/tmp/tub',
      tub_name: 'tub',
    };
    // 更早的异 tub 会话（10:00 < 12:00，合并后排前面）
    const sessionB = {
      session_id: '26-10-20_0',
      record_count: 3,
      first_index: 0,
      last_index: 2,
      start_time_ms: Date.parse('2026-10-20T10:00:00Z'),
      end_time_ms: Date.parse('2026-10-20T10:00:03Z'),
      tub_path: '/tmp/tub_2',
      tub_name: 'tub_2',
    };
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [sessionA, sessionB],
    });
    vi.mocked(getSessionRecords).mockImplementation(async (tubPath: string, sessionId: string) => ({
      status: true,
      path: tubPath,
      records: recordsFor[sessionId] ?? [],
    }));
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-20_1');
    });

    fireEvent.click(rowButton(fmt(sessionB.start_time_ms)), { ctrlKey: true });

    // 跨 tub 勾选：正常加入集合（UI 态：两行 checkbox 勾选 + 操作条），
    // 多选手势不切换全局 tub、不调 loadTub
    await waitFor(() => {
      expect(screen.getByText('已选 2 段 · 共 5 帧')).toBeInTheDocument();
    });
    expect(loadTub).not.toHaveBeenCalled();
    expect(useStore.getState().tubPath).toBe('/tmp/tub');
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.map((c) => c.getAttribute('aria-checked'))).toEqual(['true', 'true']);
    // 跨 tub 选择：挂接编辑器只读合并视图（锚点=最后点击行 B；ids 按 time-asc），操作条提示
    const state = useStore.getState();
    expect(state.activeSessionId).toBe('26-10-20_0');
    expect(state.activeSessionCrossTub).toBe(true);
    expect(state.activeSessionIds).toEqual(['26-10-20_0', '26-10-20_1']);
    // 合并 records 为两 tub 之和（B 3 帧 + A 2 帧 = 5 帧，time-asc）
    expect(state.activeSessionRecords.map((r) => r['cam/image_array'])).toEqual([
      'cam_d0.jpg', 'cam_d1.jpg', 'cam_d2.jpg', 'cam_x0.jpg', 'cam_x1.jpg',
    ]);
    expect(screen.getByText('跨 Tub 选择：编辑器为只读合并视图，编辑帧请切回单个 Tub')).toBeInTheDocument();
    // 播放器仍播合并序列（time-asc：B 3 帧 + A 2 帧 = 5 帧）
    await waitFor(() => {
      expect(screen.getByText(/1 \/ 5/)).toBeInTheDocument();
    });
    // 合并帧按各自 tub 取图：__tubPath 标传到 getImageUrl（缓存 key=URL，URL 含 tubPath 不串图）
    await waitFor(() => {
      expect(getImageUrl).toHaveBeenCalledWith('cam_d0.jpg', '/tmp/tub_2');
      expect(getImageUrl).toHaveBeenCalledWith('cam_x0.jpg', '/tmp/tub');
    });
  });

  it('single-tub multi-selection on another tub switches the working tub and keeps the set', async () => {
    const sessionF = {
      session_id: '26-10-21_2',
      record_count: 2,
      first_index: 0,
      last_index: 1,
      start_time_ms: Date.parse('2026-10-21T12:00:00Z'),
      end_time_ms: Date.parse('2026-10-21T12:00:02Z'),
      tub_path: '/tmp/tub',
      tub_name: 'tub',
    };
    const sessionG = {
      session_id: '26-10-21_1',
      record_count: 2,
      first_index: 0,
      last_index: 1,
      start_time_ms: Date.parse('2026-10-21T11:00:00Z'),
      end_time_ms: Date.parse('2026-10-21T11:00:01Z'),
      tub_path: '/tmp/tub_2',
      tub_name: 'tub_2',
    };
    const sessionH = {
      session_id: '26-10-21_0',
      record_count: 2,
      first_index: 0,
      last_index: 1,
      start_time_ms: Date.parse('2026-10-21T10:00:00Z'),
      end_time_ms: Date.parse('2026-10-21T10:00:01Z'),
      tub_path: '/tmp/tub_2',
      tub_name: 'tub_2',
    };
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [sessionF, sessionG, sessionH],
    });
    vi.mocked(getSessionRecords).mockImplementation(async (tubPath: string, sessionId: string) => ({
      status: true,
      path: tubPath,
      records: recordsFor[sessionId] ?? [],
    }));
    vi.mocked(loadTub).mockResolvedValue({
      status: true,
      path: '/tmp/tub_2',
      record_count: 0,
      total_physical_records: 0,
      records: [],
      fields: [],
      deleted_indexes: [],
    } as never);
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-21_2');
    });

    // 先取消自动选中的 F，再勾选同属 /tmp/tub_2 的 G、H → 收敛单 tub 非全局 tub
    fireEvent.click(rowButton(fmt(sessionF.start_time_ms)), { ctrlKey: true });
    await act(async () => {});
    expect(useStore.getState().activeSessionId).toBeNull();
    fireEvent.click(rowButton(fmt(sessionG.start_time_ms)), { ctrlKey: true });
    fireEvent.click(rowButton(fmt(sessionH.start_time_ms)), { ctrlKey: true });

    // 复用 pending 切换机制：切全局 tub 到 /tmp/tub_2，且集合被保留
    await waitFor(() => {
      expect(loadTub).toHaveBeenCalledWith('/tmp/tub_2');
    });
    await waitFor(() => {
      expect(useStore.getState().tubPath).toBe('/tmp/tub_2');
    });
    // 只切一次（切换落定后 effect 重跑挂接，不重复 loadTub）
    expect(loadTub).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-10-21_0', '26-10-21_1']);
    });
    const state = useStore.getState();
    expect(state.activeSessionId).toBe('26-10-21_0');
    expect(state.activeSessionRecords.map((r) => r['cam/image_array'])).toEqual([
      'cam_e0.jpg', 'cam_e1.jpg', 'cam_f0.jpg', 'cam_f1.jpg',
    ]);
  });

  it('batch delete removes every selected session in start_time order after confirmation', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    fireEvent.click(rowButton(oldestLabel), { ctrlKey: true });
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toHaveLength(2);
    });

    // 删除所选 → 批量确认弹窗（段数 + 总帧数）
    fireEvent.click(screen.getByRole('button', { name: '删除所选' }));
    expect(screen.getByText('删除所选 2 段录制？')).toBeInTheDocument();
    expect(screen.getByText(/将删除所选 2 段共 5 帧/)).toBeInTheDocument();

    // 确认后列表已无这些录制：刷新返回空 → 集合清空、不再自动选中
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [],
    });
    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(deleteTubSession).toHaveBeenCalledTimes(2);
    });
    // 按 start_time_ms 升序（旧 → 新）逐条删除，避免 manifest 并发写
    expect(deleteTubSession).toHaveBeenNthCalledWith(1, '/tmp/tub', '26-08-16_0');
    expect(deleteTubSession).toHaveBeenNthCalledWith(2, '/tmp/tub', '26-08-16_1');
    await waitFor(() => {
      expect(listFamilyTubSessions).toHaveBeenCalledTimes(2);
    });
    // 全局 tub 在被删集合里：单次 loadTub 同步；集合清空且无自动重选
    expect(loadTub).toHaveBeenCalledWith('/tmp/tub');
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual([]);
    });
    expect(useStore.getState().activeSessionId).toBeNull();
    expect(screen.queryByText(/已选 \d+ 段/)).not.toBeInTheDocument();
  });

  it('batch delete passes each session its own tub_path for cross-tub selections', async () => {
    const sessionA = {
      session_id: '26-10-20_1',
      record_count: 2,
      first_index: 0,
      last_index: 1,
      start_time_ms: Date.parse('2026-10-20T12:00:00Z'),
      end_time_ms: Date.parse('2026-10-20T12:00:02Z'),
      tub_path: '/tmp/tub',
      tub_name: 'tub',
    };
    const sessionB = {
      session_id: '26-10-20_0',
      record_count: 3,
      first_index: 0,
      last_index: 2,
      start_time_ms: Date.parse('2026-10-20T10:00:00Z'),
      end_time_ms: Date.parse('2026-10-20T10:00:03Z'),
      tub_path: '/tmp/tub_2',
      tub_name: 'tub_2',
    };
    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [sessionA, sessionB],
    });
    vi.mocked(getSessionRecords).mockImplementation(async (tubPath: string, sessionId: string) => ({
      status: true,
      path: tubPath,
      records: recordsFor[sessionId] ?? [],
    }));
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-10-20_1');
    });

    // 跨 tub 多选（time-asc：B 先 A 后）→ 批量删除各带各的 tub_path；
    // 编辑器挂接为只读合并视图（锚点=B）
    fireEvent.click(rowButton(fmt(sessionB.start_time_ms)), { ctrlKey: true });
    await waitFor(() => {
      expect(screen.getByText('已选 2 段 · 共 5 帧')).toBeInTheDocument();
    });
    expect(useStore.getState().activeSessionId).toBe('26-10-20_0');
    expect(useStore.getState().activeSessionCrossTub).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '删除所选' }));
    expect(screen.getByText('删除所选 2 段录制？')).toBeInTheDocument();

    vi.mocked(listFamilyTubSessions).mockResolvedValue({
      status: true,
      path: '/tmp/tub',
      family_root: '/tmp',
      sessions: [],
    });
    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(deleteTubSession).toHaveBeenCalledTimes(2);
    });
    expect(deleteTubSession).toHaveBeenNthCalledWith(1, '/tmp/tub_2', '26-10-20_0');
    expect(deleteTubSession).toHaveBeenNthCalledWith(2, '/tmp/tub', '26-10-20_1');
  });

  it('plain click collapses a multi-selection back to single selection', async () => {
    render(<MemoryRouter><TubLibrary /></MemoryRouter>);
    await waitFor(() => {
      expect(getSessionRecords).toHaveBeenCalledWith('/tmp/tub', '26-08-16_1');
    });

    fireEvent.click(rowButton(oldestLabel), { ctrlKey: true });
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toHaveLength(2);
    });

    // 普通点击（无修饰键）→ 折叠回单选：集合仅该行、records 单会话
    fireEvent.click(rowButton(newestLabel));
    await waitFor(() => {
      expect(useStore.getState().activeSessionIds).toEqual(['26-08-16_1']);
    });
    expect(useStore.getState().activeSessionId).toBe('26-08-16_1');
    expect(useStore.getState().activeSessionRecords.map((r) => r['cam/image_array'])).toEqual([
      'cam_a0.jpg', 'cam_a1.jpg',
    ]);
    expect(screen.queryByText(/已选 \d+ 段/)).not.toBeInTheDocument();
  });
});
