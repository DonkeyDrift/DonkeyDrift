import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConsoleMuteButton, ConsoleOtaButton, ConsoleDevToggle } from './ConsoleControls';

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

beforeEach(() => {
  vi.clearAllMocks();
  mockUseConsoleDevice.mockReturnValue({ ip: '192.168.1.10', resolving: false });
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
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false });
    render(<ConsoleMuteButton />);
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', 'console.unreachable');
  });

  it('turns blue when muted', async () => {
    mockGetJson.mockResolvedValue({ muted: 1 });
    render(<ConsoleMuteButton />);
    const btn = await screen.findByRole('button', { name: 'console.unmuteAria' });
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn.className).toContain('text-[#5cc8ff]');
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
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false });
    render(<ConsoleOtaButton />);
    const btn = screen.getByRole('button', { name: 'OTA' });
    expect(btn).toBeDisabled();
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

  it('highlights in cyan when enabled', async () => {
    mockGetJson.mockResolvedValue({ enabled: true });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(toggle.className).toContain('bg-cyan-500/25');
    expect(toggle.className).toContain('text-cyan-400');
  });

  it('is disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false });
    render(<ConsoleDevToggle />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeDisabled();
  });
});
