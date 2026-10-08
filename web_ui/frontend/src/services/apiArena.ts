/**
 * Pilot Arena API 客户端。
 *
 * 从 api.ts 抽取的 Arena 相关接口（模型列表、Pilot 加载/卸载、预测等）。
 */

import { api, API_URL, getApiErrorMessage } from './api'

export interface ArenaModel {
  name: string;
  path: string;
  format: string;
  size: number;
  modified: string;
  compatible: boolean;
}

export interface ArenaPilot {
  id: string;
  name: string;
  model_path: string;
  model_type: string;
  loaded_at: string;
}

export interface ArenaPrediction {
  status: boolean;
  record_index: number;
  user: { angle: number; throttle: number };
  pilot: { angle: number; throttle: number };
}

export interface ArenaPredictionPoint {
  index: number;
  user_angle: number;
  user_throttle: number;
  pilot_angle: number;
  pilot_throttle: number;
}

export interface ArenaMetricSummary {
  count: number;
  mae: number;
  rmse: number;
  bias: number;
  max_abs_error: number;
}

export interface ArenaPredictionsSummary {
  angle: ArenaMetricSummary | null;
  throttle: ArenaMetricSummary | null;
}

export interface ArenaPredictionsResponse {
  status: boolean;
  limit: number;
  points: ArenaPredictionPoint[];
  summary: ArenaPredictionsSummary;
}

export const listArenaModelTypes = async () => {
  const response = await api.get('/arena/model-types');
  return response.data;
};

export const listArenaModels = async (params: { workingDir?: string; modelType?: string } = {}) => {
  const response = await api.get('/arena/models', {
    params: {
      ...(params.workingDir ? { working_dir: params.workingDir } : {}),
      ...(params.modelType ? { model_type: params.modelType } : {}),
    },
  });
  return response.data as { models: ArenaModel[] };
};

export const loadArenaPilot = async (payload: {
  model_path: string;
  model_type: string;
  config_path?: string;
}) => {
  const response = await api.post('/arena/pilots/load', payload);
  return response.data as { status: boolean; pilot: ArenaPilot };
};

export const unloadArenaPilot = async (pilotId: string) => {
  const response = await api.delete(`/arena/pilots/${pilotId}`);
  return response.data;
};

export const predictArenaPilot = async (pilotId: string, payload: {
  record_index: number;
  config_path?: string;
  user_angle_field?: string;
  user_throttle_field?: string;
  pre_transformations?: string[];
  augmentations?: string[];
  post_transformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const response = await api.post(`/arena/pilots/${pilotId}/predict`, payload);
  return response.data as ArenaPrediction;
};

export const getArenaPreviewUrl = (pilotId: string, params: {
  recordIndex: number;
  configPath?: string;
  userAngleField?: string;
  userThrottleField?: string;
  preTransformations?: string[];
  augmentations?: string[];
  postTransformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const search = new URLSearchParams({
    record_index: String(params.recordIndex),
    t: String(Date.now()),
  });
  if (params.configPath) search.set('config_path', params.configPath);
  if (params.userAngleField) search.set('user_angle_field', params.userAngleField);
  if (params.userThrottleField) search.set('user_throttle_field', params.userThrottleField);
  if (params.preTransformations?.length) search.set('pre_transformations', params.preTransformations.join(','));
  if (params.augmentations?.length) search.set('augmentations', params.augmentations.join(','));
  if (params.postTransformations?.length) search.set('post_transformations', params.postTransformations.join(','));
  if (params.brightness !== undefined && params.brightness !== null) search.set('brightness', String(params.brightness));
  if (params.blur !== undefined && params.blur !== null) search.set('blur', String(params.blur));
  return `${API_URL}/arena/pilots/${pilotId}/preview?${search.toString()}`;
};

export const getArenaPredictions = async (pilotId: string, payload: {
  config_path?: string;
  start?: number;
  limit?: number;
  user_angle_field?: string;
  user_throttle_field?: string;
  pre_transformations?: string[];
  augmentations?: string[];
  post_transformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const response = await api.post(`/arena/pilots/${pilotId}/predictions`, payload);
  return response.data as ArenaPredictionsResponse;
};

// ------------------------------------------------------------------
// Simulator Discovery APIs
// ------------------------------------------------------------------

