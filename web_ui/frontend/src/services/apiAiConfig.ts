/**
 * AI Config API 客户端。
 *
 * 从 api.ts 抽取的 AI 供应商配置、OAuth、AIMO 转换接口。
 */

import { api, API_URL, getApiErrorMessage } from './api'
import type { AiActiveConfig } from './api'

export interface AimoKeyStatus {
  sdk: boolean;
  key: boolean;
  keySource: 'env' | 'file' | null;
}

export const getAimoKeyStatus = async (): Promise<AimoKeyStatus> => {
  const response = await api.get('/trainer/aimo/key-status');
  return response.data as AimoKeyStatus;
};

// 状态查询 / 停止 / SSE 日志复用训练任务的 getJobStatus / stopTrain / createLogStream

export const startAimoConvert = async (params: {
  model_path: string;
  out_dir?: string;
  working_dir?: string;
  precision?: 'INT8' | 'INT16' | 'FP16';
  calib_tubs?: string | null;
  calib_max?: number;
  calib_mix_synth?: number;
  calib_dataset?: string;
  timeout_s?: number;
}) => {
  const response = await api.post('/trainer/train/aimo', params);
  return response.data as { job_id: string; status: string };
};

// ------------------------------------------------------------------
// Car Connector APIs
// ------------------------------------------------------------------

export interface AiConfigAccount {
  id: string;
  name: string;
  api_key_masked: string | null;
  has_api_key: boolean;
  oauth_connected: boolean;
  base_url: string | null;
  models: string[] | null;
}

export interface AiConfigProvider {
  id: string;
  name: string;
  icon: string;
  base_url: string;
  oauth: boolean;
  api_format: 'openai' | 'anthropic' | string;
  custom: boolean;
  default_models: string[];
  // 该供应商是否已有可用凭据（任一账号有 API Key 或已连 OAuth）；后端列表接口返回。
  configured?: boolean;
  accounts: AiConfigAccount[];
}

export interface AiConfigProvidersResponse {
  providers: AiConfigProvider[];
  active_provider: string | null;
  active_account: string | null;
}

export const listAiConfigProviders = async (): Promise<AiConfigProvidersResponse> => {
  const response = await api.get('/ai-config/providers');
  return response.data;
};

export const fetchActiveAiConfig = async (): Promise<AiActiveConfig> => {
  const response = await api.get('/ai-config/active');
  return response.data;
};

export const saveAiConfigAccount = async (
  providerId: string,
  payload: {
    account_id?: string;
    name?: string;
    api_key?: string;
    base_url?: string;
    models?: string[];
  },
): Promise<{ status: boolean; account: AiConfigAccount }> => {
  const response = await api.post(`/ai-config/providers/${providerId}`, payload);
  return response.data;
};

export const deleteAiConfigAccount = async (
  providerId: string,
  accountId: string,
): Promise<{ status: boolean }> => {
  const response = await api.delete(`/ai-config/providers/${providerId}/accounts/${accountId}`);
  return response.data;
};

export const setActiveAiProvider = async (
  providerId: string,
  accountId?: string | null,
): Promise<AiActiveConfig> => {
  const response = await api.post(`/ai-config/providers/${providerId}/active`, {
    account_id: accountId ?? null,
  });
  return response.data;
};

export const createCustomAiProvider = async (payload: {
  name: string;
  base_url: string;
  models?: string[];
  api_format?: string;
  provider_id?: string;
}): Promise<{ status: boolean; provider_id: string }> => {
  const response = await api.post('/ai-config/custom', payload);
  return response.data;
};

export const deleteCustomAiProvider = async (
  providerId: string,
): Promise<{ status: boolean }> => {
  const response = await api.delete(`/ai-config/custom/${providerId}`);
  return response.data;
};

export interface AiOAuthDeviceCode {
  status: boolean;
  device_code: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

export const startAiOAuthDeviceCode = async (
  providerId = 'codex',
): Promise<AiOAuthDeviceCode> => {
  const response = await api.post('/ai-config/oauth/device-code', { provider_id: providerId });
  return response.data;
};

export interface AiOAuthPollResult {
  status: 'pending' | 'expired' | 'success' | 'error';
  account?: AiConfigAccount;
  detail?: string;
}

export const pollAiOAuthDeviceCode = async (
  deviceCode: string,
  userCode?: string,
): Promise<AiOAuthPollResult> => {
  const response = await api.post('/ai-config/oauth/poll', {
    device_code: deviceCode,
    user_code: userCode,
  });
  return response.data;
};

export interface AiConfigTestResult {
  ok: boolean;
  message: string;
  status_code?: number;
  latency_ms?: number;
  detail?: string;
}

export const testAiConfigConnection = async (payload?: {
  provider_id?: string;
  account_id?: string;
}): Promise<AiConfigTestResult> => {
  const response = await api.post('/ai-config/test', payload ?? {});
  return response.data;
};

