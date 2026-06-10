import '@testing-library/jest-dom/vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { VideoStream } from './VideoStream';
import { useDriveWebRtcVideo } from '../../hooks/useDriveWebRtcVideo';

vi.mock('../../hooks/useDriveWebRtcVideo', () => ({
  useDriveWebRtcVideo: vi.fn(),
}));

const mockWebRtc = vi.mocked(useDriveWebRtcVideo);

beforeEach(() => {
  mockWebRtc.mockReturnValue({
    videoRef: { current: null },
    state: 'connected',
    stats: {
      active: true,
      session_id: 'session-1',
      webrtc_available: true,
      source_fps: 60,
      sent_fps: 59,
      browser_fps: 58,
      browser_p95_frame_interval_ms: 24,
      disconnect_count: 0,
      transport: 'webrtc',
      degraded: false,
    },
    metrics: { browserFps: 58, p95FrameIntervalMs: 24 },
    error: null,
    sessionId: 'session-1',
    reconnect: vi.fn(),
  });
});

describe('VideoStream', () => {
  it('默认渲染 WebRTC video 与 60FPS 指标', () => {
    render(<VideoStream />);

    expect(screen.getByText('WebRTC')).toBeInTheDocument();
    expect(screen.getByText('P95 24ms')).toBeInTheDocument();
    expect(screen.getByText('源 60')).toBeInTheDocument();
    expect(screen.getByLabelText('WebRTC camera feed')).toBeInTheDocument();
  });

  it('mjpeg 模式直接显示 MJPEG 降级且不渲染 WebRTC video', () => {
    render(<VideoStream transport="mjpeg" />);

    expect(screen.getByText('MJPEG')).toBeInTheDocument();
    expect(screen.getByText('非 60FPS 验收路径')).toBeInTheDocument();
    expect(screen.queryByLabelText('WebRTC camera feed')).not.toBeInTheDocument();
    expect(screen.getByAltText('Camera feed')).toBeInTheDocument();
  });

  it('车端离线时显示 DriveApiBridge 连接诊断', async () => {
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
      sessionId: null,
      reconnect: vi.fn(),
    });
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ online: false, fps: 0, car_ws_connected: false, last_seen_age_sec: null }),
    })));

    render(<VideoStream />);

    await waitFor(() => {
      expect(screen.getByText('车端离线：等待 DriveApiBridge 连接到 /api/drive/ws?role=car')).toBeInTheDocument();
    });
    vi.unstubAllGlobals();
  });
});
