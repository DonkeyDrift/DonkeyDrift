import '@testing-library/jest-dom/vitest';
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { LanguageProvider } from '@/i18n';
import {
  DriftCard,
  DRIFT_WEBRTC_ICE_GATHER_TIMEOUT_MS,
  DRIFT_WEBRTC_TRACK_TIMEOUT_MS,
} from './DriftCard';

vi.mock('../../services/api', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  API_URL: '/api',
}));

import { api } from '../../services/api';

const mockGet = api.get as unknown as Mock;
const mockPost = api.post as unknown as Mock;

/** GET /api/drift/state 快照工厂（含后端新增的 camera_running 字段）。 */
const makeState = (overrides: Record<string, unknown> = {}) => ({
  state: 'idle',
  calibration_ready: true,
  camera_running: false,
  beta_deg: null,
  pose: null,
  telemetry_count: 0,
  camera_fps: 0,
  frames_written: 0,
  events: [],
  config: {},
  ...overrides,
});

const mockState = (overrides: Record<string, unknown> = {}) => {
  mockGet.mockResolvedValue({ data: makeState(overrides) });
};

/** 可控 ICE gathering 状态机的 RTCPeerConnection 假实现。 */
class FakePeerConnection {
  static instances: FakePeerConnection[] = [];
  iceGatheringState: RTCIceGatheringState = 'new';
  connectionState: RTCPeerConnectionState = 'new';
  localDescription: RTCSessionDescriptionInit | null = null;
  remoteDescription: RTCSessionDescriptionInit | null = null;
  onicegatheringstatechange: ((ev: unknown) => void) | null = null;
  onconnectionstatechange: ((ev: unknown) => void) | null = null;
  ontrack: ((ev: unknown) => void) | null = null;
  closed = false;
  addTransceiver = vi.fn();

  constructor() {
    FakePeerConnection.instances.push(this);
  }

  async createOffer() {
    return { type: 'offer' as const, sdp: 'offer-sdp-no-candidates' };
  }

  async setLocalDescription(desc: RTCSessionDescriptionInit) {
    this.localDescription = desc;
  }

  async setRemoteDescription(desc: RTCSessionDescriptionInit) {
    this.remoteDescription = desc;
  }

  /** 模拟 ICE gathering 完成：候选并入 localDescription 的 SDP。 */
  completeGathering(sdp = 'offer-sdp-with-candidates') {
    this.iceGatheringState = 'complete';
    this.localDescription = { type: 'offer', sdp };
    this.onicegatheringstatechange?.({});
  }

  setConnectionState(state: RTCPeerConnectionState) {
    this.connectionState = state;
    this.onconnectionstatechange?.({});
  }

  close() {
    this.closed = true;
  }
}

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

const renderCard = () =>
  render(
    <LanguageProvider>
      <DriftCard />
    </LanguageProvider>,
  );

const postCallsTo = (url: string) => mockPost.mock.calls.filter((c) => c[0] === url);

