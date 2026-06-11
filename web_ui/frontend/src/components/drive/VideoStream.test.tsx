import '@testing-library/jest-dom/vitest';
import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS, VideoStream } from './VideoStream';
import { useDriveWebRtcVideo } from '../../hooks/useDriveWebRtcVideo';

vi.mock('../../hooks/useDriveWebRtcVideo', () => ({
  useDriveWebRtcVideo: vi.fn(),
}));

const mockWebRtc = vi.mocked(useDriveWebRtcVideo);

const connectedState = () => ({
  videoRef: { current: null },
  state: 'connected' as const,
  stats: {
    active: true,
    session_id: 'session-1',
    webrtc_available: true,
    source_fps: 60,
    sent_fps: 59,
    browser_fps: 58,
    browser_p95_frame_interval_ms: 24,
    disconnect_count: 0,
    transport: 'webrtc' as const,
    degraded: false,
  },
  metrics: { browserFps: 58, p95FrameIntervalMs: 24 },
  error: null,
  videoReady: true,
  sessionId: 'session-1',
  reconnect: vi.fn(),
});

const degradedState = () => ({
  videoRef: { current: null },
  state: 'degraded' as const,
  stats: {
    active: true,
    session_id: 'session-1',
    webrtc_available: true,
    source_fps: 0,
    sent_fps: 0,
    browser_fps: 0,
    browser_p95_frame_interval_ms: 0,
    disconnect_count: 0,
    transport: 'webrtc' as const,
    degraded: true,
  },
  metrics: { browserFps: 0, p95FrameIntervalMs: 0 },
  error: null,
  videoReady: false,
  sessionId: 'session-1',
  reconnect: vi.fn(),
});

beforeEach(() => {
  vi.useRealTimers();
  mockWebRtc.mockReturnValue(connectedState());
});

describe('VideoStream', () => {
  it('默认渲染 WebRTC video 与 FPS 指标', () => {
    render(<VideoStream />);

    expect(screen.getByText('WebRTC')).toBeInTheDocument();
    expect(screen.getByText('58')).toBeInTheDocument();
    expect(screen.getByText('24ms')).toBeInTheDocument();
    expect(screen.queryByText('P95 24ms')).not.toBeInTheDocument();
    expect(screen.queryByText('源 60')).not.toBeInTheDocument();
    expect(screen.queryByText('发 59')).not.toBeInTheDocument();
    expect(screen.getByLabelText('WebRTC camera feed')).toHaveClass('opacity-100');
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-0');
  });

  it('WebRTC 连接时通过 onLatencyChange 回传 P95 延迟', () => {
    const onLatencyChange = vi.fn();
    render(<VideoStream onLatencyChange={onLatencyChange} />);

    expect(onLatencyChange).toHaveBeenCalledWith(24);
  });

  it('WebRTC 降级后在 fallback 延迟前 video 透明、MJPEG 可见', () => {
    vi.useFakeTimers();
    mockWebRtc.mockReturnValue(degradedState());

    render(<VideoStream />);

    expect(screen.getByLabelText('WebRTC camera feed')).toHaveClass('opacity-0');
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-100');
    expect(screen.queryByText('非 60FPS 验收路径')).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS - 1);
    });

    expect(screen.getByLabelText('WebRTC camera feed')).toHaveClass('opacity-0');
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-100');
    vi.useRealTimers();
  });

  it('WebRTC 超过 fallback 延迟后 video 透明、MJPEG 可见且显示降级标签', () => {
    vi.useFakeTimers();
    mockWebRtc.mockReturnValue(degradedState());

    render(<VideoStream />);

    act(() => {
      vi.advanceTimersByTime(DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS);
    });

    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-100');
    expect(screen.getByLabelText('WebRTC camera feed')).toHaveClass('opacity-0');
    expect(screen.getByText('非 60FPS 验收路径')).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('fallback 后 WebRTC 重试成功会切回 video 覆盖 MJPEG', () => {
    vi.useFakeTimers();
    mockWebRtc.mockReturnValue(degradedState());
    const { rerender } = render(<VideoStream />);

    act(() => {
      vi.advanceTimersByTime(DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS);
    });
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-100');

    mockWebRtc.mockReturnValue(connectedState());
    rerender(<VideoStream />);

    // WebRTC 立即开始渐入
    expect(screen.getByLabelText('WebRTC camera feed')).toHaveClass('opacity-100');
    // MJPEG 还在等待 500ms 延迟，等 WebRTC 完全显示后才开始淡出
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-100');
    expect(screen.queryByText('非 60FPS 验收路径')).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByAltText('Camera feed')).toHaveClass('opacity-0');
    vi.useRealTimers();
  });

  it('mjpeg 模式直接显示 MJPEG 降级且不渲染 WebRTC video', () => {
    render(<VideoStream transport="mjpeg" />);

    expect(screen.getByText('MJPEG')).toBeInTheDocument();
    expect(screen.getByText('非 60FPS 验收路径')).toBeInTheDocument();
    expect(screen.queryByLabelText('WebRTC camera feed')).not.toBeInTheDocument();
    expect(screen.getByAltText('Camera feed')).toBeInTheDocument();
  });

  it('车端离线且超过 fallback 延迟后显示 DriveApiBridge 连接诊断', async () => {
    vi.useFakeTimers();
    mockWebRtc.mockReturnValue({
      videoRef: { current: null },
      state: 'degraded',
      stats: {
        active: false,
        session_id: null,
        webrtc_available: false,
        source_fps: 0,
        sent_fps: 0,
        browser_fps: 0,
        browser_p95_frame_interval_ms: 0,
        disconnect_count: 0,
        transport: 'webrtc',
        degraded: true,
      },
      metrics: { browserFps: 0, p95FrameIntervalMs: 0 },
      error: null,
      videoReady: false,
      sessionId: null,
      reconnect: vi.fn(),
    });
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ online: false, fps: 0, car_ws_connected: false, last_seen_age_sec: null }),
    })));

    render(<VideoStream />);
    await act(async () => {
      vi.advanceTimersByTime(DRIVE_VIDEO_MJPEG_FALLBACK_DELAY_MS);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByText('车端离线：等待 DriveApiBridge 连接到 /api/drive/ws?role=car')).toBeInTheDocument();
    });
    vi.unstubAllGlobals();
  });
});
