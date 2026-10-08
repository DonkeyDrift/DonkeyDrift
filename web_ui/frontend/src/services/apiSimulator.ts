/**
 * Simulator & SimCollect API 客户端。
 *
 * 从 api.ts 抽取的模拟器发现/配置/采集接口。
 */

import { api, API_URL, getApiErrorMessage } from './api'

export interface SimulatorHost {
  ip: string;
  port: number;
  latency_ms: number;
  reachable: boolean;
}

export const discoverSimulator = async (carPath?: string) => {
  const response = await api.post('/config/discover_simulator', { car_path: carPath });
  return response.data as { status: boolean; found: SimulatorHost[]; count: number; scanned: number; message: string };
};

export const saveSimulatorConfig = async (payload: {
  path: string;
  config: Record<string, string | number | boolean>;
}) => {
  const response = await api.post('/config/save_simulator', payload);
  return response.data as { status: boolean; message: string };
};

// ------------------------------------------------------------------
// Sim Collect APIs（模拟器采集：后端 SSH 到 Mac 启动 DonkeySim 跑采集）
// ------------------------------------------------------------------

export interface SimCollectStartParams {
  steps?: number;
  kp?: number;
  kd?: number;
  throttle?: number;
  min_throttle?: number;
  keep_sim?: boolean;
}

export type SimCollectJobState = 'pending' | 'running' | 'done' | 'error' | 'stopped';

export interface SimCollectResult {
  steps: number;
  mean_cte: number;
  max_cte: number;
  /** 0 = 未冲出赛道，1 = 冲出赛道 */
  crashed: number;
  result_out: string;
}

export interface SimCollectStatus {
  job_id: string;
  status: SimCollectJobState;
  step: number;
  steps_total: number;
  cte: number | null;
  speed: number | null;
  result: SimCollectResult | null;
  error: string | null;
  /** 最后 200 行日志 */
  logs: string[];
}

/** 启动采集；已有任务在跑时后端返回 409（调用方按 axios error 处理）。 */

export const startSimCollect = async (params: SimCollectStartParams = {}) => {
  const response = await api.post('/simcollect/start', params);
  return response.data as { job_id: string; status: SimCollectJobState };
};

export const getSimCollectStatus = async (jobId: string) => {
  const response = await api.get(`/simcollect/${jobId}/status`);
  return response.data as SimCollectStatus;
};

export const stopSimCollect = async (jobId: string) => {
  const response = await api.post(`/simcollect/${jobId}/stop`);
  return response.data as { job_id: string; status: SimCollectJobState };
};

export const createSimCollectEventStream = (jobId: string) => {
  return new EventSource(`${API_URL}/simcollect/${jobId}/events`);
};

// ------------------------------------------------------------------
// AI Config APIs（多供应商 AI 模型配置，issue #403；供 TE「AI 一键筛选」#402 等消费）
// 安全约定：后端永不返回明文 api_key / oauth token，只返回掩码与「是否已配置」。
// ------------------------------------------------------------------

