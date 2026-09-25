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

import { listAiConfigProviders, setActiveAiProvider, saveAiConfigAccount } from '../services/api';

const mockList = vi.mocked(listAiConfigProviders);
const mockSetActive = vi.mocked(setActiveAiProvider);
const mockSave = vi.mocked(saveAiConfigAccount);

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

  it('折叠态直接显示已配置/未配置徽标（缺省 configured 时从账号推导）', async () => {
    render(<AiSettingsPanel />);
    // deepseek 账号有 key -> 已配置；codex 无账号 -> 未配置，且开关禁用并提示先填 Key
    expect(await screen.findByTestId('ai-configured-deepseek')).toBeInTheDocument();
    expect(screen.getByTestId('ai-unconfigured-codex')).toBeInTheDocument();
    expect(screen.getByTestId('ai-needkey-codex')).toBeInTheDocument();
    expect(screen.getByTestId('ai-set-active-codex')).toBeDisabled();
    expect(screen.getByTestId('ai-set-active-deepseek')).toBeEnabled();
  });

  it('优先使用后端返回的 configured 字段', async () => {
    mockList.mockImplementation(async () => ({
      providers: [{ ...baseProviders[1], configured: true }],
      active_provider: null,
      active_account: null,
    }));
    render(<AiSettingsPanel />);
    expect(await screen.findByTestId('ai-configured-codex')).toBeInTheDocument();
    expect(screen.getByTestId('ai-set-active-codex')).toBeEnabled();
  });

  it('预设供应商只填 API Key 即可保存（不带 base_url/models）', async () => {
    render(<AiSettingsPanel />);
    fireEvent.click(await screen.findByTestId('ai-toggle-codex'));
    // Base URL/模型由预设自动带出展示，不要求手填
    const autofill = await screen.findByTestId('ai-autofill-codex');
    expect(autofill).toHaveTextContent('https://api.openai.com/v1');
    expect(autofill).toHaveTextContent('gpt-4.1');

    fireEvent.change(screen.getByLabelText('aiConfig.apiKeyLabel'), { target: { value: 'sk-test-1234567890' } });
    fireEvent.click(screen.getByTestId('ai-add-account-codex'));
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const [providerId, payload] = mockSave.mock.calls[0];
    expect(providerId).toBe('codex');
    expect(payload.api_key).toBe('sk-test-1234567890');
    expect(payload).not.toHaveProperty('base_url');
    expect(payload).not.toHaveProperty('models');
  });

  it('高级设置展开后可覆盖 base_url/models', async () => {
    render(<AiSettingsPanel />);
    fireEvent.click(await screen.findByTestId('ai-toggle-codex'));
    fireEvent.click(await screen.findByTestId('ai-advanced-codex'));
    fireEvent.change(screen.getByLabelText('aiConfig.baseUrlLabel'), { target: { value: 'https://proxy.example.com/v1' } });
    fireEvent.change(screen.getByLabelText('aiConfig.modelsLabel'), { target: { value: 'gpt-5, gpt-5-mini' } });
    fireEvent.change(screen.getByLabelText('aiConfig.apiKeyLabel'), { target: { value: 'sk-override-123' } });
    fireEvent.click(screen.getByTestId('ai-add-account-codex'));
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const payload = mockSave.mock.calls[0][1];
    expect(payload.base_url).toBe('https://proxy.example.com/v1');
    expect(payload.models).toEqual(['gpt-5', 'gpt-5-mini']);
  });
});

