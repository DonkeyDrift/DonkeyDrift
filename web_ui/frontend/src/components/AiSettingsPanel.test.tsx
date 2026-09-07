import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AiSettingsPanel } from './AiSettingsPanel';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../services/api', () => ({
  listAiConfigProviders: vi.fn(),
  setActiveAiProvider: vi.fn(),
  saveAiConfigAccount: vi.fn(),
  deleteAiConfigAccount: vi.fn(),
  createCustomAiProvider: vi.fn(),
  deleteCustomAiProvider: vi.fn(),
  startAiOAuthDeviceCode: vi.fn(),
  pollAiOAuthDeviceCode: vi.fn(),
  testAiConfigConnection: vi.fn(),
}));

import { listAiConfigProviders, setActiveAiProvider } from '../services/api';

const mockList = vi.mocked(listAiConfigProviders);
const mockSetActive = vi.mocked(setActiveAiProvider);

const baseProviders = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    icon: 'search',
    base_url: 'https://api.deepseek.com/v1',
    oauth: false,
    api_format: 'openai',
    custom: false,
    default_models: ['deepseek-chat'],
    accounts: [
      { id: 'acc-1', name: '默认账号', api_key_masked: 'sk-***7890', has_api_key: true, oauth_connected: false, base_url: null, models: null },
    ],
  },
  {
    id: 'codex',
    name: 'OpenAI Codex',
    icon: 'bot',
    base_url: 'https://api.openai.com/v1',
    oauth: true,
    api_format: 'openai',
    custom: false,
    default_models: ['gpt-4.1'],
    accounts: [],
  },
];

let activeId: string | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  activeId = null;
  mockList.mockImplementation(async () => ({
    providers: baseProviders,
    active_provider: activeId,
    active_account: null,
  }));
  mockSetActive.mockImplementation(async (providerId: string) => {
    activeId = providerId;
    return { active_provider: providerId, configured: true };
  });
});

describe('AiSettingsPanel', () => {
  it('渲染预设供应商列表', async () => {
    render(<AiSettingsPanel />);
    expect(await screen.findByTestId('ai-provider-deepseek')).toBeInTheDocument();
    expect(screen.getByTestId('ai-provider-codex')).toBeInTheDocument();
    expect(screen.getByTestId('ai-name-deepseek')).toHaveTextContent('DeepSeek');
    expect(screen.getByTestId('ai-name-codex')).toHaveTextContent('OpenAI Codex');
  });

  it('点击「设为当前」调用 setActive 并显示当前徽标', async () => {
    render(<AiSettingsPanel />);
    const btn = await screen.findByTestId('ai-set-active-deepseek');
    fireEvent.click(btn);
    await waitFor(() => expect(mockSetActive).toHaveBeenCalledWith('deepseek'));
    await waitFor(() => expect(screen.getByTestId('ai-active-deepseek')).toBeInTheDocument());
  });

  it('展开后显示掩码 key，不显示明文', async () => {
    render(<AiSettingsPanel />);
    const toggle = await screen.findByTestId('ai-toggle-deepseek');
    fireEvent.click(toggle);
    const keyEl = await screen.findByTestId('ai-key-acc-1');
    expect(keyEl).toHaveTextContent('sk-***7890');
    expect(screen.queryByText(/sk-abcdefghijklmnop1234567890/)).toBeNull();
  });
});

