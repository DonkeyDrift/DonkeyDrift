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
});

describe('ConsoleOtaButton', () => {
  it('links to the car HTTP OTA page when the console is reachable', () => {
    render(<ConsoleOtaButton />);
    const link = screen.getByRole('link', { name: 'OTA' });
    expect(link).toHaveAttribute('href', 'http://192.168.1.10/update');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('renders disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false });
    render(<ConsoleOtaButton />);
    const btn = screen.getByRole('button', { name: 'OTA' });
    expect(btn).toBeDisabled();
  });
});

describe('ConsoleDevToggle', () => {
  it('reflects dev mode state and toggles via text/plain proxy', async () => {
    mockGetJson.mockResolvedValue({ enabled: false });
    render(<ConsoleDevToggle />);

    const toggle = await screen.findByRole('switch', { name: 'console.devModeTitle' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockPostText).toHaveBeenCalledWith(
        '192.168.1.10',
        'api/devmode',
        '1',
        'text/plain;charset=UTF-8',
      );
    });
  });

  it('is disabled when the console is unreachable', () => {
    mockUseConsoleDevice.mockReturnValue({ ip: null, resolving: false });
    render(<ConsoleDevToggle />);
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeDisabled();
  });
});
