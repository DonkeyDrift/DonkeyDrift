import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConsoleMuteButton, ConsoleOtaButton, ConsoleDevToggle, MUTE_CHANGED_EVENT } from './ConsoleControls';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks/useConsoleDevice', () => ({
  useConsoleDevice: vi.fn(),
}));
vi.mock('../services/console', () => ({
  consoleGetJson: vi.fn(),
  consolePostForm: vi.fn(),
  consolePostText: vi.fn(),
}));

import { useConsoleDevice } from '../hooks/useConsoleDevice';
import { consoleGetJson, consolePostForm, consolePostText } from '../services/console';

const mockUseConsoleDevice = vi.mocked(useConsoleDevice);
const mockGetJson = vi.mocked(consoleGetJson);
const mockPostForm = vi.mocked(consolePostForm);
const mockPostText = vi.mocked(consolePostText);
const mockRefresh = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mockUseConsoleDevice.mockReturnValue({ ip: '192.168.1.10', resolving: false, refresh: mockRefresh });
});

describe('ConsoleMuteButton', () => {
  it('reflects unmuted state and toggles via the console proxy', async () => {
    mockGetJson.mockResolvedValue({ muted: 0 });
    render(<ConsoleMuteButton />);

    const btn = await screen.findByRole('button', { name: 'console.muteAria' });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);

    await waitFor(() => {
      expect(mockPostForm).toHaveBeenCalledWith(
        '192.168.1.10',
        'api/mute',
        expect.any(URLSearchParams),
      );
    });
    const params = mockPostForm.mock.calls[0][2] as URLSearchParams;
    expect(params.get('muted')).toBe('1');
  });

  it('is disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false, refresh: mockRefresh });
    render(<ConsoleMuteButton />);
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', 'console.unreachable');
  });

  it('shows a connecting title while the console is still being discovered', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: true, refresh: mockRefresh });
    render(<ConsoleMuteButton />);
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', 'console.connecting');
  });

  it('turns blue when muted', async () => {
    mockGetJson.mockResolvedValue({ muted: 1 });
    render(<ConsoleMuteButton />);
    const btn = await screen.findByRole('button', { name: 'console.unmuteAria' });
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn.className).toContain('text-cyan-400');
  });

  it('broadcasts MUTE_CHANGED_EVENT after toggling so the embedded console updates immediately', async () => {
    mockGetJson.mockResolvedValue({ muted: 0 });
    const listener = vi.fn();
    window.addEventListener(MUTE_CHANGED_EVENT, listener);
    try {
      render(<ConsoleMuteButton />);
      const btn = await screen.findByRole('button', { name: 'console.muteAria' });
      fireEvent.click(btn);

      await waitFor(() => expect(listener).toHaveBeenCalledTimes(1));
      const event = listener.mock.calls[0][0] as CustomEvent<{ muted: boolean }>;
      expect(event.detail.muted).toBe(true);
    } finally {
      window.removeEventListener(MUTE_CHANGED_EVENT, listener);
    }
  });

  it('re-scans for the console when the mute fetch fails (stale cached IP)', async () => {
    mockGetJson.mockRejectedValue(new Error('boom'));
    render(<ConsoleMuteButton />);
    await waitFor(() => expect(mockRefresh).toHaveBeenCalled());
  });

  it('shows a disabled unreachable state instead of "unmuted" while the mute state is unknown', async () => {
    mockGetJson.mockRejectedValue(new Error('boom'));
    render(<ConsoleMuteButton />);
    const btn = await screen.findByRole('button', { name: 'console.muteAria' });
    await waitFor(() => expect(btn).toBeDisabled());
    expect(btn).toHaveAttribute('title', 'console.unreachable');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('ConsoleOtaButton', () => {
  it('opens an in-page upload dialog instead of navigating to a new page', async () => {
    render(<ConsoleOtaButton />);
    const btn = screen.getByRole('button', { name: 'OTA' });
    fireEvent.click(btn);

    expect(await screen.findByText('console.otaTitle')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('uploads the chosen firmware via the console proxy', async () => {
    mockPostForm.mockResolvedValue('ACK:UPDATE_OK');
    render(<ConsoleOtaButton />);

    fireEvent.click(screen.getByRole('button', { name: 'OTA' }));
    const fileInput = await screen.findByLabelText('console.otaChooseFile');
    const file = new File(['binary'], 'firmware.bin', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(screen.getByRole('button', { name: 'console.otaUpload' }));

    await waitFor(() => {
      expect(mockPostForm).toHaveBeenCalledWith(
        '192.168.1.10',
        'update',
        expect.any(FormData),
      );
    });
    const form = mockPostForm.mock.calls[0][2] as FormData;
    expect(form.get('update')).toBe(file);
  });

  it('renders disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false, refresh: mockRefresh });
    render(<ConsoleOtaButton />);
    const btn = screen.getByRole('button', { name: 'OTA' });
    expect(btn).toBeDisabled();
  });

  it('keeps the upload dialog open for the whole upload even if the console IP is lost mid-upload', async () => {
    let resolveUpload!: (v: string) => void;
    mockPostForm.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          resolveUpload = resolve;
        }),
    );
    const { rerender } = render(<ConsoleOtaButton />);

    fireEvent.click(screen.getByRole('button', { name: 'OTA' }));
    const fileInput = await screen.findByLabelText('console.otaChooseFile');
    const file = new File(['binary'], 'firmware.bin', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'console.otaUpload' }));
    await screen.findByRole('button', { name: 'console.otaUploading' });

    // 上传进行中车端 503，DD 重扫把 ip 置 null：弹窗不得消失
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false, refresh: mockRefresh });
    rerender(<ConsoleOtaButton />);
    expect(screen.getByText('console.otaTitle')).toBeInTheDocument();

    resolveUpload('ACK:UPDATE_OK');
    await waitFor(() => expect(screen.queryByText('console.otaTitle')).not.toBeInTheDocument());
  });
});

