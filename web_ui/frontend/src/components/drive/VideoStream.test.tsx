import '@testing-library/jest-dom/vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VideoStream } from './VideoStream';

vi.mock('../../hooks/useDriveWebRtcVideo', () => ({
  useDriveWebRtcVideo: vi.fn(() => ({
    videoRef: { current: null },
    state: 'connected',
    stats: {
      source_fps: 60,
      sent_fps: 59,
      browser_fps: 58,
      browser_p95_frame_interval_ms: 24,
      degraded: false,
    },
    metrics: { browserFps: 58, p95FrameIntervalMs: 24 },
    error: null,
  })),
}));

describe('VideoStream', () => {
  it('默认渲染 WebRTC video 与 60FPS 指标', () => {
    render(<VideoStream />);

    expect(screen.getByText('WebRTC')).toBeInTheDocument();
    expect(screen.getByText('P95 24ms')).toBeInTheDocument();
    expect(screen.getByText('源 60')).toBeInTheDocument();
    expect(screen.getByLabelText('WebRTC camera feed')).toBeInTheDocument();
  });
});