beforeEach(() => {
  window.localStorage.clear();
  setBrowserLanguage('zh-CN');
  FakePeerConnection.instances = [];
  vi.stubGlobal('RTCPeerConnection', FakePeerConnection);
  mockGet.mockReset();
  mockPost.mockReset();
  mockPost.mockResolvedValue({ data: { type: 'answer', sdp: 'answer-sdp' } });
  mockState();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('DriftCard 轮询', () => {
  it('轮询 /drift/state（带超时配置）并在卸载后停止', async () => {
    const { unmount } = renderCard();
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(mockGet).toHaveBeenCalledWith('/drift/state', expect.objectContaining({ timeout: expect.any(Number) }));
    unmount();
    const calls = mockGet.mock.calls.length;
    await new Promise((r) => setTimeout(r, 350));
    expect(mockGet.mock.calls.length).toBe(calls);
  });

  it('串行轮询：上一次请求未完成时不发起新请求', async () => {
    let resolveFirst: ((v: unknown) => void) | undefined;
    mockGet.mockImplementationOnce(() => new Promise((res) => { resolveFirst = res; }));
    renderCard();
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    // 远超 100ms 轮询间隔，请求不得堆积
    await new Promise((r) => setTimeout(r, 350));
    expect(mockGet).toHaveBeenCalledTimes(1);
    await act(async () => { resolveFirst?.({ data: makeState() }); });
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it('连续轮询失败达到阈值后显示离线徽标', async () => {
    mockGet.mockRejectedValue(new Error('backend down'));
    renderCard();
    expect(await screen.findByText('后端离线（状态轮询连续失败）', {}, { timeout: 3000 })).toBeInTheDocument();
  });
});

describe('DriftCard 相机状态', () => {
  it('后端快照 camera_running=true 时初始渲染即显示「关相机」', async () => {
    mockState({ camera_running: true });
    renderCard();
    expect(await screen.findByText('关相机')).toBeInTheDocument();
    expect(screen.queryByText('启动相机')).not.toBeInTheDocument();
  });

  it('标定未就绪时录制/自动按钮禁用，标定按钮可用，并显示警告', async () => {
    mockState({ camera_running: true, calibration_ready: false });
    renderCard();
    await screen.findByText('关相机');
    expect(screen.getByText('录制（人 RC 漂移）').closest('button')).toBeDisabled();
    expect(screen.getByText('自动漂移').closest('button')).toBeDisabled();
    expect(screen.getByText('标定').closest('button')).toBeEnabled();
    expect(screen.getByText(/标定文件未就绪/)).toBeInTheDocument();
  });

  it('标定按钮 POST session/start mode=calibrate', async () => {
    mockState({ camera_running: true });
    renderCard();
    await screen.findByText('关相机');
    fireEvent.click(screen.getByText('标定'));
    await waitFor(() => {
      expect(postCallsTo('/drift/session/start')[0]?.[1]).toEqual({ mode: 'calibrate' });
    });
  });
});

describe('DriftCard WebRTC 协商（aiortc 非 trickle）', () => {
  it('ICE gathering 完成后才 POST offer，且使用 localDescription 的 SDP', async () => {
    mockState({ camera_running: true });
    renderCard();
    await screen.findByText('关相机');
    await waitFor(() => expect(FakePeerConnection.instances.length).toBe(1));
    const pc = FakePeerConnection.instances[0];
    // 刷干 createOffer/setLocalDescription 微任务后，gathering 未完成前不得 POST
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(postCallsTo('/drift/webrtc/offer').length).toBe(0);
    await act(async () => { pc.completeGathering('offer-sdp-with-candidates'); });
    await waitFor(() => {
      expect(postCallsTo('/drift/webrtc/offer')[0]?.[1]).toEqual({
        sdp: 'offer-sdp-with-candidates',
        type: 'offer',
      });
    });
  });

  it('gathering 事件缺失时按超时兜底继续协商', async () => {
    vi.useFakeTimers();
    mockState({ camera_running: true });
    renderCard();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(FakePeerConnection.instances.length).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(DRIFT_WEBRTC_ICE_GATHER_TIMEOUT_MS); });
    expect(postCallsTo('/drift/webrtc/offer')[0]?.[1]).toEqual({
      sdp: 'offer-sdp-no-candidates',
      type: 'offer',
    });
  });

  it('connectionstate=failed 时回退 MJPEG', async () => {
    mockState({ camera_running: true });
    renderCard();
    await screen.findByText('关相机');
    await waitFor(() => expect(FakePeerConnection.instances.length).toBe(1));
    const pc = FakePeerConnection.instances[0];
    await act(async () => { pc.completeGathering(); });
    await waitFor(() => expect(pc.remoteDescription).not.toBeNull());
    await act(async () => { pc.setConnectionState('failed'); });
    expect(await screen.findByAltText('俯拍预览')).toBeInTheDocument();
  });

  it('首轨超时（无 ontrack）时回退 MJPEG，img 走 API_URL', async () => {
    vi.useFakeTimers();
    mockState({ camera_running: true });
    renderCard();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const pc = FakePeerConnection.instances[0];
    await act(async () => { pc.completeGathering(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(DRIFT_WEBRTC_TRACK_TIMEOUT_MS); });
    const img = screen.getByAltText('俯拍预览');
    expect(img).toHaveAttribute('src', '/api/drift/frame.mjpg');
  });

  it('卸载时关闭 PeerConnection', async () => {
    mockState({ camera_running: true });
    const { unmount } = renderCard();
    await screen.findByText('关相机');
    await waitFor(() => expect(FakePeerConnection.instances.length).toBe(1));
    unmount();
    expect(FakePeerConnection.instances[0].closed).toBe(true);
  });
});

describe('DriftCard 输入与参数', () => {
  it('非法数值输入：红框提示且不发送启动请求', async () => {
    mockState();
    renderCard();
    await screen.findByText('启动相机');
    const indexInput = screen.getAllByDisplayValue('0')[0];
    fireEvent.change(indexInput, { target: { value: 'abc' } });
    fireEvent.click(screen.getByText('启动相机'));
    expect(await screen.findByText('数值输入非法，请检查标红字段')).toBeInTheDocument();
    expect(postCallsTo('/drift/camera/start').length).toBe(0);
    expect(indexInput.className).toContain('border-red-500');
  });

  it('合法输入启动相机：携带解析后的数值', async () => {
    mockState();
    renderCard();
    await screen.findByText('启动相机');
    // 第三个 '0' 输入是朝向偏移
    fireEvent.change(screen.getAllByDisplayValue('0')[2], { target: { value: '90' } });
    fireEvent.click(screen.getByText('启动相机'));
    await waitFor(() => {
      expect(postCallsTo('/drift/camera/start')[0]?.[1]).toMatchObject({
        camera_index: 0,
        tag_id: 0,
        heading_offset_deg: 90,
      });
    });
  });

  it('参数保存按物理域 clamp（duty ≤1、增益 ≥0）', async () => {
    mockState({ camera_running: true, config: { pulse_duty: 0.5, k_beta: 2 } });
    renderCard();
    await screen.findByText('关相机');
    fireEvent.click(screen.getByText('展开控制器参数'));
    fireEvent.change(screen.getByDisplayValue('0.5'), { target: { value: '5' } });
    fireEvent.change(screen.getByDisplayValue('2'), { target: { value: '-3' } });
    fireEvent.click(screen.getByText('保存参数'));
    await waitFor(() => {
      expect(postCallsTo('/drift/config')[0]?.[1]).toEqual({ pulse_duty: 1, k_beta: 0 });
    });
  });

  it('保存参数只清已提交的 key，提交进行中输入的草稿保留', async () => {
    mockState({ camera_running: true, config: { beta_target_deg: -25, pulse_duty: 0.5 } });
    renderCard();
    await screen.findByText('关相机');
    fireEvent.click(screen.getByText('展开控制器参数'));
    fireEvent.change(screen.getByDisplayValue('-25'), { target: { value: '-30' } });
    let resolvePost: ((v: unknown) => void) | undefined;
    mockPost.mockImplementationOnce(() => new Promise((res) => { resolvePost = res; }));
    fireEvent.click(screen.getByText('保存参数'));
    // POST 进行中继续编辑另一个参数
    fireEvent.change(screen.getByDisplayValue('0.5'), { target: { value: '0.8' } });
    await act(async () => { resolvePost?.({ data: {} }); });
    // 已提交的 beta 草稿清空 → 回落 config 值；未提交的 duty 草稿保留
    await screen.findByDisplayValue('-25');
    expect(screen.getByDisplayValue('0.8')).toBeInTheDocument();
    expect(postCallsTo('/drift/config')[0]?.[1]).toEqual({ beta_target_deg: -30 });
  });
});

describe('DriftCard i18n', () => {
  it('英文界面渲染无任何中文字符串', async () => {
    setBrowserLanguage('en-US');
    mockState({ camera_running: true });
    renderCard();
    await screen.findByText('Stop camera');
    expect(screen.getByText('Overhead Drift')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/[\u4e00-\u9fff]/);
  });
});