describe('ConsoleDevToggle', () => {
  it('requires confirmation before enabling', async () => {
    mockGetJson.mockResolvedValue({ enabled: false });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    fireEvent.click(toggle);

    expect(await screen.findByText('console.devTitle')).toBeInTheDocument();
    expect(mockPostText).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'console.devConfirm' }));

    await waitFor(() => {
      expect(mockPostText).toHaveBeenCalledWith(
        '192.168.1.10',
        'api/devmode',
        '1',
        'text/plain;charset=UTF-8',
      );
    });
  });

  it('disables immediately without confirmation', async () => {
    mockGetJson.mockResolvedValue({ enabled: true });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockPostText).toHaveBeenCalledWith(
        '192.168.1.10',
        'api/devmode',
        '0',
        'text/plain;charset=UTF-8',
      );
    });
    expect(screen.queryByText('console.devTitle')).toBeNull();
  });

  it('renders as an OTA-style capsule and shows a hover hint', async () => {
    mockGetJson.mockResolvedValue({ enabled: false });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle.className).toContain('h-8');
    expect(toggle.className).toContain('bg-zinc-800');
    expect(screen.getByText('console.devHint')).toBeInTheDocument();
  });

  it('highlights like the DC DEV toggle when enabled', async () => {
    mockGetJson.mockResolvedValue({ enabled: true });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(toggle.className).toContain('bg-cyan-500/20');
    expect(toggle.className).toContain('border-cyan-500');
    expect(toggle.className).toContain('text-cyan-400');
  });

  it('is disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false, refresh: mockRefresh });
    render(<ConsoleDevToggle />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeDisabled();
  });

  it('re-scans for the console when the devmode fetch fails (stale cached IP)', async () => {
    mockGetJson.mockRejectedValue(new Error('boom'));
    render(<ConsoleDevToggle />);
    await waitFor(() => expect(mockRefresh).toHaveBeenCalled());
  });

  it('shows a disabled unreachable state instead of "off" while the devmode state is unknown', async () => {
    mockGetJson.mockRejectedValue(new Error('boom'));
    render(<ConsoleDevToggle />);
    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    await waitFor(() => expect(toggle).toBeDisabled());
    expect(toggle).toHaveAttribute('title', 'console.unreachable');
    expect(toggle).toHaveAttribute('aria-checked', 'false');
  });
});
